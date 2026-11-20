"""In-memory run store for Milestone 1. Replaced by Supabase repositories in Milestone 2."""

from threading import Lock

from app.models.preferences import SearchPreferences
from app.services.discovery import DiscoveryRun


class MemoryStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self.runs: dict[str, DiscoveryRun] = {}
        self.latest_run_id: str | None = None
        self.preferences = SearchPreferences()

    def save_run(self, run: DiscoveryRun) -> None:
        with self._lock:
            self.runs[run.id] = run
            if run.status != "failed":
                self.latest_run_id = run.id

    def latest_run(self) -> DiscoveryRun | None:
        return self.runs.get(self.latest_run_id) if self.latest_run_id else None


store = MemoryStore()


def get_store() -> MemoryStore:
    return store
