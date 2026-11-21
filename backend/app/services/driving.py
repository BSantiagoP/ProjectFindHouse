"""Driving times to configured DRIVE destinations (OpenStreetMap road network).

Primary: LocationIQ Directions (API key, 5,000 free requests/day). Fallback: the public OSRM
demo server. Free-flow times (no live traffic): rush hour will be slower. One request per
property and destination, cached on the Property.
"""

import logging
from typing import Protocol

import httpx

from app.models.analysis import DriveEstimate
from app.models.preferences import CommuteMode, SearchPreferences
from app.models.property import Property

log = logging.getLogger(__name__)


class Router(Protocol):
    def drive(self, lat: float, lon: float, dest_lat: float, dest_lon: float) -> tuple[float, float]:
        """(minutes, miles)."""
        ...


class LocationIQRouter:
    name = "locationiq"
    URL = "https://us1.locationiq.com/v1/directions/driving"

    MIN_INTERVAL = 0.6  # free plan: 2 requests/second

    def __init__(self, api_key: str, client: httpx.Client | None = None, sleep=None, clock=None) -> None:
        import time

        if not api_key:
            raise ValueError("LOCATIONIQ_API_KEY is not set")
        self._key = api_key
        self._client = client or httpx.Client(timeout=30)
        self._sleep = sleep or time.sleep
        self._clock = clock or time.monotonic
        self._last = -1e9

    def drive(self, lat: float, lon: float, dest_lat: float, dest_lon: float) -> tuple[float, float]:
        for attempt in range(3):
            wait = self.MIN_INTERVAL - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
            self._last = self._clock()
            r = self._client.get(f"{self.URL}/{lon},{lat};{dest_lon},{dest_lat}",
                                 params={"key": self._key, "overview": "false"})
            if r.status_code != 429:
                break
            self._sleep(1.5 * (attempt + 1))  # rate limited: back off and retry
        if r.status_code != 200:
            raise RuntimeError(f"LocationIQ HTTP {r.status_code}")  # never echo the URL (contains the key)
        d = r.json()
        if d.get("code") != "Ok" or not d.get("routes"):
            raise RuntimeError(f"LocationIQ: {d.get('code')}")
        route = d["routes"][0]
        return route["duration"] / 60, route["distance"] / 1609.344


class FallbackRouter:
    """Try routers in order; the estimate records which one answered."""

    def __init__(self, *routers) -> None:
        self.routers = [r for r in routers if r is not None]
        self.name = self.routers[0].name if self.routers else "none"
        self.last_used: str | None = None

    def drive(self, lat: float, lon: float, dest_lat: float, dest_lon: float) -> tuple[float, float]:
        errors = []
        for r in self.routers:
            try:
                out = r.drive(lat, lon, dest_lat, dest_lon)
                self.last_used = r.name
                return out
            except Exception as exc:
                errors.append(f"{r.name}: {exc}")
        raise RuntimeError("; ".join(errors) or "no router configured")


class OsrmRouter:
    name = "osrm"

    URL = "https://router.project-osrm.org/route/v1/driving"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=30, headers={"User-Agent": "HomeScout/0.1 (personal home search)"})

    def drive(self, lat: float, lon: float, dest_lat: float, dest_lon: float) -> tuple[float, float]:
        r = self._client.get(f"{self.URL}/{lon},{lat};{dest_lon},{dest_lat}", params={"overview": "false"})
        r.raise_for_status()
        d = r.json()
        if d.get("code") != "Ok" or not d.get("routes"):
            raise RuntimeError(f"OSRM: {d.get('code')}")
        route = d["routes"][0]
        return route["duration"] / 60, route["distance"] / 1609.344


def estimate_drives(prop: Property, prefs: SearchPreferences, router: Router | None) -> list[DriveEstimate]:
    """Keeps already-computed destinations; computes missing ones."""
    preferred = getattr(router, "name", None)
    # Reuse a computed time unless a better (preferred) provider is now available.
    have = {d.address: d for d in prop.drives if d.minutes is not None and (preferred in (None, d.source))}
    out: list[DriveEstimate] = []
    for dest in prefs.commute_destinations:
        if dest.mode is not CommuteMode.DRIVE or dest.lat is None or dest.lon is None:
            continue
        if dest.address in have:
            out.append(have[dest.address])
            continue
        est = DriveEstimate(destination=dest.label, address=dest.address, minutes=None, miles=None)
        if router is not None and prop.latitude is not None and prop.longitude is not None:
            try:
                minutes, miles = router.drive(prop.latitude, prop.longitude, dest.lat, dest.lon)
                source = getattr(router, "last_used", None) or getattr(router, "name", "osrm")
                est = est.model_copy(update={"minutes": max(1, round(minutes)), "miles": round(miles, 1), "source": source})
            except Exception as exc:
                log.warning("Drive time failed for %s: %s", prop.address.raw, exc)
                est = est.model_copy(update={"error": str(exc)[:200]})
        out.append(est)
    return out
