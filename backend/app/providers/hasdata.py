"""HasData Zillow adapter.

HasData is a third-party scraping service, not an official Zillow API. Production use is
gated on licensing review (plan.md section 2).

Docs: https://docs.hasdata.com/apis/zillow/listing and .../zillow/property
Each successful request costs 10 credits. The response shapes below come from HasData's
published excerpts; field names marked "unverified" must be confirmed with a live call.
"""

import json
import logging
import re
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from app.models.analysis import SoldComp
from app.models.property import (
    Address,
    Feature,
    FeatureSource,
    FeatureState,
    Property,
    PropertyFeatures,
    PropertyType,
)
from app.providers.base import (
    ProviderAuthError,
    ProviderQuotaError,
    ProviderRequestError,
    ProviderUnavailableError,
    RequestBudget,
    SearchQuery,
)
from app.services.address import normalize_street, parse_address

log = logging.getLogger(__name__)

# homeTypes[] request values, confirmed from a live 422 response (2026-11-20). Allowed:
# house, townhome, multiFamily, condo, lot, apartment, manufactured.
_TO_ZILLOW_TYPE = {
    PropertyType.SINGLE_FAMILY: "house",
    PropertyType.MULTI_FAMILY: "multiFamily",
    PropertyType.CONDO: "condo",
    PropertyType.TOWNHOUSE: "townhome",
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

    def search_sold(self, location: str, home_type: str, budget: RequestBudget) -> list[SoldComp]:
        """Recently sold homes (newest first, one page). home_type: 'multiFamily' or 'house'.

        Live check 2026-11-21: records have sold price, beds/baths, coordinates, zestimate and
        daysOnZillow (days since sale for sold homes); square footage is usually missing."""
        payload = self._get("/scrape/zillow/listing",
                            [("keyword", location), ("type", "sold"), ("homeTypes[]", home_type)], budget)
        records, _ = _split_listing_payload(payload, 1)
        comps, seen = [], set()
        for rec in records:
            price = _as_price(rec.get("price"))
            raw = rec.get("addressRaw")
            if price is None or not isinstance(raw, str):
                continue
            addr = _address(rec.get("address"), raw)
            # Same building listed whole and per unit: keep one.
            building = (normalize_street(addr.street or raw), addr.zip_code)
            if building in seen:
                continue
            seen.add(building)
            comps.append(SoldComp(
                address=raw, price=price, beds=_as_float(rec.get("beds")), baths=_as_float(rec.get("baths")),
                square_feet=_as_int(rec.get("area")), latitude=_as_float(rec.get("latitude")),
                longitude=_as_float(rec.get("longitude")), days_since_sold=_as_int(rec.get("daysOnZillow")),
                zestimate=_as_price(rec.get("zestimate")), url=rec.get("url"),
            ))
        return comps

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
        address_raw = rec.get("addressRaw")
        if not address_raw and isinstance(rec.get("address"), dict):
            address_raw = rec["address"].get("addressRaw")
        if not ext_id or not url or not isinstance(address_raw, str):
            log.warning("Skipping HasData record missing id/url/address: %s", rec.get("id"))
            return None

        days = _as_int(rec.get("daysOnZillow"))
        return Property(
            provider=self.name,
            external_id=str(ext_id),
            source_url=url,
            address=_address(rec.get("address"), address_raw),
            latitude=_as_float(rec.get("latitude")),
            longitude=_as_float(rec.get("longitude")),
            photo_urls=_photos(rec.get("photos")),
            town=None,  # resolved by discovery against configured towns
            price=_as_price(rec.get("price")),
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
            ("price", "price", _as_price),
        ):
            if (val := conv(d.get(src))) is not None:
                updates[dst] = val
        area = d.get("area")
        if isinstance(area, dict) and (living := _as_int(area.get("livingArea"))) is not None:
            updates["living_area_sqft"] = living
        if ht := d.get("homeType"):
            updates["property_type"] = _FROM_ZILLOW_TYPE.get(str(ht).upper(), PropertyType.OTHER)
        if isinstance(d.get("highlights"), list):
            updates["highlights"] = [h for h in d["highlights"] if isinstance(h, str)]
        if photos := _photos(d.get("photos")):
            updates["photo_urls"] = photos
        geo = d.get("geo")
        if isinstance(geo, dict):
            updates["latitude"] = _as_float(geo.get("latitude")) or prop.latitude
            updates["longitude"] = _as_float(geo.get("longitude")) or prop.longitude

        reso = d.get("resoData") if isinstance(d.get("resoData"), dict) else {}
        if (tax := _as_int(reso.get("taxAnnualAmount"))) is not None:
            updates["annual_tax"] = tax
        elif (tax := _latest_tax(d.get("taxHistory"))) is not None:
            updates["annual_tax"] = tax
        if not updates.get("listed_date") and (ms := _as_int(reso.get("onMarketDate"))):
            updates["listed_date"] = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()
        if units := _units_from_structure(reso.get("structureType")):
            updates["units"], updates["units_evidence"] = units, f"MLS structure type: {reso['structureType']}"
        updates["features"] = _reso_features(prop.features, reso)
        return prop.model_copy(update=updates)


# ---- helpers ------------------------------------------------------------------

_STREET_PARKING = {"on street", "street", "none"}


def _reso_features(current: PropertyFeatures, reso: dict[str, Any]) -> PropertyFeatures:
    """Map MLS structured facts to features (source=provider).

    Live data showed hasGarage=false on a listing with parkingFeatures=["Garage"] and a
    2-car garage in the description, so hasGarage is never used to mark a garage absent.
    """
    f = current.model_copy(deep=True)

    def ev(field: str) -> str:
        return f"MLS {field}: {json.dumps(reso.get(field))}"

    parking = [str(x) for x in reso.get("parkingFeatures") or [] if x]
    parking_l = [p.lower() for p in parking]
    garage_cap = _as_int(reso.get("garageParkingCapacity")) or 0
    if garage_cap > 0 or any("garage" in p for p in parking_l):
        f.garage = Feature(state=FeatureState.PRESENT, source=FeatureSource.PROVIDER,
                           evidence=ev("parkingFeatures") + (f", garageParkingCapacity: {garage_cap}" if garage_cap else ""))
    if any("driveway" in p or "off street" in p or "off-street" in p for p in parking_l):
        f.driveway = Feature(state=FeatureState.PRESENT, source=FeatureSource.PROVIDER, evidence=ev("parkingFeatures"))
    if parking_l and all(p in _STREET_PARKING for p in parking_l) and garage_cap == 0:
        absent = Feature(state=FeatureState.ABSENT, source=FeatureSource.PROVIDER, evidence=ev("parkingFeatures"))
        f.garage = f.garage if f.garage.is_present else absent
        f.driveway = f.driveway if f.driveway.is_present else absent

    laundry = [str(x).strip() for x in reso.get("laundryFeatures") or [] if x]
    if laundry:
        state = FeatureState.ABSENT if all(x.lower() == "none" for x in laundry) else FeatureState.PRESENT
        f.laundry = Feature(state=state, source=FeatureSource.PROVIDER, evidence=ev("laundryFeatures"))
    return f


def _units_from_structure(val: Any) -> int | None:
    if not isinstance(val, str):
        return None
    m = re.match(r"\s*(\d+)\s*(family|unit)", val, re.I)
    return int(m.group(1)) if m else None


def _address(addr: Any, raw: str) -> Address:
    parsed = parse_address(raw)
    if not isinstance(addr, dict):
        return parsed
    return parsed.model_copy(update={
        "city": addr.get("city") or parsed.city,
        "state": addr.get("state") or parsed.state,
        "zip_code": addr.get("zipcode") or parsed.zip_code,
    })


def _photos(val: Any) -> list[str]:
    if not isinstance(val, list):
        return []
    out = []
    for p in val:
        if isinstance(p, str):
            out.append(p)
        elif isinstance(p, dict) and isinstance(p.get("url"), str):
            out.append(p["url"])
    return out


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
        # Live shape: {"currentPage": 1, "otherPages": {}}; non-empty otherPages => more pages.
        if pagination.get("otherPages") or pagination.get("nextPage") or pagination.get("next"):
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


def _as_price(val: Any) -> int | None:
    """Live data returns price 0 for unpriced listings; treat that as unknown."""
    price = _as_int(val)
    return price if price is not None and price > 0 else None


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
