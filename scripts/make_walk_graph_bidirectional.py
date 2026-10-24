"""
Make data/osmnx/sydney_walk.graphml walkable in both directions.

scripts/download_graph.py originally built the graph without network_type="walk",
so OSMnx kept one-way streets one-way and pedestrians couldn't walk against
traffic (~76,000 edges, ~1,000 dead-end nodes). OSMnx's walk networks add a
reverse copy of every one-way edge instead; this script does the same to the
existing file, without re-downloading from Overpass.

It streams the file twice (no full graph load, so it needs little RAM):
  1. collect every edge's (source, target);
  2. rewrite each edge with oneway=False and, if no edge runs the other way, add
     a reverse copy with swapped ends, reversed geometry and reversed=True.
Output goes to a temporary file that replaces the original at the end. The
original stays in Git LFS (`git checkout data/osmnx/sydney_walk.graphml`).

Usage (from the project root; restart the server afterwards):
    uv run python scripts/make_walk_graph_bidirectional.py
"""

import re
import sys
from pathlib import Path

GRAPH_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "osmnx" / "sydney_walk.graphml"
)

EDGE_RE = re.compile(r'^(\s*)<edge source="([^"]+)" target="([^"]+)" id="([^"]+)">\s*$')
KEY_RE = re.compile(r'<key id="([^"]+)" for="edge" attr.name="([^"]+)"')
DATA_RE = re.compile(r'^(\s*)<data key="([^"]+)">(.*)</data>\s*$')


def edge_keys(path: Path) -> dict[str, str]:
    """attr.name -> key id for edge attributes, from the header."""
    keys = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            if "<graph " in line:
                break
            m = KEY_RE.search(line)
            if m:
                keys[m.group(2)] = m.group(1)
    return keys


def reverse_wkt(wkt: str) -> str:
    """Reverse the point order of a WKT LINESTRING."""
    head, _, body = wkt.partition("(")
    points = body.rstrip(")").split(",")
    return f"{head}({', '.join(p.strip() for p in reversed(points))})"


def main():
    if not GRAPH_PATH.exists():
        sys.exit(f"{GRAPH_PATH} not found")

    keys = edge_keys(GRAPH_PATH)
    k_oneway, k_reversed, k_geometry = (
        keys["oneway"],
        keys["reversed"],
        keys["geometry"],
    )

    print("Pass 1: collecting edges...")
    pairs: set[tuple[str, str]] = set()
    with GRAPH_PATH.open(encoding="utf-8") as f:
        for line in f:
            m = EDGE_RE.match(line)
            if m:
                pairs.add((m.group(2), m.group(3)))
    missing = {(u, v) for u, v in pairs if u != v and (v, u) not in pairs}
    print(f"  {len(pairs):,} edge pairs; {len(missing):,} have no reverse")
    if not missing:
        print("Nothing to do; the graph is already bidirectional.")
        return

    print("Pass 2: writing bidirectional graph...")
    tmp = GRAPH_PATH.with_suffix(".graphml.tmp")
    added = 0
    with (
        GRAPH_PATH.open(encoding="utf-8") as src,
        tmp.open("w", encoding="utf-8", newline="\n") as out,
    ):
        block: list[str] | None = None
        for line in src:
            if block is None:
                if EDGE_RE.match(line):
                    block = [line]
                else:
                    out.write(line)
                continue

            if "</edge>" not in line:
                # Walk networks are never one-way
                m = DATA_RE.match(line)
                if m and m.group(2) == k_oneway:
                    line = f'{m.group(1)}<data key="{k_oneway}">False</data>\n'
                block.append(line)
                continue

            block.append(line)
            out.writelines(block)

            indent, u, v, key = EDGE_RE.match(block[0]).groups()
            if (u, v) in missing:
                rev = [f'{indent}<edge source="{v}" target="{u}" id="{key}">\n']
                has_reversed = False
                for data_line in block[1:-1]:
                    m = DATA_RE.match(data_line)
                    if m and m.group(2) == k_geometry:
                        data_line = f'{m.group(1)}<data key="{k_geometry}">{reverse_wkt(m.group(3))}</data>\n'
                    elif m and m.group(2) == k_reversed:
                        data_line = (
                            f'{m.group(1)}<data key="{k_reversed}">True</data>\n'
                        )
                        has_reversed = True
                    rev.append(data_line)
                if not has_reversed:
                    rev.append(f'{indent}  <data key="{k_reversed}">True</data>\n')
                rev.append(block[-1])
                out.writelines(rev)
                added += 1
            block = None

    tmp.replace(GRAPH_PATH)
    print(f"Added {added:,} reverse edges. Saved {GRAPH_PATH}")


if __name__ == "__main__":
    main()
