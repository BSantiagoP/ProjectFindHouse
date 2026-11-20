"""Build app/data/transit_stops.json from NJ Transit GTFS (bus_data.zip, rail_data.zip).

Keeps only bus stops served by New York-bound trips (headsign contains "NEW YORK"),
inside a bounding box around the search towns, plus rail stations in the same box.
Usage: python -I scripts/build_transit_stops.py <bus_data.zip> <rail_data.zip> <out.json>

Data: NJ TRANSIT GTFS (https://www.njtransit.com/developer-tools). Free to use under
NJ TRANSIT's data feed terms; NJ TRANSIT marks/logos are not used.
"""

import csv
import io
import json
import sys
import zipfile
from datetime import date

# Lyndhurst / Cliffside Park / Fairview / Elmwood Park / Saddle Brook, with margin.
BBOX = (40.77, 40.95, -74.16, -73.94)  # lat_min, lat_max, lon_min, lon_max


def rows(z: zipfile.ZipFile, name: str):
    with z.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))


def in_bbox(lat: float, lon: float) -> bool:
    return BBOX[0] <= lat <= BBOX[1] and BBOX[2] <= lon <= BBOX[3]


def main(bus_zip: str, rail_zip: str, out: str) -> None:
    with zipfile.ZipFile(bus_zip) as z:
        route_name = {r["route_id"]: r["route_short_name"] for r in rows(z, "routes.txt")}
        ny_trips = {
            t["trip_id"]: route_name.get(t["route_id"], "?")
            for t in rows(z, "trips.txt")
            if "NEW YORK" in (t.get("trip_headsign") or "").upper()
        }
        stops = {
            s["stop_id"]: s for s in rows(z, "stops.txt")
            if in_bbox(float(s["stop_lat"]), float(s["stop_lon"]))
        }
        served: dict[str, set[str]] = {}
        for st in rows(z, "stop_times.txt"):
            route = ny_trips.get(st["trip_id"])
            if route and st["stop_id"] in stops:
                served.setdefault(st["stop_id"], set()).add(route)

    bus = [
        {"name": stops[sid]["stop_name"].title(), "lat": float(stops[sid]["stop_lat"]),
         "lon": float(stops[sid]["stop_lon"]), "routes": sorted(routes, key=lambda r: (len(r), r))}
        for sid, routes in served.items()
    ]
    with zipfile.ZipFile(rail_zip) as z:
        rail = [
            {"name": s["stop_name"].title(), "lat": float(s["stop_lat"]), "lon": float(s["stop_lon"])}
            for s in rows(z, "stops.txt")
            if in_bbox(float(s["stop_lat"]), float(s["stop_lon"])) and "LIGHT RAIL" not in s["stop_name"].upper()
        ]

    data = {
        "source": "NJ TRANSIT GTFS bus_data.zip + rail_data.zip",
        "built": date.today().isoformat(),
        "bbox": BBOX,
        "bus_ny_bound": sorted(bus, key=lambda s: (s["lat"], s["lon"])),
        "rail": sorted(rail, key=lambda s: s["name"]),
    }
    with open(out, "w") as f:
        json.dump(data, f, indent=1)
    print(f"{len(bus)} NY-bound bus stops, {len(rail)} rail stations -> {out}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
