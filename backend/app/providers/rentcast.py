"""RentCast long-term rent estimates for the RENTAL units only (owner lives in one unit).

Live check 2026-11-20: a whole-property request for a 2-family returned whole-building rent
($4,260 for 5bd/3ba), which would overstate rent offset. So we request per rental unit,
passing that unit's bedrooms/bathrooms, as an apartment-style rental.
Every request is reserved against a monthly cap first (overage is billed per request).
"""

import logging
from collections.abc import Callable
from datetime import date
from typing import Any

import httpx

from app.models.analysis import RentEstimate, UnitLayout, UnitRent
from app.models.preferences import OwnerUnit
from app.models.property import Property, PropertyType

log = logging.getLogger(__name__)

ReserveFn = Callable[[str, str, int], bool]  # (provider, period, limit) -> reserved?


class RentCastAuthError(RuntimeError):
    pass


class RentCastClient:
    name = "rentcast"

    def __init__(self, api_key: str, *, reserve: ReserveFn, monthly_cap: int,
                 client: httpx.Client | None = None, today: Callable[[], date] = date.today) -> None:
        self._client = client or httpx.Client(base_url="https://api.rentcast.io/v1", timeout=60)
        self._headers = {"X-Api-Key": api_key, "Accept": "application/json"}
        self._reserve = reserve
        self._cap = monthly_cap
        self._today = today
        self.disabled_reason: str | None = None  # set after an auth failure; no more requests this run

    def _unit_rent(self, address: str, unit: UnitLayout) -> UnitRent | None:
        """None means the monthly cap is reached (no request made)."""
        if not self._reserve(self.name, self._today().strftime("%Y-%m"), self._cap):
            return None
        params: dict[str, Any] = {"address": address, "propertyType": "Apartment", "compCount": 10}
        if unit.bedrooms is not None:
            params["bedrooms"] = unit.bedrooms
        if unit.bathrooms is not None:
            params["bathrooms"] = unit.bathrooms
        resp = self._client.get("/avm/rent/long-term", params=params, headers=self._headers)
        if resp.status_code in (401, 403):
            # Auth failures are not billable requests; stop the run's rent lookups loudly.
            raise RentCastAuthError(f"RentCast HTTP {resp.status_code}: clave API rechazada")
        if resp.status_code != 200:
            raise RuntimeError(f"RentCast HTTP {resp.status_code}: {resp.text[:200]}")
        d = resp.json()
        return UnitRent(
            label=unit.label, bedrooms=unit.bedrooms, bathrooms=unit.bathrooms,
            rent=_int(d.get("rent")), range_low=_int(d.get("rentRangeLow")), range_high=_int(d.get("rentRangeHigh")),
        )

    def estimate(self, prop: Property, owner_unit: OwnerUnit) -> RentEstimate:
        rental = rental_units(prop, owner_unit)
        if rental is None:
            return RentEstimate(status="not_estimated", reason="Distribución o número de recámaras desconocido; no se puede estimar la renta")
        owner, units = rental
        if not units:
            return RentEstimate(status="not_estimated", reason="Sin unidades para alquilar (unifamiliar)", owner_unit=owner)
        if self.disabled_reason:
            return RentEstimate(status="not_estimated", reason=f"Error de RentCast: {self.disabled_reason}", owner_unit=owner)
        address = prop.address.raw
        results: list[UnitRent] = []
        for unit in units:
            try:
                r = self._unit_rent(address, unit)
            except RentCastAuthError as exc:
                self.disabled_reason = str(exc)
                return RentEstimate(status="not_estimated", reason=f"Error de RentCast: {exc}", owner_unit=owner)
            except Exception as exc:
                log.warning("RentCast failed for %s %s: %s", address, unit.label, exc)
                return RentEstimate(status="not_estimated", reason=f"Error de RentCast: {exc}", owner_unit=owner)
            if r is None:
                return RentEstimate(status="not_estimated", reason=f"Se alcanzó el límite mensual de RentCast ({self._cap})",
                                    owner_unit=owner, rental_units=results)
            results.append(r)
        if any(r.rent is None for r in results):
            return RentEstimate(status="not_estimated", reason="RentCast no devolvió una estimación",
                                owner_unit=owner, rental_units=results)
        return RentEstimate(status="estimated", owner_unit=owner, rental_units=results,
                            monthly_rent_total=sum(r.rent for r in results))


def rental_units(prop: Property, owner_unit: OwnerUnit) -> tuple[str | None, list[UnitLayout]] | None:
    """(owner unit label, rental units). None if the layout is unknown."""
    if prop.property_type is PropertyType.SINGLE_FAMILY:
        return None, []
    units = prop.llm_analysis.units if prop.llm_analysis else []
    if not units or (prop.units is not None and len(units) != prop.units):
        return None
    if any(u.bedrooms is None for u in units):
        return None  # can't pick the owner unit or price a rental without bedroom counts
    ordered = sorted(units, key=lambda u: (u.bedrooms or 0, u.bathrooms or 0),
                     reverse=owner_unit is OwnerUnit.LARGEST)
    return ordered[0].label, ordered[1:]


def _int(v: Any) -> int | None:
    try:
        return int(round(float(v))) if v is not None else None
    except (TypeError, ValueError):
        return None
