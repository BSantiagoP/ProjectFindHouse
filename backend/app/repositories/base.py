from datetime import datetime
from typing import Protocol

from pydantic import BaseModel

from app.models.preferences import SearchPreferences
from app.models.property import Property
from app.services.discovery import DiscoveryRun, ListingKey


class RepositoryError(Exception):
    pass


class PriceSnapshot(BaseModel):
    price: int | None
    status: str | None
    observed_at: datetime


class Repository(Protocol):
    def known_properties(self, keys: list[ListingKey]) -> dict[ListingKey, Property]:
        """Previously stored properties for these provider listing keys."""
        ...

    def save_run(self, run: DiscoveryRun) -> None:
        """Persist the run, upsert properties/listings, record price changes, set result property_ids."""
        ...

    def get_run(self, run_id: str) -> DiscoveryRun | None: ...

    def latest_run(self) -> DiscoveryRun | None:
        """Most recent run that did not fail."""
        ...

    def price_history(self, property_id: str) -> list[PriceSnapshot]: ...

    def reserve_api_request(self, provider: str, period: str, limit: int) -> bool:
        """Atomically count one paid request if under the monthly limit."""
        ...

    def get_preferences(self) -> SearchPreferences: ...

    def save_preferences(self, prefs: SearchPreferences) -> None: ...
