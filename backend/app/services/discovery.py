"""Discovery pipeline: search towns -> normalize -> dedupe -> reuse known details or fetch -> features -> filter."""

import logging
import uuid
from collections.abc import Callable
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

ListingKey = tuple[str, str]
KnownLookup = Callable[[list[ListingKey]], dict[ListingKey, Property]]


@dataclass
class EvaluatedProperty:
    property: Property
    filter: FilterResult
    is_new: bool = True  # never seen in a previous run
    previous_price: int | None = None  # set only when the price changed since last seen
    property_id: str | None = None  # database id, once persisted

    @property
    def price_changed(self) -> bool:
        return self.previous_price is not None


@dataclass
class DiscoveryRun:
    id: str
    started_at: datetime
    completed_at: datetime | None = None
    status: str = "running"  # running | succeeded | partial | failed
    provider: str = ""
    requests_used: int = 0
    request_budget: int = 0
    details_reused: int = 0  # detail calls avoided because the listing was already known
    errors: list[str] = field(default_factory=list)
    results: list[EvaluatedProperty] = field(default_factory=list)

    def by_status(self, status: FilterStatus) -> list[EvaluatedProperty]:
        return [r for r in self.results if r.filter.status is status]

    def counts(self) -> dict[str, int]:
        c = {s.value: len(self.by_status(s)) for s in FilterStatus}
        c["new"] = sum(r.is_new for r in self.results)
        c["price_changed"] = sum(r.price_changed for r in self.results)
        return c


def resolve_town(prop: Property, prefs: SearchPreferences) -> Property:
    towns = {normalize_town(t): t for t in prefs.towns}
    city = prop.address.city
    state_ok = prop.address.state in (None, prefs.state)
    town = towns.get(normalize_town(city)) if city and state_ok else None
    return prop.model_copy(update={"town": town})


def merge_known(known: Property, fresh: Property) -> Property:
    """Keep stored details (description, features, evidence); take fresh search-level facts."""
    updates = {
        "price": fresh.price if fresh.price is not None else known.price,
        "status": fresh.status or known.status,
        "days_on_market": fresh.days_on_market,
        "observed_at": fresh.observed_at,
        "provider": fresh.provider,
        "external_id": fresh.external_id,
        "source_url": fresh.source_url,
    }
    if fresh.photo_urls and not known.photo_urls:
        updates["photo_urls"] = fresh.photo_urls
    return known.model_copy(update=updates)


def run_discovery(
    provider: PropertyProvider,
    prefs: SearchPreferences,
    *,
    max_requests: int,
    fetch_details: bool = True,
    today: date | None = None,
    known_lookup: KnownLookup | None = None,
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
    known: dict[ListingKey, Property] = {}
    if known_lookup and candidates:
        try:
            known = known_lookup([p.key for p in candidates])
        except Exception as exc:  # storage outage must not lose a paid search
            log.exception("Known-listing lookup failed")
            run.errors.append(f"Could not load previously seen listings: {exc}")

    enriched: list[Property] = []
    for prop in candidates:
        prior = known.get(prop.key)
        if prior is not None and prior.details_fetched:
            prop = resolve_town(merge_known(prior, prop), prefs)
            run.details_reused += 1
        elif fetch_details and not fatal and passes_prefilter(prop, prefs):
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

    for p in deduplicate(enriched):
        prior = known.get(p.key)
        changed = prior is not None and None not in (prior.price, p.price) and prior.price != p.price
        run.results.append(
            EvaluatedProperty(
                p,
                apply_hard_filters(p, prefs, today),
                is_new=prior is None,
                previous_price=prior.price if changed else None,
            )
        )

    run.requests_used = budget.used
    run.completed_at = datetime.now(timezone.utc)
    if fatal and not found:
        run.status = "failed"
    elif run.errors:
        run.status = "partial"
    else:
        run.status = "succeeded"
    log.info(
        "Discovery %s: %s, %d results (%d new), %d/%d requests, %d detail calls reused",
        run.id, run.status, len(run.results), run.counts()["new"],
        run.requests_used, max_requests, run.details_reused,
    )
    return run
