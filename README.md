# NSW Transport Data

A Python/Flask application that consumes [GTFS (General Transit Feed Specification)](https://gtfs.org/) schedule data from the [Transport for NSW Open Data API](https://opendata.transport.nsw.gov.au/) and uses it to analyse Sydney/NSW public transport: station listings, service frequency statistics, point-to-point travel times, journey planning with transfers, and walking/cycling isochrones.

## Features

- **Stations & Stops API** — List and search stations, platforms, entrances and other GTFS stop types for any supported mode.
- **Service Statistics** — Per-station daily stats (`/api/stop-stats`) and direct point-to-point stats with headways and travel times (`/api/trip-stats`).
- **Journey Planner** — Timetable-based routing between two stations, including transfers (`/api/trips`).
- **Transport Map** — Every Sydney Trains, Sydney Metro and NSW TrainLink (intercity and regional) station and line on one map, with per-network toggles, station search and a popup listing each station's lines.
- **Isochrone Explorer** — Walking/cycling reachability polygons computed on a local OpenStreetMap street graph, with an interactive Leaflet UI for generating, importing/exporting, and merging/intersecting isochrone layers.
- **Multi-mode Support** — Sydney Trains, Sydney Metro, NSW TrainLink, four light rail networks and two ferry operators, plus a combined trains + metro mode.
- **Smart Caching** — GTFS zips are downloaded once per (Sydney) day and cached on disk; parsed feeds are cached in memory.
- **Batch Scripts** — Scripts that call the running API to generate GeoJSON isochrone layers and CSV travel-time reports.

## Prerequisites

- **[uv](https://docs.astral.sh/uv/)** — Python package and project manager.
- **TfNSW API Key** — Register at [opendata.transport.nsw.gov.au](https://opendata.transport.nsw.gov.au/) to get a free API key.
- **[Git LFS](https://git-lfs.com/)** *(optional)* — Only needed to pull the pre-built walking graph used by the isochrone endpoints.

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/spooky-book/nswTranportData.git
cd nswTranportData
```

### 2. Install dependencies

```bash
uv sync
```

This installs the pinned Python version (3.14), creates a virtual environment, and installs all dependencies.

### 3. Set your API key

**PowerShell (Windows):**

```powershell
$env:TRANSPORT_NSW_API_KEY = "your-api-key-here"
```

**Bash / Zsh (macOS / Linux):**

```bash
export TRANSPORT_NSW_API_KEY="your-api-key-here"
```

### 4. (Optional) Get the walking graph for isochrones

The isochrone endpoints need `data/osmnx/sydney_walk.graphml` (~530 MB). It is stored in Git LFS and **excluded from the default fetch** (see `.lfsconfig`) so that clones stay fast. Either pull it:

```bash
git lfs pull --include="data/osmnx/sydney_walk.graphml" --exclude=""
```

or build it fresh from OpenStreetMap (takes several minutes):

```bash
uv run python scripts/download_graph.py
```

### 5. Run the server

Run from the **project root**:

```bash
uv run python src/app.py
```

The server starts at [http://localhost:5000](http://localhost:5000) (override with the `PORT` environment variable). The home page links to every page and endpoint.

## Pages

| Page | Description |
|---|---|
| `GET /` | Home page linking to the maps and the JSON API |
| `GET /map/transport` | Transport Map: train and metro stations and lines, toggleable by network (Sydney Trains, Sydney Metro, Intercity, Regional) |
| `GET /map/isochrone` | Isochrone Explorer: generate, import/export and combine walking/cycling isochrones. `?lat=&lon=` pre-fills the origin |

`GET /api/map`, the old Isochrone Explorer URL, redirects to `/map/isochrone`.

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /api` | JSON index listing the available endpoints |
| `GET /api/stations` | List stations (`location_type = 1`) for a mode; falls back to platforms for feeds without stations. Query params: `mode`, `search` |
| `GET /api/stops` | List any GTFS stop type. Query params: `mode`, `search`, `location_type` (0–4) |
| `POST /api/stop-stats` | Daily service statistics per station, aggregated across child platforms |
| `POST /api/trip-stats` | Direct (no-transfer) service stats between two stations: trip counts, headways, travel times. Filter by `period` (`all` (default), `early_morning`, `am_peak`, `interpeak`, `pm_peak`, `evening`, `late_night`) or a custom time window |
| `POST /api/trips` | Journey planner between two stations, including transfers. Transfer times use real in-station walking times where available (run `scripts/download_pathways.py`), plus a `transfer_buffer_secs` safety margin (default 30) |
| `POST /api/isochrone` | Walking/cycling reachability polygon (GeoJSON) — requires the walking graph |
| `GET /api/network?lat=&lon=` | Debug endpoint: walkable street edges within ~1.5 km of a point, as GeoJSON |
| `GET /api/rail-network` | Train and metro stations with the lines serving each, plus line geometry as GeoJSON (powers the Transport Map) |

Full request/response schemas are documented in each blueprint's module docstring under `src/api/`.

### Examples

```bash
# Search Sydney Trains stations
curl "http://localhost:5000/api/stations?search=central"

# Direct-train stats from Central to Parramatta, 7am–7pm
curl -X POST http://localhost:5000/api/trip-stats \
  -H "Content-Type: application/json" \
  -d '{"origin_stop_id": "200060", "destination_stop_id": "215020",
       "time_window_start": "07:00:00", "time_window_end": "19:00:00"}'

# Same, morning peak only (06:30–10:00, the Opal peak window)
curl -X POST http://localhost:5000/api/trip-stats \
  -H "Content-Type: application/json" \
  -d '{"origin_stop_id": "200060", "destination_stop_id": "215020", "period": "am_peak"}'

# Journeys (with transfers) across trains + metro
curl -X POST http://localhost:5000/api/trips \
  -H "Content-Type: application/json" \
  -d '{"mode": "sydney_trains_and_metro", "origin_stop_id": "200060",
       "destination_stop_id": "215020", "time_window_start": "08:00:00",
       "time_window_end": "09:00:00"}'

# 15-minute walking isochrone around Central
curl -X POST http://localhost:5000/api/isochrone \
  -H "Content-Type: application/json" \
  -d '{"lat": -33.8829, "lon": 151.2066, "max_duration_minutes": 15}'
```

> **Note:** The first request for a transport mode downloads that mode's GTFS feed (requires `TRANSPORT_NSW_API_KEY`) and can take a while. The first isochrone request loads the large walking graph into memory and is also slow; later requests are fast.

## Supported Transport Modes

Pass these as the `mode` parameter (default: `sydney_trains`).

| Mode key                    | Network                               |
|-----------------------------|---------------------------------------|
| `sydney_trains`             | Sydney Trains                         |
| `sydney_metro`              | Sydney Metro (TfNSW GTFS API v2)      |
| `sydney_trains_and_metro`   | Sydney Trains + Metro merged into one feed |
| `nsw_trains`                | NSW TrainLink (intercity / regional)  |
| `light_rail_parramatta`     | Parramatta Light Rail                 |
| `light_rail_inner_west`     | Inner West Light Rail                 |
| `light_rail_cbd_south_east` | CBD & South East Light Rail           |
| `light_rail_newcastle`      | Newcastle Light Rail                  |
| `ferries_sydney`            | Sydney Ferries                        |
| `ferries_mff`               | Manly Fast Ferry                      |

## Scripts

Scripts live in `scripts/` and are run from the project root. All except `download_graph.py` call the **running** API at `http://localhost:5000`, so start the server first.

| Script | Purpose | Output |
|---|---|---|
| `download_graph.py` | Downloads the Sydney walking network from OpenStreetMap | `data/osmnx/sydney_walk.graphml` |
| `generate_station_isochrones.py` | Isochrones for a hard-coded list of stations | `station_isochrones.geojson` |
| `generate_supermarket_isochrones.py` | Finds Coles/Woolworths/Aldi stores via OSM and builds isochrones for each | `supermarket_isochrones.geojson` |
| `all_to_central.py` | Travel-time and headway stats from every station to Central | `stats_to_destination_<id>_date_<date>_time_window_<start>-<end>.csv` |
| `download_pathways.py` | Downloads TfNSW's in-station walking paths (from the ~300 MB complete GTFS bundle) for realistic journey-planner transfer times. `--from-zip PATH` reuses a bundle you already have | `data/pathways/<date>/pathways.txt` |

Generated `.geojson` files can be loaded into the Isochrone Explorer via **Import**. Several previously generated outputs are committed in the project root.

## Project Structure

```
nswTranportData/
├── pyproject.toml           # Project metadata & dependencies (uv)
├── uv.lock                  # Pinned dependency lockfile
├── .python-version          # Python version pin (3.14)
├── .gitattributes           # Registers sydney_walk.graphml with Git LFS
├── .lfsconfig               # Excludes the walking graph from default LFS fetches
├── README.md
├── AGENTS.md                # Detailed context for AI coding agents
├── CLAUDE.md                # Imports AGENTS.md for Claude Code
│
├── src/                     # Flask app (import root = src/)
│   ├── app.py               # App factory, blueprint registration, GET /api index & entry point
│   ├── pages.py             # HTML pages: /, /map/transport, /map/isochrone
│   ├── config.py            # Paths, env vars, transport mode definitions
│   ├── constants.py         # LocationTypeEnum (GTFS location_type values)
│   ├── api/
│   │   ├── stations.py      # GET  /api/stations
│   │   ├── stops.py         # GET  /api/stops
│   │   ├── stop_stats.py    # POST /api/stop-stats (+ shared date/time validation helpers)
│   │   ├── trip_stats.py    # POST /api/trip-stats
│   │   ├── trips.py         # POST /api/trips (journey planner)
│   │   ├── isochrone.py     # POST /api/isochrone, GET /api/network
│   │   └── rail_network.py  # GET  /api/rail-network (stations + line geometry)
│   ├── gtfs/
│   │   ├── downloader.py    # Downloads & caches GTFS zips per day
│   │   ├── loader.py        # Loads/normalises/filters feeds into gtfs_kit.Feed (in-memory cache)
│   │   └── pathways.py      # In-station walking times between platforms, for transfers
│   ├── static/
│   │   └── basemaps.js      # Shared Leaflet basemap switcher
│   └── templates/
│       ├── home.html            # Home page
│       ├── transport_map.html   # Transport Map UI
│       └── isochrone_map.html   # Leaflet + Turf.js Isochrone Explorer UI
│
├── scripts/                 # Graph download & batch generation scripts (see above)
├── maps/                    # Legacy generated Folium map (static HTML)
├── data/                    # GTFS cache (git-ignored) + LFS walking graph
│   ├── schedule-gtfs/<YYYY-MM-DD>/<mode>/gtfs_schedule.zip
│   └── osmnx/sydney_walk.graphml
└── *.geojson, *.csv         # Generated script outputs
```

> **Import convention**: Modules inside `src/` import relative to `src/` as the root
> (e.g. `from gtfs.loader import get_feed`). Always run the app from the **project root** with `uv run python src/app.py`.

## Environment Variables

| Variable                | Required | Description                                            |
|-------------------------|----------|--------------------------------------------------------|
| `TRANSPORT_NSW_API_KEY` | Yes*     | TfNSW API key for downloading GTFS data (*not needed if today's feeds are already cached) |
| `PORT`                  | No       | Flask server port (default: 5000)                      |
| `TRANSFER_BUFFER_SECS`  | No       | Safety margin added to each journey-planner transfer walk (default: 30) |
| `DEFAULT_TRANSFER_SECS` | No       | Transfer time used where a station has no pathway data (default: 180) |

## Development

```bash
uv run ruff check .     # lint
uv run ruff format .    # format
```

There is no automated test suite yet.

## Tech Stack

- **Python 3.14** with **uv** for package management
- **Flask** for the API and UI
- **gtfs-kit**, **pandas** and **numpy** for GTFS loading and analysis
- **osmnx**, **networkx**, **shapely** and **scikit-learn** for the street graph, routing and isochrone geometry
- **Leaflet** and **Turf.js** (via CDN) for the Isochrone Explorer frontend
- **Ruff** for linting and formatting

## License

This project is licensed under the [Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0) License](LICENSE).
