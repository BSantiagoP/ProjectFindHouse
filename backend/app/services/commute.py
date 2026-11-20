"""Commute estimate until Google Routes is available.

total = walk from the property to the nearest bus stop / rail station (OpenStreetMap)
      + the town's researched stop-to-7-WTC time (editable in preferences).
"""

import logging
import math
from typing import Protocol

import httpx

from app.models.analysis import CommuteEstimate
from app.models.preferences import SearchPreferences
from app.models.property import Property

log = logging.getLogger(__name__)

WALK_METERS_PER_MIN = 80
STREET_DETOUR_FACTOR = 1.25  # straight-line -> street distance
SEARCH_RADIUS_M = 2000


class StopFinder(Protocol):
    def nearest(self, lat: float, lon: float, access: str) -> tuple[str, int] | None:
        """(stop name, straight-line meters) or None."""
        ...


class OverpassStopFinder:
    # Public Overpass servers are often busy (live run 2026-11-20: 502s and timeouts),
    # so try mirrors in turn with a short pause between attempts.
    URLS = (
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass.private.coffee/api/interpreter",
    )

    def __init__(self, client: httpx.Client | None = None, sleep=None) -> None:
        import time

        self._client = client or httpx.Client(timeout=40, headers={"User-Agent": "HomeScout/0.1 (personal home search)"})
        self._sleep = sleep or time.sleep

    def _post(self, query: str) -> dict:
        last: Exception | None = None
        for attempt, url in enumerate(self.URLS):
            try:
                resp = self._client.post(url, data={"data": query})
                resp.raise_for_status()
                return resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                last = exc
                log.info("Overpass %s failed (%s), trying next", url, exc)
                self._sleep(1 + attempt)
        raise RuntimeError(f"All Overpass servers failed: {last}")

    def nearest(self, lat: float, lon: float, access: str) -> tuple[str, int] | None:
        around = f"(around:{SEARCH_RADIUS_M},{lat},{lon})"
        if access == "rail":
            body = f'node{around}[railway~"^(station|halt)$"];'
        else:
            body = f"node{around}[highway=bus_stop];node{around}[public_transport=platform][bus=yes];"
        query = f"[out:json][timeout:25];({body});out body;"
        best: tuple[str, int] | None = None
        for el in self._post(query).get("elements", []):
            d = haversine_m(lat, lon, el["lat"], el["lon"])
            name = (el.get("tags") or {}).get("name") or "unnamed stop"
            if best is None or d < best[1]:
                best = (name, int(d))
        return best


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def estimate_commute(prop: Property, prefs: SearchPreferences, finder: StopFinder | None) -> CommuteEstimate | None:
    if prop.town is None or prop.town not in prefs.town_commutes:
        return None
    town = prefs.town_commutes[prop.town]
    dest = prefs.commute_destinations[0].label if prefs.commute_destinations else "destination"
    est = CommuteEstimate(destination=dest, town_minutes=town.minutes, route=town.route)
    if finder is None or prop.latitude is None or prop.longitude is None:
        return est  # walk unknown: total stays None (not rewarded)
    try:
        found = finder.nearest(prop.latitude, prop.longitude, town.access)
    except Exception as exc:
        log.warning("Stop lookup failed for %s: %s", prop.address.raw, exc)
        return est.model_copy(update={"nearest_stop": f"lookup failed: {exc}"[:200]})
    if found is None:
        return est.model_copy(update={"nearest_stop": f"none within {SEARCH_RADIUS_M} m"})
    name, meters = found
    walk_m = int(meters * STREET_DETOUR_FACTOR)
    walk_min = math.ceil(walk_m / WALK_METERS_PER_MIN)
    return est.model_copy(update={
        "nearest_stop": name, "walk_meters": walk_m, "walk_minutes": walk_min,
        "total_minutes": town.minutes + walk_min,
    })
