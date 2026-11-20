"""In-memory repository: used in tests and when Supabase is not configured."""

import copy
import uuid
from threading import Lock

from app.models.preferences import SearchPreferences
from app.models.property import Property
from app.repositories.base import PriceSnapshot
from app.services.deduplication import address_key
from app.services.discovery import DiscoveryRun, ListingKey


class MemoryRepository:
    def __init__(self) -> None:
        self._lock = Lock()
        self.runs: dict[str, DiscoveryRun] = {}
        self.properties: dict[str, Property] = {}  # property_id -> Property
        self.listings: dict[ListingKey, str] = {}  # listing key -> property_id
        self.by_address: dict[tuple, str] = {}
        self.snapshots: dict[str, list[PriceSnapshot]] = {}
        self.preferences = SearchPreferences()
        self.api_usage: dict[tuple[str, str], int] = {}

    def known_properties(self, keys: list[ListingKey]) -> dict[ListingKey, Property]:
        return {k: self.properties[self.listings[k]] for k in keys if k in self.listings}

    def save_run(self, run: DiscoveryRun) -> None:
        with self._lock:
            for ev in run.results:
                p = ev.property
                addr = address_key(p)
                pid = self.listings.get(p.key) or (self.by_address.get(addr) if addr else None) or str(uuid.uuid4())
                prev = self.properties.get(pid)
                if prev is None or prev.price != p.price or prev.status != p.status:
                    self.snapshots.setdefault(pid, []).append(
                        PriceSnapshot(price=p.price, status=p.status, observed_at=p.observed_at)
                    )
                self.properties[pid] = p
                self.listings[p.key] = pid
                if addr:
                    self.by_address[addr] = pid
                ev.property_id = pid
            self.runs[run.id] = copy.deepcopy(run)

    def get_run(self, run_id: str) -> DiscoveryRun | None:
        return self.runs.get(run_id)

    def latest_run(self) -> DiscoveryRun | None:
        ok = [r for r in self.runs.values() if r.status != "failed"]
        return max(ok, key=lambda r: r.started_at) if ok else None

    def price_history(self, property_id: str) -> list[PriceSnapshot]:
        return list(self.snapshots.get(property_id, []))

    def reserve_api_request(self, provider: str, period: str, limit: int) -> bool:
        with self._lock:
            used = self.api_usage.get((provider, period), 0)
            if used >= limit:
                return False
            self.api_usage[(provider, period)] = used + 1
            return True

    def get_preferences(self) -> SearchPreferences:
        return self.preferences

    def save_preferences(self, prefs: SearchPreferences) -> None:
        self.preferences = prefs
