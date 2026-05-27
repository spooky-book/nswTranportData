"""
Script to download the OpenStreetMap walking graph for Sydney and save it locally.
This avoids hitting Overpass API rate limits during app runtime.
"""

import sys
from pathlib import Path

import osmnx as ox

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


def main():
    place_name = "Sydney, New South Wales, Australia"
    output_filename = "sydney_walk.graphml"
    output_path = DATA_DIR / "osmnx" / output_filename

    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Downloading expanded walk graph for: {place_name}")
    print("This may take a few minutes depending on the size of the area...")

    # We use a custom filter to be extremely permissive. It grabs anything that is a highway
    # (except motorways/trunks) AND anything explicitly tagged foot=yes or foot=designated,
    # ensuring we don't miss bridges or cycleways that allow walking.
    custom_filter = (
        '["area"!~"yes"]["highway"!~"motor|motorway|motorway_link|trunk|trunk_link|proposed|construction|abandoned|platform|raceway"]'
        '["foot"!~"no"]["access"!~"private"]'
    )

    try:
        # Use a bounding box or place name. Place name is easier.
        # We also simplify the graph to reduce size and speed up routing
        G = ox.graph_from_place(place_name, custom_filter=custom_filter, simplify=True)
        print(
            f"Graph downloaded successfully: {len(G.nodes)} nodes, {len(G.edges)} edges."
        )

        print(f"Saving graph to {output_path}...")
        ox.save_graphml(G, filepath=output_path)
        print("Done!")

    except Exception as e:
        print(f"Error downloading graph: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
