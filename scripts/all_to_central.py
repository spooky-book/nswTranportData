import requests
import csv
import concurrent.futures

# ==========================================
# CONFIGURATION
# ==========================================
API_BASE_URL = "http://localhost:5000/api"
MODE = "sydney_trains"
DESTINATION_ID = "200060"  # Central Station

# Modify these to change the data you are requesting
DATE = "20260525"
TIME_WINDOW_START = "07:00:00"
TIME_WINDOW_END = "23:00:00"

# Generate a safe filename automatically
_safe_start = TIME_WINDOW_START.replace(":", "")
_safe_end = TIME_WINDOW_END.replace(":", "")
OUTPUT_CSV = f"stats_to_destination_{DESTINATION_ID}_date_{DATE}_time_window_{_safe_start}-{_safe_end}.csv"
# ==========================================


def get_all_stations():
    print(f"Fetching all stations for mode: {MODE}...")
    url = f"{API_BASE_URL}/stations?mode={MODE}"
    response = requests.get(url)
    response.raise_for_status()
    return response.json().get("stations", [])


def get_route_stats(origin_id):
    url = f"{API_BASE_URL}/route-stats"
    payload = {
        "mode": MODE,
        "origin_stop_id": origin_id,
        "destination_stop_id": DESTINATION_ID,
        "dates": [DATE],
        "time_window_start": TIME_WINDOW_START,
        "time_window_end": TIME_WINDOW_END,
    }
    response = requests.post(url, json=payload)
    if response.status_code != 200:
        return None
    return response.json()


def _process_station(args):
    station, index, total = args
    origin_id = station["stop_id"]
    origin_name = station["stop_name"]

    if origin_id == DESTINATION_ID:
        return None

    print(f"[{index}/{total}] Fetching stats: {origin_name} -> Central...")
    stats = get_route_stats(origin_id)

    if not stats or not stats.get("dates"):
        return None

    # Extract the stats for the first (and only) date we requested
    date_stats = stats["dates"][0]

    # Only include stations that actually have direct trips to Central
    if date_stats.get("num_trips", 0) > 0:
        return {
            "origin_id": origin_id,
            "origin_name": origin_name,
            "num_trips": date_stats.get("num_trips"),
            "num_routes": date_stats.get("num_routes"),
            "min_headway_secs": date_stats.get("min_headway_secs"),
            "max_headway_secs": date_stats.get("max_headway_secs"),
            "mean_headway_secs": date_stats.get("mean_headway_secs"),
            "median_headway_secs": date_stats.get("median_headway_secs"),
            "mode_headway_secs": date_stats.get("mode_headway_secs"),
            "min_travel_time_secs": date_stats.get("travel_time_min_secs"),
            "max_travel_time_secs": date_stats.get("travel_time_max_secs"),
            "mean_travel_time_secs": date_stats.get("travel_time_mean_secs"),
            "median_travel_time_secs": date_stats.get("travel_time_median_secs"),
            "mode_travel_time_secs": date_stats.get("travel_time_mode_secs"),
        }
    return None


def main():
    stations = get_all_stations()
    total = len(stations)
    print(f"Found {total} stations.")

    # Prepare arguments for the worker threads
    args_list = [(station, i, total) for i, station in enumerate(stations, 1)]
    results = []

    # Use ThreadPoolExecutor to run up to 5 requests concurrently.
    # executor.map guarantees that the results are returned in the exact
    # same order as the input args_list, preserving station order!
    with concurrent.futures.ThreadPoolExecutor() as executor:
        for res in executor.map(_process_station, args_list):
            if res:
                results.append(res)

    # Save to CSV
    if results:
        print(f"\nSaving results to {OUTPUT_CSV}...")
        with open(OUTPUT_CSV, mode="w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
        print("Done!")
    else:
        print("No direct trips found for any station.")


if __name__ == "__main__":
    main()
