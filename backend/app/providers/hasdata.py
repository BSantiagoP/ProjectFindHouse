"""HasData Zillow adapter.

HasData is a third-party scraping service, not an official Zillow API. Production use is
gated on licensing review (plan.md section 2).

Docs: https://docs.hasdata.com/apis/zillow/listing and .../zillow/property
Each successful request costs 10 credits. The response shapes below come from HasData's
published excerpts; field names marked "unverified" must be confirmed with a live call.
"""

import logging
import time
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import httpx

from app.models.property import Property, PropertyType
from app.providers.base import (
    ProviderAuthError,
    ProviderQuotaError,
    ProviderRequestError,
    ProviderUnavailableError,
    RequestBudget,
    SearchQuery,
)
from app.services.address import parse_address

log = logging.getLogger(__name__)

# Zillow home-type identifiers. MULTI_FAMILY is unverified for HasData's homeTypes[] filter.
_TO_ZILLOW_TYPE = {
    PropertyType.SINGLE_FAMILY: "SINGLE_FAMILY",
    PropertyType.MULTI_FAMILY: "MULTI_FAMILY",
    PropertyType.CONDO: "CONDO",
    PropertyType.TOWNHOUSE: "TOWNHOUSE",
}
_FROM_ZILLOW_TYPE = {
    "SINGLE_FAMILY": PropertyType.SINGLE_FAMILY,
    "MULTI_FAMILY": PropertyType.MULTI_FAMILY,
    "CONDO": PropertyType.CONDO,
    "TOWNHOUSE": PropertyType.TOWNHOUSE,
    "LOT": PropertyType.LAND,
    "LAND": PropertyType.LAND,
}

_RETRYABLE = {400, 429, 500, 502, 503, 504}


class HasDataProvider:
    name = "hasdata"

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        base_url: str = "https://api.hasdata.com",
        timeout: float = 300.0,
        max_pages: int = 1,
        max_retries: int = 2,
        sleep: Callable[[float], None] = time.sleep,
        today: Callable[[], date] = date.today,
    ) -> None:
        if not api_key:
            raise ProviderAuthError("HASDATA_API_KEY is not set")
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout)
        self._headers = {"x-api-key": api_key, "Content-Type": "application/json"}
        self._max_pages = max_pages
        self._max_retries = max_retries
        self._sleep = sleep
        self._today = today

    # ---- HTTP -----------------------------------------------------------------

    def _get(self, path: str, params: list[tuple[str, str]], budget: RequestBudget) -> Any:
        for attempt in range(self._max_retries + 1):
            budget.spend()
            try:
                resp = self._client.get(path, params=params, headers=self._headers)
            except httpx.TimeoutException as exc:
                # HasData does not charge for timed-out requests.
                budget.used -= 1
                if attempt == self._max_retries:
                    raise ProviderUnavailableError(f"HasData timeout: {exc}") from exc
                self._sleep(2**attempt)
                continue

            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 401:
                raise ProviderAuthError("HasData rejected the API key (401)")
            if resp.status_code == 403:
                raise ProviderQuotaError("HasData account is out of credits (403)")
            if resp.status_code == 422:
                raise ProviderRequestError(f"HasData validation error: {resp.text[:500]}")
            if resp.status_code in _RETRYABLE:
                # 400/504 are documented as uncharged; refund so the cap reflects billing.
                if resp.status_code in (400, 504):
                    budget.used -= 1
                if attempt == self._max_retries:
                    raise ProviderUnavailableError(f"HasData returned {resp.status_code} after retries")
                log.warning("HasData %s on %s, retrying", resp.status_code, path)
                self._sleep(2**attempt)
                continue
            raise ProviderRequestError(f"Unexpected HasData status {resp.status_code}")
        raise ProviderUnavailableError("unreachable")  # pragma: no cover

    # ---- Public API -----------------------------------------------------------

    def search(self, query: SearchQuery, budget: RequestBudget) -> list[Property]:
        results: list[Property] = []
        for page in range(1, self._max_pages + 1):
            params = [
                ("keyword", query.location),
                ("type", "forSale"),
                ("price[max]", str(query.max_price)),
                ("daysOnZillow", str(query.max_days_listed)),
                ("page", str(page)),
            ]
            for pt in query.property_types:
                if pt in _TO_ZILLOW_TYPE:
                    params.append(("homeTypes[]", _TO_ZILLOW_TYPE[pt]))

            payload = self._get("/scrape/zillow/listing", params, budget)
            records, has_next = _split_listing_payload(payload, page)
            for rec in records:
                prop = self.normalize_listing(rec)
                if prop is not None:
                    results.append(prop)
            if not has_next or not records:
                break
        return results

    def enrich(self, prop: Property, budget: RequestBudget) -> Property:
        payload = self._get("/scrape/zillow/property", [("url", str(prop.source_url))], budget)
        if not isinstance(payload, dict):
            return prop
        if payload.get("error") and not payload.get("property"):
            log.info("HasData has no details for %s: %s", prop.source_url, payload["error"])
            return prop
        detail = payload.get("property", payload)
        return self.apply_details(prop, detail)

    # ---- Normalization --------------------------------------------------------

    def normalize_listing(self, rec: dict[str, Any]) -> Property | None:
        ext_id = rec.get("id") or rec.get("zpid")
        url = rec.get("url")
        address_raw = rec.get("addressRaw") or rec.get("address")
        if not ext_id or not url or not isinstance(address_raw, str):
            log.warning("Skipping HasData record missing id/url/address: %s", rec.get("id"))
            return None

        days = _as_int(rec.get("daysOnZillow"))
        return Property(
            provider=self.name,
            external_id=str(ext_id),
            source_url=url,
            address=parse_address(address_raw),
            town=None,  # resolved by discovery against configured towns
            price=_as_int(rec.get("price")),
            property_type=_FROM_ZILLOW_TYPE.get(str(rec.get("homeType", "")).upper(), PropertyType.OTHER)
            if rec.get("homeType")
            else PropertyType.UNKNOWN,
            beds=_as_float(rec.get("beds")),
            baths=_as_float(rec.get("baths")),
            living_area_sqft=_as_int(rec.get("area")),
            days_on_market=days,
            listed_date=self._today() - timedelta(days=days) if days is not None else None,
            status=rec.get("status"),
            provider_estimated_rent=_as_int(rec.get("estimatedRent")),
        )

    def apply_details(self, prop: Property, d: dict[str, Any]) -> Property:
        updates: dict[str, Any] = {"details_fetched": True}
        if isinstance(d.get("description"), str):
            updates["description"] = d["description"]
        if posted := _as_date(d.get("datePosted")):
            updates["listed_date"] = posted
        for src, dst, conv in (
            ("beds", "beds", _as_float),
            ("baths", "baths", _as_float),
            ("yearBuilt", "year_built", _as_int),
            ("price", "price", _as_int),
        ):
            if (val := conv(d.get(src))) is not None:
                updates[dst] = val
        area = d.get("area")
        if isinstance(area, dict) and (living := _as_int(area.get("livingArea"))) is not None:
            updates["living_area_sqft"] = living
        if ht := d.get("homeType"):
            updates["property_type"] = _FROM_ZILLOW_TYPE.get(str(ht).upper(), PropertyType.OTHER)
        if (tax := _latest_tax(d.get("taxHistory"))) is not None:
            updates["annual_tax"] = tax
        return prop.model_copy(update=updates)


# ---- helpers ------------------------------------------------------------------


def _split_listing_payload(payload: Any, page: int) -> tuple[list[dict[str, Any]], bool]:
    """Accept either a bare array or {"properties": [...], "pagination": {...}} (unverified)."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)], False
    if not isinstance(payload, dict):
        return [], False
    records = payload.get("properties") or []
    pagination = payload.get("pagination") or {}
    has_next = False
    if isinstance(pagination, dict):
        if pagination.get("nextPage") or pagination.get("next"):
            has_next = True
        total = _as_int(pagination.get("totalPages"))
        if total is not None and page < total:
            has_next = True
    return [r for r in records if isinstance(r, dict)], has_next


def _latest_tax(history: Any) -> int | None:
    if not isinstance(history, list):
        return None
    paid = [h for h in history if isinstance(h, dict) and _as_int(h.get("taxPaid")) is not None]
    if not paid:
        return None
    latest = max(paid, key=lambda h: _as_int(h.get("time")) or 0)
    return _as_int(latest.get("taxPaid"))


def _as_int(val: Any) -> int | None:
    if val is None or isinstance(val, bool):
        return None
    try:
        return int(round(float(val)))
    except (TypeError, ValueError):
        return None


def _as_float(val: Any) -> float | None:
    if val is None or isinstance(val, bool):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _as_date(val: Any) -> date | None:
    if not isinstance(val, str):
        return None
    try:
        return date.fromisoformat(val[:10])
    except ValueError:
        return None
