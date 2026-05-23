"""
Stops API blueprint.

Provides a generic /api/stops endpoint for querying any GTFS stop type
by location_type value.

GTFS location_type reference:
    0 (or missing) — Stop/Platform  (where passengers board)
    1              — Station        (parent structure containing platforms)
    2              — Entrance/Exit
    3              — Generic Node   (path waypoint inside a station)
    4              — Boarding Area  (specific area on a platform)
"""

import pandas as pd
from flask import Blueprint, jsonify, request

from gtfs.loader import get_feed

stops_bp = Blueprint("stops", __name__, url_prefix="/api")

# Human-readable labels for each GTFS location_type value, used in responses
_LOCATION_TYPE_LABELS = {
    0: "platform",
    1: "station",
    2: "entrance_exit",
    3: "generic_node",
    4: "boarding_area",
}


@stops_bp.route("/stops", methods=["GET"])
def get_stops():
    """
    Return stops from the GTFS feed, optionally filtered by location_type. This is generic version of stations

    Query parameters:
        search        (str, optional): Case-insensitive substring filter on stop_name.
        mode          (str, optional): Transport mode key. Defaults to sydney_trains.
        location_type (int, optional): GTFS location_type to filter by.
                                       If omitted, all stop types are returned.
                                       Common values:
                                         0 = platforms/stops
                                         1 = stations
                                         2 = entrances/exits

    Returns:
        JSON object:
        {
            "count": <int>,
            "mode": "<mode>",
            "location_type_filter": <int|null>,
            "stops": [
                {
                    "stop_id": "...",
                    "stop_name": "...",
                    "stop_lat": <float|null>,
                    "stop_lon": <float|null>,
                    "parent_station": "<stop_id>|null",
                    "location_type": <int|null>,
                    "location_type_label": "<label>|null"
                },
                ...
            ]
        }
    """
    search_query = request.args.get("search", "").strip()
    mode = request.args.get("mode", "sydney_trains")

    # Parse the optional location_type filter
    location_type_filter: int | None = None
    raw_location_type = request.args.get("location_type", "").strip()
    if raw_location_type:
        try:
            location_type_filter = int(raw_location_type)
        except ValueError:
            return jsonify(
                {
                    "error": f"Invalid location_type '{raw_location_type}'. Must be an integer (0–4)."
                }
            ), 400

    try:
        feed = get_feed(mode)
    except (ValueError, EnvironmentError, RuntimeError) as e:
        return jsonify({"error": str(e)}), 500

    stops_df = feed.stops.copy()

    # Apply location_type filter if provided
    if location_type_filter is not None and "location_type" in stops_df.columns:
        stops_df = stops_df[stops_df["location_type"] == location_type_filter]
    # If location_type=0 was requested but the column is missing, all stops are platforms by default
    # so we return everything — no filtering needed.

    # Apply name search filter
    if search_query:
        stops_df = stops_df[
            stops_df["stop_name"].str.contains(search_query, case=False, na=False)
        ]

    # Sort by name for consistent output
    stops_df = stops_df.sort_values("stop_name")

    # Select only the columns we want to expose
    columns_to_keep = [
        "stop_id",
        "stop_name",
        "stop_lat",
        "stop_lon",
        "parent_station",
        "location_type",
    ]
    result_df = stops_df.reindex(columns=columns_to_keep)

    # Replace any remaining float NaN (stop_lat/stop_lon) with None for JSON
    result_df = result_df.where(pd.notnull(result_df), None)

    records = result_df.to_dict(orient="records")

    # Attach a human-readable label for each stop's location_type
    for record in records:
        lt = record.get("location_type")
        record["location_type_label"] = (
            _LOCATION_TYPE_LABELS.get(lt) if lt is not None else None
        )

    return jsonify(
        {
            "count": len(records),
            "mode": mode,
            "location_type_filter": location_type_filter,
            "stops": records,
        }
    )
