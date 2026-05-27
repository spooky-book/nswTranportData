"""
Isochrone API blueprint.

Provides POST /api/isochrone which computes a walking/biking isochrone polygon
based on the local street network.

Request body (JSON):
{
    "lat": -33.8829,
    "lon": 151.2066,
    "speed": 1.4,                 // speed in m/s (default 1.4 for walking)
    "max_duration_minutes": 15,   // maximum travel time in minutes
    "resolution": "high"          // "ultra", "high" (concave hull) or "low" (convex hull)
}

Response body (JSON):
{
    "lat": -33.8829,
    "lon": 151.2066,
    "speed": 1.4,
    "max_duration_minutes": 15.0,
    "resolution": "high",
    "isochrone": { ... GeoJSON Polygon ... }
}
"""

from pathlib import Path

import networkx as nx
import osmnx as ox
from flask import Blueprint, jsonify, request, render_template
from shapely.geometry import MultiPoint

isochrone_bp = Blueprint("isochrone", __name__, url_prefix="/api")

@isochrone_bp.route("/map", methods=["GET"])
def isochrone_map():
    """Serves the interactive frontend UI for the Isochrone generator."""
    return render_template("isochrone_map.html")

# Global cache for the graph
_WALK_GRAPH = None
_GRAPH_LOADED = False

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
GRAPH_PATH = DATA_DIR / "osmnx" / "sydney_walk.graphml"


def get_graph():
    """Lazily load the graphml file and pre-compute node penalties."""
    global _WALK_GRAPH, _GRAPH_LOADED
    if not _GRAPH_LOADED:
        if not GRAPH_PATH.exists():
            raise FileNotFoundError(
                f"Graph file not found at {GRAPH_PATH}. "
                "Please run scripts/download_graph.py first."
            )
        print(f"Loading graph from {GRAPH_PATH} (this may take a moment)...")
        _WALK_GRAPH = ox.load_graphml(GRAPH_PATH)

        print("Pre-computing intersection penalties...")
        for node, data in _WALK_GRAPH.nodes(data=True):
            penalty_sec = 0
            highway = data.get("highway", "")
            # If highway is a list (can happen in OSMnx if multiple tags), convert to string or check
            if isinstance(highway, list):
                highway = ",".join(highway)

            if "traffic_signals" in highway:
                penalty_sec = 30
            elif "crossing" in highway:
                penalty_sec = 10

            data["penalty_sec"] = penalty_sec

        _GRAPH_LOADED = True
        print("Graph loaded successfully.")
    return _WALK_GRAPH


@isochrone_bp.route("/isochrone", methods=["POST"])
def calculate_isochrone():
    body: dict = request.get_json(silent=True) or {}

    lat = body.get("lat")
    lon = body.get("lon")

    if lat is None or lon is None:
        return jsonify({"error": "'lat' and 'lon' are required."}), 400

    try:
        lat = float(lat)
        lon = float(lon)
    except ValueError:
        return jsonify({"error": "'lat' and 'lon' must be numbers."}), 400

    speed = float(body.get("speed", 1.4))  # Default 1.4 m/s (walking)
    max_duration_minutes = float(body.get("max_duration_minutes", 15))
    resolution = body.get("resolution", "high").lower()

    max_duration_sec = max_duration_minutes * 60

    try:
        G = get_graph()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # 1. Find the nearest node on the graph to the requested coordinates
    try:
        center_node = ox.distance.nearest_nodes(G, X=lon, Y=lat)
    except Exception as e:
        return jsonify({"error": f"Failed to find nearest node: {e}"}), 500

    # 2. Calculate travel times for all edges dynamically
    # Use ego_graph/Dijkstra to find reachable nodes.
    # We use a custom weight function to add the base walking time (length/speed)
    # plus the pre-computed node penalty (intersection delay).

    def travel_time_weight(u, v, data):
        # In a MultiDiGraph, 'data' is a dictionary of all edges between u and v
        # e.g., {0: {'length': 10}, 1: {'length': 15}}
        min_time_sec = float("inf")
        for edge_key, edge_data in data.items():
            length = edge_data.get("length", 0)
            # Sometimes length can be a list if edges were simplified by OSMnx
            if isinstance(length, list):
                length = length[0]

            time_sec = float(length) / speed
            if time_sec < min_time_sec:
                min_time_sec = time_sec

        # Penalty for crossing the destination node (in seconds)
        penalty_sec = G.nodes[v].get("penalty_sec", 0)
        return min_time_sec + penalty_sec

    # Find reachable nodes using Dijkstra
    # cutoff is in seconds because our weight function returns seconds
    reachable_nodes = nx.single_source_dijkstra_path_length(
        G, center_node, cutoff=max_duration_sec, weight=travel_time_weight
    )

    if not reachable_nodes:
        return jsonify({"error": "No reachable nodes found from this origin."}), 404

    # 3. Extract node coordinates
    node_points = []
    for node in reachable_nodes.keys():
        node_data = G.nodes[node]
        if "x" in node_data and "y" in node_data:
            node_points.append((node_data["x"], node_data["y"]))

    # If resolution is high or ultra, add the edge geometries for a much tighter hull
    if resolution in ["high", "ultra"]:
        for u, v, data in G.subgraph(reachable_nodes.keys()).edges(data=True):
            if "geometry" in data:
                for coord in data["geometry"].coords:
                    node_points.append(coord)

    if len(node_points) < 3:
        # A polygon needs at least 3 points. Return a simple buffer (circle) in degrees as a fallback
        # 1 degree is roughly 111km, so buffer by (max_duration_sec * speed / 111000)
        fallback_buffer = (max_duration_sec * speed) / 111000
        from shapely.geometry import Point

        poly = Point(lon, lat).buffer(fallback_buffer)
    else:
        import shapely

        mp = MultiPoint(node_points)
        if resolution in ["high", "ultra"]:
            # concave_hull creates a tight "shrink-wrap" boundary rather than a rubber band
            # Since we inject thousands of edge points, a very low ratio (e.g. 0.05) will trace the roads exactly 
            # and carve out the city blocks, creating a "splattered" look.
            # Ratios around 0.15-0.35 are now large enough to bridge across city blocks 
            # because our new dataset has millions of extra points (driveways, alleys, etc).
            ratio = 0.15 if resolution == "ultra" else 0.35
            poly = shapely.concave_hull(mp, ratio=ratio, allow_holes=False)

            # Fallback if concave hull produces invalid geometry due to weird node clusters
            if poly.is_empty or poly.geom_type not in ["Polygon", "MultiPolygon"]:
                poly = mp.convex_hull
        else:
            # Low resolution / convex hull
            poly = mp.convex_hull

    # Convert the Shapely Polygon to GeoJSON
    # Using __geo_interface__ which provides valid GeoJSON dictionary
    try:
        geojson = poly.__geo_interface__
    except AttributeError:
        return jsonify({"error": "Failed to generate valid geometry."}), 500

    return jsonify(
        {
            "lat": lat,
            "lon": lon,
            "speed": speed,
            "max_duration_minutes": max_duration_minutes,
            "resolution": resolution,
            "isochrone": geojson,
        }
    )


@isochrone_bp.route("/network", methods=["GET"])
def get_local_network():
    """Returns the walkable street network within a ~1.5km bounding box for debugging."""
    lat = request.args.get("lat", type=float)
    lon = request.args.get("lon", type=float)

    if lat is None or lon is None:
        return jsonify({"error": "Missing lat/lon"}), 400

    G = get_graph()
    if not G:
        return jsonify({"error": "Graph not loaded"}), 500

    # 0.015 degrees is roughly 1.5km
    margin = 0.015
    min_x, max_x = lon - margin, lon + margin
    min_y, max_y = lat - margin, lat + margin

    # Fast bbox filter
    bbox_nodes = [
        n for n, d in G.nodes(data=True)
        if min_x <= d.get("x", 0) <= max_x and min_y <= d.get("y", 0) <= max_y
    ]
    
    local_g = G.subgraph(bbox_nodes)
    
    features = []
    for u, v, data in local_g.edges(data=True):
        if "geometry" in data:
            coords = list(data["geometry"].coords)
        else:
            coords = [
                (G.nodes[u]["x"], G.nodes[u]["y"]),
                (G.nodes[v]["x"], G.nodes[v]["y"])
            ]
            
        features.append({
            "type": "Feature",
            "properties": {
                "highway": data.get("highway", "unknown"),
                "length": data.get("length", 0)
            },
            "geometry": {
                "type": "LineString",
                "coordinates": coords
            }
        })

    return jsonify({
        "type": "FeatureCollection",
        "features": features
    })
