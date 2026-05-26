# NSW Transport Data

A Python application that consumes [GTFS (General Transit Feed Specification)](https://gtfs.org/) data from the [Transport for NSW Open Data API](https://opendata.transport.nsw.gov.au/) to generate interactive maps and provide route-finding capabilities for Sydney/NSW public transport.

## Features

- **Interactive Maps** — Generates [Folium](https://python-visualization.github.io/folium/) maps showing transit routes and stops for trains, light rail, and ferries across NSW.
- **Route Finder Web App** — A Flask-based web interface for searching stops and computing shortest-path routes using BFS graph traversal.
- **Multi-mode Support** — Covers Sydney Trains, NSW Trains, multiple light rail lines, and ferry services.
- **Smart Caching** — Downloads are date-stamped and cached locally to avoid redundant API calls.

## Prerequisites

- **[uv](https://docs.astral.sh/uv/)** — Python package and project manager.
- **TfNSW API Key** — Register at [opendata.transport.nsw.gov.au](https://opendata.transport.nsw.gov.au/) to get a free API key.

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/<your-username>/nswTransportData.git
cd nswTransportData
```

### 2. Install dependencies

```bash
uv sync
```

This will automatically install the correct Python version (3.14), create a virtual environment, and install all dependencies.

### 3. Set your API key

**PowerShell (Windows):**

```powershell
$env:TRANSPORT_NSW_API_KEY = "your-api-key-here"
```

**Bash / Zsh (macOS / Linux):**

```bash
export TRANSPORT_NSW_API_KEY="your-api-key-here"
```

### 4. Generate maps

```bash
uv run python main.py
```

This downloads GTFS schedule data for the configured transport modes and generates an interactive HTML map at `maps/gtfs_shapes_sydneyTrains.html`. Open it in your browser to explore routes and stops.

### 5. Run the Stations API

```bash
uv run python src/app.py
```

The Stations API starts at [http://localhost:5000](http://localhost:5000). Available endpoints:

| Endpoint | Description |
|---|---|
| `GET /` | API index with available endpoints |
| `GET /api/stations` | List all stations for the default mode (Sydney Trains) |
| `GET /api/stations?search=central` | Search stations by name |
| `GET /api/stations?mode=light_rail_parramatta` | List stations for a specific transport mode |
| `POST /api/stop-stats` | Compute daily service statistics per station |
| `POST /api/route-stats` | Compute point-to-point service statistics between stations (direct trains) |
| `POST /api/isochrone` | Compute a walking/biking reachability polygon (requires downloaded OSMnx graph) |

> **Note:** On first request for a transit mode, the GTFS data will be downloaded (requires `TRANSPORT_NSW_API_KEY`). The Isochrone API requires you to run `uv run python scripts/download_graph.py` first to generate the local street network.

### 6. Run the legacy route finder web app

```bash
uv run python web/app.py
```

The web app starts at [http://localhost:5000](http://localhost:5000). It provides a UI to search for stops and find the shortest route between them.

> **Note:** The web app requires a pre-downloaded GTFS zip file. Set the `GTFS_STATIC_ZIP` environment variable to point to your zip, or place it at the default path (`data/gtfs_schedule_sydneytrains.zip`).
>
> ⚠️ The legacy `web/app.py` currently has a known startup crash — see the Known Issues section in AGENTS.md.

## Project Structure

```
nswTransportData/
├── main.py                  # CLI entry point — downloads GTFS data & generates maps
├── constants.py             # Shared enums (LocationTypeEnum)
├── pyproject.toml           # Project metadata & dependencies (uv)
├── uv.lock                  # Pinned dependency lockfile
├── .python-version          # Python version pin (3.14)
│
├── src/                     # Stations API Flask package (import root = src/)
│   ├── app.py               # Flask app factory & entry point
│   ├── config.py            # Paths, env vars, transport mode definitions
│   ├── api/
│   │   ├── isochrone.py     # /api/isochrone Blueprint
│   │   ├── route_stats.py   # /api/route-stats Blueprint
│   │   ├── stations.py      # /api/stations Blueprint
│   │   └── stop_stats.py    # /api/stop-stats Blueprint
│   └── gtfs/
│       ├── downloader.py    # Downloads & caches GTFS zips
│       └── loader.py        # Loads GTFS into gtfs_kit.Feed (in-memory cache)
│
├── loader/
│   └── loader.py            # Legacy GTFS parser — reads zip into pandas DataFrames
│
├── common/
│   └── helpers.py           # Utility functions
│
├── scripts/
│   └── download_graph.py    # Script to download OSMnx walking graphs
│
├── services/
│   ├── map_service.py       # Folium map generation (routes + stops)
│   └── routing_service.py   # Stop graph & BFS shortest path
│
├── web/
│   ├── app.py               # Legacy Flask app (route finder)
│   └── templates/
│       └── index.html       # Route finder UI
│
├── data/                    # Downloaded GTFS data (git-ignored)
└── maps/                    # Generated HTML map outputs
```

> **Import convention**: All modules inside `src/` import relative to `src/` as the root
> (e.g. `from gtfs.loader import get_feed`). Always run from the **project root** directory.

## Supported Transport Modes

| Mode                    | Status                   |
|-------------------------|--------------------------|
| Parramatta Light Rail   | ✅ Active                |
| Inner West Light Rail   | ✅ Active                |
| CBD & South East LR     | Available (commented out)|
| Newcastle Light Rail    | Available (commented out)|
| Sydney Trains           | Available (commented out)|
| NSW Trains (Intercity)  | Available (commented out)|
| Sydney Ferries          | Available (commented out)|
| MFF Ferries             | Available (commented out)|

To enable additional modes, uncomment the relevant sections in `main.py`.

## Environment Variables

| Variable                | Required | Description                                            |
|-------------------------|----------|--------------------------------------------------------|
| `TRANSPORT_NSW_API_KEY` | Yes      | TfNSW API key for downloading GTFS data                |
| `GTFS_STATIC_ZIP`       | No       | Override GTFS zip path for the legacy web app          |
| `PORT`                  | No       | Flask server port for both apps (default: 5000)        |

## Tech Stack

- **Python 3.14** with **uv** for package management
- **pandas** + **pyarrow** for high-performance data processing
- **gtfs-kit** for loading GTFS feeds into DataFrames in the `src/` API
- **osmnx**, **networkx**, and **shapely** for local street network graph generation and isochrone routing
- **Folium** for interactive Leaflet.js map generation
- **Flask** for both the Stations API (`src/`) and the legacy route finder web app
- **Ruff** for linting and formatting

## License

This is a personal/exploratory project. No license has been specified.
