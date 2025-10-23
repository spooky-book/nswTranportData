import os

import requests

from loader.loader import GTFSStatic
from services.map_service import generate_map_all_routes, add_train_stops_to_map


def main():
	api_key = os.getenv("TRANSPORT_NSW_API_KEY")
	if not api_key:
		raise EnvironmentError("TRANSPORT_NSW_API_KEY is not set in environment variables.")

	url = "https://api.transport.nsw.gov.au/v1/gtfs/schedule/sydneytrains"
	resp = requests.get(url, headers={"Authorization": f"apikey {api_key}"})

	with open("./data/gtfs_schedule_sydneytrains.zip", "wb") as f:
		f.write(resp.content)

	gtfs = GTFSStatic.from_bytes(resp.content)

	map_all_routes = generate_map_all_routes(gtfs)
	map_all_stations = add_train_stops_to_map(gtfs, m=map_all_routes, display_platforms=False)
	map_all_stations.save("./maps/gtfs_shapes_sydneyTrains.html")


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
	main()

# See PyCharm help at https://www.jetbrains.com/help/pycharm/
