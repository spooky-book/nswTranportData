"""
Rail network API blueprint.

Provides GET /api/rail-network, which returns every train and metro station with
the lines that serve it, plus each line's track geometry, for the transport map
page (/map/transport).

Stations and lines come from two feeds:
- sydney_trains: Sydney Trains (T lines) and NSW TrainLink intercity and regional
  trains. NSW TrainLink routes whose route_desc starts with "NSW TrainLink" are
  regional (XPT/Xplorer); the rest are intercity.
- sydney_metro: Sydney Metro.

Query parameters: none.

Response body (JSON):
{
    "categories": {
        "sydney_trains": {"label": "Sydney Trains", "color": "#F6891F"},
        ...
    },
    "stations": [
        {
            "stop_id": "200060",
            "stop_name": "Central Station",
            "lat": -33.8840,
            "lon": 151.2063,
            "categories": ["intercity", "metro", "regional", "sydney_trains"],
            "lines": ["BMT", "CCN", "M1", "T1", ...]
        },
        ...
    ],
    "lines": {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "line": "T1",
                    "name": "T1 North Shore Line",
                    "color": "#F99D1C",
                    "category": "sydney_trains"
                },
                "geometry": { ... GeoJSON MultiLineString ... }
            },
            ...
        ]
    }
}

The result is built once per process and cached, like the feeds it is built from.
"""

import threading

import numpy as np
import shapely
from flask import Blueprint, jsonify
from shapely.geometry import LineString, mapping

from gtfs.loader import get_feed

rail_network_bp = Blueprint("rail_network", __name__, url_prefix="/api")

CATEGORIES = {
    "sydney_trains": {"label": "Sydney Trains", "color": "#F6891F"},
    "metro": {"label": "Sydney Metro", "color": "#168388"},
    "intercity": {"label": "Intercity (NSW TrainLink)", "color": "#D11F2F"},
    "regional": {"label": "Regional (NSW TrainLink)", "color": "#732A82"},
}

FEED_MODES = ("sydney_trains", "sydney_metro")

# Simplification tolerance in degrees (~5 m); keeps the response small.
SIMPLIFY_TOLERANCE = 0.00005
COORD_DECIMALS = 5
MAX_SHAPE_GAP_KM = 20

_network_cache: dict | None = None
_network_lock = threading.Lock()


def _route_category(mode: str, route: dict) -> str:
    """Classify a route as sydney_trains, metro, intercity or regional."""
    if mode == "sydney_metro":
        return "metro"
    if route.get("agency_id") == "SydneyTrains":
        return "sydney_trains"
    if (route.get("route_desc") or "").startswith("NSW TrainLink"):
        return "regional"
    return "intercity"


def _shape_segments(lons: np.ndarray, lats: np.ndarray) -> list[LineString]:
    """
    Split a shape into LineStrings wherever consecutive points are more than
    MAX_SHAPE_GAP_KM apart. Some shapes jump straight to a far terminus with no
    track geometry in between (e.g. Broken Hill -> Perth), which would otherwise
    draw as one long straight line.
    """
    dx = np.diff(lons) * np.cos(np.radians(lats[:-1])) * 111.32
    dy = np.diff(lats) * 110.57
    breaks = np.flatnonzero(np.hypot(dx, dy) > MAX_SHAPE_GAP_KM) + 1
    return [
        LineString(zip(seg_lons, seg_lats))
        for seg_lons, seg_lats in zip(np.split(lons, breaks), np.split(lats, breaks))
        if len(seg_lons) >= 2
    ]


def _round_coords(coords):
    """Recursively round nested GeoJSON coordinate arrays."""
    if isinstance(coords[0], (int, float)):
        return [round(c, COORD_DECIMALS) for c in coords]
    return [_round_coords(c) for c in coords]


def _build_network() -> dict:
    stations: dict[str, dict] = {}
    line_meta: dict[str, dict] = {}
    line_geoms: dict[str, list[LineString]] = {}

    for mode in FEED_MODES:
        feed = get_feed(mode)

        # Routes without a short name are "Out Of Service" trips
        routes = feed.routes[feed.routes["route_short_name"].notna()].copy()
        routes["category"] = [
            _route_category(mode, r) for r in routes.to_dict("records")
        ]

        trips = feed.trips.merge(
            routes[["route_id", "route_short_name", "category"]], on="route_id"
        )

        # Metro's route_desc is just "Sydney Metro Network"; its long name is the line name
        name_cols = (
            ("route_long_name", "route_desc")
            if mode == "sydney_metro"
            else ("route_desc", "route_long_name")
        )
        for r in routes.drop_duplicates("route_short_name").to_dict("records"):
            line_meta.setdefault(
                r["route_short_name"],
                {
                    "line": r["route_short_name"],
                    "name": r.get(name_cols[0])
                    or r.get(name_cols[1])
                    or r["route_short_name"],
                    "color": f"#{r['route_color']}"
                    if r.get("route_color")
                    else CATEGORIES[r["category"]]["color"],
                    "category": r["category"],
                },
            )

        # Station membership: stop_times reference platforms, so map them to parent stations
        served = (
            feed.stop_times[["trip_id", "stop_id"]]
            .drop_duplicates()
            .merge(trips[["trip_id", "route_short_name", "category"]], on="trip_id")[
                ["stop_id", "route_short_name", "category"]
            ]
            .drop_duplicates()
        )
        stops = feed.stops.set_index("stop_id")
        served["station_id"] = (
            served["stop_id"].map(stops["parent_station"]).fillna(served["stop_id"])
        )

        for station_id, group in served.groupby("station_id"):
            if station_id not in stops.index:
                continue
            stop = stops.loc[station_id]
            entry = stations.setdefault(
                station_id,
                {
                    "stop_id": station_id,
                    "stop_name": stop["stop_name"],
                    "lat": float(stop["stop_lat"]),
                    "lon": float(stop["stop_lon"]),
                    "categories": set(),
                    "lines": set(),
                },
            )
            entry["categories"].update(group["category"])
            entry["lines"].update(group["route_short_name"])

        # Line geometry: the segments of every distinct shape used by the line
        if feed.shapes is not None:
            shape_ids = (
                trips[["route_short_name", "shape_id"]].dropna().drop_duplicates()
            )
            shapes = feed.shapes.sort_values(["shape_id", "shape_pt_sequence"])
            shape_segments = {
                shape_id: _shape_segments(
                    pts["shape_pt_lon"].to_numpy(dtype=float),
                    pts["shape_pt_lat"].to_numpy(dtype=float),
                )
                for shape_id, pts in shapes.groupby("shape_id")
            }
            for line, shape_id in shape_ids.itertuples(index=False):
                line_geoms.setdefault(line, []).extend(shape_segments.get(shape_id, []))

    features = []
    for line, geoms in sorted(line_geoms.items()):
        if not geoms:
            continue
        merged = shapely.line_merge(shapely.union_all(geoms)).simplify(
            SIMPLIFY_TOLERANCE
        )
        geometry = mapping(merged)
        geometry["coordinates"] = _round_coords(geometry["coordinates"])
        features.append(
            {"type": "Feature", "properties": line_meta[line], "geometry": geometry}
        )

    station_list = [
        {**s, "categories": sorted(s["categories"]), "lines": sorted(s["lines"])}
        for s in sorted(stations.values(), key=lambda s: s["stop_name"])
    ]

    return {
        "categories": CATEGORIES,
        "stations": station_list,
        "lines": {"type": "FeatureCollection", "features": features},
    }


def get_network() -> dict:
    """Build the rail network once per process (double-checked locking)."""
    global _network_cache
    if _network_cache is None:
        with _network_lock:
            if _network_cache is None:
                _network_cache = _build_network()
    return _network_cache


@rail_network_bp.route("/rail-network", methods=["GET"])
def rail_network():
    """Return train and metro stations with their lines, plus line geometry."""
    try:
        network = get_network()
    except (ValueError, EnvironmentError, RuntimeError) as e:
        return jsonify(
            {
                "error": str(e),
                "hint": "Set TRANSPORT_NSW_API_KEY so today's sydney_trains and sydney_metro feeds can be downloaded.",
            }
        ), 500
    return jsonify(network)
