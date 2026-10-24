"""
Precompute 15-minute walking isochrones around every train and metro station for
the (temporary) Desirable Property Locator page.

The walking graph needs several GB of RAM, so this runs in its own short-lived
process instead of inside the server, and writes one GeoJSON file that the page
loads. Station coordinates come from the running server's /api/rail-network, so
start the server first.

Usage (from the project root):
    uv run python scripts/generate_property_isochrones.py

Writes data/property_locator/station_isochrones_15min_walk.geojson. Progress is
saved as it goes; re-running skips stations already done (delete the file to
start over).
"""

import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from api.isochrone import compute_isochrone, get_graph  # noqa: E402
from api.property_locator import ISOCHRONE_MINUTES, ISOCHRONES_PATH  # noqa: E402

API_BASE_URL = "http://localhost:5000/api"
WALK_SPEED = 1.4  # m/s
RESOLUTION = "high"
SIMPLIFY_TOLERANCE = 0.00005  # degrees (~5 m)
SAVE_EVERY = 25


def round_coords(coords):
    if isinstance(coords[0], (int, float)):
        return [round(c, 5) for c in coords]
    return [round_coords(c) for c in coords]


def save(features: dict[str, dict]) -> None:
    ISOCHRONES_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = ISOCHRONES_PATH.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"type": "FeatureCollection", "features": list(features.values())}),
        encoding="utf-8",
    )
    tmp.replace(ISOCHRONES_PATH)


def main():
    stations = requests.get(f"{API_BASE_URL}/rail-network", timeout=600).json()[
        "stations"
    ]

    features: dict[str, dict] = {}
    if ISOCHRONES_PATH.exists():
        for f in json.loads(ISOCHRONES_PATH.read_text(encoding="utf-8"))["features"]:
            features[f["properties"]["stop_id"]] = f
    todo = [s for s in stations if s["stop_id"] not in features]
    print(f"{len(stations)} stations, {len(features)} already done, {len(todo)} to go")
    if not todo:
        return

    print("Loading walking graph (about a minute)...")
    graph = get_graph()

    start = time.time()
    for i, s in enumerate(todo, 1):
        try:
            result = compute_isochrone(
                graph, s["lat"], s["lon"], WALK_SPEED, ISOCHRONE_MINUTES, RESOLUTION
            )
        except Exception as e:  # keep going; a missing station just has no walking area
            print(f"  {s['stop_name']}: failed ({e})")
            continue

        geometry = result["polygon"].simplify(SIMPLIFY_TOLERANCE).__geo_interface__
        features[s["stop_id"]] = {
            "type": "Feature",
            "properties": {
                "stop_id": s["stop_id"],
                "name": s["stop_name"],
                "minutes": ISOCHRONE_MINUTES,
                "speed": WALK_SPEED,
                "reachable_nodes": result["reachable_nodes"],
                "fallback_circle": result["fallback_circle"],
            },
            "geometry": {
                "type": geometry["type"],
                "coordinates": round_coords(geometry["coordinates"]),
            },
        }

        if i % SAVE_EVERY == 0 or i == len(todo):
            save(features)
            rate = (time.time() - start) / i
            print(
                f"  {i}/{len(todo)} done ({rate:.1f} s each, ~{rate * (len(todo) - i) / 60:.0f} min left)"
            )

    print(f"Saved {len(features)} isochrones to {ISOCHRONES_PATH}")


if __name__ == "__main__":
    main()
