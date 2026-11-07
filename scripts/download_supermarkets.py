"""
Download Coles, Woolworths and Aldi store locations around Sydney.

Source: AllThePlaces (https://www.alltheplaces.xyz/, CC0), which scrapes each
retailer's own store locator weekly, so it is more complete than OpenStreetMap
tags and says which stores are small formats:
  - Coles Local: Coles stores whose branch name starts with "Coles Local", plus
    "Coles Central" (the older name for Coles' small CBD stores)
  - Woolworths Metro: brand "Woolworths Metro" (or "Metro" in the branch name)
Small formats carry a narrower range, usually at higher prices, so they are
marked separately from full supermarkets. Woolworths' online-order fulfilment
centres ("CFC") are dropped because they aren't shops.

Keeps stores inside BBOX (Sydney plus the intercity network: Newcastle/Hunter,
Central Coast, Blue Mountains/Lithgow, Southern Highlands/Goulburn, Illawarra and
South Coast) and writes data/supermarkets/supermarkets.geojson, served by
GET /api/supermarkets.

Usage (from the project root; no API key or running server needed):
    uv run python scripts/download_supermarkets.py
"""

import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = PROJECT_ROOT / "data" / "supermarkets" / "supermarkets.geojson"

LATEST_RUN_URL = "https://data.alltheplaces.xyz/runs/latest.json"
RUN_BASE_URL = (
    "https://alltheplaces-data.openaddresses.io/runs/{run_id}/output/{spider}.geojson"
)
SPIDERS = ["coles_au", "woolworths_au", "aldi_sud_au"]

NOT_A_SHOP = re.compile(r"\bCFC\b|fulfilment", re.IGNORECASE)

# (min_lat, min_lon, max_lat, max_lon)
BBOX = (-35.0, 149.6, -32.0, 152.3)

STORE_TYPES = {
    "coles": {"chain": "Coles", "label": "Coles", "full_store": True},
    "coles_local": {"chain": "Coles", "label": "Coles Local", "full_store": False},
    "woolworths": {"chain": "Woolworths", "label": "Woolworths", "full_store": True},
    "woolworths_metro": {
        "chain": "Woolworths",
        "label": "Woolworths Metro",
        "full_store": False,
    },
    "aldi": {"chain": "Aldi", "label": "Aldi", "full_store": True},
}


def classify(props: dict) -> str | None:
    """Store type key for an AllThePlaces feature, or None to skip it."""
    if props.get("shop") != "supermarket":
        return None  # Liquorland, First Choice etc. share the Coles spider
    brand = props.get("brand", "")
    branch = (props.get("branch") or "").lower()
    if NOT_A_SHOP.search(branch):
        return None
    if brand == "Coles":
        small = branch.startswith(("coles local", "coles central"))
        return "coles_local" if small else "coles"
    if brand == "Woolworths Metro" or (brand == "Woolworths" and "metro" in branch):
        return "woolworths_metro"
    if brand == "Woolworths":
        return "woolworths"
    if brand == "Aldi":
        return "aldi"
    return None


def display_name(label: str, props: dict) -> str:
    """e.g. "Coles Local Chatswood", "Woolworths Metro Pitt St", "Aldi Auburn"."""
    branch = (props.get("branch") or props.get("addr:city") or "").strip()
    if branch.lower().startswith(label.lower()):
        return branch
    for prefix in ("coles ", "woolworths ", "aldi "):
        if branch.lower().startswith(prefix):
            branch = branch[len(prefix) :]
    return f"{label} {branch}".strip()


def main():
    try:
        latest = requests.get(LATEST_RUN_URL, timeout=60).json()
    except requests.RequestException as e:
        sys.exit(f"Couldn't reach AllThePlaces: {e}")
    run_id = latest["run_id"]
    print(f"AllThePlaces run {run_id}")

    min_lat, min_lon, max_lat, max_lon = BBOX
    features = []
    for spider in SPIDERS:
        url = RUN_BASE_URL.format(run_id=run_id, spider=spider)
        res = requests.get(url, timeout=300)
        res.raise_for_status()
        source = res.json()["features"]
        print(f"  {spider}: {len(source):,} locations Australia-wide")

        for f in source:
            props = f.get("properties", {})
            geom = f.get("geometry") or {}
            store_type = classify(props)
            if store_type is None or geom.get("type") != "Point":
                continue
            lon, lat = geom["coordinates"][:2]
            if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
                continue
            info = STORE_TYPES[store_type]
            address = ", ".join(
                p
                for p in (
                    props.get("addr:street_address"),
                    props.get("addr:city"),
                    props.get("addr:postcode"),
                )
                if p
            )
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "id": f"{spider}:{props.get('ref')}",
                        "name": display_name(info["label"], props),
                        "chain": info["chain"],
                        "store_type": store_type,
                        "store_type_label": info["label"],
                        "full_store": info["full_store"],
                        "address": address or None,
                        "opening_hours": props.get("opening_hours"),
                        "website": props.get("website"),
                    },
                    "geometry": {
                        "type": "Point",
                        "coordinates": [round(lon, 6), round(lat, 6)],
                    },
                }
            )

    features.sort(key=lambda f: f["properties"]["name"])
    counts = Counter(f["properties"]["store_type"] for f in features)
    collection = {
        "type": "FeatureCollection",
        "metadata": {
            "source": "AllThePlaces (CC0), scraped from each retailer's store locator",
            "alltheplaces_run": run_id,
            "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "bbox": BBOX,
            "store_types": STORE_TYPES,
            "counts": dict(counts),
        },
        "features": features,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(collection), encoding="utf-8")
    for key in STORE_TYPES:
        print(f"  {STORE_TYPES[key]['label']:<17} {counts[key]:>4}")
    print(f"Saved {len(features):,} stores to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
