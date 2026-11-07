"""
Supermarkets API blueprint.

Provides GET /api/supermarkets: Coles, Woolworths, Aldi, Foodworks and IGA stores around
Sydney and the intercity network, from data/supermarkets/supermarkets.geojson
(written by scripts/download_supermarkets.py from AllThePlaces, which scrapes each
retailer's store locator; Foodworks and IGA stores are geocoded from their addresses).
Independent of GTFS.

Query parameters:
    full_store (str, optional): "true" for full supermarkets only, "false" for
        everything else (Coles Local, Woolworths Metro, Foodworks, IGA, IGA Local Grocer/Xpress). Default: all.

Response body (GeoJSON FeatureCollection):
{
    "type": "FeatureCollection",
    "metadata": {
        "source": "AllThePlaces (CC0), ...",
        "geocoding": "Stores without coordinates were located from their address: ...",
        "alltheplaces_run": "2026-10-17-13-32-31",
        "downloaded_at": "2026-10-25T01:23:45+00:00",
        "bbox": [-35.0, 149.6, -32.0, 152.3],
        "store_types": {"coles": {"chain": "Coles", "label": "Coles", "full_store": true},
                        "foodworks": {..., "full_store": false, "note": "Independent grocer: ..."}, ...},
        "counts": {"coles": 182, "coles_local": 12, ...}
    },
    "features": [
        {
            "type": "Feature",
            "properties": {
                "id": "coles_au:4417",
                "name": "Coles Local Chatswood",
                "chain": "Coles",                    // Coles | Woolworths | Aldi | Foodworks | IGA
                "store_type": "coles_local",         // coles | coles_local | woolworths | woolworths_metro | aldi | foodworks |
                                                     // romeos_iga | romeos_small | supa_iga | iga | iga_local
                "store_type_label": "Coles Local",
                "full_store": false,                 // false for Coles Local, Woolworths Metro, Foodworks, romeos_small, iga, iga_local
                "address": "...", "opening_hours": "Mo-Su 06:00-22:00", "website": "...",
                "location_accuracy": "store"         // store (locator coords) | address (geocoded) | street (approximate)
            },
            "geometry": {"type": "Point", "coordinates": [151.18, -33.79]}
        },
        ...
    ]
}
"""

import json

from flask import Blueprint, jsonify, request, send_file

from config import PROJECT_ROOT

supermarkets_bp = Blueprint("supermarkets", __name__, url_prefix="/api")

SUPERMARKETS_PATH = PROJECT_ROOT / "data" / "supermarkets" / "supermarkets.geojson"
ISOCHRONE_MINUTES = 10
ISOCHRONES_PATH = (
    PROJECT_ROOT
    / "data"
    / "supermarkets"
    / f"supermarket_isochrones_{ISOCHRONE_MINUTES}min_walk.geojson"
)


@supermarkets_bp.route("/supermarkets", methods=["GET"])
def supermarkets():
    if not SUPERMARKETS_PATH.exists():
        return jsonify(
            {
                "error": "Supermarket locations haven't been downloaded yet.",
                "hint": "Run: uv run python scripts/download_supermarkets.py",
            }
        ), 404

    full_store = request.args.get("full_store")
    if full_store not in (None, "true", "false"):
        return jsonify(
            {
                "error": f"Invalid full_store: {full_store!r}",
                "hint": 'Use "true" (full supermarkets) or "false" (small formats).',
            }
        ), 400

    # Read on every request (~200 KB) so a re-download shows up without a restart
    collection = json.loads(SUPERMARKETS_PATH.read_text(encoding="utf-8"))
    if full_store is not None:
        want = full_store == "true"
        collection["features"] = [
            f for f in collection["features"] if f["properties"]["full_store"] == want
        ]
    return jsonify(collection)


@supermarkets_bp.route("/supermarkets/isochrones", methods=["GET"])
def supermarket_isochrones():
    """
    Precomputed 10-minute walking isochrones around every store, as a GeoJSON
    FeatureCollection (one Polygon per store; properties: id, name, store_type,
    full_store, minutes, speed, reachable_nodes, fallback_circle). Feature ids
    match /api/supermarkets. 404 until the script has run.
    """
    if not ISOCHRONES_PATH.exists():
        return jsonify(
            {
                "error": "Supermarket walking areas haven't been generated yet.",
                "hint": "Run: uv run python scripts/generate_supermarket_walk_areas.py",
            }
        ), 404
    # max_age=0: the browser revalidates, so a regenerated file shows up on reload
    return send_file(ISOCHRONES_PATH, mimetype="application/geo+json", max_age=0)
