# NSW Transport Data — Project Context

> **Purpose of this file:** Provide AI coding agents with a comprehensive understanding of
> this project — its goals, architecture, data flow, conventions, and current state.

---

## 1. Project Overview

This is a **Python application** that consumes **GTFS (General Transit Feed Specification)** data
from the [Transport for NSW (TfNSW) Open Data API](https://opendata.transport.nsw.gov.au/) and uses
it to:

1. **Serve a Flask web API and UI** that provides access to GTFS transit data, shortest-path train routes, and generates isochrone reachability maps.

The project targets **Sydney / NSW public transport** exclusively.

---

## 2. Directory Structure

```
nswTransportData/
├── src/                          # Flask API package (import root = src/)
│   ├── __init__.py
│   ├── app.py                    # Flask application factory & entry point
│   ├── config.py                 # Paths, env vars, transport mode definitions
│   ├── api/
│   │   ├── __init__.py
│   │   ├── route_stats.py        # /api/route-stats Blueprint (direct train stats)
│   │   ├── stations.py           # /api/stations Blueprint (search & list stations)
│   │   ├── stop_stats.py         # /api/stop-stats Blueprint (station-level stats)
│   │   └── isochrone.py          # /api/isochrone Blueprint (walking/biking reachability)
│   └── gtfs/
│       ├── __init__.py
│       ├── downloader.py         # Downloads & caches GTFS zips from TfNSW API
│       └── loader.py             # Loads GTFS zip into a gtfs_kit.Feed (with in-memory cache)
│
├── data/                         # Downloaded & cached GTFS data (git-ignored)
│   ├── osmnx/                    # Cached OSMnx walking graphs
│   │   └── sydney_walk.graphml
│   ├── schedule-gtfs/            # Per-date cached schedule GTFS zips (by transport mode)
│   │   └── <YYYY-MM-DD>/
│   │       ├── light_rail_parramatta/
│   │       ├── light_rail_inner_west/
│   │       ├── sydney_trains/
│   │       └── ...
│   ├── complete-gtfs/            # Per-date cached complete GTFS bundle
│   └── gtfs_schedule_sydneytrains/  # Pre-extracted Sydney Trains GTFS text files
│
├── scripts/                      # Standalone data acquisition scripts
│   ├── download_graph.py         # Downloads OSMnx walking graph for Sydney
│   ├── generate_supermarket_isochrones.py
│   └── generate_station_isochrones.py
│
├── .venv/                        # Python virtual environment (managed by uv)
├── .idea/                        # PyCharm / JetBrains project config
└── .gitignore                    # Ignores .venv, data/, __pycache__, .idea/, etc.
```

---

## 3. Key Modules

### 3.9 `src/app.py` — New Flask Application Factory

- **`create_app()`**: Flask application factory that registers blueprints.
- Registers the `stations_bp`, `stop_stats_bp`, `route_stats_bp`, and `isochrone_bp` blueprints.
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

### 3.16 `src/api/isochrone.py` — Isochrone Blueprint

- **`POST /api/isochrone`** — computes a walking/biking reachability polygon using a local OpenStreetMap network.
  - Requires the `data/osmnx/sydney_walk.graphml` file to exist (generated by `scripts/download_graph.py`).
  - Accepts `{lat, lon, speed, max_duration_minutes, resolution}`.
  - Uses `osmnx` and `networkx` for Dijkstra shortest path length calculation.
  - Applies a custom `travel_time` edge weight incorporating crossing penalties for intersections and traffic lights.
  - Returns a GeoJSON `Polygon` generated via `shapely` concave hull (alpha shape) for high resolution output.
- **`GET /api/map`** — serves an interactive Leaflet frontend (`src/templates/isochrone_map.html`) to visualize isochrones.
- **`GET /api/network`** — returns the raw `sydney_walk.graphml` graph edges within a 1.5km bounding box as GeoJSON for UI debugging.

### 3.17 `scripts/download_graph.py` — OSMnx Graph Downloader

- Script to download the local OpenStreetMap walking graph for Sydney.
- Uses a highly permissive custom Overpass QL filter (`["highway"]["area"!~"yes"]["highway"!~"motorway|trunk..."]`) to explicitly capture footpaths, shared cycleways, and bridges that are normally dropped by OSMnx's default `walk` filter, while correctly avoiding rivers and train tracks.

---

## 4. Data Flow

```
TfNSW API  ──(HTTPS + API key)──►  src/gtfs/downloader.py  ──(zip file)──►  src/gtfs/loader.py (gtfs_kit)
                                      │                                            │
                                      ▼                                            ▼
                              data/schedule-gtfs/                               src/app.py (Flask)
                              (date-stamped cache)                                 │
                                                                                   ▼
                                                                             Browser UI & APIs
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

# Run the Flask app
uv run python src/app.py
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
| networkx       | 3.5      | Graph library (used for isochrone BFS) |
| osmnx          | 2.0.1    | OpenStreetMap street network downloads |
| shapely        | 2.1.2    | Geometry creation (Convex/Concave hull)|
| scikit-learn   | 1.8.0    | Fast nearest node unprojected search   |
| partridge      | 1.1.2    | GTFS library (installed but unused)    |

> **Note**: `networkx` and `partridge` are installed but not imported anywhere in the codebase.
> The project uses a custom BFS implementation instead of networkx.

---

## 6. Environment Variables

| Variable                 | Required By              | Description                        |
|--------------------------|--------------------------|-------------------------------------|
| `TRANSPORT_NSW_API_KEY`  | `src/`                   | TfNSW API key for GTFS downloads   |
| `PORT`                   | `src/app.py`             | Flask server port (default: 5000)  |

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

None currently.

---

## 10. How to Run

### Prerequisites

- **[uv](https://docs.astral.sh/uv/)** installed (`pip install uv` or see uv docs for other methods).
- A **TfNSW API key** from [opendata.transport.nsw.gov.au](https://opendata.transport.nsw.gov.au/).

### Install Dependencies

```bash
uv sync
```

### API Server (Flask — `src/`)

```bash
# Windows (PowerShell):
$env:TRANSPORT_NSW_API_KEY = "your-api-key"
# Unix/macOS:
export TRANSPORT_NSW_API_KEY="your-api-key"

uv run python src/app.py
# Runs on http://localhost:5000
# API index: GET /
# Map UI: GET /api/map
# List stations: GET /api/stations
```

> **Import convention for `src/`**: All modules inside `src/` use paths relative to `src/` as the
> import root (e.g. `from gtfs.loader import get_feed`). Always run the app from the **project root** so Python adds `src/` to `sys.path` correctly.

---

## 11. Development Notes

- **Package manager**: [uv](https://docs.astral.sh/uv/) — manages Python version, virtual environment, and dependencies.
- **IDE**: PyCharm (JetBrains), based on `.idea/` project files.
- **Python version**: **3.14** (pinned via `.python-version`, managed by uv).
- **Linting / Formatting**: [Ruff](https://docs.astral.sh/ruff/) is included as a dependency.
- **No tests** exist in the project.
- The project is a **personal/exploratory tool** — not packaged for distribution.
