"""
Stop Statistics API blueprint.

Provides POST /api/stop-stats which computes daily service statistics per
station by aggregating across all child platforms.

Key design:
- Input stop_ids are treated as PARENT STATION IDs (location_type=1).
- For each station, child platform IDs are looked up and stats are computed
  at the platform level, then aggregated back up to the station level.
- Default (no stop_ids): all parent stations in the feed.
- num_trips  → sum across platforms
- num_routes → unique count across platforms
- headways   → omitted at station level (ambiguous when platforms differ)
- start_time → earliest platform first departure
- end_time   → latest platform last departure
"""

import re
from datetime import date as dt_date

import pandas as pd
from flask import Blueprint, jsonify, request

from gtfs.loader import get_feed
from constants import LocationTypeEnum

stop_stats_bp = Blueprint("stop_stats", __name__, url_prefix="/api")

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

_DATE_RE = re.compile(r"^\d{8}$")  # YYYYMMDD
_TIME_RE = re.compile(r"^\d{2}:\d{2}:\d{2}$")  # HH:MM:SS

_DEFAULT_HEADWAY_START = "07:00:00"
_DEFAULT_HEADWAY_END = "19:00:00"


# ──────────────────────────────────────────────────────────────────────────────
# Validation helpers
# ──────────────────────────────────────────────────────────────────────────────


def _validate_date(value: str) -> str | None:
    """Return an error message if value is not a valid YYYYMMDD date string."""
    if not _DATE_RE.match(value):
        return f"'{value}' is not a valid date. Expected format: YYYYMMDD (e.g. '20260522')."
    try:
        dt_date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    except ValueError:
        return f"'{value}' is not a valid calendar date."
    return None


def _validate_time(value: str, field: str) -> str | None:
    """Return an error message if value is not a valid HH:MM:SS time string."""
    if not _TIME_RE.match(value):
        return (
            f"'{value}' is not a valid value for '{field}'. "
            "Expected format: HH:MM:SS (e.g. '07:00:00'). "
            "Hours may exceed 23 per the GTFS spec."
        )
    mm, ss = int(value[3:5]), int(value[6:8])
    if mm > 59 or ss > 59:
        return (
            f"'{value}' is not a valid value for '{field}': "
            "minutes and seconds must be 0–59."
        )
    return None


def _resolve_dates(
    requested: list[str], feed_dates: list[str]
) -> tuple[list[str], str | None]:
    """
    Given the requested date list and the feed's valid date list, return
    (resolved_dates, warning_message|None).

    - No dates requested → today, or first feed date with a warning if today
      is out of range.
    - Dates outside the feed range are dropped and a warning is returned.
    - If all requested dates are out of range, falls back to the first feed date.
    """
    feed_date_set = set(feed_dates)
    today = dt_date.today().strftime("%Y%m%d")

    if not requested:
        if today in feed_date_set:
            return [today], None
        first = feed_dates[0]
        return [first], (
            f"Today ({today}) is outside the feed's date range. "
            f"Using the first available date instead: {first}."
        )

    valid = [d for d in requested if d in feed_date_set]
    invalid = [d for d in requested if d not in feed_date_set]

    if not valid:
        first = feed_dates[0]
        return [first], (
            f"None of the requested dates {requested} fall within the feed's "
            f"date range ({feed_dates[0]}–{feed_dates[-1]}). "
            f"Using the first available date instead: {first}."
        )

    warning = None
    if invalid:
        warning = (
            f"The following dates are outside the feed's date range and were ignored: "
            f"{invalid}. Feed covers {feed_dates[0]}–{feed_dates[-1]}."
        )
    return valid, warning


def _time_min(a: str | None, b: str | None) -> str | None:
    """Return the earlier of two HH:MM:SS strings, handling None."""
    if a is None:
        return b
    if b is None:
        return a
    return a if a <= b else b


def _time_max(a: str | None, b: str | None) -> str | None:
    """Return the later of two HH:MM:SS strings, handling None."""
    if a is None:
        return b
    if b is None:
        return a
    return a if a >= b else b


# ──────────────────────────────────────────────────────────────────────────────
# Aggregation helper
# ──────────────────────────────────────────────────────────────────────────────


def _aggregate_platform_stats(
    platform_stats: pd.DataFrame,
    date: str,
    platform_ids: list[str],
    route_id_by_platform: dict[str, set[str]],
) -> dict:
    """
    Aggregate per-platform stats for a single date into a single station-level record.

    platform_stats: rows from compute_stop_stats filtered to this date.
    platform_ids: all platform IDs belonging to this station.
    route_id_by_platform: mapping from stop_id → set of route_ids (from stop_times/trips join).
    """
    rows = platform_stats[platform_stats["stop_id"].isin(platform_ids)]

    if rows.empty:
        return {
            "date": date,
            "num_trips": 0,
            "num_routes": 0,
            "start_time": None,
            "end_time": None,
        }

    # num_trips: sum across all platforms
    num_trips = int(rows["num_trips"].sum()) if "num_trips" in rows.columns else 0

    # num_routes: unique routes across all platforms
    all_routes: set[str] = set()
    for pid in platform_ids:
        all_routes |= route_id_by_platform.get(pid, set())
    num_routes = len(all_routes)

    # start_time: earliest first departure across platforms
    start_time: str | None = None
    if "start_time" in rows.columns:
        for t in rows["start_time"].dropna():
            start_time = _time_min(start_time, t)

    # end_time: latest last departure across platforms
    end_time: str | None = None
    if "end_time" in rows.columns:
        for t in rows["end_time"].dropna():
            end_time = _time_max(end_time, t)

    return {
        "date": date,
        "num_trips": num_trips,
        "num_routes": num_routes,
        "start_time": start_time,
        "end_time": end_time,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Endpoint
# ──────────────────────────────────────────────────────────────────────────────


@stop_stats_bp.route("/stop-stats", methods=["POST"])
def get_stop_stats():
    """
    Compute daily service statistics per station, aggregated across all child platforms.

    Stats are always reported at the STATION level (location_type=1). When stop_ids
    are provided they must be parent station IDs. The endpoint automatically resolves
    child platform IDs, runs compute_stop_stats at the platform level, then aggregates
    back up.

    Request body (JSON, all fields optional):
    {
        "mode": "sydney_trains",          // transport mode key (default: sydney_trains)
        "dates": ["20260523"],            // YYYYMMDD list; default: today or first feed date
        "stop_ids": ["200060"],           // parent station IDs to filter to; default: all stations
        "headway_start_time": "07:00:00", // headway window start (default: 07:00:00)
        "headway_end_time":   "19:00:00"  // headway window end   (default: 19:00:00)
    }

    Response body (JSON):
    {
        "mode": "sydney_trains",
        "dates_used": ["20260523"],
        "warning": null,
        "stop_count": 377,
        "stations": [
            {
                "station_id":   "200060",
                "station_name": "Central Station",
                "stop_lat":     -33.883,
                "stop_lon":      151.206,
                "platform_ids": ["2000336", "2000337", ...],
                "dates": [
                    {
                        "date":       "20260523",
                        "num_trips":  1850,      // sum across all platforms
                        "num_routes": 12,         // unique routes across platforms
                        "start_time": "04:03:00", // earliest first departure
                        "end_time":   "26:10:01"  // latest last departure (may exceed 24h)
                    }
                ]
            }
        ]
    }

    Notes:
    - Headways are intentionally omitted at the station level — they are ambiguous
      when individual platforms run different schedules.
    - Dates outside the feed's active range are silently dropped; a 'warning' field
      describes any adjustments.
    - Running for all stations on a large feed (Sydney Trains: 377 stations) takes
      several seconds. Provide stop_ids to narrow the query.
    - end_time may exceed 24:00:00 — this is per the GTFS spec for services that
      run past midnight.
    """
    body: dict = request.get_json(silent=True) or {}

    # ── Parse & validate mode ──────────────────────────────────────────────
    mode: str = body.get("mode", "sydney_trains")
    if not isinstance(mode, str) or not mode.strip():
        return jsonify({"error": "'mode' must be a non-empty string."}), 400
    mode = mode.strip()

    # ── Parse & validate stop_ids ──────────────────────────────────────────
    raw_stop_ids = body.get("stop_ids")
    stop_ids_filter: list[str] | None = None

    if raw_stop_ids is not None:
        if not isinstance(raw_stop_ids, list):
            return jsonify(
                {"error": "'stop_ids' must be a JSON array of strings."}
            ), 400
        if not all(isinstance(s, str) for s in raw_stop_ids):
            return jsonify({"error": "Every item in 'stop_ids' must be a string."}), 400
        stop_ids_filter = [s.strip() for s in raw_stop_ids if s.strip()]
        if not stop_ids_filter:
            return jsonify({"error": "'stop_ids' must not be an empty list."}), 400

    # ── Parse & validate dates ─────────────────────────────────────────────
    raw_dates = body.get("dates")
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
        requested_dates: list[str] = raw_dates
    else:
        requested_dates = []

    # ── Parse & validate headway window ───────────────────────────────────
    headway_start = body.get("headway_start_time", _DEFAULT_HEADWAY_START)
    headway_end = body.get("headway_end_time", _DEFAULT_HEADWAY_END)

    if not isinstance(headway_start, str):
        return jsonify(
            {"error": "'headway_start_time' must be a string (HH:MM:SS)."}
        ), 400
    if not isinstance(headway_end, str):
        return jsonify(
            {"error": "'headway_end_time' must be a string (HH:MM:SS)."}
        ), 400

    err = _validate_time(headway_start, "headway_start_time")
    if err:
        return jsonify({"error": err}), 400
    err = _validate_time(headway_end, "headway_end_time")
    if err:
        return jsonify({"error": err}), 400

    # ── Load feed ──────────────────────────────────────────────────────────
    try:
        feed = get_feed(mode)
    except (ValueError, EnvironmentError, RuntimeError) as e:
        return jsonify({"error": str(e)}), 500

    # ── Resolve dates ──────────────────────────────────────────────────────
    try:
        feed_dates: list[str] = feed.get_dates()
    except Exception as e:
        return jsonify({"error": f"Could not determine feed date range: {e}"}), 500

    if not feed_dates:
        return jsonify({"error": "The feed has no active dates."}), 500

    dates_to_use, date_warning = _resolve_dates(requested_dates, feed_dates)

    # ── Build station → platform mapping ──────────────────────────────────
    # Only consider stops with location_type=1 as stations.
    # Platforms are stops whose parent_station points to a station.
    stops_df = feed.stops[
        [
            "stop_id",
            "stop_name",
            "stop_lat",
            "stop_lon",
            "location_type",
            "parent_station",
        ]
    ].copy()
    stops_df = stops_df.where(pd.notnull(stops_df), None)

    # All stations in this feed
    all_stations = stops_df[stops_df["location_type"] == LocationTypeEnum.STATION.value].copy()

    if all_stations.empty:
        return jsonify(
            {
                "error": (
                    "This feed has no stops with location_type=1 (stations). "
                    "The feed may not define parent station relationships. "
                    "Try GET /api/stops?location_type=0 to see available stops."
                )
            }
        ), 404

    # Validate requested station IDs
    if stop_ids_filter is not None:
        known_station_ids = set(all_stations["stop_id"].dropna().astype(str))
        non_station: list[str] = []
        unknown: list[str] = []
        all_stop_ids = set(stops_df["stop_id"].dropna().astype(str))

        for sid in stop_ids_filter:
            if sid not in all_stop_ids:
                unknown.append(sid)
            elif sid not in known_station_ids:
                non_station.append(sid)

        if unknown:
            return jsonify(
                {
                    "error": f"The following stop_ids were not found in the feed: {unknown}",
                    "hint": "Use GET /api/stops to discover valid stop IDs.",
                }
            ), 400

        if non_station:
            return jsonify(
                {
                    "error": (
                        f"The following stop_ids are not parent stations (location_type=1): "
                        f"{non_station}. This endpoint only accepts station IDs."
                    ),
                    "hint": (
                        "Use GET /api/stops?location_type=1 to list valid station IDs. "
                        "Platform IDs (location_type=0) are automatically resolved internally."
                    ),
                }
            ), 400

        target_stations = all_stations[all_stations["stop_id"].isin(stop_ids_filter)]
    else:
        target_stations = all_stations

    # Build station_id → list of platform_ids mapping
    platforms_df = stops_df[
        stops_df["parent_station"].isin(target_stations["stop_id"])
        & (stops_df["location_type"] == LocationTypeEnum.PLATFORMSTOP.value)
    ]

    station_to_platforms: dict[str, list[str]] = {
        sid: [] for sid in target_stations["stop_id"].tolist()
    }
    for _, row in platforms_df.iterrows():
        parent = row["parent_station"]
        pid = row["stop_id"]
        if parent in station_to_platforms and pid:
            station_to_platforms[parent].append(str(pid))

    # Gather all platform IDs needed for the stats query
    all_platform_ids: list[str] = [
        pid for pids in station_to_platforms.values() for pid in pids
    ]

    if not all_platform_ids:
        return jsonify(
            {
                "error": (
                    "None of the selected stations have linked platform IDs "
                    "(no stops with parent_station pointing to them). "
                    "The feed may not define platform-to-station relationships."
                ),
                "hint": "Use GET /api/stops?location_type=0 to inspect platform records.",
            }
        ), 404

    # ── Build route_id lookup per platform (for unique route counting) ─────
    # Join stop_times → trips to get route_id per stop visit
    st = feed.stop_times[["trip_id", "stop_id"]].copy()
    tr = feed.trips[["trip_id", "route_id"]].copy()
    st_routes = st.merge(tr, on="trip_id", how="left")
    st_routes = st_routes[st_routes["stop_id"].isin(all_platform_ids)]

    route_id_by_platform: dict[str, set[str]] = {}
    for pid, grp in st_routes.groupby("stop_id"):
        route_id_by_platform[str(pid)] = set(
            grp["route_id"].dropna().astype(str).unique()
        )

    # ── Run compute_stop_stats at platform level ───────────────────────────
    try:
        stats_df: pd.DataFrame = feed.compute_stop_stats(
            dates=dates_to_use,
            stop_ids=all_platform_ids,
            headway_start_time=headway_start,
            headway_end_time=headway_end,
            split_directions=False,  # always False — aggregating across platforms
        )
    except ValueError as e:
        return jsonify({"error": f"compute_stop_stats failed: {e}"}), 400
    except Exception as e:
        return jsonify(
            {"error": f"An unexpected error occurred while computing stats: {e}"}
        ), 500

    # Sanitise NaN → None
    if not stats_df.empty:
        stats_df = stats_df.where(pd.notnull(stats_df), None)

    # ── Aggregate platform stats → station level ───────────────────────────
    station_meta = target_stations.set_index("stop_id")[
        ["stop_name", "stop_lat", "stop_lon"]
    ].where(
        pd.notnull(
            target_stations.set_index("stop_id")[["stop_name", "stop_lat", "stop_lon"]]
        ),
        None,
    )

    result_stations: list[dict] = []
    for _, station_row in target_stations.sort_values("stop_name").iterrows():
        sid = station_row["stop_id"]
        platform_ids = station_to_platforms.get(str(sid), [])

        date_records: list[dict] = []
        for date in dates_to_use:
            date_agg = _aggregate_platform_stats(
                stats_df, date, platform_ids, route_id_by_platform
            )
            date_records.append(date_agg)

        meta = station_meta.loc[sid] if sid in station_meta.index else {}
        result_stations.append(
            {
                "station_id": str(sid),
                "station_name": station_row.get("stop_name"),
                "stop_lat": station_row.get("stop_lat"),
                "stop_lon": station_row.get("stop_lon"),
                "platform_ids": sorted(platform_ids),
                "dates": date_records,
            }
        )

    return jsonify(
        {
            "mode": mode,
            "dates_used": dates_to_use,
            "warning": date_warning,
            "stop_count": len(result_stations),
            "stations": result_stations,
        }
    )
