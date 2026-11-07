"""
Precompute 10-minute walking isochrones around every store in
data/supermarkets/supermarkets.geojson (from download_supermarkets.py).

10 minutes (~800 m) is the usual limit for walking to the shops and carrying
the groceries home. Small formats (Coles Local, Woolworths Metro) and Foodworks
are included and keep their full_store flag, so the map can show or hide them.

Like generate_property_isochrones.py, this loads the multi-GB walking graph in
its own short-lived process so the server never has to. No server needed.

Usage (from the project root):
    uv run python scripts/generate_supermarket_walk_areas.py

Writes data/supermarkets/supermarket_isochrones_10min_walk.geojson, served by
GET /api/supermarkets/isochrones. Progress is saved as it goes; re-running skips
stores already done (delete the file to start over, e.g. after re-downloading
the stores).
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from api.isochrone import compute_isochrone, get_graph  # noqa: E402
from api.supermarkets import (  # noqa: E402
    ISOCHRONE_MINUTES,
    ISOCHRONES_PATH,
    SUPERMARKETS_PATH,
)

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
    if not SUPERMARKETS_PATH.exists():
        sys.exit(
            "No store list yet. Run: uv run python scripts/download_supermarkets.py"
        )
    stores = json.loads(SUPERMARKETS_PATH.read_text(encoding="utf-8"))["features"]

    features: dict[str, dict] = {}
    if ISOCHRONES_PATH.exists():
        for f in json.loads(ISOCHRONES_PATH.read_text(encoding="utf-8"))["features"]:
            features[f["properties"]["id"]] = f
    todo = [s for s in stores if s["properties"]["id"] not in features]
    print(f"{len(stores)} stores, {len(features)} already done, {len(todo)} to go")
    if not todo:
        return

    print("Loading walking graph (about a minute)...")
    graph = get_graph()

    start = time.time()
    for i, store in enumerate(todo, 1):
        p = store["properties"]
        lon, lat = store["geometry"]["coordinates"]
        try:
            result = compute_isochrone(
                graph, lat, lon, WALK_SPEED, ISOCHRONE_MINUTES, RESOLUTION
            )
        except Exception as e:  # keep going; a missing store just has no walking area
            print(f"  {p['name']}: failed ({e})")
            continue

        geometry = result["polygon"].simplify(SIMPLIFY_TOLERANCE).__geo_interface__
        features[p["id"]] = {
            "type": "Feature",
            "properties": {
                "id": p["id"],
                "name": p["name"],
                "store_type": p["store_type"],
                "full_store": p["full_store"],
                "minutes": ISOCHRONE_MINUTES,
                "speed": WALK_SPEED,
                "reachable_nodes": result["reachable_nodes"],
                "fallback_circle": result["fallback_circle"],
                "snap_distance_m": round(result["snap_distance_m"], 1),
            },
            "geometry": {
                "type": geometry["type"],
                "coordinates": round_coords(geometry["coordinates"]),
            },
        }

        if i % SAVE_EVERY == 0:
            save(features)
            rate = (time.time() - start) / i
            print(
                f"  {i}/{len(todo)} done ({rate:.1f} s each, ~{rate * (len(todo) - i) / 60:.0f} min left)"
            )

    save(features)
    print(f"Saved {len(features)} isochrones to {ISOCHRONES_PATH}")


if __name__ == "__main__":
    main()
