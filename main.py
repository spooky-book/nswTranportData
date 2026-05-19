import sys
from datetime import datetime
import os
from pathlib import Path
from zipfile import BadZipFile
from zoneinfo import ZoneInfo

import requests
from tqdm import tqdm

from loader.loader import GTFSStatic
from services.map_service import generate_map_all_routes, add_train_stops_to_map


def main():
	# gtfs = get_complete_gtfs()
	gtfs1 = get_schedule_gtfs_light_rail_parramatta()
	gtfs2 = get_schedule_gtfs_light_rail_inner_west()
	# gtfs3 = get_schedule_gtfs_light_rail_newcastle()
	# gtfs4 = get_schedule_gtfs_sydney_trains()
	# gtfs5 = get_schedule_gtfs_light_rail_city_and_south_east()
	# gtfs6 = get_schedule_gtfs_ferries_mff()
	# gtfs7 = get_schedule_gtfs_ferries_sydney_ferries()
	# gtfs8 = get_schedule_gtfs_nsw_trains()

	map_all_routes = generate_map_all_routes(gtfs1, max_workers=3)
	map_all_stations = add_train_stops_to_map(gtfs1, m=map_all_routes, display_platforms=True)
	map_all_routes = generate_map_all_routes(gtfs2, max_workers=3, m=map_all_stations)
	map_all_stations = add_train_stops_to_map(gtfs2, m=map_all_routes, display_platforms=False)
	# map_all_routes = generate_map_all_routes(gtfs3, max_workers=3, m=map_all_stations)
	# map_all_stations = add_train_stops_to_map(gtfs3, m=map_all_routes, display_platforms=False)
	# map_all_routes = generate_map_all_routes(gtfs4, max_workers=3, m=map_all_stations)
	# map_all_stations = add_train_stops_to_map(gtfs4, m=map_all_routes, display_platforms=False)
	# map_all_routes = generate_map_all_routes(gtfs5, max_workers=3, m=map_all_stations)
	# map_all_stations = add_train_stops_to_map(gtfs5, m=map_all_routes, display_platforms=False)
	# map_all_routes = generate_map_all_routes(gtfs6, max_workers=3, m=map_all_stations)
	# map_all_stations = add_train_stops_to_map(gtfs6, m=map_all_routes, display_platforms=False)
	# map_all_routes = generate_map_all_routes(gtfs7, max_workers=3, m=map_all_stations)
	# map_all_stations = add_train_stops_to_map(gtfs7, m=map_all_routes, display_platforms=False)
	# map_all_routes = generate_map_all_routes(gtfs8, max_workers=3, m=map_all_stations)
	# map_all_stations = add_train_stops_to_map(gtfs8, m=map_all_routes, display_platforms=False)
	map_all_stations.save("./maps/gtfs_shapes_sydneyTrains.html")
	# map_all_stations.save("./maps/gtfs_shapes_complete.html")


def get_schedule_gtfs_shared(api_path: str, file_path: str):
	print(f"Retrieving schedule GTFS data for sydney {file_path}")
	api_key = os.getenv("TRANSPORT_NSW_API_KEY")
	if not api_key:
		raise EnvironmentError("TRANSPORT_NSW_API_KEY is not set in environment variables.")

	sydney_datetime = datetime.now(ZoneInfo("Australia/Sydney"))
	sydney_date = sydney_datetime.date()

	my_file = Path(f"./data/schedule-gtfs/{sydney_date}/{file_path}/gtfs_schedule.zip")
	if my_file.is_file():
		print("Today's data has been cached, reusing cached data")

		try:
			return GTFSStatic.from_bytes(my_file.read_bytes())
		except BadZipFile as e:
			print(f"Error reading from cached file {e}")

	try:
		print("Retrieving schedule GTFS data from api endpoint")

		url = f"https://api.transport.nsw.gov.au/v1/gtfs/schedule/{api_path}"
		with requests.get(url, headers={"Authorization": f"apikey {api_key}"}, stream=True, timeout=120) as r:
			r.raise_for_status()
			total_size = int(r.headers.get("content-length", 0)) or None
			chunk_size = 8192  # 8 KB

			my_file.parent.mkdir(exist_ok=True, parents=True)

			with open(my_file, "wb") as f, tqdm(
					total=total_size, unit="B", unit_scale=True, desc="Downloading", ncols=80,
			) as pbar:
				for chunk in r.iter_content(chunk_size=chunk_size):
					if chunk:
						f.write(chunk)
						pbar.update(len(chunk))

			return GTFSStatic.from_bytes(my_file.read_bytes())

	except requests.exceptions.HTTPError as e:
		print(f"HTTP error occurred: {e}", file=sys.stderr)
		return None
	except requests.exceptions.RequestException as e:
		print(f"Other error occurred: {e}", file=sys.stderr)
		return None
	except Exception as e:
		print(f"Something went wrong {e}", file=sys.stderr)
		return None


def get_schedule_gtfs_light_rail_inner_west() -> GTFSStatic:
	return get_schedule_gtfs_shared("lightrail/innerwest", "light_rail_inner_west")

def get_schedule_gtfs_light_rail_city_and_south_east() -> GTFSStatic:
	return get_schedule_gtfs_shared("lightrail/cbdandsoutheast", "light_rail_city_and_south_west")

def get_schedule_gtfs_light_rail_parramatta() -> GTFSStatic:
	return get_schedule_gtfs_shared("lightrail/parramatta", "light_rail_parramatta")

def get_schedule_gtfs_light_rail_newcastle() -> GTFSStatic:
	return get_schedule_gtfs_shared("lightrail/newcastle", "light_rail_newcastle")

def get_schedule_gtfs_sydney_trains() -> GTFSStatic:
	return get_schedule_gtfs_shared("sydneytrains", "sydney_trains")

def get_schedule_gtfs_nsw_trains() -> GTFSStatic:
	return get_schedule_gtfs_shared("nswtrains", "nsw_trains")

# def get_schedule_gtfs_buses() -> GTFSStatic:
# 	return get_schedule_gtfs_shared("buses")

# def get_schedule_gtfs_region_buses() -> GTFSStatic:
# 	return get_schedule_gtfs_shared("region_buses")

def get_schedule_gtfs_ferries_sydney_ferries() -> GTFSStatic:
	return get_schedule_gtfs_shared("ferries/sydneyferries", "ferries_sydney_ferries")

def get_schedule_gtfs_ferries_mff() -> GTFSStatic:
	return get_schedule_gtfs_shared("ferries/MFF", "ferries_mff")

def get_complete_gtfs():
	print("Retrieving complete GTFS data for sydney")
	api_key = os.getenv("TRANSPORT_NSW_API_KEY")
	if not api_key:
		raise EnvironmentError("TRANSPORT_NSW_API_KEY is not set in environment variables.")

	sydney_datetime = datetime.now(ZoneInfo("Australia/Sydney"))
	sydney_date = sydney_datetime.date()

	my_file = Path(f"./data/complete-gtfs/{sydney_date}/gtfs_complete.zip")
	if my_file.is_file():
		print("Today's data has been cached, reusing cached data")

		try:
			with open(my_file, "rb") as f:
				return GTFSStatic.from_bytes(f.read())
		except BadZipFile as e:
			print(f"Error reading from cached file {e}")

	try:
		print("Retrieving complete GTFS data from api endpoint")

		url = "https://api.transport.nsw.gov.au/v1/publictransport/timetables/complete/gtfs"
		with requests.get(url, headers={"Authorization": f"apikey {api_key}"}, stream=True, timeout=120) as r:
			r.raise_for_status()
			total_size = int(r.headers.get("content-length", 0)) or None
			chunk_size = 8192  # 8 KB

			my_file.parent.mkdir(exist_ok=True, parents=True)

			with open(my_file, "wb") as f, tqdm(
				total=total_size, unit="B", unit_scale=True, desc="Downloading", ncols=80,
			) as pbar:
				for chunk in r.iter_content(chunk_size=chunk_size):
					if chunk:
						f.write(chunk)
						pbar.update(len(chunk))

			return GTFSStatic.from_bytes(my_file.read_bytes())

	except requests.exceptions.HTTPError as e:
		print(f"HTTP error occurred: {e}", file=sys.stderr)
		return None
	except requests.exceptions.RequestException as e:
		print(f"Other error occurred: {e}", file=sys.stderr)
		return None
	except Exception as e:
		print(f"Something went wrong {e}", file=sys.stderr)
		return None


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
	main()

# See PyCharm help at https://www.jetbrains.com/help/pycharm/
