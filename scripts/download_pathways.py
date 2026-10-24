"""
Extract TfNSW's in-station pathways.txt for journey-planner transfer times.

pathways.txt is only published in the complete GTFS bundle (~300 MB zip), so
this downloads the bundle, keeps pathways.txt as
data/pathways/<YYYY-MM-DD>/pathways.txt, and deletes the zip. Station layouts
change rarely, so re-running it every month or two is plenty.

Usage (from the project root):
    uv run python scripts/download_pathways.py                     # download (needs TRANSPORT_NSW_API_KEY)
    uv run python scripts/download_pathways.py --from-zip PATH.zip # extract from a bundle you already have

Restart the server afterwards; pathways are loaded once per process.
"""

import argparse
import re
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config import TRANSPORT_NSW_API_KEY  # noqa: E402
from gtfs.pathways import PATHWAYS_DIR  # noqa: E402

COMPLETE_GTFS_URL = (
    "https://api.transport.nsw.gov.au/v1/publictransport/timetables/complete/gtfs"
)


def download_bundle(dest: Path) -> None:
    if not TRANSPORT_NSW_API_KEY:
        sys.exit("TRANSPORT_NSW_API_KEY is not set. Set it, or use --from-zip.")

    print(f"Downloading complete GTFS bundle from {COMPLETE_GTFS_URL} ...")
    with requests.get(
        COMPLETE_GTFS_URL,
        headers={"Authorization": f"apikey {TRANSPORT_NSW_API_KEY}"},
        stream=True,
        timeout=300,
    ) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0)) or None
        with (
            open(dest, "wb") as f,
            tqdm(total=total, unit="B", unit_scale=True, ncols=80) as bar,
        ):
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                bar.update(len(chunk))


def extract_pathways(zip_path: Path, date: str) -> Path:
    out = PATHWAYS_DIR / date / "pathways.txt"
    with zipfile.ZipFile(zip_path) as zf:
        if "pathways.txt" not in zf.namelist():
            sys.exit(f"{zip_path} has no pathways.txt")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(zf.read("pathways.txt"))
    rows = sum(1 for _ in out.open(encoding="utf-8")) - 1
    print(f"Saved {rows} pathways to {out}")
    return out


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--from-zip", type=Path, help="existing complete GTFS zip to extract from"
    )
    args = parser.parse_args()

    today = str(datetime.now(ZoneInfo("Australia/Sydney")).date())

    if args.from_zip:
        # Date the copy by its folder (e.g. data/complete-gtfs/2026-05-20/) when it has one
        folder = args.from_zip.resolve().parent.name
        date = folder if re.fullmatch(r"\d{4}-\d{2}-\d{2}", folder) else today
        extract_pathways(args.from_zip, date)
        return

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "gtfs_complete.zip"
        try:
            download_bundle(zip_path)
        except requests.exceptions.RequestException as e:
            sys.exit(f"Download failed: {e}")
        extract_pathways(zip_path, today)


if __name__ == "__main__":
    main()
