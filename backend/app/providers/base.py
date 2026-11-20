from dataclasses import dataclass
from typing import Protocol

from app.models.property import Property, PropertyType


class ProviderError(Exception):
    """Base class for provider failures."""


class ProviderAuthError(ProviderError):
    """Invalid or missing credentials."""


class ProviderQuotaError(ProviderError):
    """Provider account is out of credits."""


class ProviderRequestError(ProviderError):
    """The request was rejected as invalid (not retryable)."""


class ProviderUnavailableError(ProviderError):
    """Transient failure that persisted after retries."""


class BudgetExceededError(ProviderError):
    """The per-run request budget is exhausted."""


class RequestBudget:
    """Hard cap on billable provider requests within one search run."""

    def __init__(self, max_requests: int) -> None:
        self.max_requests = max_requests
        self.used = 0

    @property
    def remaining(self) -> int:
        return max(self.max_requests - self.used, 0)

    def spend(self) -> None:
        if self.used >= self.max_requests:
            raise BudgetExceededError(f"Request budget of {self.max_requests} exhausted")
        self.used += 1


@dataclass(frozen=True)
class SearchQuery:
    location: str  # e.g. "Lyndhurst, NJ"
    max_price: int
    property_types: tuple[PropertyType, ...]
    max_days_listed: int


class PropertyProvider(Protocol):
    name: str

    def search(self, query: SearchQuery, budget: RequestBudget) -> list[Property]:
        """Return normalized for-sale listings matching the query."""
        ...

    def enrich(self, prop: Property, budget: RequestBudget) -> Property:
        """Return the property with detail fields (description, dates, tax) filled in."""
        ...
