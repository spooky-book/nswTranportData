"""
Trips/Journey Planner API blueprint.

Provides POST /api/trips which calculates transit journeys between two stations
using a multi-departure timetable Dijkstra routing algorithm (supporting transfers).

Request body (JSON):
{
    "origin_stop_id": "200060",        // Required: Parent station ID of origin (e.g. Central)
    "destination_stop_id": "215020",   // Required: Parent station ID of destination (e.g. Parramatta)
    "mode": "sydney_trains",           // Optional: Mode key (e.g. "sydney_trains_and_metro")
    "max_transfers": 5,                // Optional: Maximum allowed transfers (default 5)
    "time_window_start": "08:00:00",   // Optional: HH:MM:SS search start time
    "time_window_end": "09:00:00",     // Optional: HH:MM:SS search end time
    "dates": ["20260613"]              // Optional: list of YYYYMMDD strings
}

Response body (JSON):
{
    "mode": "sydney_trains",
    "origin_stop_id": "200060",
    "origin_name": "Central Station",
    "destination_stop_id": "215020",
    "destination_name": "Parramatta Station",
    "max_transfers": 5,
    "date_records": [
        {
            "date": "2026-06-13",
            "journeys": [
                {
                    "departure_time": "08:02:30",
                    "arrival_time": "08:31:00",
                    "total_travel_secs": 1710,
                    "transfers": 0,
                    "legs": [
                        {
                            "origin_id": "200060-1",
                            "origin_name": "Central Station, Platform 1",
                            "destination_id": "215020-2",
                            "destination_name": "Parramatta Station, Platform 2",
                            "trip_id": "123.T.1.2",
                            "route_id": "T1",
                            "departure_time": "08:02:30",
                            "arrival_time": "08:31:00"
                        }
                    ]
                }
            ]
        }
    ]
}
"""

import pandas as pd
from flask import Blueprint, jsonify, request
from collections import defaultdict
import heapq
import time
import itertools

from gtfs.loader import get_feed
from api.stop_stats import _resolve_dates, _validate_date, _validate_time
from api.trip_stats import _time_to_seconds

trips_bp = Blueprint("trips", __name__, url_prefix="/api")

_DEFAULT_WINDOW_START = "00:00:00"
_DEFAULT_WINDOW_END = "29:59:59"


def get_transfer_time_secs(station_id: str, from_trip: str, to_trip: str) -> int:
    """
    Returns the minimum transfer time in seconds at a given station.
    Currently returns a constant 180 seconds (3 minutes).
    """
    return 180


def _format_time(seconds: int) -> str:
    if seconds is None:
        return None
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


@trips_bp.route("/trips", methods=["POST"])
def get_trips():
    body: dict = request.get_json(silent=True) or {}

    mode: str = body.get("mode", "sydney_trains")
    origin_id = body.get("origin_stop_id")
    dest_id = body.get("destination_stop_id")

    if not origin_id or not dest_id:
        return jsonify(
            {"error": "'origin_stop_id' and 'destination_stop_id' are required."}
        ), 400

    max_transfers = int(body.get("max_transfers", 5))

    raw_dates = body.get("dates")
    requested_dates = []
    if raw_dates is not None:
        for d in raw_dates:
            err = _validate_date(d)
            if err:
                return jsonify({"error": err}), 400
            requested_dates.append(d)

    window_start = body.get("time_window_start", _DEFAULT_WINDOW_START)
    window_end = body.get("time_window_end", _DEFAULT_WINDOW_END)
    w_start_sec = _time_to_seconds(window_start)
    w_end_sec = _time_to_seconds(window_end)

    try:
        feed = get_feed(mode)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    feed_dates = feed.get_dates()
    if not feed_dates:
        return jsonify({"error": "The feed has no active dates."}), 500

    dates_to_use, date_warning = _resolve_dates(requested_dates, feed_dates)

    # Resolve stations to platforms
    stops_df = feed.stops[
        ["stop_id", "stop_name", "location_type", "parent_station"]
    ].copy()
    stops_df = stops_df.where(pd.notnull(stops_df), None)
    stop_name_map = stops_df.set_index("stop_id")["stop_name"].to_dict()
    all_stations = stops_df[stops_df["location_type"] == 1]

    known_stations = set(all_stations["stop_id"].dropna().astype(str))
    if origin_id not in known_stations or dest_id not in known_stations:
        return jsonify(
            {"error": "Origin or destination not in feed or not parent stations."}
        ), 400

    origin_name = all_stations[all_stations["stop_id"] == origin_id]["stop_name"].iloc[
        0
    ]
    dest_name = all_stations[all_stations["stop_id"] == dest_id]["stop_name"].iloc[0]

    platforms_A = set(
        stops_df[stops_df["parent_station"] == origin_id]["stop_id"]
        .dropna()
        .astype(str)
    )
    platforms_B = set(
        stops_df[stops_df["parent_station"] == dest_id]["stop_id"].dropna().astype(str)
    )

    # Pre-build timetable graph
    st = feed.stop_times[
        [
            "trip_id",
            "stop_id",
            "arrival_time",
            "departure_time",
            "stop_sequence",
            "pickup_type",
            "drop_off_type",
        ]
    ].copy()
    st["dep_sec"] = st["departure_time"].apply(_time_to_seconds)
    st["arr_sec"] = st["arrival_time"].apply(_time_to_seconds)

    tr = feed.trips[["trip_id", "route_id"]].set_index("trip_id")["route_id"].to_dict()

    date_records = []

    for date in dates_to_use:
        active_trips_df = feed.get_trips(date)
        if active_trips_df is None or active_trips_df.empty:
            date_records.append({"date": date, "journeys": []})
            continue

        active_trips = set(active_trips_df["trip_id"].dropna().astype(str))

        # Filter stop times to active trips
        day_st = st[st["trip_id"].isin(active_trips)].sort_values(
            ["trip_id", "stop_sequence"]
        )

        # Build trip sequences and stop departures
        trip_path = defaultdict(list)
        stop_deps = defaultdict(list)

        for row in day_st.itertuples(index=False):
            t_id = str(row.trip_id)
            s_id = str(row.stop_id)
            arr = row.arr_sec
            dep = row.dep_sec
            seq = row.stop_sequence
            pickup = row.pickup_type
            dropoff = row.drop_off_type

            idx = len(trip_path[t_id])
            trip_path[t_id].append(
                {
                    "stop_id": s_id,
                    "arr": arr,
                    "dep": dep,
                    "seq": seq,
                    "pickup": pickup,
                    "dropoff": dropoff,
                }
            )

            if pickup != 1:  # Can board here
                stop_deps[s_id].append((dep, t_id, idx))

        for s_id in stop_deps:
            stop_deps[s_id].sort(key=lambda x: x[0])

        # Parent station mapping for fast lookup
        platform_to_parent = stops_df.set_index("stop_id")["parent_station"].to_dict()

        def get_parent(s):
            p = platform_to_parent.get(s)
            return p if p else s

        # Multi-departure search
        # We find all valid trips departing origin platforms in the time window
        origin_departures = []
        for p in platforms_A:
            for dep, t_id, idx in stop_deps.get(p, []):
                if w_start_sec <= dep <= w_end_sec:
                    origin_departures.append((dep, t_id, idx, p))

        journeys = []

        # To avoid massive duplicate paths, we use a pareto frontier at the destination
        # and standard Dijkstra state: (time, transfers, current_station, current_trip, path)

        counter = itertools.count()

        for start_dep, start_trip, start_idx, start_plat in origin_departures:
            # Dijkstra PQ
            # Priority: (arrival_time, transfers_used)
            # Tuple: (arr_time, transfers_used, tiebreaker, current_plat, current_trip, curr_trip_idx, path)
            pq = []
            heapq.heappush(
                pq, (start_dep, 0, next(counter), start_plat, start_trip, start_idx, [])
            )

            # Pareto frontier per station: stop_id -> list of (arr_time, transfers_used)
            # We only explore a state if it is strictly better in at least one dimension
            best_arrivals = defaultdict(list)

            found_dest = False

            while pq:
                time_sec, transfers, _, curr_plat, curr_trip, curr_idx, path = (
                    heapq.heappop(pq)
                )

                if found_dest:
                    continue  # We just want the fastest path for THIS specific departure

                # If we are at destination, save journey and break to move to next departure!
                # Because we sort PQ by time_sec, the first time we hit dest is the earliest arrival for this departure.
                if curr_plat in platforms_B:
                    # Construct full journey
                    j = {
                        "departure_time": _format_time(start_dep),
                        "arrival_time": _format_time(time_sec),
                        "total_travel_secs": time_sec - start_dep,
                        "transfers": transfers,
                        "legs": path,
                    }
                    journeys.append(j)
                    found_dest = True
                    break

                # Pareto check
                is_dominated = False
                for best_time, best_tx in best_arrivals[curr_plat]:
                    if best_time <= time_sec and best_tx <= transfers:
                        is_dominated = True
                        break
                if is_dominated:
                    continue
                best_arrivals[curr_plat].append((time_sec, transfers))

                # Expand: we are ON a trip. We can either stay on it, or alight and transfer.
                trip_stops = trip_path[curr_trip]

                # 1. Stay on trip (traverse to all future stops)
                # We can alight at any future stop where dropoff != 1
                for next_idx in range(curr_idx + 1, len(trip_stops)):
                    next_stop = trip_stops[next_idx]
                    if next_stop["dropoff"] == 1:
                        continue

                    next_plat = next_stop["stop_id"]
                    next_arr = next_stop["arr"]

                    # Create leg
                    leg = {
                        "origin_id": curr_plat,
                        "origin_name": stop_name_map.get(curr_plat, curr_plat),
                        "destination_id": next_plat,
                        "destination_name": stop_name_map.get(next_plat, next_plat),
                        "trip_id": curr_trip,
                        "route_id": tr.get(curr_trip, "unknown"),
                        "departure_time": _format_time(trip_stops[curr_idx]["dep"]),
                        "arrival_time": _format_time(next_arr),
                    }

                    new_path = list(path)
                    new_path.append(leg)

                    # We have now "arrived" at next_plat at next_arr.
                    # We add a state to the PQ representing standing at next_plat ready to transfer.
                    # But wait, to transfer, we need to take another trip.
                    # Instead of pushing "ready to transfer", we can directly find the next trips.

                    # If this is the destination, push it so we can pop and win!
                    if next_plat in platforms_B:
                        heapq.heappush(
                            pq,
                            (
                                next_arr,
                                transfers,
                                next(counter),
                                next_plat,
                                None,
                                None,
                                new_path,
                            ),
                        )

                    if transfers < max_transfers:
                        # Find transfers from next_plat
                        transfer_time = get_transfer_time_secs(
                            get_parent(next_plat), curr_trip, "any"
                        )
                        available_time = next_arr + transfer_time

                        # We can transfer to any platform in the same parent station
                        parent = get_parent(next_plat)
                        sibling_plats = [
                            p
                            for p in platforms_A | platforms_B | set(stop_deps.keys())
                            if get_parent(p) == parent
                        ]

                        for sib in sibling_plats:
                            # Binary search or linear scan for next departure
                            deps = stop_deps.get(sib, [])
                            for sib_dep, sib_trip, sib_idx in deps:
                                if sib_dep >= available_time:
                                    if (
                                        sib_trip != curr_trip
                                    ):  # Don't transfer to same trip
                                        heapq.heappush(
                                            pq,
                                            (
                                                sib_dep,
                                                transfers + 1,
                                                next(counter),
                                                sib,
                                                sib_trip,
                                                sib_idx,
                                                new_path,
                                            ),
                                        )
                                    # Since deps are sorted, we only need the *first* departure of each trip/route.
                                    # For simplicity, we just push all valid ones and let Pareto prune them.
                                    # Actually, to prevent explosion, we should break after a reasonable window.
                                    # Let's break if departure is > available_time + 2 hours (no point waiting forever)
                                    if sib_dep > available_time + 7200:
                                        break

        # Post-process: Remove completely dominated/overtaken journeys
        # 1. Group by departure time and keep only the best journey (earliest arrival, then fewest transfers) for each unique departure time
        best_by_dep = {}
        for j in journeys:
            dep = j["departure_time"]
            arr_sec = _time_to_seconds(j["arrival_time"])
            tx = j["transfers"]

            if dep not in best_by_dep:
                best_by_dep[dep] = j
            else:
                curr_best = best_by_dep[dep]
                curr_best_arr_sec = _time_to_seconds(curr_best["arrival_time"])
                curr_best_tx = curr_best["transfers"]

                if arr_sec < curr_best_arr_sec or (
                    arr_sec == curr_best_arr_sec and tx < curr_best_tx
                ):
                    best_by_dep[dep] = j

        unique_dep_journeys = sorted(
            best_by_dep.values(), key=lambda x: _time_to_seconds(x["departure_time"])
        )

        # 2. Filter out overtaken journeys (journeys that depart after a previous train, but arrive after a later train/trip)
        filtered_journeys = []
        for i, j in enumerate(unique_dep_journeys):
            dep_j = _time_to_seconds(j["departure_time"])
            arr_j = _time_to_seconds(j["arrival_time"])

            # Check if there is a previous journey (departs strictly before j)
            has_previous = any(
                _time_to_seconds(other["departure_time"]) < dep_j
                for other in unique_dep_journeys
            )

            # Check if there is a later journey (departs strictly after j) that arrives at least as early as j
            has_better_later = any(
                _time_to_seconds(other["departure_time"]) > dep_j
                and _time_to_seconds(other["arrival_time"]) <= arr_j
                for other in unique_dep_journeys
            )

            if has_previous and has_better_later:
                # Overtaken and redundant: we leave after an earlier option, but arrive after a later option.
                continue

            filtered_journeys.append(j)

        date_records.append({"date": date, "journeys": filtered_journeys})

    return jsonify(
        {
            "mode": mode,
            "origin_stop_id": origin_id,
            "origin_name": origin_name,
            "destination_stop_id": dest_id,
            "destination_name": dest_name,
            "max_transfers": max_transfers,
            "date_records": date_records,
        }
    )
