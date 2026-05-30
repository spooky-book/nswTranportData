import requests
import json
import concurrent.futures
import osmnx as ox

API_BASE_URL = "http://localhost:5000/api"
OUTPUT_FILE = "supermarket_isochrones.geojson"


def fetch_supermarkets():
    print("Querying OpenStreetMap for supermarkets in Sydney...")
    # Fetch all supermarkets in the Sydney region
    tags = {"shop": "supermarket"}
    gdf = ox.features_from_place("Sydney, New South Wales, Australia", tags)

    print(f"Found {len(gdf)} total supermarkets in Sydney.")

    # Filter for Coles, Woolworths, and Aldi
    target_names = ["Coles", "Woolworths", "Aldi"]

    supermarkets = []

    for idx, row in gdf.iterrows():
        name = str(row.get("name", ""))

        # Check if the name contains one of our target brands
        if not any(brand.lower() in name.lower() for brand in target_names):
            continue

        # If it's a polygon (a building footprint), get its center point
        if (
            row.geometry.geom_type == "Polygon"
            or row.geometry.geom_type == "MultiPolygon"
        ):
            centroid = row.geometry.centroid
            lat, lon = centroid.y, centroid.x
        elif row.geometry.geom_type == "Point":
            lat, lon = row.geometry.y, row.geometry.x
        else:
            continue

        # Determine the brand for coloring
        brand = "Unknown"
        color = "#000000"
        if "coles" in name.lower():
            brand = "Coles"
            color = "#DC2626"  # Red
        elif "woolworths" in name.lower() or "woolies" in name.lower():
            brand = "Woolworths"
            color = "#16A34A"  # Green
        elif "aldi" in name.lower():
            brand = "Aldi"
            color = "#2563EB"  # Blue

        supermarkets.append(
            {"name": name, "brand": brand, "color": color, "lat": lat, "lon": lon}
        )

    print(f"Filtered down to {len(supermarkets)} {', '.join(target_names)} locations.")
    return supermarkets


def process_supermarket(supermarket):
    name = supermarket["name"]
    lat = supermarket["lat"]
    lon = supermarket["lon"]
    color = supermarket["color"]
    brand = supermarket["brand"]

    print(f"Requesting isochrone for {name} ({lat}, {lon})...")

    response = requests.post(
        f"{API_BASE_URL}/isochrone",
        json={
            "lat": lat,
            "lon": lon,
            "speed": 1.4,
            "max_duration_minutes": 15,
            "resolution": "high",
        },
    )

    features = []

    if response.status_code == 200:
        data = response.json()
        if "isochrone" in data:
            # Create the Isochrone Polygon feature
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "name": f"Isochrone - {name}",
                        "brand": brand,
                        "color": color,
                        "center_point": [lon, lat],
                        "reachable_nodes": data.get("reachable_nodes", 0),
                        "fallback_circle": data.get("fallback_circle", False)
                    },
                    "geometry": data["isochrone"],
                }
            )
    else:
        print(f"Error fetching isochrone for {name}: {response.text}")

    return features


def main():
    supermarkets = fetch_supermarkets()

    # We might find hundreds of them, so let's limit it to 50 for testing,
    # or you can remove this slice to process all of them!
    # supermarkets = supermarkets[:50]

    all_features = []

    # Run requests concurrently to save time
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(process_supermarket, sm) for sm in supermarkets]
        for future in concurrent.futures.as_completed(futures):
            all_features.extend(future.result())

    # Assemble final FeatureCollection
    feature_collection = {"type": "FeatureCollection", "features": all_features}

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(feature_collection, f, indent=2)

    print(
        f"\nDone! Generated {len(all_features)} total features (points and polygons)."
    )
    print(f"Saved to {OUTPUT_FILE}. You can now import this file into the map UI!")


if __name__ == "__main__":
    main()
