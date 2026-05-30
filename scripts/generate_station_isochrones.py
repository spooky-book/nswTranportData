import requests
import json
import concurrent.futures

API_BASE_URL = "http://localhost:5000/api"
OUTPUT_FILE = "station_isochrones.geojson"

# The user's list of stations
STATIONS_INPUT = """
200066, Gadigal Station, sydney_metro
201721, Waterloo Station, sydney_metro
201510, Redfern Station, sydney_trains
200030, Martin Place Station, sydney_metro
200070, Town Hall Station, sydney_trains
201710, Green Square Station, sydney_trains
200030, Martin Place Station, sydney_trains
201520, Macdonaldtown Station, sydney_trains
200046, Barangaroo Station, sydney_metro
204420, Sydenham Station, sydney_metro
204310, Erskineville Station, sydney_trains
204210, Newtown Station, sydney_trains
200080, Wynyard Station, sydney_trains
201110, Kings Cross Station, sydney_trains
202010, Mascot Station, sydney_trains
204420, Sydenham Station, sydney_trains
206044, Victoria Cross Station, sydney_metro
200020, Circular Quay Station, sydney_trains
204410, St Peters Station, sydney_trains
204810, Stanmore Station, sydney_trains
202710, Edgecliff Station, sydney_trains
202020, Domestic Airport Station, sydney_trains
206516, Crows Nest Station, sydney_metro
204910, Petersham Station, sydney_trains
206110, Milsons Point Station, sydney_trains
200050, St James Station, sydney_trains
204920, Lewisham Station, sydney_trains
220510, Wolli Creek Station, sydney_trains
202210, Bondi Junction Station, sydney_trains
202030, International Airport Station, sydney_trains
206010, North Sydney Station, sydney_trains
200040, Museum Station, sydney_trains
206710, Chatswood Station, sydney_metro
213010, Summer Hill Station, sydney_trains
213510, Strathfield Station, sydney_trains
213410, Burwood Station, sydney_trains
206020, Waverton Station, sydney_trains
213110, Ashfield Station, sydney_trains
206510, Wollstonecraft Station, sydney_trains
213210, Croydon Station, sydney_trains
213710, North Strathfield Station, sydney_trains
221620, Rockdale Station, sydney_trains
211320, North Ryde Station, sydney_metro
206520, St Leonards Station, sydney_trains
213810, Concord West Station, sydney_trains
221710, Kogarah Station, sydney_trains
222010, Hurstville Station, sydney_trains
211340, Macquarie Park Station, sydney_metro
221810, Carlton Station, sydney_trains
206410, Artarmon Station, sydney_trains
213820, Rhodes Station, sydney_trains
211310, Macquarie University Station, sydney_metro
214020, Flemington Station, sydney_trains
212710, Olympic Park Station, sydney_trains
222020, Allawah Station, sydney_trains
211430, Meadowbank Station, sydney_trains
206710, Chatswood Station, sydney_trains
215020, Parramatta Station, sydney_trains
222210, Penshurst Station, sydney_trains
214110, Lidcombe Station, sydney_trains
214010, Homebush Station, sydney_trains
212110, Epping Station, sydney_metro
211420, West Ryde Station, sydney_trains
222310, Mortdale Station, sydney_trains
206910, Roseville Station, sydney_trains
211410, Denistone Station, sydney_trains
"""


def fetch_station_coords():
    print("Fetching station coordinates from API...")
    coords = {}
    for mode in ["sydney_trains", "sydney_metro"]:
        response = requests.get(f"{API_BASE_URL}/stations?mode={mode}")
        response.raise_for_status()
        for s in response.json().get("stations", []):
            coords[f"{s['stop_id']}_{mode}"] = (s["stop_lat"], s["stop_lon"])
    return coords


def process_station(item, coords):
    parts = [p.strip() for p in item.split(",")]
    if len(parts) != 3:
        return []

    stop_id, name, mode = parts
    key = f"{stop_id}_{mode}"

    if key not in coords:
        print(f"Warning: Could not find coordinates for {name} ({stop_id}) in {mode}")
        return []

    lat, lon = coords[key]
    print(f"Requesting isochrone for {name} ({lat}, {lon})...")

    # 1. Fetch Isochrone
    response = requests.post(
        f"{API_BASE_URL}/isochrone",
        json={
            "lat": lat,
            "lon": lon,
            "speed": 1.4,
            "max_duration_minutes": 15,
            "resolution": "high",  # Use high for smoother boundaries on a map with many shapes
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
                        "color": "#EC4899" if "metro" in mode else "#4F46E5",
                        "center_point": [lon, lat],
                    },
                    "geometry": data["isochrone"],
                }
            )
    else:
        print(f"Error fetching isochrone for {name}: {response.text}")

    return features


def main():
    coords = fetch_station_coords()

    lines = [
        line.strip() for line in STATIONS_INPUT.strip().split("\n") if line.strip()
    ]

    all_features = []

    # Run requests concurrently to save time
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(process_station, line, coords) for line in lines]
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
