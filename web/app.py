from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from flask import Flask, jsonify, render_template, request

from loader.loader import GTFSStatic
from services.routing_service import StopGraph, stops_for_display


BASE_DIR = Path(__file__).resolve().parent

# Check for pre-extracted folder or fallback zip path relative to project root
DEFAULT_DATA_PATH = BASE_DIR.parent / "data/gtfs_schedule_sydneytrains"
if not DEFAULT_DATA_PATH.exists():
    DEFAULT_DATA_PATH = BASE_DIR.parent / "data/gtfs_schedule_sydneytrains.zip"


app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
)


_gtfs: GTFSStatic | None = None
_graph: StopGraph | None = None


def _load_gtfs_once() -> None:
    global _gtfs, _graph
    if _gtfs is not None and _graph is not None:
        return

    zip_path_env = os.getenv("GTFS_STATIC_ZIP")
    if zip_path_env:
        zip_path = Path(zip_path_env)
    else:
        zip_path = DEFAULT_DATA_PATH

    if not zip_path.exists():
        raise FileNotFoundError(
            f"Could not find GTFS data at {zip_path}. "
            "Please download/place the GTFS data or set the GTFS_STATIC_ZIP env variable."
        )

    print(f"Loading GTFS data from: {zip_path.resolve()}")
    _gtfs = GTFSStatic.from_zip(str(zip_path))
    _graph = StopGraph.from_gtfs(_gtfs)


@app.before_request
def ensure_data_loaded() -> None:
    _load_gtfs_once()


@app.get("/")
def index() -> str:
    assert _graph is not None
    popular = _graph.popular_stops(limit=25)
    return render_template("index.html", popular_stops=popular)


@app.get("/api/stops")
def search_stops() -> Any:
    assert _gtfs is not None
    query = request.args.get("query", "").strip()

    if not query:
        assert _graph is not None
        stops = _graph.popular_stops(limit=20)
    else:
        results = _gtfs.search_stops(query, limit=20)
        stops = stops_for_display(results)

    return jsonify({"stops": stops})


@app.post("/api/route")
def compute_route() -> Any:
    assert _graph is not None
    data: Dict[str, Any] = request.get_json(force=True, silent=True) or {}
    origin = str(data.get("origin_stop_id", "")).strip()
    destination = str(data.get("destination_stop_id", "")).strip()

    if not origin or not destination:
        return jsonify(
            {"error": "Both origin_stop_id and destination_stop_id are required."}
        ), 400

    path = _graph.shortest_path(origin, destination)
    if not path:
        return jsonify(
            {"error": "No connection found between the selected stops."}
        ), 404

    stops: List[Dict[str, Any]] = [_graph.stop_details(stop_id) for stop_id in path]
    return jsonify({"stops": stops})


def create_app() -> Flask:
    """Flask factory for testing."""
    return app


if __name__ == "__main__":
    app.run(debug=True, port=int(os.getenv("PORT", "5000")))
