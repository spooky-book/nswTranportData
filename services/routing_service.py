from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd

from loader.loader import GTFSStatic


def _clean_value(value):
    if pd.isna(value):
        return None
    return value


@dataclass(slots=True)
class StopGraph:
    adjacency: Dict[str, set]
    stop_lookup: Dict[str, Dict[str, Optional[str]]]

    @classmethod
    def from_gtfs(cls, gtfs: GTFSStatic) -> "StopGraph":
        adjacency: Dict[str, set] = defaultdict(set)

        stop_times = gtfs.stop_times
        if not stop_times.empty:
            required_cols = {"trip_id", "stop_id", "stop_sequence"}
            missing = required_cols - set(stop_times.columns)
            if missing:
                raise KeyError(
                    f"stop_times table missing expected columns: {', '.join(sorted(missing))}"
                )

            filtered = stop_times.dropna(
                subset=["trip_id", "stop_id", "stop_sequence"]
            ).sort_values(["trip_id", "stop_sequence"])

            for trip_id, group in filtered.groupby("trip_id"):
                stop_ids = []
                for stop_id in group["stop_id"]:
                    sid = str(stop_id).strip()
                    if sid:
                        stop_ids.append(sid)
                if not stop_ids:
                    continue
                for stop in stop_ids:
                    adjacency.setdefault(stop, set())
                for current, nxt in zip(stop_ids, stop_ids[1:]):
                    if current == nxt:
                        continue
                    adjacency[current].add(nxt)
                    adjacency[nxt].add(current)

        stop_lookup = {}
        if not gtfs.stops.empty:
            columns = [
                col
                for col in ["stop_name", "parent_station", "stop_lat", "stop_lon"]
                if col in gtfs.stops.columns
            ]
            if columns:
                for row in (
                    gtfs.stops.dropna(subset=["stop_id"])
                    .drop_duplicates("stop_id")
                    .itertuples(index=False)
                ):
                    stop_id = str(getattr(row, "stop_id")).strip()
                    if not stop_id:
                        continue
                    stop_lookup[stop_id] = {
                        col: _clean_value(getattr(row, col, None)) for col in columns
                    }
                    adjacency.setdefault(stop_id, set())

        return cls(adjacency=dict(adjacency), stop_lookup=stop_lookup)

    def shortest_path(self, origin: str, destination: str) -> List[str]:
        if not origin or not destination:
            return []
        origin = origin.strip()
        destination = destination.strip()
        if origin == destination and origin in self.stop_lookup:
            return [origin]
        if origin not in self.adjacency or destination not in self.adjacency:
            return []

        visited = {origin: None}
        queue: deque[str] = deque([origin])

        while queue:
            current = queue.popleft()
            if current == destination:
                break
            for neighbour in self.adjacency.get(current, set()):
                if neighbour not in visited:
                    visited[neighbour] = current
                    queue.append(neighbour)
        else:
            return []

        path = [destination]
        while visited[path[-1]] is not None:
            path.append(visited[path[-1]])
        path.reverse()
        return path

    def stop_details(self, stop_id: str) -> Dict[str, Optional[str]]:
        info = self.stop_lookup.get(stop_id, {})
        return {
            "stop_id": stop_id,
            "stop_name": info.get("stop_name") or stop_id,
            "parent_station": info.get("parent_station"),
            "stop_lat": info.get("stop_lat"),
            "stop_lon": info.get("stop_lon"),
        }

    def popular_stops(self, limit: int = 20) -> List[Dict[str, Optional[str]]]:
        # Provide deterministic ordering for UI auto-fill
        sorted_ids = sorted(
            self.stop_lookup.keys(),
            key=lambda sid: str(self.stop_lookup[sid].get("stop_name") or sid).lower(),
        )
        return [self.stop_details(stop_id) for stop_id in sorted_ids[:limit]]


def stops_for_display(df: pd.DataFrame) -> List[Dict[str, Optional[str]]]:
    if df is None or df.empty:
        return []

    available = [
        col for col in ("stop_id", "stop_name", "parent_station") if col in df.columns
    ]
    if not available:
        return []

    subset = df[available].dropna(subset=["stop_id"]).copy()
    subset["stop_id"] = subset["stop_id"].astype(str).str.strip()
    subset = subset[subset["stop_id"] != ""]

    display: List[Dict[str, Optional[str]]] = []
    for row in subset.itertuples(index=False):
        stop_id = str(getattr(row, "stop_id")).strip()
        if not stop_id:
            continue
        stop_name = getattr(row, "stop_name", None)
        display.append(
            {
                "stop_id": stop_id,
                "stop_name": _clean_value(stop_name) or stop_id,
                "parent_station": _clean_value(getattr(row, "parent_station", None)),
            }
        )
    return display
