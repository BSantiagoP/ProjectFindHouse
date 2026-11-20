"""Commute estimate until Google Routes is available.

total = walk from the property to the nearest NY-bound bus stop / rail station (NJ Transit GTFS)
      + the town's researched stop-to-7-WTC time (editable in preferences).
"""

import json
import logging
import math
from pathlib import Path
from typing import Protocol

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


class GtfsStopFinder:
    """Nearest NJ Transit stop from a prebuilt GTFS extract (scripts/build_transit_stops.py).

    Bus: only stops served by New York-bound trips. Rail: stations. No network calls.
    Replaced OpenStreetMap/Overpass after it failed repeatedly (502s/timeouts) on 2026-11-20.
    """

    DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "transit_stops.json"

    def __init__(self, path: Path = DEFAULT_PATH) -> None:
        data = json.loads(path.read_text())
        self._stops = {"bus": data["bus_ny_bound"], "rail": data["rail"]}

    def nearest(self, lat: float, lon: float, access: str) -> tuple[str, int] | None:
        best: tuple[str, int] | None = None
        for s in self._stops.get(access, []):
            d = haversine_m(lat, lon, s["lat"], s["lon"])
            if d <= SEARCH_RADIUS_M and (best is None or d < best[1]):
                routes = s.get("routes")
                label = f"{s['name']} (bus {', '.join(routes[:4])})" if routes else f"{s['name']} station"
                best = (label, int(d))
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
