"""Daily SMS digest: up to N ranked, never-before-sent properties per recipient.

Rules (plan.md section 9, confirmed decisions):
- Only ranked ELIGIBLE properties; never needs-verification or rejected.
- A property is sent to a recipient at most once (no price-drop re-alerts).
- No SMS when there is nothing new.
- Idempotent: (run, recipient) is reserved before sending; a retry never double-sends.
- STOP replies are honored (Twilio error 21610 -> recipient marked opted out).
"""

import logging
import re
from dataclasses import dataclass
from typing import Protocol

from app.services.discovery import DiscoveryRun, EvaluatedProperty

log = logging.getLogger(__name__)

OPT_OUT_FOOTER = "Reply STOP to opt out."
TWILIO_OPTED_OUT = 21610


@dataclass(frozen=True)
class Recipient:
    key: str  # env var name, e.g. RECIPIENT1
    phone: str  # E.164

    @property
    def last2(self) -> str:
        return self.phone[-2:]


class SendResult(Protocol):
    sid: str | None
    error_code: int | None
    error: str | None


@dataclass
class SmsResult:
    sid: str | None = None
    error_code: int | None = None
    error: str | None = None


class SmsSender(Protocol):
    def send(self, to: str, body: str) -> SmsResult: ...


class NotificationStore(Protocol):
    def sent_property_ids(self, recipient_key: str) -> set[str]: ...
    def is_opted_out(self, recipient_key: str) -> bool: ...
    def reserve_notification(self, run_id: str, recipient_key: str, last2: str, property_ids: list[str]) -> bool: ...
    def finish_notification(self, run_id: str, recipient_key: str, status: str, sid: str | None, error: str | None,
                            property_ids: list[str]) -> None: ...
    def set_opted_out(self, recipient_key: str) -> None: ...


def recipients_from_env(env: dict[str, str | None]) -> list[Recipient]:
    out = []
    for key in sorted(k for k in env if re.fullmatch(r"RECIPIENT\d+", k)):
        phone = (env[key] or "").strip()
        if re.fullmatch(r"\+1\d{10}", phone):
            out.append(Recipient(key, phone))
        elif phone:
            log.warning("%s is not a +1XXXXXXXXXX number; skipped", key)
    return out


def _town_short(ev: EvaluatedProperty) -> str:
    return ev.property.town or (ev.property.address.city or "")


def format_line(i: int, ev: EvaluatedProperty, include_links: bool = True) -> str:
    p, a = ev.property, ev.analysis
    kind = f"{p.units}-fam" if p.units and p.units > 1 else "1-fam"
    parts = [f"{i}) {_town_short(ev)} {kind} ${p.price:,}", f"{a.score:.0f}/100"]
    primary = a.finance.get(a.primary_scenario)
    rent_known = bool(p.rent_estimate and p.rent_estimate.status == "estimated")
    if primary is not None and rent_known:
        parts.append(f"~${primary.effective_owner_cost:,.0f}/mo after rent")
    elif primary is not None:
        parts.append(f"~${primary.monthly_housing_cost:,.0f}/mo (rent not estimated)")
    if p.commute and p.commute.total_minutes:
        parts.append(f"~{p.commute.total_minutes}min to WTC")
    line = " | ".join(parts)
    return f"{line}\n{p.source_url}" if include_links else line


def build_digest(items: list[EvaluatedProperty], include_links: bool = True) -> str:
    n = len(items)
    header = f"HomeScout: {n} new match{'es' if n != 1 else ''}"
    body = "\n".join(format_line(i, ev, include_links) for i, ev in enumerate(items, start=1))
    return f"{header}\n{body}\n{OPT_OUT_FOOTER}"


def select_for_recipient(run: DiscoveryRun, already_sent: set[str], limit: int) -> list[EvaluatedProperty]:
    ranked = sorted((ev for ev in run.results if ev.rank and ev.analysis and ev.property_id), key=lambda ev: ev.rank)
    return [ev for ev in ranked if ev.property_id not in already_sent][:limit]


@dataclass
class DeliveryReport:
    recipient_key: str
    status: str  # sent | failed | opted_out | nothing_new | already_handled
    count: int = 0
    error: str | None = None


def send_digest(run: DiscoveryRun, recipients: list[Recipient], store: NotificationStore, sender: SmsSender,
                *, limit: int = 5, include_links: bool = True) -> list[DeliveryReport]:
    reports: list[DeliveryReport] = []
    for r in recipients:
        if store.is_opted_out(r.key):
            reports.append(DeliveryReport(r.key, "opted_out"))
            continue
        items = select_for_recipient(run, store.sent_property_ids(r.key), limit)
        if not items:
            reports.append(DeliveryReport(r.key, "nothing_new"))
            continue
        ids = [ev.property_id for ev in items]
        if not store.reserve_notification(run.id, r.key, r.last2, ids):
            reports.append(DeliveryReport(r.key, "already_handled"))
            continue
        result = sender.send(r.phone, build_digest(items, include_links))
        if result.sid:
            store.finish_notification(run.id, r.key, "sent", result.sid, None, ids)
            reports.append(DeliveryReport(r.key, "sent", len(items)))
        elif result.error_code == TWILIO_OPTED_OUT:
            store.set_opted_out(r.key)
            store.finish_notification(run.id, r.key, "opted_out", None, result.error, [])
            reports.append(DeliveryReport(r.key, "opted_out", error=result.error))
        else:
            store.finish_notification(run.id, r.key, "failed", None, result.error, [])
            reports.append(DeliveryReport(r.key, "failed", error=result.error))
            log.error("SMS to %s (...%s) failed: %s", r.key, r.last2, result.error)
    return reports
