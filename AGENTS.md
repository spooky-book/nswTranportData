# NSW Transport Data — Project Context

> **Purpose of this file:** Give AI coding agents a working understanding of this project:
> its goals, architecture, data flow, conventions, and current state. This is the single
> source of truth for agent instructions; `CLAUDE.md` just imports it. Keep it in sync with
> the code. When you add or rename an endpoint, mode, script, or dependency, update this file
> and `README.md` too.

---

## 1. Project Overview

A **Python 3.14 / Flask** application that consumes **GTFS schedule** data from the
[Transport for NSW (TfNSW) Open Data API](https://opendata.transport.nsw.gov.au/) and
exposes it via a JSON API plus a small browser UI. It is used to:

1. List and search stations/stops for each NSW transit mode.
2. Compute service statistics: per-station daily stats, and direct point-to-point headways and travel times.
3. Plan journeys between stations, including transfers.
4. Compute walking/cycling **isochrones** on a local OpenStreetMap graph, and explore them in a Leaflet UI.
5. Batch-generate GeoJSON/CSV datasets (via `scripts/`) by calling the running API.

Scope is **Sydney / NSW public transport** only. It is a personal/exploratory tool and is not packaged for distribution.

---

## 2. Commands

```bash
uv sync                                   # create .venv and install locked deps
uv run python src/app.py                  # dev server on http://localhost:5000 (PORT overrides)
uv run ruff check <files>                 # lint (ruff defaults; no config file)
uv run ruff format <files>                # format
uv add <pkg> / uv remove <pkg>            # manage dependencies
git lfs pull --exclude=                   # fetch data/osmnx/sydney_walk.graphml (~530 MB)
uv run python scripts/download_graph.py   # ...or rebuild that graph from Overpass (slow)
```

- Feed downloads need `TRANSPORT_NSW_API_KEY`. A download happens on the first request for a mode
  on each new Sydney calendar day; the key is only needed when today's zip isn't already cached.
- `.lfsconfig` puts the walk graph in `fetchexclude`, so plain `git lfs pull` skips it. `--exclude=`
  clears that for one run. Without the graph, the GTFS endpoints still work but the isochrone endpoints return 500.
- **Ruff isn't clean repo-wide**, so `ruff format .` or `ruff check --fix .` rewrites unrelated files.
  Pass only the files you changed.
- **There is no test suite or test runner.** To verify a change, run the server and call the endpoint:
  ```bash
  curl -s -X POST localhost:5000/api/trip-stats -H "Content-Type: application/json" \
    -d '{"origin_stop_id": "200060", "destination_stop_id": "215020"}'
  ```
  200060 is Central and 215020 is Parramatta. Each endpoint's docstring documents its full request and response JSON.
- `app.run(debug=True)` restarts the server whenever a `.py` file changes, which throws away the
  in-memory feed and graph caches. Expect the next GTFS request (download + parse) and the next
  isochrone request (~530 MB graph load) to be slow and memory-heavy.

---

## 3. Directory Structure

```
nswTranportData/
├── src/                          # Flask app (import root = src/)
│   ├── __init__.py
│   ├── app.py                    # create_app(): registers blueprints, GET / index; entry point
│   ├── config.py                 # PROJECT_ROOT, DATA_DIR, API key, TRANSPORT_MODES, DEFAULT_MODE, FLASK_PORT
│   ├── constants.py              # LocationTypeEnum (GTFS location_type 0–4)
│   ├── api/
│   │   ├── __init__.py
│   │   ├── stations.py           # GET  /api/stations
│   │   ├── stops.py              # GET  /api/stops
│   │   ├── stop_stats.py         # POST /api/stop-stats  (also owns shared validation helpers)
│   │   ├── trip_stats.py         # POST /api/trip-stats  (also owns _time_to_seconds)
│   │   ├── trips.py              # POST /api/trips       (journey planner with transfers)
│   │   └── isochrone.py          # POST /api/isochrone, GET /api/map, GET /api/network
│   ├── gtfs/
│   │   ├── __init__.py
│   │   ├── downloader.py         # Downloads & caches GTFS zips from TfNSW (per Sydney date)
│   │   └── loader.py             # gtfs_kit Feed loading, normalising, filtering, merging, caching
│   └── templates/
│       └── isochrone_map.html    # Isochrone Explorer UI (Leaflet + Turf.js from unpkg CDN)
│
├── scripts/                      # Standalone scripts (see §6)
│   ├── download_graph.py
│   ├── generate_station_isochrones.py
│   ├── generate_supermarket_isochrones.py
│   └── all_to_central.py
│
├── data/                         # Mostly git-ignored (see .gitignore)
│   ├── schedule-gtfs/<YYYY-MM-DD>/<cache_folder>/gtfs_schedule.zip   # GTFS cache (ignored)
│   └── osmnx/sydney_walk.graphml # ~530 MB walking graph, tracked with Git LFS
│
├── maps/gtfs_shapes_sydneyTrains.html   # Legacy Folium output (see §12)
├── *.geojson                     # Committed outputs of the isochrone scripts
├── stats_to_destination_*.csv    # Committed output of all_to_central.py
├── pyproject.toml / uv.lock / .python-version
├── .gitattributes                # LFS rule for sydney_walk.graphml
├── .lfsconfig                    # fetchexclude for sydney_walk.graphml (clones skip it)
├── AGENTS.md                     # This file
├── CLAUDE.md                     # Imports AGENTS.md for Claude Code
├── README.md                     # User-facing docs
└── LICENSE                       # CC BY-NC 4.0
```

---

## 4. Key Modules

### 4.1 `src/app.py`: Application Factory

- `create_app()` registers `stations_bp`, `stops_bp`, `stop_stats_bp`, `trip_stats_bp`,
  `trips_bp` and `isochrone_bp` (all use `url_prefix="/api"`).
- `GET /` returns a hand-maintained JSON index of endpoints. Update it when you add an endpoint.
- `uv run python src/app.py` runs with `debug=True` on `FLASK_PORT`.

### 4.2 `src/config.py`: Configuration

- `PROJECT_ROOT`; `DATA_DIR = PROJECT_ROOT / "data" / "schedule-gtfs"` (GTFS cache only, **not** `data/`).
- `TRANSPORT_NSW_API_KEY` is read from the environment at import time.
- `TRANSPORT_MODES` maps a mode key to `api_path`, `cache_folder`, and optional `version`
  (default `"v1"`; Sydney Metro uses `"v2"`). See §8.
- `DEFAULT_MODE = "sydney_trains"`. `FLASK_PORT` comes from `PORT` (default `5000`).
- Every GTFS endpoint takes `mode` (a query param on GET, a JSON field on POST) and defaults to `sydney_trains`.

### 4.3 `src/constants.py`

- `LocationTypeEnum(IntEnum)`: `PLATFORMSTOP=0`, `STATION=1`, `ENTRANCE=2`, `GENERIC_NODE=3`, `BOARDING_AREA=4`.

### 4.4 `src/gtfs/downloader.py`: GTFS Downloader

- `get_gtfs_zip_path(mode) -> Path`: returns
  `data/schedule-gtfs/<today in Australia/Sydney>/<cache_folder>/gtfs_schedule.zip`, downloading
  it first if absent from `https://api.transport.nsw.gov.au/<version>/gtfs/schedule/<api_path>`
  with header `Authorization: apikey <key>` and a `tqdm` progress bar.
- Raises `ValueError` (unknown mode, including the virtual `sydney_trains_and_metro`),
  `EnvironmentError` (no API key when a download is needed), or `RuntimeError` (HTTP or network failure).
- Old date folders are never cleaned up automatically.

### 4.5 `src/gtfs/loader.py`: Feed Loader

- `get_feed(mode=DEFAULT_MODE) -> gtfs_kit.Feed` keeps one `Feed` per mode in `_feed_cache` for the
  life of the process. It is never refreshed at midnight, so restart the server to pick up a new day's feed.
  It uses double-checked locking (`RLock`) because the dev server is threaded and the scripts send concurrent requests.
- Load pipeline: `gk.read_feed(zip, dist_units="km")` → `_normalise_feed` → `_filter_non_passenger_services`.
  **All endpoint code assumes these transforms:**
  - `_normalise_feed` converts pandas nullable dtypes (`Int32`, `string`) to `object`. Cells then hold
    plain `int`/`str` values and missing values are `None`, not `pd.NA`. That's why endpoints compare
    `location_type` with plain ints (`LocationTypeEnum`) and can `jsonify` DataFrame records directly.
  - `_filter_non_passenger_services` drops trips whose `trip_headsign` contains "Empty Train" and
    stop_times where `pickup_type == 1 and drop_off_type == 1` (pass-through timing points). Stops that
    are pickup-only or drop-off-only remain, so routing code still checks each column separately.
- **Virtual mode `sydney_trains_and_metro`**: only `get_feed` knows about it; it isn't in `TRANSPORT_MODES`.
  - `_merge_feeds` concatenates the `sydney_trains` and `sydney_metro` tables and deduplicates on GTFS
    keys; Sydney Trains rows win.
  - The two feeds share parent station IDs at interchanges (Central 200060, Martin Place, Sydenham,
    Chatswood, Epping). The journey planner uses those shared IDs to transfer between trains and metro.
  - It works for every endpoint because they all go through `get_feed`.
- `clear_cache()` empties the in-memory cache.

### 4.6 `src/api/stations.py`: `GET /api/stations`

- Query params: `search` (case-insensitive substring on `stop_name`), `mode`.
- Returns `location_type == 1` stops; if the feed has none (e.g. some light rail), falls back to
  platforms (`location_type` 0 or missing).
- Response: `{count, mode, stations: [{stop_id, stop_name, stop_lat, stop_lon, parent_station, location_type}]}`.

### 4.7 `src/api/stops.py`: `GET /api/stops`

- Generic version of stations. Query params: `search`, `mode`, `location_type` (0–4, optional).
- Response: `{count, mode, location_type_filter, stops: [{..., location_type, location_type_label}]}`.

### 4.8 `src/api/stop_stats.py`: `POST /api/stop-stats`

- Body (all optional): `mode`, `dates` (YYYYMMDD list), `stop_ids` (parent station IDs),
  `headway_start_time`, `headway_end_time` (defaults `07:00:00` to `19:00:00`).
- Resolves station → child platforms → `feed.compute_stop_stats()` → aggregates back to the station
  (`num_trips` summed, `num_routes` unique, earliest `start_time`, latest `end_time`; headways omitted).
- **Shared helpers imported by other blueprints:** `_validate_date`, `_validate_time`, `_resolve_dates`.
  A change to one of them affects several endpoints.
  - `_resolve_dates` drops requested dates outside the feed's range and explains why in the response's
    `warning` field. If no valid dates remain, it falls back to the feed's first date.
  - Its default "today" uses the **machine's local date** (`date.today()`), whereas the downloader uses Australia/Sydney.

### 4.9 `src/api/trip_stats.py`: `POST /api/trip-stats`

- Direct (single-trip, no transfer) stats between `origin_stop_id` and `destination_stop_id` (parent station IDs).
- Optional: `mode`, `dates`, `time_window_start` / `time_window_end` (default `00:00:00` to `29:59:59`, filtered on departure).
- Per date: `num_trips`, `num_routes`, `start_time`, `end_time`, `min/mean/median/mode/max_headway_secs`,
  `travel_time_min/mean/median/mode/max_secs`, and a `trips` list.
- Exports `_time_to_seconds` (used by `trips.py`).

### 4.10 `src/api/trips.py`: `POST /api/trips`

- Journey planner with transfers. Each request rebuilds a timetable from `stop_times` for every requested date.
- For each departure from the origin's platforms inside the time window, it runs Dijkstra over
  (time, transfers) with per-platform Pareto pruning.
- Body: `origin_stop_id`, `destination_stop_id` (required); `mode`, `max_transfers` (default 5),
  `time_window_start/end`, `dates`.
- Transfers are allowed between platforms that share a parent station. The minimum connection time comes
  from `get_transfer_time_secs()`, currently a constant **180 s** (it's the hook for per-station values).
  The longest wait it considers is about 2 h. Walking transfers between different stations are not modelled.
- Results are de-duplicated per departure time (keeping the earliest arrival, then the fewest transfers),
  and any journey overtaken by a later departure is dropped.
  Response: `{..., date_records: [{date, journeys: [{departure_time, arrival_time, total_travel_secs, transfers, legs: [...]}]}]}`.

### 4.11 `src/api/isochrone.py`: Isochrones and Map UI (independent of GTFS)

- `get_graph()` lazily loads `data/osmnx/sydney_walk.graphml` into a module-level global under a lock and
  precomputes node `penalty_sec`: 30 s at `traffic_signals`, 10 s at `crossing`. Paths are resolved from
  `__file__` (`GRAPH_PATH` lives in this module, not `config.py`).
- `POST /api/isochrone`: body `{lat, lon, speed=1.4 m/s, max_duration_minutes=15, resolution="high"}`.
  Finds the nearest node, runs `nx.single_source_dijkstra_path_length` with a weight of
  `length / speed + penalty_sec(v)`, cut off at the time budget, then builds a polygon:
  - `ultra` / `high`: shapely `concave_hull` over the reachable nodes plus edge-geometry points (ratio 0.15 / 0.35).
  - `low`: convex hull of the reachable nodes.
  - With fewer than 3 points it returns a buffered circle and sets `fallback_circle: true`.
  Returns `{lat, lon, speed, max_duration_minutes, resolution, isochrone: <GeoJSON Polygon>, ...}`.
- **Hidden dependency:** `scikit-learn` is never imported directly, but `osmnx.distance.nearest_nodes`
  needs it for this unprojected graph.
- `GET /api/map` renders `templates/isochrone_map.html`, a single file with inline JS that loads Leaflet 1.9.4
  and Turf 6 from unpkg. The UI calls `/api/isochrone` and `/api/network`, can toggle the street network
  overlay, import/export GeoJSON layers, and union, intersect or XOR layers with Turf.
- `GET /api/network?lat=&lon=` returns graph edges within ±0.015° (about 1.5 km) as GeoJSON for debugging.

---

## 5. Data Flow

```
TfNSW GTFS API ──(HTTPS + apikey)──► gtfs/downloader.py ──► data/schedule-gtfs/<date>/<mode>/gtfs_schedule.zip
                                                                     │
                                                                     ▼
                                    gtfs/loader.py: read_feed → normalise → filter (→ merge) → in-memory cache
                                                                     │
                                                                     ▼
                     api/stations · stops · stop_stats · trip_stats · trips  (Flask, src/app.py)

OSM (osmnx) ──► scripts/download_graph.py ──► data/osmnx/sydney_walk.graphml ──► api/isochrone.py ──► /api/map UI

scripts/generate_*_isochrones.py, scripts/all_to_central.py ──(HTTP to localhost:5000)──► *.geojson / *.csv
```

---

## 6. Scripts (`scripts/`)

Run them from the project root. Every script except `download_graph.py` is an HTTP client of the running server
(`API_BASE_URL = "http://localhost:5000/api"`) and writes its output to the current directory, which is where the
output files at the repo root came from. The GeoJSON files are meant to be loaded into the map UI.
Configuration is hard-coded as constants at the top of each file.

| Script | What it does |
|---|---|
| `download_graph.py` | `ox.graph_from_place("Sydney, NSW")` with a custom Overpass filter that is more permissive than OSMnx's `walk` network. It keeps footpaths, shared paths, cycleways and bridges, and excludes motorways, trunks, platforms, private access and `foot=no`. Writes `data/osmnx/sydney_walk.graphml`. osmnx caches Overpass responses in `./cache/` (git-ignored). |
| `generate_station_isochrones.py` | Isochrones for a hard-coded `STATIONS_INPUT` list (`stop_id, name, mode`). Writes `station_isochrones.geojson`. |
| `generate_supermarket_isochrones.py` | Uses OSM to find Coles, Woolworths and Aldi stores, then builds an isochrone for each. Writes `supermarket_isochrones.geojson`. |
| `all_to_central.py` | Stats from every `sydney_trains` and `sydney_metro` station to Central (`200060`). Writes `stats_to_destination_*.csv`. **Currently broken** (see §11). |

---

## 7. Dependencies

The project uses **[uv](https://docs.astral.sh/uv/)** (`pyproject.toml`, `uv.lock`, `.python-version` = 3.14).

| Package | Used for |
|---|---|
| flask (+ jinja2, werkzeug) | Web framework and template rendering |
| gtfs-kit | GTFS feed parsing and `compute_stop_stats` |
| pandas, numpy | Table manipulation and stats |
| requests, tqdm | TfNSW downloads with progress; script HTTP clients |
| osmnx, networkx | Walking graph download/load and Dijkstra |
| shapely | Concave/convex hull isochrone polygons |
| scikit-learn | Required by `osmnx.distance.nearest_nodes` for unprojected graphs |
| ruff | Lint and format |

**Installed but unused by current code:** `folium` and `branca` (left over from the old map generator), `partridge`, and `pyarrow` (not imported directly).
Most of the other pinned packages are transitive dependencies listed explicitly.

---

## 8. Transport Modes

| Mode key                    | API path                    | API ver | Cache folder                     |
|-----------------------------|-----------------------------|---------|----------------------------------|
| `sydney_trains` (default)   | `sydneytrains`              | v1      | `sydney_trains`                  |
| `sydney_metro`              | `metro`                     | v2      | `sydney_metro`                   |
| `nsw_trains`                | `nswtrains`                 | v1      | `nsw_trains`                     |
| `light_rail_parramatta`     | `lightrail/parramatta`      | v1      | `light_rail_parramatta`          |
| `light_rail_inner_west`     | `lightrail/innerwest`       | v1      | `light_rail_inner_west`          |
| `light_rail_cbd_south_east` | `lightrail/cbdandsoutheast` | v1      | `light_rail_city_and_south_west` |
| `light_rail_newcastle`      | `lightrail/newcastle`       | v1      | `light_rail_newcastle`           |
| `ferries_sydney`            | `ferries/sydneyferries`     | v1      | `ferries_sydney_ferries`         |
| `ferries_mff`               | `ferries/MFF`               | v1      | `ferries_mff`                    |
| `sydney_trains_and_metro`   | *(virtual: merge of trains and metro, in `loader.py`)* | n/a | n/a (memory only) |

To add a mode, add an entry to `TRANSPORT_MODES` in `src/config.py`, then update the tables here and in `README.md`.

---

## 9. GTFS Notes

- Standard tables are used: `agency`, `stops`, `routes`, `trips`, `stop_times`, `calendar`, `calendar_dates`, `shapes`.
- **Stations vs platforms.** Station IDs are **parent stations** (`location_type = 1`, e.g. Central = `200060`,
  Parramatta = `215020`). `stop_times` only references **child platforms** (`parent_station` = station ID).
  `/api/stop-stats`, `/api/trip-stats` and `/api/trips` take station IDs, resolve them to platforms via
  `stops.parent_station`, compute per platform, then aggregate up to the station.
- GTFS times are `HH:MM:SS` strings, and the hour exceeds 23 for after-midnight services. Time-window defaults
  run from `00:00:00` to `29:59:59`. Convert with `_time_to_seconds` before doing arithmetic; never use `datetime.time`.
- Dates are `YYYYMMDD` strings. The downloader's "today" is Australia/Sydney; `_resolve_dates`' default is the machine's local date.

---

## 10. Conventions

- **Import root is `src/`**: write `from gtfs.loader import get_feed`, `from config import ...`, `from api.stop_stats import ...`.
  Never use `src.`-prefixed or relative imports. `python src/app.py` works because Python puts the script's directory
  on `sys.path`; any other entry point (REPL, scratch script, future tests) has to add `src/` to `sys.path` itself.
- Always obtain feeds with `get_feed(mode)`. Do not read zips directly.
- Reuse the validation helpers in `stop_stats.py` (`_validate_date`, `_validate_time`, `_resolve_dates`) rather than duplicating them.
- Format and lint with Ruff, passing only the files you changed (see §2).
- Large binary data goes in Git LFS. `data/` is otherwise git-ignored.

### Adding an endpoint

1. Create a `Blueprint(..., url_prefix="/api")` in `src/api/` and register it in `create_app()` (`src/app.py`).
2. List it in the hand-maintained index returned by `GET /` and in the endpoint table in `README.md`.
3. Read the body with `request.get_json(silent=True) or {}`, validate it up front, and return errors as
   `jsonify({"error": ..., "hint": ...}), <status>`: 400 for validation, 500 for feed or graph load failures.
4. Document the request and response schema in the module docstring.

---

## 11. Known Issues & TODOs

- **`scripts/all_to_central.py` calls `POST /api/route-stats`, which no longer exists.** That endpoint was renamed
  to `/api/trip-stats`, so the script gets 404s until it is updated.
- **`/api/trips`**: some valid trips may be missing from the results (noted in the commit that added the endpoint; not yet diagnosed).
- `/api/trips` uses a constant 180 s transfer time (`get_transfer_time_secs`) and does not model walking transfers between stations.
- `get_feed` caches feeds for the life of the process, so a long-running server keeps serving the day it first loaded.
- The isochrone graph path is hard-coded in `api/isochrone.py` rather than defined in `config.py`.
- `/api/isochrone` does not validate `speed`, `max_duration_minutes` or `resolution`; bad values raise 500s.
- There are **no automated tests**.

---

## 12. Legacy Leftovers

Commit `b605e3b` removed an earlier version of the project, including a Folium map generator, a BFS route finder,
`main.py` and `web/app.py`. These remnants of it aren't used by current code, so don't build on them:

- the README's "Interactive Maps" and "Route Finder" feature bullets
- the `main.py` and `web/app.py` configs in `.vscode/launch.json`
- `maps/gtfs_shapes_sydneyTrains.html`
- `data/complete-gtfs/` and `data/gtfs_schedule_sydneytrains/`
- the `folium` and `partridge` dependencies
