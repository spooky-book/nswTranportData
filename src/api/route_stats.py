"""
Route Statistics API blueprint.

Provides POST /api/route-stats which computes point-to-point service statistics
between an origin station and a destination station (direct trains only).

Request body (JSON, origin and destination required):
{
    "mode": "sydney_trains",          // transport mode key (default: sydney_trains)
    "origin_stop_id": "200060",       // parent station ID for origin
    "destination_stop_id": "215020",  // parent station ID for destination
    "dates": ["20260523"],            // YYYYMMDD list; default: today or first feed date
    "time_window_start": "00:00:00",  // filter all stats to trips departing after this time
    "time_window_end":   "29:59:59"   // filter all stats to trips departing before this time
}

Response body (JSON):
{
    "mode": "sydney_trains",
    "origin_stop_id": "200060",
    "origin_name": "Central Station",
    "destination_stop_id": "215020",
    "destination_name": "Parramatta Station",
    "dates_used": ["20260523"],
    "warning": null,
    "time_window": {"start": "00:00:00", "end": "29:59:59"},
    "dates": [
        {
            "date": "20260523",
            "num_trips": 136,
            "num_routes": 4,
            "start_time": "04:36:00",
            "end_time": "25:11:01",
            "min_headway_secs": 120,
            "mean_headway_secs": 534,
            "median_headway_secs": 420,
            "mode_headway_secs": 900,
            "max_headway_secs": 900,
            "travel_time_min_secs": 1440,
            "travel_time_mean_secs": 1860,
            "travel_time_median_secs": 1800,
            "travel_time_mode_secs": 1800,
            "travel_time_max_secs": 2340,
            "trips": [
                {
                    "trip_id": "845A.1373.155.128.A.8.89773032",
                    "route_id": "WST_2d",
                    "departure_time": "05:29:00",
                    "arrival_time": "06:00:00",
                    "travel_secs": 1860
                }
            ]
        }
    ]
}
"""

import pandas as pd
import numpy as np
from flask import Blueprint, jsonify, request

from gtfs.loader import get_feed
from api.stop_stats import (
    _resolve_dates,
    _validate_date,
    _validate_time,
)

route_stats_bp = Blueprint("route_stats", __name__, url_prefix="/api")

_DEFAULT_WINDOW_START = "00:00:00"
_DEFAULT_WINDOW_END = "29:59:59"


def _time_to_seconds(t: str) -> int:
    """Convert GTFS HH:MM:SS string to seconds since midnight."""
    if not isinstance(t, str) or pd.isna(t):
        return 0
    h, m, s = map(int, t.split(":"))
    return h * 3600 + m * 60 + s


@route_stats_bp.route("/route-stats", methods=["POST"])
def get_route_stats():
    body: dict = request.get_json(silent=True) or {}

    # ── Parse & validate mode ──────────────────────────────────────────────
    mode: str = body.get("mode", "sydney_trains")
    if not isinstance(mode, str) or not mode.strip():
        return jsonify({"error": "'mode' must be a non-empty string."}), 400
    mode = mode.strip()

    # ── Parse & validate stations ──────────────────────────────────────────
    origin_id = body.get("origin_stop_id")
    dest_id = body.get("destination_stop_id")

    if not origin_id or not dest_id:
        return jsonify(
            {"error": "'origin_stop_id' and 'destination_stop_id' are required."}
        ), 400

    if not isinstance(origin_id, str) or not isinstance(dest_id, str):
        return jsonify({"error": "Station IDs must be strings."}), 400

    origin_id = origin_id.strip()
    dest_id = dest_id.strip()

    if origin_id == dest_id:
        return jsonify({"error": "Origin and destination cannot be the same."}), 400

    # ── Parse & validate dates ─────────────────────────────────────────────
    raw_dates = body.get("dates")
    requested_dates = []
    if raw_dates is not None:
        if not isinstance(raw_dates, list):
            return jsonify(
                {"error": "'dates' must be a JSON array of YYYYMMDD strings."}
            ), 400
        for d in raw_dates:
            if not isinstance(d, str):
                return jsonify(
                    {"error": f"Each date must be a string, got: {d!r}"}
                ), 400
            err = _validate_date(d)
            if err:
                return jsonify({"error": err}), 400
        requested_dates = raw_dates

    # ── Parse & validate time window ───────────────────────────────────────
    window_start = body.get("time_window_start", _DEFAULT_WINDOW_START)
    window_end = body.get("time_window_end", _DEFAULT_WINDOW_END)

    if not isinstance(window_start, str) or not isinstance(window_end, str):
        return jsonify({"error": "Time window values must be strings (HH:MM:SS)."}), 400

    err = _validate_time(window_start, "time_window_start") or _validate_time(
        window_end, "time_window_end"
    )
    if err:
        return jsonify({"error": err}), 400

    w_start_sec = _time_to_seconds(window_start)
    w_end_sec = _time_to_seconds(window_end)

    # ── Load feed ──────────────────────────────────────────────────────────
    try:
        feed = get_feed(mode)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    try:
        feed_dates: list[str] = feed.get_dates()
    except Exception as e:
        return jsonify({"error": f"Could not determine feed date range: {e}"}), 500

    if not feed_dates:
        return jsonify({"error": "The feed has no active dates."}), 500

    dates_to_use, date_warning = _resolve_dates(requested_dates, feed_dates)

    # ── Resolve stations to platforms ──────────────────────────────────────
    stops_df = feed.stops[
        ["stop_id", "stop_name", "location_type", "parent_station"]
    ].copy()
    stops_df = stops_df.where(pd.notnull(stops_df), None)

    all_stations = stops_df[stops_df["location_type"] == 1]

    known_stations = set(all_stations["stop_id"].dropna().astype(str))
    if origin_id not in known_stations or dest_id not in known_stations:
        return jsonify(
            {
                "error": "Origin and/or destination are either not in the feed or are not parent stations (location_type=1).",
                "hint": "Use GET /api/stops?location_type=1 to list valid station IDs.",
            }
        ), 400

    origin_name = all_stations[all_stations["stop_id"] == origin_id]["stop_name"].iloc[
        0
    ]
    dest_name = all_stations[all_stations["stop_id"] == dest_id]["stop_name"].iloc[0]

    platforms_A = (
        stops_df[stops_df["parent_station"] == origin_id]["stop_id"]
        .dropna()
        .astype(str)
        .tolist()
    )
    platforms_B = (
        stops_df[stops_df["parent_station"] == dest_id]["stop_id"]
        .dropna()
        .astype(str)
        .tolist()
    )

    if not platforms_A or not platforms_B:
        return jsonify(
            {
                "error": "One or both stations have no child platforms defined in the GTFS feed."
            }
        ), 400

    # ── Pre-filter stop_times globally for these platforms ─────────────────
    # Note: Non-passenger trains (Empty Trains, pass-throughs) are already
    # filtered out globally in loader.py, so we only deal with passenger services!

    # We need the full stop_times subset for our platforms to find valid trips
    st = feed.stop_times[
        ["trip_id", "stop_id", "arrival_time", "departure_time", "stop_sequence", "pickup_type", "drop_off_type"]
    ]

    # Platform A departures (must allow pickup: != 1)
    st_A = st[st["stop_id"].isin(platforms_A) & (st["pickup_type"] != 1)][
        ["trip_id", "departure_time", "stop_sequence"]
    ].rename(columns={"departure_time": "dep_A", "stop_sequence": "seq_A"})
    
    # Platform B arrivals (must allow drop off: != 1)
    st_B = st[st["stop_id"].isin(platforms_B) & (st["drop_off_type"] != 1)][
        ["trip_id", "arrival_time", "stop_sequence"]
    ].rename(columns={"arrival_time": "arr_B", "stop_sequence": "seq_B"})

    # Merge A and B on trip_id
    # A trip must serve A and then B
    merged = pd.merge(st_A, st_B, on="trip_id")
    direct = merged[merged["seq_B"] > merged["seq_A"]].copy()

    # Join route info
    tr = feed.trips[["trip_id", "route_id"]]
    direct = pd.merge(direct, tr, on="trip_id", how="left")

    # Pre-calculate departure seconds and travel times for all valid direct trips
    direct["dep_sec"] = direct["dep_A"].apply(_time_to_seconds)
    direct["arr_sec"] = direct["arr_B"].apply(_time_to_seconds)
    direct["travel_secs"] = direct["arr_sec"] - direct["dep_sec"]

    # ── Process stats per date ─────────────────────────────────────────────
    date_records = []

    for date in dates_to_use:
        # Get active trips for this date
        active_trips_df = feed.get_trips(date)
        if active_trips_df is None or active_trips_df.empty:
            active_trips = set()
        else:
            active_trips = set(active_trips_df["trip_id"].dropna().astype(str))

        # Filter our pre-computed direct trips to this date
        day_trips = direct[direct["trip_id"].isin(active_trips)].copy()
        
        # Filter by the requested time window
        day_trips = day_trips[
            (day_trips["dep_sec"] >= w_start_sec) & (day_trips["dep_sec"] <= w_end_sec)
        ]

        if day_trips.empty:
            date_records.append(
                {
                    "date": date,
                    "num_trips": 0,
                    "num_routes": 0,
                    "start_time": None,
                    "end_time": None,
                    "max_headway_secs": None,
                    "min_headway_secs": None,
                    "mean_headway_secs": None,
                    "median_headway_secs": None,
                    "mode_headway_secs": None,
                    "travel_time_min_secs": None,
                    "travel_time_max_secs": None,
                    "travel_time_mean_secs": None,
                    "travel_time_median_secs": None,
                    "travel_time_mode_secs": None,
                    "trips": []
                }
            )
            continue

        day_trips = day_trips.sort_values("dep_sec")

        num_trips = len(day_trips)
        num_routes = int(day_trips["route_id"].nunique())
        start_time = day_trips["dep_A"].iloc[0]
        end_time = day_trips["dep_A"].iloc[-1]

        # Travel times
        t_min = (
            int(day_trips["travel_secs"].min())
            if not pd.isna(day_trips["travel_secs"].min())
            else None
        )
        t_max = (
            int(day_trips["travel_secs"].max())
            if not pd.isna(day_trips["travel_secs"].max())
            else None
        )
        t_mean = (
            int(day_trips["travel_secs"].mean())
            if not pd.isna(day_trips["travel_secs"].mean())
            else None
        )
        t_median = (
            int(day_trips["travel_secs"].median())
            if not pd.isna(day_trips["travel_secs"].median())
            else None
        )
        t_mode_series = day_trips["travel_secs"].mode()
        t_mode = int(t_mode_series.iloc[0]) if not t_mode_series.empty else None

        # Headways
        if len(day_trips) > 1:
            diffs = np.diff(day_trips["dep_sec"].values)
            max_h = int(np.max(diffs))
            min_h = int(np.min(diffs))
            mean_h = int(np.mean(diffs))
            median_h = int(np.median(diffs))
            mode_h_series = pd.Series(diffs).mode()
            mode_h = int(mode_h_series.iloc[0]) if not mode_h_series.empty else None
        else:
            max_h = min_h = mean_h = median_h = mode_h = None
            
        trips_list = []
        for _, row in day_trips.iterrows():
            trips_list.append({
                "trip_id": row["trip_id"],
                "route_id": row["route_id"],
                "departure_time": row["dep_A"],
                "arrival_time": row["arr_B"],
                "travel_secs": int(row["travel_secs"])
            })

        date_records.append(
            {
                "date": date,
                "num_trips": num_trips,
                "num_routes": num_routes,
                "start_time": start_time,
                "end_time": end_time,
                "max_headway_secs": max_h,
                "min_headway_secs": min_h,
                "mean_headway_secs": mean_h,
                "median_headway_secs": median_h,
                "mode_headway_secs": mode_h,
                "travel_time_min_secs": t_min,
                "travel_time_max_secs": t_max,
                "travel_time_mean_secs": t_mean,
                "travel_time_median_secs": t_median,
                "travel_time_mode_secs": t_mode,
                "trips": trips_list
            }
        )

    return jsonify(
        {
            "mode": mode,
            "origin_stop_id": origin_id,
            "origin_name": origin_name,
            "destination_stop_id": dest_id,
            "destination_name": dest_name,
            "dates_used": dates_to_use,
            "warning": date_warning,
            "time_window": {"start": window_start, "end": window_end},
            "dates": date_records,
        }
    )
