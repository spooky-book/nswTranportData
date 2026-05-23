# NSW Transport Data — Project Context

> **Purpose of this file:** Provide AI coding agents with a comprehensive understanding of
> this project — its goals, architecture, data flow, conventions, and current state.

---

## 1. Project Overview

This is a **Python application** that consumes **GTFS (General Transit Feed Specification)** data
from the [Transport for NSW (TfNSW) Open Data API](https://opendata.transport.nsw.gov.au/) and uses
it to:

1. **Generate interactive Folium maps** showing transit routes (shapes) and stops for various NSW
   transport modes (trains, light rail, ferries).
2. **Serve a Flask web app** that lets users search for stops and compute shortest-path routes
   between them using a BFS graph traversal.

The project targets **Sydney / NSW public transport** exclusively.

---

## 2. Directory Structure

```
nswTransportData/
├── main.py                       # CLI entry point — downloads GTFS data & generates maps
├── constants.py                  # Shared enums (LocationTypeEnum)
├── pyproject.toml                # Project metadata & dependencies (managed by uv)
├── uv.lock                       # uv lockfile — pinned dependency versions
├── .python-version               # Python version pin (3.14)
│
├── src/                          # New Flask API package (import root = src/)
│   ├── __init__.py
│   ├── app.py                    # Flask application factory & entry point
│   ├── config.py                 # Paths, env vars, transport mode definitions
│   ├── api/
│   │   ├── __init__.py
│   │   ├── route_stats.py        # /api/route-stats Blueprint (direct train stats)
│   │   ├── stations.py           # /api/stations Blueprint (search & list stations)
│   │   └── stop_stats.py         # /api/stop-stats Blueprint (station-level stats)
│   └── gtfs/
│       ├── __init__.py
│       ├── downloader.py         # Downloads & caches GTFS zips from TfNSW API
│       └── loader.py             # Loads GTFS zip into a gtfs_kit.Feed (with in-memory cache)
│
├── loader/
│   └── loader.py                 # GTFSStatic dataclass — parses GTFS zip into pandas DataFrames
│
├── common/
│   └── helpers.py                # Utility functions (hex colour padding)
│
├── services/
│   ├── map_service.py            # Folium map generation (routes + stops)
│   └── routing_service.py        # StopGraph (adjacency graph + BFS shortest path)
│
├── web/
│   ├── app.py                    # Legacy Flask app (route finder UI + API)
│   └── templates/
│       └── index.html            # Jinja2 template — route finder single-page UI
│
├── data/                         # Downloaded & cached GTFS data (git-ignored)
│   ├── schedule-gtfs/            # Per-date cached schedule GTFS zips (by transport mode)
│   │   └── <YYYY-MM-DD>/
│   │       ├── light_rail_parramatta/
│   │       ├── light_rail_inner_west/
│   │       ├── sydney_trains/
│   │       └── ...
│   ├── complete-gtfs/            # Per-date cached complete GTFS bundle
│   └── gtfs_schedule_sydneytrains/  # Pre-extracted Sydney Trains GTFS text files
│
├── maps/                         # Generated HTML map outputs
│   └── gtfs_shapes_sydneyTrains.html
│
├── .venv/                        # Python virtual environment (managed by uv)
├── .idea/                        # PyCharm / JetBrains project config
└── .gitignore                    # Ignores .venv, data/, __pycache__, .idea/, etc.
```

---

## 3. Key Modules

### 3.1 `main.py` — Entry Point

- Orchestrates GTFS data retrieval for multiple transport modes.
- Each `get_schedule_gtfs_*()` function:
  - Checks for a **date-stamped local cache** under `data/schedule-gtfs/<date>/<mode>/`.
  - If missing, calls the TfNSW API with an `Authorization: apikey <key>` header.
  - Downloads with `tqdm` progress bar, saves zip, and parses via `GTFSStatic.from_bytes()`.
- After loading, calls `generate_map_all_routes()` and `add_train_stops_to_map()` to produce a
  Folium HTML map, saved to `maps/`.
- Requires the **`TRANSPORT_NSW_API_KEY`** environment variable.

**Currently active transport modes** (uncommented in `main()`):
- Parramatta Light Rail
- Inner West Light Rail

**Available but commented out:**
- Newcastle Light Rail, Sydney Trains, CBD & South East Light Rail, Sydney Ferries, MFF Ferries,
  NSW Trains, Complete GTFS bundle.

### 3.2 `loader/loader.py` — GTFS Parser

- **`GTFSStatic`** dataclass with a `tables: Dict[str, pd.DataFrame]` field.
- **`from_bytes(content, tables=None)`**: Parses a GTFS zip from raw bytes.
  - Default tables: `agency`, `stops`, `routes`, `trips`, `stop_times`, `calendar`,
    `calendar_dates`, `shapes`, `fare_attributes`, `fare_rules`.
  - Special handling for `shapes.txt`: uses specific dtypes (`float32`, `int32`, `string[pyarrow]`),
    categorical `shape_id`, and pyarrow CSV engine for performance.
  - Other tables: read as strings with `low_memory=False`.
- **`_normalise_table()`**: Post-processing per table:
  - `stops`: converts lat/lon to numeric, creates `location_type_enum` column mapped to
    `LocationTypeEnum`.
  - `stop_times`: converts `stop_sequence` to numeric.
- **Query helpers**: `search_stops()`, `routes_by_agency()`, `trips_for_route()`,
  `stop_times_for_trip()`.
- **`download_ttfnsw_gtfs()`**: Standalone downloader (uses a different env var `TFNSW_API_KEY`).

### 3.3 `constants.py`

```python
class LocationTypeEnum(IntEnum):
    PLATFORMSTOP = 0
    STATION = 1
    ENTRANCE = 2
    GENERIC_NODE = 3
    BOARDING_AREA = 4
```

### 3.4 `common/helpers.py`

- **`pad_hex(color, default)`**: Normalises hex colour strings to `#RRGGBB` format. Handles `None`,
  3-digit shorthand, and short strings.

### 3.5 `services/map_service.py` — Map Generation

- **`generate_map_all_routes(gtfs, ...)`**:
  - Builds a Folium map with one `FeatureGroup` layer per route.
  - Converts shapes to GeoJSON `MultiLineString` features (lon/lat ordering).
  - Supports **parallel processing** via `ProcessPoolExecutor` with a worker-initializer pattern.
  - Optional path decimation for performance.
  - Accepts an existing `folium.Map` (`m` parameter) to overlay multiple GTFS datasets.
- **`add_train_stops_to_map(gtfs, ...)`**:
  - Adds `CircleMarker`s for stops, coloured by type (blue = station, green = other).
  - Optional platform display toggle.
- **`generate_map_by_route()`**: Stub — not yet implemented.
- Internal helpers: `_paths_by_shape()`, `_route_index()`, `_route_to_shapes()`,
  `_swap_latlon_to_lonlat()`, `_make_route_feature()`, `decimate_path()`.

### 3.6 `services/routing_service.py` — Graph & Routing

- **`StopGraph`** dataclass:
  - `adjacency: Dict[str, set]` — undirected graph of stop connections (built from `stop_times`
    ordered by trip).
  - `stop_lookup: Dict[str, Dict]` — stop metadata (name, parent station, lat/lon).
  - **`from_gtfs(cls, gtfs)`**: Constructs graph from GTFS data.
  - **`shortest_path(origin, destination)`**: BFS shortest path returning list of stop IDs.
  - **`stop_details(stop_id)`**: Returns metadata for a stop.
  - **`popular_stops(limit)`**: Alphabetically sorted stops for UI auto-fill.
- **`stops_for_display(df)`**: Converts a stops DataFrame to a list of display-friendly dicts.

### 3.7 `web/app.py` — Legacy Flask Web App

- Single Flask app with three endpoints:
  - **`GET /`**: Renders `index.html` with pre-loaded popular stops.
  - **`GET /api/stops?query=...`**: Returns matching stops as JSON (search or popular default).
  - **`POST /api/route`**: Accepts `{origin_stop_id, destination_stop_id}`, returns the
    shortest-path route as a JSON list of stops.
- Lazily loads GTFS from a zip file (defaults to
  `data/gtfs_schedule_sydneytrains.zip`, overridable via `GTFS_STATIC_ZIP` env var).
- ⚠️ **Known issue**: `_load_gtfs_once()` calls `GTFSStatic.from_zip()` which does **not exist**
  on the `GTFSStatic` class (only `from_bytes()` exists). This will fail at runtime.

### 3.8 `web/templates/index.html` — Route Finder UI

- Single-page app with:
  - Two autocomplete inputs (origin / destination) backed by `<datalist>` elements.
  - Live search via `/api/stops` endpoint.
  - Route computation via `/api/route` endpoint.
  - Inline CSS with clean, minimal styling.
  - Jinja2 template variable: `popular_stops` (pre-populated datalist).

### 3.9 `src/app.py` — New Flask Application Factory

- **`create_app()`**: Flask application factory that registers blueprints.
- Registers the `stations_bp`, `stop_stats_bp`, and `route_stats_bp` blueprints.
- Exposes a root `GET /` endpoint returning a JSON API index.
- Run directly with `uv run python src/app.py` (serves on port from `PORT` env var, default 5000).

### 3.10 `src/config.py` — Centralised Configuration

- `PROJECT_ROOT`, `DATA_DIR` — resolved filesystem paths.
- `TRANSPORT_NSW_API_KEY` — read from environment.
- `TRANSPORT_MODES` — dict mapping mode keys to `api_path` and `cache_folder`.
- `DEFAULT_MODE` = `"sydney_trains"`.
- `FLASK_PORT` — read from `PORT` env var (default `5000`).

### 3.11 `src/api/stations.py` — Stations Blueprint

- **`GET /api/stations`** — returns stations from the GTFS feed.
  - Query params: `search` (substring filter), `mode` (transport mode key, default `sydney_trains`).
  - Filters stops by `location_type == "1"` (GTFS stations); falls back to platforms if none exist.
  - Returns `{count, mode, stations: [{stop_id, stop_name, stop_lat, stop_lon, parent_station, location_type}]}`.
- Uses `get_feed(mode)` from `src/gtfs/loader.py` to obtain a `gtfs_kit.Feed`.

### 3.12 `src/gtfs/downloader.py` — GTFS Downloader

- **`get_gtfs_zip_path(mode)`**: Returns a `Path` to the cached zip for today's date.
  - If not cached, downloads from `https://api.transport.nsw.gov.au/v1/gtfs/schedule/<api_path>`
    using `TRANSPORT_NSW_API_KEY` and saves to `data/schedule-gtfs/<YYYY-MM-DD>/<cache_folder>/gtfs_schedule.zip`.
  - Uses `tqdm` progress bar during download.
  - Raises `ValueError` for unknown modes, `EnvironmentError` if API key is missing, `RuntimeError` on HTTP failure.

### 3.13 `src/gtfs/loader.py` — gtfs_kit Feed Loader

- **`get_feed(mode)`**: Returns a `gtfs_kit.Feed` for the given mode.
  - Uses an in-memory dict `_feed_cache` — subsequent calls for the same mode return instantly.
  - Calls `get_gtfs_zip_path(mode)` then `gtfs_kit.read_feed(zip_path, dist_units="km")`.
  - Runs **`_filter_non_passenger_services`** on load: Globally strips out "Empty Train" deadheads and pass-through timing points (`pickup_type=1` AND `drop_off_type=1`) from `trips` and `stop_times` to ensure accurate passenger statistics.
- **`clear_cache()`**: Clears the in-memory feed cache.
- The `Feed` object exposes all GTFS tables as pandas DataFrames (`.stops`, `.routes`, etc.).

### 3.14 `src/api/stop_stats.py` — Stop Stats Blueprint

- **`POST /api/stop-stats`** — computes daily service statistics per station.
  - Aggregates stats across all child platforms for a parent station.
  - Returns `{num_trips, num_routes, start_time, end_time}`.
  - Resolves station ID -> child platform IDs -> `feed.compute_stop_stats()` -> aggregates back to station level.

### 3.15 `src/api/route_stats.py` — Route Stats Blueprint

- **`POST /api/route-stats`** — computes point-to-point service statistics between stations (direct trains only).
  - Matches departures at the origin platforms with arrivals at the destination platforms.
  - Returns `{num_trips, num_routes, start_time, end_time, min_headway_secs, travel_time_mean_secs, ...}`.

---

## 4. Data Flow

```
TfNSW API  ──(HTTPS + API key)──►  main.py  ──(zip bytes)──►  GTFSStatic.from_bytes()
                                      │                              │
                                      ▼                              ▼
                              data/schedule-gtfs/        Dict[str, pd.DataFrame]
                              (date-stamped cache)              │
                                                                ├──► map_service.py ──► Folium HTML map
                                                                └──► routing_service.py ──► StopGraph
                                                                                               │
                                                                                               ▼
                                                                                         web/app.py (Flask)
                                                                                               │
                                                                                               ▼
                                                                                         Browser UI
```

---

## 5. Package Management

This project uses **[uv](https://docs.astral.sh/uv/)** as its package manager and virtual
environment manager (replacing pip).

- **`pyproject.toml`** — Defines project metadata and all dependencies.
- **`uv.lock`** — Lockfile with exact pinned versions for reproducible installs.
- **`.python-version`** — Pins the Python version to **3.14** (managed by uv).
- **`.venv/`** — Virtual environment created and managed by uv.

### Key Commands

```bash
# Install all dependencies (creates .venv if needed)
uv sync

# Add a new dependency
uv add <package>

# Remove a dependency
uv remove <package>

# Run a script within the managed environment
uv run python main.py

# Or activate the venv and run directly
# Windows:  .venv\Scripts\activate
# Unix:     source .venv/bin/activate
python main.py
```

### Dependencies

| Package        | Version  | Purpose                                |
|----------------|----------|----------------------------------------|
| pandas         | 2.3.3    | DataFrames for GTFS table manipulation |
| pandas-stubs   | 2.3.2    | Type stubs for pandas                  |
| pyarrow        | 22.0.0   | High-performance CSV engine for shapes |
| numpy          | 2.3.4    | Array operations (coordinate swapping) |
| folium         | 0.20.0   | Interactive Leaflet.js map generation  |
| branca         | 0.8.2    | Folium dependency (HTML generation)    |
| flask          | 3.1.2    | Web framework for route finder app     |
| jinja2         | 3.1.6    | Template engine (Flask dependency)     |
| requests       | 2.32.5   | HTTP client for TfNSW API calls        |
| tqdm           | 4.67.1   | Download progress bars                 |
| ruff           | ≥0.15.13 | Linting & formatting                   |
| networkx       | 3.5      | Graph library (installed but unused)   |
| partridge      | 1.1.2    | GTFS library (installed but unused)    |

> **Note**: `networkx` and `partridge` are installed but not imported anywhere in the codebase.
> The project uses a custom BFS implementation instead of networkx.

---

## 6. Environment Variables

| Variable                 | Required By              | Description                        |
|--------------------------|--------------------------|-------------------------------------|
| `TRANSPORT_NSW_API_KEY`  | `main.py`, `src/`        | TfNSW API key for GTFS downloads   |
| `TFNSW_API_KEY`          | `loader/loader.py`       | Alternative API key (standalone downloader fn)  |
| `GTFS_STATIC_ZIP`        | `web/app.py` (legacy)    | Override path to GTFS zip for legacy web app   |
| `PORT`                   | `src/app.py`, `web/app.py` | Flask server port (default: 5000)  |

---

## 7. GTFS Data Schema

The project works with standard GTFS tables:

| Table             | Key Columns                                             | Notes                      |
|-------------------|---------------------------------------------------------|----------------------------|
| `agency`          | `agency_id`, `agency_name`                              |                            |
| `stops`           | `stop_id`, `stop_name`, `stop_lat`, `stop_lon`, `location_type`, `parent_station` | Normalised with enum       |
| `routes`          | `route_id`, `route_short_name`, `route_long_name`, `route_color` |                            |
| `trips`           | `trip_id`, `route_id`, `shape_id`                       |                            |
| `stop_times`      | `trip_id`, `stop_id`, `stop_sequence`, `arrival_time`, `departure_time` | Sequence normalised to int |
| `shapes`          | `shape_id`, `shape_pt_lat`, `shape_pt_lon`, `shape_pt_sequence`, `shape_dist_traveled` | Optimised dtypes           |
| `calendar`        | `service_id`, day columns, `start_date`, `end_date`     |                            |
| `calendar_dates`  | `service_id`, `date`, `exception_type`                  |                            |

---

## 8. Supported Transport Modes

| Mode                      | API Path                       | Cache Folder                     |
|---------------------------|--------------------------------|----------------------------------|
| Parramatta Light Rail     | `lightrail/parramatta`         | `light_rail_parramatta`          |
| Inner West Light Rail     | `lightrail/innerwest`          | `light_rail_inner_west`          |
| CBD & South East LR       | `lightrail/cbdandsoutheast`    | `light_rail_city_and_south_west` |
| Newcastle Light Rail      | `lightrail/newcastle`          | `light_rail_newcastle`           |
| Sydney Trains             | `sydneytrains`                 | `sydney_trains`                  |
| NSW Trains (Intercity)    | `nswtrains`                    | `nsw_trains`                     |
| Sydney Ferries            | `ferries/sydneyferries`        | `ferries_sydney_ferries`         |
| MFF Ferries               | `ferries/MFF`                  | `ferries_mff`                    |
| Complete GTFS bundle      | (different URL)                | `complete-gtfs/`                 |

---

## 9. Known Issues & TODOs

1. **`GTFSStatic.from_zip()` does not exist** — `web/app.py` (legacy) line 49 calls `GTFSStatic.from_zip()`
   but only `from_bytes()` is defined. The legacy web app will crash on startup.
2. **`generate_map_by_route()`** is a stub (returns `None`).
3. **Inconsistent API key env vars** — `main.py` uses `TRANSPORT_NSW_API_KEY`, `loader/loader.py` uses
   `TFNSW_API_KEY`.
4. **Shape ID type mismatch** — Comment in `_pack_make_feature()` notes that shape IDs are strings
   vs numbers, causing issues between trains and light rail.
5. **Commented-out code** — `map_service.py` contains ~40 lines of old commented-out implementation.
6. **Mixed indentation** — `routing_service.py` uses spaces; other files use tabs.

---

## 10. How to Run

### Prerequisites

- **[uv](https://docs.astral.sh/uv/)** installed (`pip install uv` or see uv docs for other methods).
- A **TfNSW API key** from [opendata.transport.nsw.gov.au](https://opendata.transport.nsw.gov.au/).

### Install Dependencies

```bash
uv sync
```

### Map Generation (CLI)

```bash
# Set your API key
# Windows (PowerShell):
$env:TRANSPORT_NSW_API_KEY = "your-api-key"
# Unix/macOS:
export TRANSPORT_NSW_API_KEY="your-api-key"

# Run the map generator
uv run python main.py
# Outputs: maps/gtfs_shapes_sydneyTrains.html
```

### New Stations API (Flask — `src/`)

```bash
# Windows (PowerShell):
$env:TRANSPORT_NSW_API_KEY = "your-api-key"
# Unix/macOS:
export TRANSPORT_NSW_API_KEY="your-api-key"

uv run python src/app.py
# Runs on http://localhost:5000
# API index: GET /
# List stations: GET /api/stations
# Search stations: GET /api/stations?search=central
# Filter by mode: GET /api/stations?mode=sydney_trains
```

> **Import convention for `src/`**: All modules inside `src/` use paths relative to `src/` as the
> import root (e.g. `from gtfs.loader import get_feed`, NOT `from src.gtfs.loader import get_feed`).
> Always run the app from the **project root** so Python adds `src/` to `sys.path` correctly.

### Legacy Route Finder (Flask — `web/`)

```bash
# Optionally set a GTFS zip path
# Windows (PowerShell):
$env:GTFS_STATIC_ZIP = "path/to/gtfs.zip"
# Unix/macOS:
export GTFS_STATIC_ZIP="path/to/gtfs.zip"

uv run python web/app.py
# Runs on http://localhost:5000
```

> ⚠️ The legacy `web/app.py` currently crashes on startup due to a missing `GTFSStatic.from_zip()` method.

---

## 11. Development Notes

- **Package manager**: [uv](https://docs.astral.sh/uv/) — manages Python version, virtual environment, and dependencies.
- **IDE**: PyCharm (JetBrains), based on `.idea/` project files.
- **Python version**: **3.14** (pinned via `.python-version`, managed by uv).
- **Linting / Formatting**: [Ruff](https://docs.astral.sh/ruff/) is included as a dependency.
- **No tests** exist in the project.
- The project is a **personal/exploratory tool** — not packaged for distribution.
