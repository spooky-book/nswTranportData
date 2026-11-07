"""
Download Coles, Woolworths, Aldi, Foodworks and IGA store locations around Sydney.

Source: AllThePlaces (https://www.alltheplaces.xyz/, CC0), which scrapes each
retailer's own store locator weekly, so it is more complete than OpenStreetMap
tags and says which stores are small formats:
  - Coles Local: Coles stores whose branch name starts with "Coles Local", plus
    "Coles Central" (the older name for Coles' small CBD stores)
  - Woolworths Metro: brand "Woolworths Metro" (or "Metro" in the branch name)
Small formats carry a narrower range, usually at higher prices, so they are
marked separately from full supermarkets. Woolworths' online-order fulfilment
centres ("CFC") and Foodworks bottle shops are dropped because they aren't
grocery shops. Foodworks is an independent (Metcash-supplied) chain of mostly
small neighbourhood stores, so it is marked as not a full supermarket. IGA stores
are also independent and are split by format from their names: Romeo's IGA
(premium food halls) and Supa IGA are full-range; plain IGA varies in size; IGA
Local Grocer and IGA Xpress are convenience-sized.

Foodworks' and IGA's store locators give addresses but no coordinates, so those stores are
geocoded (see geocode()): first against NSW address points (NSW Spatial Services
Geocoded Addressing Theme, CC BY 4.0, built from G-NAF), then OpenStreetMap's
Nominatim for the few that don't match. Each store records how it was located in
`location_accuracy`: "store" (coordinates from the store locator), "address"
(the street address) or "street" (only the street was found, so it's approximate).
Results are cached in data/supermarkets/geocode_cache.json, so re-runs only look
up new addresses.

Keeps stores inside BBOX (Sydney plus the intercity network: Newcastle/Hunter,
Central Coast, Blue Mountains/Lithgow, Southern Highlands/Goulburn, Illawarra and
South Coast) and writes data/supermarkets/supermarkets.geojson, served by
GET /api/supermarkets.

Usage (from the project root; no API key or running server needed):
    uv run python scripts/download_supermarkets.py
"""

import json
import math
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "data" / "supermarkets"
OUTPUT_PATH = OUTPUT_DIR / "supermarkets.geojson"
GEOCODE_CACHE_PATH = OUTPUT_DIR / "geocode_cache.json"

LATEST_RUN_URL = "https://data.alltheplaces.xyz/runs/latest.json"
RUN_BASE_URL = (
    "https://alltheplaces-data.openaddresses.io/runs/{run_id}/output/{spider}.geojson"
)
SPIDERS = ["coles_au", "woolworths_au", "aldi_sud_au", "foodworks_au", "iga_au"]

NSW_ADDRESS_URL = (
    "https://portal.spatial.nsw.gov.au/server/rest/services/"
    "NSW_Geocoded_Addressing_Theme/FeatureServer/1/query"
)
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "nswTransportData/1.0 (personal research script)"

# Romeo's Retail Group runs IGA-supplied stores, but IGA's store locator lists some of
# them as plain IGA (North Sydney, Mortdale, Summer Hill) and misses others entirely
# (South Eveleigh, the Locali stores). So their NSW stores come from Romeo's own list,
# copied by hand from ROMEOS_URL (checked 2026-11-07; re-check it when re-downloading):
# (page slug, name, store type, address). Each replaces any IGA-locator store within
# ROMEOS_MATCH_M. Romeo's stores that only IGA's locator lists (Paddington, Parramatta,
# Turramurra) stay as IGA lists them.
ROMEOS_URL = "https://romeosretailgroup.com.au/locations-nsw/"
ROMEOS_MATCH_M = 100
ROMEOS_NSW = [
    (
        "bondi-food-hall",
        "Romeo's Food Hall Bondi",
        "romeos_iga",
        "48 Hall Street, Bondi Beach NSW 2026",
    ),
    (
        "doonside-supa-valu",
        "Romeo's Supa Valu Doonside",
        "iga",
        "52 Rosenthal Street, Doonside NSW 2767",
    ),
    (
        "george-st-locali",
        "Romeo's Locali George St",
        "romeos_small",
        "388 George Street, Sydney NSW 2000",
    ),
    (
        "martin-place-food-hall",
        "Romeo's Locali Martin Place",
        "romeos_small",
        "25 Martin Place, Sydney NSW 2000",
    ),
    (
        "mortdale-food-hall",
        "Romeo's Food Hall Mortdale",
        "romeos_iga",
        "42-44 Morts Road, Mortdale NSW 2223",
    ),
    (
        "north-sydney-food-hall",
        "Romeo's Food Hall North Sydney",
        "romeos_iga",
        "36 Blue Street, North Sydney NSW 2060",
    ),
    (
        "romeos-foodhall-st-leonards",
        "Romeo's Food Hall St Leonards",
        "romeos_iga",
        "201-205 Pacific Highway, St Leonards NSW 2065",
    ),
    (
        "south-eveleigh-food-hall",
        "Romeo's Food Hall South Eveleigh",
        "romeos_iga",
        "2 Locomotive Street, Eveleigh NSW 2015",
    ),
    (
        "summer-hill-food-hall",
        "Romeo's Food Hall Summer Hill",
        "romeos_iga",
        "1-11 Hardie Street, Summer Hill NSW 2130",
    ),
    (
        "wynyard-station-locali",
        "Romeo's Locali Wynyard Station",
        "romeos_small",
        "301 George Street, Sydney NSW 2000",
    ),
    (
        "kirribilli-romeos-local-grocer",
        "Romeo's Local Grocer Kirribilli",
        "romeos_small",
        "23-25 Broughton Street, Kirribilli NSW 2061",
    ),
]

# Store-locator addresses with street-name typos, corrected after checking the
# right spelling exists in the NSW address points (2026-11-07)
ADDRESS_FIXES = {
    "101 Carldarra Ave, Engadine, 2233, NSW": "101 Caldarra Avenue, Engadine, 2233, NSW",
    "Cnr Jacob Street & The Mall, Bankstown, 2200, NSW": (
        "Cnr Jacobs Street & The Mall, Bankstown, 2200, NSW"
    ),
}

NOT_A_SHOP = re.compile(r"\bCFC\b|fulfilment|bottle shop|\bliquor$", re.IGNORECASE)

# (min_lat, min_lon, max_lat, max_lon)
BBOX = (-35.0, 149.6, -32.0, 152.3)

SMALL_FORMAT_NOTE = "Small format: smaller range, usually pricier"
STORE_TYPES = {
    "coles": {"chain": "Coles", "label": "Coles", "full_store": True},
    "coles_local": {
        "chain": "Coles",
        "label": "Coles Local",
        "full_store": False,
        "note": SMALL_FORMAT_NOTE,
    },
    "woolworths": {"chain": "Woolworths", "label": "Woolworths", "full_store": True},
    "woolworths_metro": {
        "chain": "Woolworths",
        "label": "Woolworths Metro",
        "full_store": False,
        "note": SMALL_FORMAT_NOTE,
    },
    "aldi": {"chain": "Aldi", "label": "Aldi", "full_store": True},
    "foodworks": {
        "chain": "Foodworks",
        "label": "Foodworks",
        "full_store": False,
        "note": "Independent grocer: mostly small stores, usually pricier",
    },
    # IGA stores are independently owned (Metcash-supplied) and come in several formats
    "romeos_iga": {
        "chain": "IGA",
        "label": "Romeo's IGA",
        "full_store": True,
        "note": "Premium food hall: full range, pricier",
    },
    "romeos_small": {
        "chain": "IGA",
        "label": "Romeo's Locali / Local Grocer",
        "full_store": False,
        "note": "Small format: Romeo's convenience store, pricier",
    },
    "supa_iga": {
        "chain": "IGA",
        "label": "Supa IGA",
        "full_store": True,
        "note": "Large IGA: full range, usually pricier than Coles/Woolworths",
    },
    "iga": {
        "chain": "IGA",
        "label": "IGA",
        "full_store": False,
        "note": "Independent supermarket: size varies, usually pricier",
    },
    "iga_local": {
        "chain": "IGA",
        "label": "IGA Local Grocer / Xpress",
        "full_store": False,
        "note": "Small format: convenience-sized, usually pricier",
    },
}

# Street-type abbreviations -> the full words NSW address points use
STREET_TYPES = {
    "ST": "STREET",
    "RD": "ROAD",
    "AV": "AVENUE",
    "AVE": "AVENUE",
    "HWY": "HIGHWAY",
    "PDE": "PARADE",
    "DR": "DRIVE",
    "CRES": "CRESCENT",
    "PL": "PLACE",
    "BLVD": "BOULEVARD",
    "TCE": "TERRACE",
    "CT": "COURT",
    "LN": "LANE",
    "CL": "CLOSE",
    "CCT": "CIRCUIT",
    "SQ": "SQUARE",
    "ESP": "ESPLANADE",
    "GR": "GROVE",
    "HWAY": "HIGHWAY",
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
    if brand == "Foodworks":
        return "foodworks"
    if brand == "IGA":
        # The IGA locator also lists a few other Metcash banners (Supamart, Supa Valu, ...);
        # they're mid-size independents, so they count as plain IGA
        name = (props.get("name") or "").upper()
        if "ROMEO" in name:
            return "romeos_iga"
        if "SUPA IGA" in name:
            return "supa_iga"
        if re.search(r"IGA (LOCAL GROCER|X-?PRESS)", name):
            return "iga_local"
        return "iga"
    return None


def display_name(label: str, props: dict) -> str:
    """e.g. "Coles Local Chatswood", "Woolworths Metro Pitt St", "Aldi Auburn"."""
    if not props.get("branch") and props.get("brand") == "IGA":
        # IGA gives each store's own name ("Ritchies IGA Wauchope", "IGA PUTNEY + LIQUOR");
        # drop the liquor suffix and repair apostrophes that arrive as U+FFFD
        name = re.sub(
            r"\s*(\+|\bplus)\s*liquor\b", "", props.get("name") or "", flags=re.I
        )
        return name.replace("\ufffd", "'").strip() or label
    branch = (props.get("branch") or props.get("addr:city") or "").strip()
    if branch.lower().startswith(label.lower()):
        return branch
    for prefix in ("coles ", "woolworths ", "aldi ", "foodworks "):
        if branch.lower().startswith(prefix):
            branch = branch[len(prefix) :]
    return f"{label} {branch}".strip()


# "SHOP 5 ", "SHOP 1 & 2 ", "UNIT 4/", "LOT-4 ", "SHOP 1&3 / ", "2-4/" before the house number
UNIT_PREFIX = re.compile(
    r"^(?:(?:SHOPS?|UNIT|LOT|SUITE|KIOSK)[\s-]*[\dA-Z]*\d[\dA-Z]*"
    r"(?:\s*(?:&|AND|-)\s*[\dA-Z]*\d[\dA-Z]*)*\s*(?:/\s*|\s+|$)"
    r"|[\dA-Z]*\d[\dA-Z]*(?:\s*(?:&|-)\s*[\dA-Z]*\d[\dA-Z]*)*\s*/\s*)"
)


def parse_nsw_address(full: str) -> dict | None:
    """
    Split e.g. "Shop 5 172 New England HWY, ABERDEEN NSW 2336" (Foodworks) or
    "1/137 Croudace Road, Elermore Vale, 2287, NSW" (IGA) into
    {"number": "172", "number_full": "172", "street": "NEW ENGLAND HIGHWAY", "suburb": "ABERDEEN",
    "postcode": "2336"}.
    Unit/shop prefixes are dropped; "number" is the first house number of a range
    ("88-94" -> "88"). Returns None for non-NSW addresses; street/number are None
    when the address has no street line (e.g. just "EAST MAITLAND NSW 2323").
    """
    m = re.match(
        r"^(.*?)[,\s]+(?:NSW[,\s]+(\d{4})|(\d{4})[,\s]+NSW)\s*$",
        full.strip(),
        re.IGNORECASE,
    )
    if not m:
        return None
    parts = [p.strip() for p in m.group(1).upper().split(",") if p.strip()]
    if not parts:
        return None
    suburb = parts.pop()
    # "...STREET ABERDEEN" with no comma before the suburb isn't handled; ATP always has one
    street = number = number_full = None
    for part in reversed(parts):
        # "SHOP 13 & 14 MELVILLE ROAD": 13 and 14 are shop numbers, not the house number
        part = UNIT_PREFIX.sub("", part).rstrip(" &")  # "LINDEN AVE &"
        if corner := re.match(r"CNR\.?\s+([A-Z][A-Z' ]+?)\s*(?:&|AND)\s", part):
            street = street or corner.group(1)  # "CNR JACOB STREET & THE MALL"
            continue
        hit = re.search(r"(\d+[A-Z]?)(?:\s*-\s*(\d+[A-Z]?))?\s+([A-Z][A-Z' ]+)$", part)
        if hit:
            number = hit.group(1)
            number_full = f"{hit.group(1)}-{hit.group(2)}" if hit.group(2) else number
            street = hit.group(3)
            break
        if not street and re.fullmatch(r"[A-Z][A-Z' ]+", part):
            street = part  # e.g. "LINKS AVENUE" with no number
    if street:
        words = street.split()
        if words[-1] in STREET_TYPES:
            words[-1] = STREET_TYPES[words[-1]]
        street = " ".join(words)
    return {
        "number": number,
        "number_full": number_full,
        "street": street,
        "suburb": suburb,
        "postcode": m.group(2) or m.group(3),
    }


def _nsw_query(where: str) -> list[dict]:
    res = requests.get(
        NSW_ADDRESS_URL,
        params={"where": where, "outFields": "address", "outSR": 4326, "f": "json"},
        headers={"User-Agent": USER_AGENT},
        timeout=60,
    )
    res.raise_for_status()
    return res.json().get("features", [])


def _nominatim(**query) -> dict | None:
    time.sleep(1.1)  # Nominatim's usage policy: at most one request per second
    res = requests.get(
        NOMINATIM_URL,
        params={**query, "countrycodes": "au", "format": "jsonv2", "limit": 1},
        headers={"User-Agent": USER_AGENT},
        timeout=60,
    )
    res.raise_for_status()
    hits = res.json()
    return hits[0] if hits else None


def _nominatim_address(street: str, suburb: str) -> dict | None:
    return _nominatim(street=street, city=suburb, state="New South Wales")


def _nsw_address(a: dict, suburb: str) -> dict | None:
    """NSW address point for parse_nsw_address() result `a` in `suburb`, or None."""
    tail = f"{a['street']} {suburb}".replace("'", "''")
    for candidate in dict.fromkeys([a["number_full"], a["number"]]):
        hits = _nsw_query(f"address = '{candidate} {tail}'")
        if hits:
            break
    else:
        # Prefix match, keeping only addresses whose number really starts with ours
        hits = [
            h
            for h in _nsw_query(f"address LIKE '{a['number']}% {tail}'")
            if re.match(rf"{a['number']}(?:[A-Z]|-|\s)", h["attributes"]["address"])
        ]
    if not hits:
        return None
    g = hits[0]["geometry"]
    return {
        "lat": g["y"],
        "lon": g["x"],
        "accuracy": "address",
        "matched": hits[0]["attributes"]["address"],
    }


def _street_in_postcode(street: str, postcode: str) -> dict | None:
    """
    Nominatim's match for `street` in `postcode`, with its official suburb, or None.
    Store locators sometimes give an unofficial suburb ("Oakhill" for Castle Hill,
    "Taren Point" for a Caringbah address), which the NSW lookup can't match.
    Nominatim can ignore the postcode, so the result's postcode must match.
    """
    hit = _nominatim(q=f"{street}, {postcode}, New South Wales", addressdetails=1)
    address = (hit or {}).get("address", {})
    if not hit or address.get("postcode") != postcode:
        return None
    suburb = next(
        (address[k] for k in ("suburb", "town", "village", "hamlet") if address.get(k)),
        None,
    )
    return {**hit, "official_suburb": suburb.upper() if suburb else None}


def geocode(full: str, chain: str) -> dict | None:
    """
    {"lat", "lon", "accuracy": "address" | "street", "matched": <what was found>} for a
    store of `chain` at an NSW street address, or None. Tries NSW address points (exact,
    then the house number as a prefix to catch "88-92" or "14A"), the same with the
    official suburb for the street's postcode, Nominatim with the number, the store
    itself if it's mapped in OpenStreetMap ("Foodworks, Glenbrook"), and finally just
    the street ("street" accuracy).
    """
    a = parse_nsw_address(full)
    if not a:
        return None
    if not a["street"]:
        return _osm_shop(chain, a["suburb"])
    if a["number"] and (found := _nsw_address(a, a["suburb"])):
        return found
    in_postcode = _street_in_postcode(a["street"], a["postcode"])
    official = (in_postcode or {}).get("official_suburb")
    if a["number"] and official and official != a["suburb"]:
        if found := _nsw_address(a, official):
            return found
    if a["number"]:
        hit = _nominatim_address(f"{a['number']} {a['street']}", a["suburb"])
        if hit and hit.get("category") != "highway":
            return {
                "lat": float(hit["lat"]),
                "lon": float(hit["lon"]),
                "accuracy": "address",
                "matched": hit["display_name"],
            }
    if shop := _osm_shop(chain, a["suburb"]):
        return shop
    hit = _nominatim_address(a["street"], a["suburb"]) or in_postcode
    if hit:
        return {
            "lat": float(hit["lat"]),
            "lon": float(hit["lon"]),
            "accuracy": "street",
            "matched": hit["display_name"],
        }
    return None


def _osm_shop(chain: str, suburb: str) -> dict | None:
    """The chain's shop in `suburb` if it's mapped in OpenStreetMap."""
    hit = _nominatim(q=f"{chain}, {suburb}, New South Wales")
    name = (hit or {}).get("name") or ""
    if (
        hit
        and hit.get("category") == "shop"
        and chain.lower() in name.lower().replace(" ", "")
    ):
        return {
            "lat": float(hit["lat"]),
            "lon": float(hit["lon"]),
            "accuracy": "address",
            "matched": f"OSM shop: {hit['display_name']}",
        }
    return None


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Equirectangular distance; plenty accurate over a few hundred metres."""
    dx = math.radians(lon2 - lon1) * math.cos(math.radians(lat1))
    return 6_371_000 * math.hypot(math.radians(lat2 - lat1), dx)


def add_romeos(features: list, geocode_cache: dict, not_found: list) -> None:
    """Add ROMEOS_NSW to `features`, replacing IGA-locator duplicates of each store."""
    for slug, name, store_type, full in ROMEOS_NSW:
        if full not in geocode_cache:
            geocode_cache[full] = geocode(full, "IGA")
        hit = geocode_cache[full]
        if hit is None:
            not_found.append(f"{name}: {full}")
            continue
        features[:] = [
            f
            for f in features
            if f["properties"]["chain"] != "IGA"
            or _distance_m(hit["lat"], hit["lon"], *f["geometry"]["coordinates"][::-1])
            > ROMEOS_MATCH_M
        ]
        info = STORE_TYPES[store_type]
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "id": f"romeos:{slug}",
                    "name": name,
                    "chain": info["chain"],
                    "store_type": store_type,
                    "store_type_label": info["label"],
                    "full_store": info["full_store"],
                    "address": full,
                    "opening_hours": None,
                    "website": (
                        f"https://romeosretailgroup.com.au/{slug}/"
                        if slug.startswith("kirribilli")
                        else f"{ROMEOS_URL}{slug}/"
                    ),
                    "location_accuracy": hit["accuracy"],
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [round(hit["lon"], 6), round(hit["lat"], 6)],
                },
            }
        )


def load_geocode_cache() -> dict:
    if GEOCODE_CACHE_PATH.exists():
        return json.loads(GEOCODE_CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def main():
    try:
        latest = requests.get(LATEST_RUN_URL, timeout=60).json()
    except requests.RequestException as e:
        sys.exit(f"Couldn't reach AllThePlaces: {e}")
    run_id = latest["run_id"]
    print(f"AllThePlaces run {run_id}")

    geocode_cache = load_geocode_cache()
    not_found = []

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
            if store_type is None:
                continue
            if geom.get("type") == "Point":
                lon, lat = geom["coordinates"][:2]
                accuracy = "store"
            else:
                full = props.get("addr:full") or ""
                full = ADDRESS_FIXES.get(full, full)
                if not parse_nsw_address(full):
                    continue  # interstate
                if full not in geocode_cache:
                    try:
                        geocode_cache[full] = geocode(
                            full, STORE_TYPES[store_type]["chain"]
                        )
                    except requests.RequestException as e:
                        print(f"    geocoding failed for {full!r}: {e}")
                        continue
                hit = geocode_cache[full]
                if hit is None:
                    not_found.append(
                        f"{props.get('branch') or props.get('name')}: {full}"
                    )
                    continue
                lat, lon, accuracy = hit["lat"], hit["lon"], hit["accuracy"]
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
                        # Foodworks has no addr:city, so its street line alone isn't enough
                        "address": (
                            address
                            if props.get("addr:city")
                            else props.get("addr:full") or address or None
                        ),
                        "opening_hours": props.get("opening_hours"),
                        "website": props.get("website"),
                        "location_accuracy": accuracy,
                    },
                    "geometry": {
                        "type": "Point",
                        "coordinates": [round(lon, 6), round(lat, 6)],
                    },
                }
            )

    try:
        add_romeos(features, geocode_cache, not_found)
    except requests.RequestException as e:
        print(f"    geocoding Romeo's stores failed: {e}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    GEOCODE_CACHE_PATH.write_text(json.dumps(geocode_cache, indent=1), encoding="utf-8")

    features.sort(key=lambda f: f["properties"]["name"])
    counts = Counter(f["properties"]["store_type"] for f in features)
    collection = {
        "type": "FeatureCollection",
        "metadata": {
            "source": "AllThePlaces (CC0), scraped from each retailer's store locator",
            "geocoding": (
                "Stores without coordinates were located from their address: NSW Spatial "
                "Services Geocoded Addressing Theme (CC BY 4.0), else OpenStreetMap Nominatim (ODbL)"
            ),
            "alltheplaces_run": run_id,
            "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "bbox": BBOX,
            "store_types": STORE_TYPES,
            "counts": dict(counts),
        },
        "features": features,
    }

    OUTPUT_PATH.write_text(json.dumps(collection), encoding="utf-8")
    for key in STORE_TYPES:
        print(f"  {STORE_TYPES[key]['label']:<17} {counts[key]:>4}")
    accuracy = Counter(f["properties"]["location_accuracy"] for f in features)
    print(f"  located by: {dict(accuracy)}")
    if not_found:
        print(f"  {len(not_found)} NSW addresses couldn't be located (skipped):")
        for line in not_found:
            print(f"    {line}")
    print(f"Saved {len(features):,} stores to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
