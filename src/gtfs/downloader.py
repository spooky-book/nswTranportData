"""
GTFS data downloader for Transport for NSW.

Downloads GTFS schedule zip files from the TfNSW Open Data API
and caches them in date-stamped directories.
"""

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from tqdm import tqdm

from config import DATA_DIR, TRANSPORT_MODES, TRANSPORT_NSW_API_KEY


def get_gtfs_zip_path(mode: str) -> Path:
    """
    Return the path to a cached GTFS zip file for the given transport mode.

    If the zip isn't cached for today, automatically downloads it from the
    TfNSW API. Requires the TRANSPORT_NSW_API_KEY environment variable.

    Args:
            mode: A key from TRANSPORT_MODES (e.g. "sydney_trains").

    Returns:
            Path to the downloaded/cached GTFS zip file.

    Raises:
            ValueError: If the mode is not recognised.
            EnvironmentError: If the API key is not set and a download is needed.
            RuntimeError: If the download fails.
    """
    if mode not in TRANSPORT_MODES:
        raise ValueError(
            f"Unknown transport mode '{mode}'. "
            f"Valid modes: {', '.join(TRANSPORT_MODES.keys())}"
        )

    mode_config = TRANSPORT_MODES[mode]
    api_path = mode_config["api_path"]
    cache_folder = mode_config["cache_folder"]

    sydney_date = datetime.now(ZoneInfo("Australia/Sydney")).date()
    zip_path = DATA_DIR / str(sydney_date) / cache_folder / "gtfs_schedule.zip"

    # Return cached file if it exists
    if zip_path.is_file():
        print(f"[downloader] Using cached GTFS data for '{mode}' ({sydney_date})")
        return zip_path

    # Need to download — check for API key
    if not TRANSPORT_NSW_API_KEY:
        raise EnvironmentError(
            "TRANSPORT_NSW_API_KEY is not set in environment variables. "
            "Cannot download GTFS data."
        )

    print(f"[downloader] Downloading GTFS data for '{mode}' from TfNSW API...")

    url = f"https://api.transport.nsw.gov.au/v1/gtfs/schedule/{api_path}"

    try:
        with requests.get(
            url,
            headers={"Authorization": f"apikey {TRANSPORT_NSW_API_KEY}"},
            stream=True,
            timeout=120,
        ) as r:
            r.raise_for_status()
            total_size = int(r.headers.get("content-length", 0)) or None

            zip_path.parent.mkdir(exist_ok=True, parents=True)

            with (
                open(zip_path, "wb") as f,
                tqdm(
                    total=total_size,
                    unit="B",
                    unit_scale=True,
                    desc=f"Downloading {mode}",
                    ncols=80,
                ) as pbar,
            ):
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        pbar.update(len(chunk))

        print(f"[downloader] Saved to {zip_path}")
        return zip_path

    except requests.exceptions.HTTPError as e:
        print(f"[downloader] HTTP error: {e}", file=sys.stderr)
        raise RuntimeError(f"Failed to download GTFS data for '{mode}': {e}") from e
    except requests.exceptions.RequestException as e:
        print(f"[downloader] Request error: {e}", file=sys.stderr)
        raise RuntimeError(f"Failed to download GTFS data for '{mode}': {e}") from e
