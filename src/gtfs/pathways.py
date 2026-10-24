"""
In-station walking times from TfNSW's GTFS pathways.txt.

pathways.txt maps the inside of each station (platforms, concourses, stairs,
escalators, lifts, gates) as a graph whose edges carry a traversal_time in
seconds. It is only published in TfNSW's complete GTFS bundle, not the per-mode
feeds, so scripts/download_pathways.py extracts it to
data/pathways/<YYYY-MM-DD>/pathways.txt. The newest copy is used.

Platform IDs match the sydney_trains and sydney_metro feeds, so the shortest
path between two platforms is the walking time for a transfer between them.
Around 280 of the ~390 train and metro stations have platform-to-platform data.
"""

import threading
from pathlib import Path

import networkx as nx
import pandas as pd

from config import PROJECT_ROOT

PATHWAYS_DIR = PROJECT_ROOT / "data" / "pathways"

# Transfers longer than this are treated as unknown (no realistic in-station walk is this long)
MAX_WALK_SECS = 1800

_graph: nx.DiGraph | None = None
_graph_loaded = False
_graph_lock = threading.Lock()
_walk_cache: dict[str, dict[str, float]] = {}


def find_pathways_file() -> Path | None:
    """Return the newest data/pathways/<date>/pathways.txt, or None if there is none."""
    files = sorted(PATHWAYS_DIR.glob("*/pathways.txt"))
    return files[-1] if files else None


def _get_graph() -> nx.DiGraph | None:
    """Load pathways.txt into a directed graph once per process (double-checked locking)."""
    global _graph, _graph_loaded
    if _graph_loaded:
        return _graph

    with _graph_lock:
        if not _graph_loaded:
            path = find_pathways_file()
            if path is None:
                print(
                    "[pathways] No pathways.txt found; transfers use the default time. "
                    "Run scripts/download_pathways.py to enable per-platform times."
                )
            else:
                pw = pd.read_csv(path, dtype=str)
                graph = nx.DiGraph()
                for row in pw.itertuples(index=False):
                    secs = int(float(row.traversal_time))
                    graph.add_edge(row.from_stop_id, row.to_stop_id, secs=secs)
                    if row.is_bidirectional == "1":
                        graph.add_edge(row.to_stop_id, row.from_stop_id, secs=secs)
                _graph = graph
                print(f"[pathways] Loaded {len(pw)} pathways from {path}")
            _graph_loaded = True

    return _graph


def get_walk_secs(from_platform: str, to_platform: str) -> int | None:
    """
    Shortest in-station walking time in seconds from one platform to another,
    or None when there is no pathway data connecting them.
    """
    graph = _get_graph()
    if graph is None or from_platform not in graph or to_platform not in graph:
        return None

    dists = _walk_cache.get(from_platform)
    if dists is None:
        dists = nx.single_source_dijkstra_path_length(
            graph, from_platform, cutoff=MAX_WALK_SECS, weight="secs"
        )
        _walk_cache[from_platform] = dists

    secs = dists.get(to_platform)
    return None if secs is None else int(secs)
