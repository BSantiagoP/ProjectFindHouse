"""Supabase (PostgREST) repository using the service-role key. Server-side only."""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from app.models.preferences import SearchPreferences
from app.models.property import Property
from app.repositories.base import PriceSnapshot, RepositoryError
from app.services.deduplication import address_key
from app.services.discovery import DiscoveryRun, EvaluatedProperty, ListingKey
from app.services.filtering import FilterResult, FilterStatus
from app.services.scoring import Analysis

log = logging.getLogger(__name__)

_CHUNK = 100


def _addr_key_str(p: Property) -> str | None:
    k = address_key(p)
    return "|".join(k) if k else None


def _in(values: list[str]) -> str:
    """PostgREST in.() filter with quoted values."""
    return "in.(" + ",".join('"' + v.replace('"', '\\"') + '"' for v in values) + ")"


def _chunks(items: list, size: int = _CHUNK):
    for i in range(0, len(items), size):
        yield items[i : i + size]


class SupabaseRepository:
    def __init__(self, url: str, key: str, *, client: httpx.Client | None = None) -> None:
        if not url or not key:
            raise RepositoryError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
        # Accept both the project URL and the "REST URL" (…/rest/v1) shown in the dashboard.
        base = url.strip().rstrip("/").removesuffix("/rest/v1")
        self._client = client or httpx.Client(base_url=base + "/rest/v1", timeout=30)
        self._headers = {"apikey": key, "Content-Type": "application/json"}
        # Legacy service_role keys are JWTs and go in Authorization too; new sb_secret_ keys must not.
        if key.startswith("eyJ"):
            self._headers["Authorization"] = f"Bearer {key}"

    # ---- HTTP -----------------------------------------------------------------

    def _req(self, method: str, table: str, *, params: Any = None, body: Any = None, prefer: str | None = None) -> Any:
        headers = dict(self._headers)
        if prefer:
            headers["Prefer"] = prefer
        try:
            resp = self._client.request(
                method, f"/{table}", params=params, headers=headers,
                content=json.dumps(body, default=str) if body is not None else None,
            )
        except httpx.HTTPError as exc:
            raise RepositoryError(f"{method} {table}: {exc}") from exc
        if resp.status_code >= 400:
            raise RepositoryError(f"{method} {table}: HTTP {resp.status_code} {resp.text[:300]}")
        return resp.json() if resp.content else None

    def _upsert(self, table: str, rows: list[dict], on_conflict: str) -> None:
        for chunk in _chunks(rows):
            self._req("POST", table, params={"on_conflict": on_conflict}, body=chunk,
                      prefer="resolution=merge-duplicates,return=minimal")

    def _insert(self, table: str, rows: list[dict]) -> None:
        for chunk in _chunks(rows):
            self._req("POST", table, body=chunk, prefer="return=minimal")

    # ---- Reads ----------------------------------------------------------------

    def _listing_rows(self, keys: list[ListingKey], select: str) -> list[dict]:
        rows: list[dict] = []
        by_provider: dict[str, list[str]] = {}
        for provider, ext in keys:
            by_provider.setdefault(provider, []).append(ext)
        for provider, ids in by_provider.items():
            for chunk in _chunks(ids):
                rows += self._req("GET", "provider_listings", params={
                    "select": select, "provider": f"eq.{provider}", "external_id": _in(chunk),
                })
        return rows

    def known_properties(self, keys: list[ListingKey]) -> dict[ListingKey, Property]:
        if not keys:
            return {}
        rows = self._listing_rows(keys, "provider,external_id,properties(data)")
        return {
            (r["provider"], r["external_id"]): Property.model_validate(r["properties"]["data"])
            for r in rows if r.get("properties")
        }

    def get_run(self, run_id: str) -> DiscoveryRun | None:
        rows = self._req("GET", "search_runs", params={"id": f"eq.{run_id}", "select": "*"})
        return self._load_run(rows[0]) if rows else None

    def latest_run(self) -> DiscoveryRun | None:
        rows = self._req("GET", "search_runs", params={
            "status": "neq.failed", "order": "started_at.desc", "limit": "1", "select": "*",
        })
        return self._load_run(rows[0]) if rows else None

    def _load_run(self, row: dict) -> DiscoveryRun:
        results = self._req("GET", "run_results", params={
            "search_run_id": f"eq.{row['id']}", "select": "*,properties(data)",
        })
        run = DiscoveryRun(
            id=row["id"],
            started_at=datetime.fromisoformat(row["started_at"]),
            completed_at=datetime.fromisoformat(row["completed_at"]) if row.get("completed_at") else None,
            status=row["status"],
            provider=row["provider"],
            requests_used=row["requests_used"],
            request_budget=row["request_budget"],
            details_reused=(row.get("counts") or {}).get("details_reused", 0),
            errors=row.get("errors") or [],
        )
        for r in results:
            run.results.append(EvaluatedProperty(
                property=Property.model_validate(r["properties"]["data"]),
                filter=FilterResult(FilterStatus(r["filter_status"]), r["rejections"], r["unverified"]),
                is_new=r["is_new"],
                previous_price=r.get("previous_price"),
                property_id=r["property_id"],
                analysis=Analysis.model_validate(r["analysis"]) if r.get("analysis") else None,
                rank=r.get("rank"),
            ))
        return run

    def price_history(self, property_id: str) -> list[PriceSnapshot]:
        rows = self._req("GET", "property_snapshots", params={
            "property_id": f"eq.{property_id}", "order": "observed_at.asc", "select": "price,status,observed_at",
        })
        return [PriceSnapshot.model_validate(r) for r in rows]

    def reserve_api_request(self, provider: str, period: str, limit: int) -> bool:
        resp = self._client.post("/rpc/reserve_api_request", headers=self._headers,
                                 content=json.dumps({"p_provider": provider, "p_period": period, "p_limit": limit}))
        if resp.status_code >= 400:
            raise RepositoryError(f"reserve_api_request: HTTP {resp.status_code} {resp.text[:200]}")
        return resp.json() is True

    def get_preferences(self) -> SearchPreferences:
        rows = self._req("GET", "search_preferences", params={"id": "eq.1", "select": "data"})
        return SearchPreferences.model_validate(rows[0]["data"]) if rows else SearchPreferences()

    def save_preferences(self, prefs: SearchPreferences) -> None:
        self._upsert("search_preferences", [{
            "id": 1, "data": prefs.model_dump(mode="json"), "updated_at": datetime.now(timezone.utc).isoformat(),
        }], "id")

    # ---- Writes ---------------------------------------------------------------

    def save_run(self, run: DiscoveryRun) -> None:
        counts = run.counts() | {"details_reused": run.details_reused}
        self._upsert("search_runs", [{
            "id": run.id, "provider": run.provider, "status": run.status,
            "started_at": run.started_at.isoformat(),
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "requests_used": run.requests_used, "request_budget": run.request_budget,
            "errors": run.errors, "counts": counts,
        }], "id")
        if not run.results:
            return

        # Resolve property ids: by listing key, then by normalized address, else new.
        keys = [ev.property.key for ev in run.results]
        listing_pid = {(r["provider"], r["external_id"]): r["property_id"]
                       for r in self._listing_rows(keys, "provider,external_id,property_id")}
        addr_keys = [a for ev in run.results if (a := _addr_key_str(ev.property))]
        addr_pid: dict[str, str] = {}
        for chunk in _chunks(addr_keys):
            for r in self._req("GET", "properties", params={"select": "id,address_key", "address_key": _in(chunk)}):
                addr_pid[r["address_key"]] = r["id"]

        for ev in run.results:
            addr = _addr_key_str(ev.property)
            ev.property_id = listing_pid.get(ev.property.key) or (addr_pid.get(addr) if addr else None) or str(uuid.uuid4())

        existing: dict[str, dict] = {}
        ids = [ev.property_id for ev in run.results]
        for chunk in _chunks(ids):
            for r in self._req("GET", "properties", params={"select": "id,current_price,status", "id": _in(chunk)}):
                existing[r["id"]] = r

        now = datetime.now(timezone.utc).isoformat()
        prop_rows, listing_rows, snapshot_rows, result_rows = [], [], [], []
        for ev in run.results:
            p, pid = ev.property, ev.property_id
            prop_rows.append({
                "id": pid,
                "address_key": _addr_key_str(p),
                "town": p.town,
                "property_type": p.property_type.value,
                "units": p.units,
                "current_price": p.price,
                "status": p.status,
                "listed_date": p.listed_date.isoformat() if p.listed_date else None,
                "data": p.model_dump(mode="json"),
                "details_fetched_at": now if p.details_fetched else None,
                "last_seen_at": now,
            })
            listing_rows.append({
                "provider": p.provider, "external_id": p.external_id, "property_id": pid,
                "source_url": str(p.source_url), "last_seen_at": now,
            })
            prev = existing.get(pid)
            if prev is None or prev.get("current_price") != p.price or prev.get("status") != p.status:
                snapshot_rows.append({"property_id": pid, "search_run_id": run.id, "price": p.price,
                                      "status": p.status, "observed_at": now})
            result_rows.append({
                "search_run_id": run.id, "property_id": pid, "filter_status": ev.filter.status.value,
                "rejections": ev.filter.rejections, "unverified": ev.filter.unverified,
                "is_new": ev.is_new, "previous_price": ev.previous_price,
                "analysis": ev.analysis.model_dump(mode="json") if ev.analysis else None,
                "rank": ev.rank,
            })

        self._upsert("properties", prop_rows, "id")
        self._upsert("provider_listings", listing_rows, "provider,external_id")
        if snapshot_rows:
            self._insert("property_snapshots", snapshot_rows)
        self._upsert("run_results", result_rows, "search_run_id,property_id")

    # ---- notifications ----
    def sent_property_ids(self, recipient_key: str) -> set[str]:
        rows = self._req("GET", "sent_properties", params={"recipient_key": f"eq.{recipient_key}", "select": "property_id"})
        return {r["property_id"] for r in rows}

    def is_opted_out(self, recipient_key: str) -> bool:
        rows = self._req("GET", "recipient_status", params={"recipient_key": f"eq.{recipient_key}", "select": "opted_out"})
        return bool(rows and rows[0]["opted_out"])

    def reserve_notification(self, run_id: str, recipient_key: str, last2: str, property_ids: list[str]) -> bool:
        """Insert-if-absent. Returns False if this (run, recipient) was already reserved/sent."""
        rows = self._req("POST", "notifications", params={"on_conflict": "search_run_id,recipient_key"},
                         body=[{"search_run_id": run_id, "recipient_key": recipient_key, "recipient_last2": last2,
                                "status": "reserved", "property_ids": property_ids}],
                         prefer="resolution=ignore-duplicates,return=representation")
        return bool(rows)

    def finish_notification(self, run_id, recipient_key, status, sid, error, property_ids) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._req("PATCH", "notifications",
                  params={"search_run_id": f"eq.{run_id}", "recipient_key": f"eq.{recipient_key}"},
                  body={"status": status, "twilio_sid": sid, "error": error, "updated_at": now},
                  prefer="return=minimal")
        if status == "sent" and property_ids:
            self._req("POST", "sent_properties", params={"on_conflict": "recipient_key,property_id"},
                      body=[{"recipient_key": recipient_key, "property_id": pid} for pid in property_ids],
                      prefer="resolution=ignore-duplicates,return=minimal")

    def set_opted_out(self, recipient_key: str) -> None:
        self._upsert("recipient_status", [{"recipient_key": recipient_key, "opted_out": True,
                                           "updated_at": datetime.now(timezone.utc).isoformat()}], "recipient_key")
