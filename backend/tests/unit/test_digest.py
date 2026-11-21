"""SMS digest: selection, formatting, idempotency, opt-out, no repeats."""

from datetime import datetime, timezone

import httpx

from app.models.preferences import SearchPreferences
from app.notifications.digest import (
    OPT_OUT_FOOTER, Recipient, SmsResult, build_digest, recipients_from_env, send_digest,
)
from app.notifications.twilio_client import TwilioSender
from app.repositories.memory import MemoryRepository
from app.services.discovery import DiscoveryRun, EvaluatedProperty
from app.services.filtering import FilterResult, FilterStatus
from app.services.rates import MortgageRate
from app.services.scoring import score_property
from tests.conftest import make_property

ME = Recipient("RECIPIENT1", "+12015550170")


class FakeSender:
    def __init__(self, result=None):
        self.sent, self.result = [], result or SmsResult(sid="SM1")

    def send(self, to, body):
        self.sent.append((to, body))
        return self.result


def ranked_run(n=3, run_id="run1"):
    results = []
    for i in range(1, n + 1):
        p = make_property(external_id=str(i), price=700_000 + i * 10_000, units=2)
        ev = EvaluatedProperty(p, FilterResult(FilterStatus.ELIGIBLE), property_id=f"pid{i}", rank=i,
                               analysis=score_property(p, SearchPreferences(), MortgageRate(0.06, None, "t")))
        results.append(ev)
    unranked = make_property(external_id="x")
    results.append(EvaluatedProperty(unranked, FilterResult(FilterStatus.NEEDS_VERIFICATION, unverified=["laundry"]),
                                     property_id="pidx"))
    return DiscoveryRun(id=run_id, started_at=datetime.now(timezone.utc), status="succeeded", results=results)


def test_recipients_from_env_only_valid_us_numbers():
    env = {"RECIPIENT1": "+12015550170", "RECIPIENT2": "201-555-0100", "OTHER": "+12015550199", "RECIPIENT3": ""}
    assert recipients_from_env(env) == [ME]


def test_digest_contains_ranked_only_with_links_and_opt_out():
    run = ranked_run()
    sender = FakeSender()
    reports = send_digest(run, [ME], MemoryRepository(), sender)
    body = sender.sent[0][1]
    assert reports[0].status == "sent" and reports[0].count == 3
    assert body.startswith("HomeScout: 3 new matches") and body.endswith(OPT_OUT_FOOTER)
    assert body.count("https://example.com/listing/") == 3
    assert "laundry" not in body  # needs-verification never sent


def test_same_run_never_sent_twice():
    repo, sender, run = MemoryRepository(), FakeSender(), ranked_run()
    send_digest(run, [ME], repo, sender)
    again = send_digest(run, [ME], repo, sender)
    assert len(sender.sent) == 1 and again[0].status in ("nothing_new", "already_handled")


def test_properties_never_resent_on_later_runs_and_no_sms_when_nothing_new():
    repo, sender = MemoryRepository(), FakeSender()
    send_digest(ranked_run(2, "run1"), [ME], repo, sender)
    reports = send_digest(ranked_run(3, "run2"), [ME], repo, sender)
    assert reports[0].count == 1 and "HomeScout: 1 new match\n" in sender.sent[1][1]
    reports = send_digest(ranked_run(3, "run3"), [ME], repo, sender)
    assert reports[0].status == "nothing_new" and len(sender.sent) == 2


def test_limit_five():
    sender = FakeSender()
    send_digest(ranked_run(8), [ME], MemoryRepository(), sender, limit=5)
    assert sender.sent[0][1].count("\n5) ") == 1 and "\n6) " not in sender.sent[0][1]


def test_stop_reply_marks_opted_out_and_skips_future():
    repo = MemoryRepository()
    blocked = FakeSender(SmsResult(error_code=21610, error="unsubscribed"))
    assert send_digest(ranked_run(run_id="a"), [ME], repo, blocked)[0].status == "opted_out"
    ok = FakeSender()
    assert send_digest(ranked_run(run_id="b"), [ME], repo, ok)[0].status == "opted_out"
    assert ok.sent == []


def test_failed_send_does_not_mark_properties_sent():
    repo = MemoryRepository()
    send_digest(ranked_run(run_id="a"), [ME], repo, FakeSender(SmsResult(error="HTTP 500")))
    assert repo.sent_property_ids("RECIPIENT1") == set()


def test_twilio_sender_uses_messaging_service():
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(201, json={"sid": "SM123"})

    client = httpx.Client(base_url="https://api.twilio.com/2010-04-01", transport=httpx.MockTransport(handler))
    r = TwilioSender("AC1", "tok", "MG1", client=client).send("+12015550170", "hi")
    form = dict(x.split("=") for x in seen[0].content.decode().split("&"))
    assert r.sid == "SM123" and form["MessagingServiceSid"] == "MG1" and "From" not in form


def test_twilio_opt_out_error_code_parsed():
    client = httpx.Client(base_url="https://api.twilio.com/2010-04-01", transport=httpx.MockTransport(
        lambda req: httpx.Response(400, json={"code": 21610, "message": "Attempt to send to unsubscribed recipient"})))
    r = TwilioSender("AC1", "tok", "MG1", client=client).send("+12015550170", "hi")
    assert r.sid is None and r.error_code == 21610


def test_unestimated_rent_not_described_as_after_rent():
    run = ranked_run(1)
    body = build_digest([ev for ev in run.results if ev.rank])
    assert "rent not estimated" in body and "after rent" not in body


def test_digest_without_links():
    run = ranked_run(2)
    body = build_digest([ev for ev in run.results if ev.rank], include_links=False)
    assert "http" not in body and body.endswith(OPT_OUT_FOOTER)


def test_schedule_every_other_day_after_8am_eastern():
    from zoneinfo import ZoneInfo
    from app.jobs.daily_search import is_due

    et = ZoneInfo("America/New_York")
    repo = MemoryRepository()
    assert is_due(repo, every_days=2, run_hour=8, now=datetime(2026, 11, 20, 9, tzinfo=et))[0]  # never ran
    run = ranked_run(1, "mon")
    run.started_at = datetime(2026, 11, 20, 8, 5, tzinfo=et)
    repo.save_run(run)
    due = lambda d, h: is_due(repo, every_days=2, run_hour=8, now=datetime(2026, 11, d, h, tzinfo=et))[0]
    assert not due(20, 15)  # same day
    assert not due(21, 9)   # next day
    assert not due(22, 7)   # due day but before 8 AM
    assert due(22, 8)       # due day at 8
    assert due(23, 13)      # Mac was closed on the 22nd: catches up next time it is awake


def test_rejected_in_dashboard_never_texted():
    repo, sender = MemoryRepository(), FakeSender()
    repo.rejected.add("pid1")
    send_digest(ranked_run(3), [ME], repo, sender)
    assert "$710,000" not in sender.sent[0][1] and sender.sent[0][1].startswith("HomeScout: 2 new matches")


def test_preference_limits_enforced():
    import pytest
    from pydantic import ValidationError

    for bad in ({"max_price": 50}, {"target_monthly_cost": 10}, {"towns": []}):
        with pytest.raises(ValidationError):
            SearchPreferences(**bad)
