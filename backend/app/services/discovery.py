"""Discovery pipeline: search towns -> normalize -> dedupe -> prefilter -> details -> features -> filter."""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from app.models.preferences import SearchPreferences
from app.models.property import Property, PropertyType
from app.providers.base import (
    BudgetExceededError,
    PropertyProvider,
    ProviderAuthError,
    ProviderError,
    ProviderQuotaError,
    RequestBudget,
    SearchQuery,
)
from app.services.address import normalize_town
from app.services.deduplication import deduplicate
from app.services.features import apply_description_features
from app.services.filtering import FilterResult, FilterStatus, apply_hard_filters, passes_prefilter

log = logging.getLogger(__name__)


@dataclass
class EvaluatedProperty:
    property: Property
    filter: FilterResult


@dataclass
class DiscoveryRun:
    id: str
    started_at: datetime
    completed_at: datetime | None = None
    status: str = "running"  # running | succeeded | partial | failed
    provider: str = ""
    requests_used: int = 0
    request_budget: int = 0
    errors: list[str] = field(default_factory=list)
    results: list[EvaluatedProperty] = field(default_factory=list)

    def by_status(self, status: FilterStatus) -> list[EvaluatedProperty]:
        return [r for r in self.results if r.filter.status is status]


def resolve_town(prop: Property, prefs: SearchPreferences) -> Property:
    towns = {normalize_town(t): t for t in prefs.towns}
    city = prop.address.city
    state_ok = prop.address.state in (None, prefs.state)
    town = towns.get(normalize_town(city)) if city and state_ok else None
    return prop.model_copy(update={"town": town})


def run_discovery(
    provider: PropertyProvider,
    prefs: SearchPreferences,
    *,
    max_requests: int,
    fetch_details: bool = True,
    today: date | None = None,
) -> DiscoveryRun:
    today = today or date.today()
    budget = RequestBudget(max_requests)
    run = DiscoveryRun(
        id=str(uuid.uuid4()),
        started_at=datetime.now(timezone.utc),
        provider=provider.name,
        request_budget=max_requests,
    )

    found: list[Property] = []
    fatal = False
    for town in prefs.towns:
        query = SearchQuery(
            location=f"{town}, {prefs.state}",
            max_price=prefs.max_price,
            property_types=(PropertyType.MULTI_FAMILY, PropertyType.SINGLE_FAMILY),
            max_days_listed=prefs.listing_window_days,
        )
        try:
            found.extend(provider.search(query, budget))
        except (ProviderAuthError, ProviderQuotaError) as exc:
            run.errors.append(f"{town}: {exc}")
            fatal = True
            break
        except BudgetExceededError as exc:
            run.errors.append(f"{town}: {exc}")
            break
        except ProviderError as exc:
            run.errors.append(f"{town}: {exc}")

    candidates = deduplicate([resolve_town(p, prefs) for p in found])

    enriched: list[Property] = []
    for prop in candidates:
        if fetch_details and not fatal and passes_prefilter(prop, prefs):
            try:
                prop = resolve_town(provider.enrich(prop, budget), prefs)
            except BudgetExceededError:
                run.errors.append(f"Details skipped for {prop.address.raw}: request budget exhausted")
            except (ProviderAuthError, ProviderQuotaError) as exc:
                run.errors.append(str(exc))
                fatal = True
            except ProviderError as exc:
                run.errors.append(f"Details failed for {prop.address.raw}: {exc}")
        enriched.append(apply_description_features(prop))

    run.results = [
        EvaluatedProperty(p, apply_hard_filters(p, prefs, today)) for p in deduplicate(enriched)
    ]
    run.requests_used = budget.used
    run.completed_at = datetime.now(timezone.utc)
    if fatal and not found:
        run.status = "failed"
    elif run.errors:
        run.status = "partial"
    else:
        run.status = "succeeded"
    log.info(
        "Discovery %s: %s, %d results, %d/%d requests",
        run.id, run.status, len(run.results), run.requests_used, max_requests,
    )
    return run
