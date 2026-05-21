"""
Stations API blueprint.

Provides endpoints for querying GTFS stations (location_type == 1).
"""

import pandas as pd
from flask import Blueprint, jsonify, request

from gtfs.loader import get_feed

stations_bp = Blueprint("stations", __name__, url_prefix="/api")


@stations_bp.route("/stations", methods=["GET"])
def get_stations():
    """
    Return all stations from the GTFS feed.

    Query parameters:
            search (str, optional): Filter stations by name (case-insensitive substring match).
            mode (str, optional): Transport mode to query. Defaults to sydney_trains.

    Returns:
            JSON array of station objects with fields:
            - stop_id
            - stop_name
            - stop_lat
            - stop_lon
            - parent_station
            - location_type
    """
    search_query = request.args.get("search", "").strip()
    mode = request.args.get("mode", "sydney_trains")

    try:
        feed = get_feed(mode)
    except (ValueError, EnvironmentError, RuntimeError) as e:
        return jsonify({"error": str(e)}), 500

    stops_df = feed.stops.copy()

    # In GTFS, location_type 1 = Station.
    # Some feeds may not have location_type set (None defaults to 0 = Stop/Platform).
    # Try to filter to stations first; fall back to all stops if none exist.
    # Note: after _normalise_feed(), pd.NA is already replaced with None,
    # so we only need to handle None and plain numeric values here.
    if "location_type" in stops_df.columns:
        stations_df = stops_df[stops_df["location_type"] == 1]
        if stations_df.empty:
            # No explicit stations — fall back to stops (location_type 0 or missing)
            stations_df = stops_df[
                stops_df["location_type"].isna() | (stops_df["location_type"] == 0)
            ]
    else:
        stations_df = stops_df

    # Apply search filter
    if search_query:
        stations_df = stations_df[
            stations_df["stop_name"].str.contains(search_query, case=False, na=False)
        ]

    # Sort by name for consistent output
    stations_df = stations_df.sort_values("stop_name")

    # Select only the fields we want to expose, filling in any missing columns with None
    columns_to_keep = [
        "stop_id", "stop_name", "stop_lat", "stop_lon", "parent_station", "location_type"
    ]
    result_df = stations_df.reindex(columns=columns_to_keep)

    # Replace any remaining float NaN (from stop_lat/stop_lon) with None for JSON
    result_df = result_df.where(pd.notnull(result_df), None)

    return jsonify(
        {
            "count": len(result_df),
            "mode": mode,
            "stations": result_df.to_dict(orient="records"),
        }
    )
