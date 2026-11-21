"""Driving times to configured DRIVE destinations via the public OSRM router (OpenStreetMap).

Free-flow times (no live traffic): rush hour will be slower. One request per property and
destination, cached on the Property.
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


class OsrmRouter:
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
    have = {d.address: d for d in prop.drives if d.minutes is not None}
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
                est = est.model_copy(update={"minutes": max(1, round(minutes)), "miles": round(miles, 1)})
            except Exception as exc:
                log.warning("Drive time failed for %s: %s", prop.address.raw, exc)
                est = est.model_copy(update={"error": str(exc)[:200]})
        out.append(est)
    return out
