# NSW Transport Data

A Python application that consumes [GTFS (General Transit Feed Specification)](https://gtfs.org/) data from the [Transport for NSW Open Data API](https://opendata.transport.nsw.gov.au/) to generate interactive maps and provide route-finding capabilities for Sydney/NSW public transport.

## Features

- **Interactive Maps** — Generates [Folium](https://python-visualization.github.io/folium/) maps showing transit routes and stops for trains, light rail, and ferries across NSW.
- **Route Finder Web App** — A Flask-based web interface for searching stops and computing shortest-path routes using BFS graph traversal.
- **Isochrone Explorer** — An interactive frontend UI that visually generates high-resolution walking/biking reachability polygons.
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

### 4. Run the API and UI Server

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
| `GET /api/map` | Interactive Leaflet UI for exploring the Isochrone API visually |
| `GET /api/network` | Debugging endpoint that returns the raw OpenStreetMap walkable graph |

> **Note:** On first request for a transit mode, the GTFS data will be downloaded (requires `TRANSPORT_NSW_API_KEY`).
> The Isochrone API requires the local street network file `data/osmnx/sydney_walk.graphml` to exist. To keep the repository clone fast, this large file is stored via Git LFS and is configured to be skipped on initial clone.
> 
> To pull the pre-downloaded walking graph, make sure you have [Git LFS](https://git-lfs.com/) installed and run:
> ```bash
> git lfs pull
> ```
> Alternatively, you can generate/download it fresh from scratch by running:
> ```bash
> uv run python scripts/download_graph.py
> ```



## Project Structure

```
nswTransportData/
├── pyproject.toml           # Project metadata & dependencies (uv)
├── uv.lock                  # Pinned dependency lockfile
├── .python-version          # Python version pin (3.14)
├── .lfsconfig               # Git LFS local fetch exclude rules
├── .gitattributes           # Git attributes registering sydney_walk.graphml with LFS
│
├── src/                     # Flask package (import root = src/)
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
├── scripts/
│   ├── download_graph.py    # Script to download OSMnx walking graphs
│   ├── generate_supermarket_isochrones.py
│   └── generate_station_isochrones.py
│
└── data/                    # Downloaded GTFS data (git-ignored except walk graph)
```

> **Import convention**: All modules inside `src/` import relative to `src/` as the root
> (e.g. `from gtfs.loader import get_feed`). Always run from the **project root** directory.

## Supported Transport Modes

| Mode                    | Status                   |
|-------------------------|--------------------------|
| Sydney Trains           | ✅ Supported             |
| NSW Trains (Intercity)  | ✅ Supported             |
| Parramatta Light Rail   | ✅ Supported             |
| Inner West Light Rail   | ✅ Supported             |
| CBD & South East LR     | ✅ Supported             |
| Newcastle Light Rail    | ✅ Supported             |
| Sydney Ferries          | ✅ Supported             |
| MFF Ferries             | ✅ Supported             |

## Environment Variables

| Variable                | Required | Description                                            |
|-------------------------|----------|--------------------------------------------------------|
| `TRANSPORT_NSW_API_KEY` | Yes      | TfNSW API key for downloading GTFS data                |
| `PORT`                  | No       | Flask server port (default: 5000)                      |

## Tech Stack

- **Python 3.14** with **uv** for package management
- **pandas** + **pyarrow** for high-performance data processing
- **gtfs-kit** for loading GTFS feeds into DataFrames in the `src/` API
- **osmnx**, **networkx**, and **shapely** for local street network graph generation and isochrone routing
- **Flask** for the Stations and Isochrone API (`src/`)
- **Ruff** for linting and formatting

## License

This project is licensed under the [Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0) License](LICENSE).
