"""
Desirable Property Locator API blueprint (temporary, single-purpose).

Provides GET /api/property-locator, which returns every train and metro station
with its median travel time to Central (transfers allowed) and how often a useful
train leaves, for three periods, for the /map/property-locator page. Thresholds
are applied client-side, so this only reports times.

Periods (departure time from the station, weekday):
- peak:      Opal AM peak, 06:30–10:00 (towards Central)
- interpeak: 10:00–15:00
- offpeak:   official Opal off-peak (departures outside the peaks), trimmed to
             05:00–23:00 so sparse very early/late trains don't skew it:
             05:00–06:30, 10:00–15:00 and 19:00–23:00
The PM peak (15:00–19:00) is in none of them: it is peak, but for the trip home.

Query parameters:
    date (str, optional): YYYYMMDD service date. Default: the first Tuesday on or
        after today that is also on or after the Bankstown metro opening (30 Oct 2026).

Response body (JSON):
{
    "date": "20261103",
    "warning": null,
    "periods": {
        "peak":      {"label": "Peak", "windows": [{"start": "06:30:00", "end": "09:59:59"}]},
        "interpeak": {"label": "Interpeak", "windows": [...]},
        "offpeak":   {"label": "Off-peak", "windows": [...]}
    },
    "transfer_buffer_secs": 30,
    "stations": [
        {
            "stop_id": "215020",
            "stop_name": "Parramatta Station",
            "lat": -33.817, "lon": 151.005,
            "categories": ["intercity", "regional", "sydney_trains"],
            "lines": ["BMT", "T1", "T5", ...],
            "peak": {
                "median_secs": 1500, "min_secs": 1494, "max_secs": 2430, "journeys": 51,
                "headway_secs": 240,      // effective gap between useful trains
                "max_headway_secs": 720   // longest gap
            },
            "interpeak": {...},
            "offpeak": {...}
        },
        ...
    ]
}

How times are computed: one backward profile scan (Connection Scan Algorithm)
over every train and metro connection on the date gives, for each platform, the
earliest arrival at any Central platform for every useful departure. Transfers
use the same per-platform walk + buffer as /api/trips. A departure is useful if
no later departure from the station reaches Central as early; only useful
departures count. Travel time is the median of (arrival at Central - departure);
waiting at the origin is not included.

Frequency is the effective gap sum(gap^2) / sum(gap) over the gaps between
consecutive useful departures within each window: the average gap someone
turning up at a random time lands in. A regular 3-min service scores 3 min; an
irregular 1.4 + 13.6 min pattern scores ~12.5 min rather than its 1.4 min median.
"""

import statistics
import threading
from bisect import bisect_right
from collections import defaultdict
from datetime import date as dt_date
from datetime import datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import pandas as pd
from flask import Blueprint, jsonify, request, send_file

from api.rail_network import get_network
from api.stop_stats import _resolve_dates, _validate_date
from api.trip_stats import PERIODS
from api.trips import get_transfer_time_secs
from config import PROJECT_ROOT, TRANSFER_BUFFER_SECS
from gtfs.loader import get_feed

property_locator_bp = Blueprint("property_locator", __name__, url_prefix="/api")

MODE = "sydney_trains_and_metro"
CENTRAL_ID = "200060"
# Off-peak ignores the sparse very early / very late trains, which would skew it
OFFPEAK_FIRST = "05:00:00"
OFFPEAK_LAST = "22:59:59"

# label, [(start, end), ...] departure windows (inclusive); peaks follow trip-stats PERIODS
LOCATOR_PERIODS: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "peak": ("Peak", [PERIODS["am_peak"]]),
    "interpeak": ("Interpeak", [PERIODS["interpeak"]]),
    "offpeak": (
        "Off-peak",
        [
            (OFFPEAK_FIRST, PERIODS["early_morning"][1]),
            PERIODS["interpeak"],
            (PERIODS["evening"][0], OFFPEAK_LAST),
        ],
    ),
}
METRO_SOUTHWEST_OPENING = dt_date(2026, 10, 30)

# Precomputed by scripts/generate_property_isochrones.py (the walking graph is too
# big to keep loaded in the server)
ISOCHRONE_MINUTES = 15
ISOCHRONES_PATH = (
    PROJECT_ROOT / "data" / "property_locator" / "station_isochrones_15min_walk.geojson"
)
_INF = float("inf")

_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()


def _default_date() -> str:
    """First Tuesday on or after max(today in Sydney, Bankstown metro opening)."""
    start = max(
        datetime.now(ZoneInfo("Australia/Sydney")).date(), METRO_SOUTHWEST_OPENING
    )
    return (start + timedelta(days=(1 - start.weekday()) % 7)).strftime("%Y%m%d")


def _to_secs(times: pd.Series) -> pd.Series:
    parts = times.str.split(":", expand=True).astype(int)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def _hms_to_secs(hms: str) -> int:
    h, m, s = map(int, hms.split(":"))
    return h * 3600 + m * 60 + s


def _useful_departures(entries: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """(dep, arr) pairs no later departure beats to Central, sorted by departure."""
    kept, best_arr = [], _INF
    for dep, arr in sorted(entries, reverse=True):  # latest departure first
        if arr < best_arr:
            best_arr = arr
            kept.append((dep, arr))
    return kept[::-1]


def _summary(useful: list[tuple[int, int]], windows: list[tuple[int, int]]) -> dict:
    """Travel time and frequency over useful departures inside the windows."""
    in_windows = [
        [(d, a) for d, a in useful if start <= d <= end] for start, end in windows
    ]
    kept = [e for w in in_windows for e in w]
    # Gaps only within a window, never across the peak between two windows
    gaps = [b[0] - a[0] for w in in_windows for a, b in zip(w, w[1:])]

    if not kept:
        return {
            "median_secs": None,
            "min_secs": None,
            "max_secs": None,
            "journeys": 0,
            "headway_secs": None,
            "max_headway_secs": None,
        }

    durations = [arr - dep for dep, arr in kept]
    return {
        "median_secs": int(statistics.median(durations)),
        "min_secs": min(durations),
        "max_secs": max(durations),
        "journeys": len(kept),
        "headway_secs": int(sum(g * g for g in gaps) / sum(gaps))
        if sum(gaps)
        else None,
        "max_headway_secs": max(gaps) if gaps else None,
    }


def _compute(date: str) -> dict[str, list[tuple[int, int]]]:
    """Profile scan: platform -> [(departure_secs, earliest_arrival_at_central_secs), ...]."""
    feed = get_feed(MODE)

    active = set(feed.get_trips(date)["trip_id"].astype(str))
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
    ]
    st = st[st["trip_id"].isin(active)].copy()
    st["seq"] = st["stop_sequence"].astype(int)
    st = st.sort_values(["trip_id", "seq"])

    # Consecutive stops of the same trip form one connection u -> v
    nxt = st.shift(-1)
    same_trip = st["trip_id"] == nxt["trip_id"]
    conns = pd.DataFrame(
        {
            "trip": st["trip_id"],
            "u": st["stop_id"],
            "v": nxt["stop_id"],
            "dep": _to_secs(st["departure_time"]),
            "arr": _to_secs(nxt["arrival_time"].where(same_trip, "00:00:00")),
            "board": st["pickup_type"] != 1,
            "alight": nxt["drop_off_type"] != 1,
        }
    )[same_trip].sort_values(["dep", "arr"], ascending=False)

    stops = feed.stops.set_index("stop_id")
    parent = {s: (p if p else s) for s, p in stops["parent_station"].items()}
    central = {s for s, p in parent.items() if p == CENTRAL_ID}

    siblings: dict[str, list[str]] = defaultdict(list)
    for p in set(conns["u"]):
        siblings[parent.get(p, p)].append(p)

    @lru_cache(maxsize=None)
    def transfer(from_plat: str, to_plat: str) -> int:
        return get_transfer_time_secs(from_plat, to_plat, TRANSFER_BUFFER_SECS)

    # Per-platform Pareto profile, appended in decreasing departure order:
    # neg_deps ascending (-dep), arrs strictly decreasing.
    neg_deps: dict[str, list[int]] = defaultdict(list)
    arrs: dict[str, list[int]] = defaultdict(list)

    def earliest_from(plat: str, t: int) -> float:
        k = bisect_right(neg_deps[plat], -t)
        return arrs[plat][k - 1] if k else _INF

    trip_best: dict[str, float] = {}
    for trip, u, v, dep, arr, board, alight in conns.itertuples(index=False):
        best = trip_best.get(trip, _INF)  # stay seated
        if alight:
            if v in central:
                best = min(best, arr)
            else:
                for p in siblings.get(parent.get(v, v), ()):
                    best = min(best, earliest_from(p, arr + transfer(v, p)))
        trip_best[trip] = best

        if board and best < _INF and u not in central:
            if not arrs[u] or best < arrs[u][-1]:
                if neg_deps[u] and neg_deps[u][-1] == -dep:
                    arrs[u][-1] = best
                else:
                    neg_deps[u].append(-dep)
                    arrs[u].append(best)

    by_station: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for plat, nd in neg_deps.items():
        by_station[parent.get(plat, plat)].extend(zip((-d for d in nd), arrs[plat]))
    return by_station


def _build(date: str) -> dict:
    by_station = _compute(date)
    windows = {
        key: [(_hms_to_secs(start), _hms_to_secs(end)) for start, end in wins]
        for key, (_, wins) in LOCATOR_PERIODS.items()
    }

    stations = []
    for s in get_network()["stations"]:
        if s["stop_id"] == CENTRAL_ID:
            continue
        useful = _useful_departures(by_station.get(s["stop_id"], []))
        stations.append(
            {**s, **{key: _summary(useful, w) for key, w in windows.items()}}
        )

    return {
        "date": date,
        "periods": {
            key: {
                "label": label,
                "windows": [{"start": start, "end": end} for start, end in wins],
            }
            for key, (label, wins) in LOCATOR_PERIODS.items()
        },
        "transfer_buffer_secs": TRANSFER_BUFFER_SECS,
        "stations": stations,
    }


@property_locator_bp.route("/property-locator", methods=["GET"])
def property_locator():
    requested = request.args.get("date", "").strip() or _default_date()
    err = _validate_date(requested)
    if err:
        return jsonify({"error": err, "hint": "Use YYYYMMDD, e.g. 20261103."}), 400

    try:
        feed = get_feed(MODE)
        dates, warning = _resolve_dates([requested], feed.get_dates())
    except (ValueError, EnvironmentError, RuntimeError) as e:
        return jsonify(
            {
                "error": str(e),
                "hint": "Set TRANSPORT_NSW_API_KEY so today's feeds can be downloaded.",
            }
        ), 500
    date = dates[0]

    if date not in _cache:
        with _cache_lock:
            if date not in _cache:
                _cache[date] = _build(date)
    return jsonify({**_cache[date], "warning": warning})


@property_locator_bp.route("/property-locator/isochrones", methods=["GET"])
def property_locator_isochrones():
    """
    Precomputed 15-minute walking isochrones around every train/metro station, as a
    GeoJSON FeatureCollection (one Polygon per station; properties: stop_id, name,
    minutes, speed, reachable_nodes, fallback_circle). 404 until the script has run.
    """
    if not ISOCHRONES_PATH.exists():
        return jsonify(
            {
                "error": "Walking areas haven't been generated yet.",
                "hint": "With the server running, run: uv run python scripts/generate_property_isochrones.py",
            }
        ), 404
    return send_file(ISOCHRONES_PATH, mimetype="application/geo+json")
