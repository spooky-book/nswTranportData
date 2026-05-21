"""
Application configuration.

Centralises paths, environment variables, and transport mode definitions.
"""

import os
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "schedule-gtfs"

# ── API key ────────────────────────────────────────────────────────────────────
TRANSPORT_NSW_API_KEY: str | None = os.getenv("TRANSPORT_NSW_API_KEY")

# ── Transport modes ────────────────────────────────────────────────────────────
# Each entry maps a human-readable mode name to its TfNSW API path
# and local cache folder name.
TRANSPORT_MODES: dict[str, dict[str, str]] = {
    "sydney_trains": {
        "api_path": "sydneytrains",
        "cache_folder": "sydney_trains",
    },
    "light_rail_parramatta": {
        "api_path": "lightrail/parramatta",
        "cache_folder": "light_rail_parramatta",
    },
    "light_rail_inner_west": {
        "api_path": "lightrail/innerwest",
        "cache_folder": "light_rail_inner_west",
    },
    "light_rail_newcastle": {
        "api_path": "lightrail/newcastle",
        "cache_folder": "light_rail_newcastle",
    },
    "light_rail_cbd_south_east": {
        "api_path": "lightrail/cbdandsoutheast",
        "cache_folder": "light_rail_city_and_south_west",
    },
    "nsw_trains": {
        "api_path": "nswtrains",
        "cache_folder": "nsw_trains",
    },
    "ferries_sydney": {
        "api_path": "ferries/sydneyferries",
        "cache_folder": "ferries_sydney_ferries",
    },
    "ferries_mff": {
        "api_path": "ferries/MFF",
        "cache_folder": "ferries_mff",
    },
}

DEFAULT_MODE = "sydney_trains"

# ── Flask ──────────────────────────────────────────────────────────────────────
FLASK_PORT = int(os.getenv("PORT", "5000"))
