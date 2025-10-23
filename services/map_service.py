import folium
from folium.plugins import FeatureGroupSubGroup

from constants import LocationTypeEnum
from loader.loader import GTFSStatic
from common.helpers import pad_hex


# TODO we will need to add the m to the parameters as well
def generate_map_all_routes(gtfs: GTFSStatic, *, tiles="OpenStreetMap", zoom_start=11, default_show=True) -> folium.Map:
	route_id_to_shape_id_map = (
		gtfs.trips
	   .dropna(subset=["route_id", "shape_id"])
	   .groupby("route_id")["shape_id"]
	   .unique()
	   .to_dict()
	)

	# get all shapes associated with a route id
	shapes_by_routes = {}
	for route_id, shape_ids in route_id_to_shape_id_map.items():
		shapes_by_routes[route_id] = gtfs.shapes[gtfs.shapes["shape_id"].isin(shape_ids)]

	# sorts shapes and gets mean lat and long
	shapes_data = gtfs.shapes.copy()
	shapes_data = shapes_data.sort_values(["shape_id", "shape_pt_sequence"])
	centre = [shapes_data["shape_pt_lat"].mean(), shapes_data["shape_pt_lon"].mean()]
	m = folium.Map(location=centre, zoom_start=zoom_start, tiles=tiles)

	routes_data = gtfs.routes.copy()

	# for every route id and its associated shape ids plot it on the m
	for route_id, shape_ids in route_id_to_shape_id_map.items():
		r = routes_data[routes_data["route_id"] == route_id]
		colour = pad_hex(r.iloc[0].get("route_color", None)) if not r.empty else pad_hex(None)
		route_short_name = r.iloc[0].get("route_short_name", "") if not r.empty else ""
		route_long_name = r.iloc[0].get("route_long_name", "") if not r.empty else ""
		label_prefix = f"{route_id} ({route_short_name}) – {route_long_name}".strip(" –")

		# parent layer
		route_layer = folium.FeatureGroup(name=label_prefix, show=True)
		route_layer.add_to(m)

		shape_data_for_shape_ids = shapes_data[shapes_data["shape_id"].isin(shape_ids.astype(str))]
		paths = shape_data_for_shape_ids.groupby("shape_id")[["shape_pt_lat", "shape_pt_lon"]].apply(
			lambda g: g[["shape_pt_lat", "shape_pt_lon"]].to_numpy().tolist()
		)

		for sid, latlon in paths.items():
			sublayer = FeatureGroupSubGroup(route_layer, name=f"{label_prefix}", show=default_show)
			sublayer.add_to(m)
			folium.PolyLine(
				latlon,
				weight=3,
				opacity=0.8,
				color=colour,
				tooltip=f"{label_prefix} | shape_id={sid}",
			).add_to(sublayer)

	folium.LayerControl(collapsed=False).add_to(m)

	return m

def add_train_stops_to_map(gtfs: GTFSStatic, *, m: folium.Map = None, display_platforms=False) -> folium.Map:
	stops_copy = gtfs.stops.copy()
	stops_with_location_type = stops_copy.dropna(subset=["location_type"])

	centre = [stops_with_location_type["stop_lat"].mean(), stops_with_location_type["stop_lon"].mean()]
	if m is None:
		m = folium.Map(location=centre, zoom_start=11, tiles="OpenStreetMap")

	for row in stops_with_location_type.itertuples(index=False):
		colour = "blue" if row.location_type_enum == LocationTypeEnum.STATION else "green"
		if not display_platforms and row.location_type_enum == LocationTypeEnum.PLATFORMSTOP:
			continue

		try:
			folium.CircleMarker(
				location=[row.stop_lat, row.stop_lon],
				radius=3,
				color=colour,
				fill=True,
				fill_opacity=0.9,
				tooltip=f"{row.stop_name} ({row.stop_id})"
						+ (f"<br>Parent: {row.parent_station}" if row.parent_station else "")
			).add_to(m)

		except Exception as e:
			print(e)

	return m


def generate_map_by_route(gtfs: GTFSStatic, route_id: str) -> folium.Map:
	route_ids = gtfs.trips["route_id"].dropna().unique()
