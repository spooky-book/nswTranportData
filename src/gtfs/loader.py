"""
GTFS feed loader using GTFS Kit.

Loads GTFS data from zip files into gtfs_kit Feed objects
and caches them in memory for reuse.
"""

import gtfs_kit as gk

from config import DEFAULT_MODE
from gtfs.downloader import get_gtfs_zip_path

# In-memory cache: mode name → Feed object
_feed_cache: dict[str, gk.Feed] = {}


def get_feed(mode: str = DEFAULT_MODE) -> gk.Feed:
    """
    Get a GTFS Kit Feed for the given transport mode.

    On first call for a mode, downloads the GTFS zip (if not cached today)
    and parses it with gtfs_kit.read_feed(). Subsequent calls return the
    cached Feed object.

    Args:
            mode: A key from TRANSPORT_MODES (e.g. "sydney_trains").

    Returns:
            A gtfs_kit.Feed object with all GTFS tables loaded as DataFrames.
    """
    if mode in _feed_cache:
        return _feed_cache[mode]

    zip_path = get_gtfs_zip_path(mode)
    print(f"[loader] Loading GTFS feed from {zip_path} ...")

    feed = gk.read_feed(str(zip_path), dist_units="km")
    _normalise_feed(feed)
    _filter_non_passenger_services(feed)
    _feed_cache[mode] = feed

    print(f"[loader] Feed loaded: {len(feed.stops)} stops, {len(feed.routes)} routes")
    return feed


def _normalise_feed(feed: gk.Feed) -> None:
    """
    Convert nullable Pandas extension types (pd.NA) to plain Python-compatible
    types on every GTFS table in the feed.

    gtfs_kit loads data with dtype_backend="numpy_nullable", which means
    missing values come back as pd.NA (from Int32, string extension types)
    rather than float('nan') or None.  pd.NA is not JSON-serializable, so
    we normalise all tables here once at load time so the rest of the app
    never has to deal with NAType.

    Specifically this converts:
    - Nullable integer columns (Int32 etc.) → Python int, with NA → None
    - Nullable string columns → Python str, with NA → None
    - Regular float columns already use float('nan') which is handled
      separately by JSON serializers or pd.isna() checks.
    """
    import pandas as pd

    for attr in (
        "stops",
        "routes",
        "trips",
        "agency",
        "calendar",
        "calendar_dates",
        "stop_times",
        "shapes",
    ):
        df = getattr(feed, attr, None)
        if df is None or df.empty:
            continue

        # Find columns that use Pandas nullable extension types (Int32, string, etc.)
        # These are the columns whose NA values are pd.NA (not float nan).
        nullable_cols = [
            col
            for col, dtype in df.dtypes.items()
            if pd.api.types.is_extension_array_dtype(dtype)
        ]
        if not nullable_cols:
            continue

        # Convert those columns to plain object dtype so NA becomes None,
        # integers become plain int, and strings become plain str.
        df[nullable_cols] = (
            df[nullable_cols]
            .astype(object)
            .where(df[nullable_cols].notna(), other=None)
        )
        setattr(feed, attr, df)


def _filter_non_passenger_services(feed: gk.Feed) -> None:
    """
    Remove trips and stop times that do not serve passengers.

    This globally strips out "Empty Train" deadheads and pass-through
    timing points, ensuring all stats, routes, and maps only reflect
    trains passengers can actually board. This reduces memory usage and
    simplifies routing/stats logic globally.
    """
    import pandas as pd

    if (
        getattr(feed, "trips", None) is None
        or getattr(feed, "stop_times", None) is None
    ):
        return

    # 1. Identify Empty Trains
    tr = feed.trips
    if "trip_headsign" in tr.columns:
        empty_mask = tr["trip_headsign"].str.contains(
            "Empty Train", case=False, na=False
        )
        empty_trips = tr[empty_mask]["trip_id"]
        feed.trips = tr[~empty_mask]
    else:
        empty_trips = pd.Series(dtype=str)

    # 2. Filter stop_times
    st = feed.stop_times

    # Remove stop_times belonging to empty trips
    st = st[~st["trip_id"].isin(empty_trips)]

    # Remove pass-through stops (where train neither picks up nor drops off)
    # GTFS standard: 1 = no pickup / no drop off. Missing value (NaN) implies 0 (regular).
    # Missing values safely evaluate to False when compared to 1.
    if "pickup_type" in st.columns and "drop_off_type" in st.columns:
        pickup = st["pickup_type"]
        dropoff = st["drop_off_type"]
        st = st[~((pickup == 1) & (dropoff == 1))]

    feed.stop_times = st


def clear_cache() -> None:
    """Clear the in-memory feed cache."""
    _feed_cache.clear()
