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

### 5. Run the route finder web app

```bash
uv run python web/app.py
```

The web app starts at [http://localhost:5000](http://localhost:5000). It provides a UI to search for stops and find the shortest route between them.

> **Note:** The web app requires a pre-downloaded GTFS zip file. Set the `GTFS_STATIC_ZIP` environment variable to point to your zip, or place it at the default path (`data/gtfs_schedule_sydneytrains.zip`).

## Project Structure

```
nswTransportData/
├── main.py                  # CLI entry point — downloads GTFS data & generates maps
├── constants.py             # Shared enums (LocationTypeEnum)
├── pyproject.toml           # Project metadata & dependencies (uv)
├── uv.lock                  # Pinned dependency lockfile
├── .python-version          # Python version pin (3.14)
│
├── loader/
│   └── loader.py            # GTFS parser — reads zip into pandas DataFrames
│
├── common/
│   └── helpers.py           # Utility functions
│
├── services/
│   ├── map_service.py       # Folium map generation (routes + stops)
│   └── routing_service.py   # Stop graph & BFS shortest path
│
├── web/
│   ├── app.py               # Flask web app (route finder)
│   └── templates/
│       └── index.html       # Route finder UI
│
├── data/                    # Downloaded GTFS data (git-ignored)
└── maps/                    # Generated HTML map outputs
```

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

| Variable                | Required | Description                              |
|-------------------------|----------|------------------------------------------|
| `TRANSPORT_NSW_API_KEY` | Yes      | TfNSW API key for downloading GTFS data  |
| `GTFS_STATIC_ZIP`      | No       | Override GTFS zip path for the web app   |
| `PORT`                  | No       | Flask server port (default: 5000)        |

## Tech Stack

- **Python 3.14** with **uv** for package management
- **pandas** + **pyarrow** for high-performance data processing
- **Folium** for interactive Leaflet.js map generation
- **Flask** for the route finder web application
- **Ruff** for linting and formatting

## License

This is a personal/exploratory project. No license has been specified.
