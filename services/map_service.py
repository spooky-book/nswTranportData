from concurrent.futures import ProcessPoolExecutor, as_completed

import folium
import numpy as np
from folium.plugins import FeatureGroupSubGroup

from constants import LocationTypeEnum
from loader.loader import GTFSStatic
from common.helpers import pad_hex


# TODO we will need to add the m to the parameters as well
def generate_map_all_routes(gtfs: GTFSStatic, *, tiles="OpenStreetMap", zoom_start=11, default_show=True, parallel=True, decimation_step=None, max_workers=None, m:folium.Map=None) -> folium.Map:
	print("Generating map of all routes")
	shapes = gtfs.shapes.copy()
	trips = gtfs.trips.copy()
	routes = gtfs.routes.copy()

	# Centre
	shapes_sorted = shapes.sort_values(["shape_id", "shape_pt_sequence"])
	centre = [shapes["shape_pt_lat"].mean(), shapes["shape_pt_lon"].mean()]
	if m is None:
		m = folium.Map(location=centre, zoom_start=zoom_start, tiles=tiles)

	# Indices:
	paths_by_shape = _paths_by_shape(shapes_sorted)  # shape_id -> [[lat,lon],...]
	route_to_shapes = _route_to_shapes(trips)  # route_id -> [shape_id, ...]
	route_meta = _route_index(routes)

	# ---------- Build features (optionally in parallel) ----------
	if parallel:
		features = _build_features_parallel(route_to_shapes, paths_by_shape, route_meta,
											decimation_step=decimation_step, max_workers=max_workers)
	else:
		features = []
		for rid, sids in route_to_shapes.items():
			paths = [paths_by_shape[sid] for sid in sids if sid in paths_by_shape]
			if decimation_step and decimation_step > 1:
				paths = [decimate_path(p, decimation_step) for p in paths]
			features.append(_make_route_feature(rid, paths, route_meta.get(rid, {})))

	for feat in features:
		props = feat["properties"]
		label = props.get("label") or props.get("route_id", "route")
		color = props.get("route_color") or ""
		# Parent layer per route
		route_layer = folium.FeatureGroup(name=label, show=default_show)
		route_layer.add_to(m)

		folium.GeoJson(
			feat,
			name=label,
			style_function=lambda _f, _c=color: {"weight": 3, "opacity": 0.8, "color": f"#{_c}" if _c else "#333333"},
			tooltip=folium.GeoJsonTooltip(fields=[], aliases=[], labels=False, sticky=True,  # use property 'label'
										  tooltip=props.get("label", "")),
		).add_to(route_layer)

	folium.LayerControl(collapsed=False).add_to(m)
	return m
# route_id_to_shape_id_map = (
# 		gtfs.trips
# 	   .dropna(subset=["route_id", "shape_id"])
# 	   .groupby("route_id")["shape_id"]
# 	   .unique()
# 	   .to_dict()
# 	)
#
# 	# get all shapes associated with a route id
# 	shapes_by_routes = {}
# 	for route_id, shape_ids in route_id_to_shape_id_map.items():
# 		print(f"creating shape for route {route_id}")
# 		shapes_by_routes[route_id] = gtfs.shapes[gtfs.shapes["shape_id"].isin(shape_ids)]
#
# 	# for every route id and its associated shape ids plot it on the m
# 	for route_id, shape_ids in route_id_to_shape_id_map.items():
# 		print(f"writing route to map for {route_id}")
# 		r = routes_data[routes_data["route_id"] == route_id]
# 		colour = pad_hex(r.iloc[0].get("route_color", None)) if not r.empty else pad_hex(None)
# 		route_short_name = r.iloc[0].get("route_short_name", "") if not r.empty else ""
# 		route_long_name = r.iloc[0].get("route_long_name", "") if not r.empty else ""
# 		label_prefix = f"{route_id} ({route_short_name}) – {route_long_name}".strip(" –")
#
# 		# parent layer
# 		route_layer = folium.FeatureGroup(name=label_prefix, show=True)
# 		route_layer.add_to(m)
#
# 		shape_data_for_shape_ids = shapes_data[shapes_data["shape_id"].isin(shape_ids.astype(str))]
# 		paths = shape_data_for_shape_ids.groupby("shape_id")[["shape_pt_lat", "shape_pt_lon"]].apply(
# 			lambda g: g[["shape_pt_lat", "shape_pt_lon"]].to_numpy().tolist()
# 		)
#
# 		for sid, latlon in paths.items():
# 			sublayer = FeatureGroupSubGroup(route_layer, name=f"{label_prefix}", show=default_show)
# 			sublayer.add_to(m)
# 			folium.PolyLine(
# 				latlon,
# 				weight=3,
# 				opacity=0.8,
# 				color=colour,
# 				tooltip=f"{label_prefix} | shape_id={sid}",
# 			).add_to(sublayer)
#
# 	folium.LayerControl(collapsed=False).add_to(m)

	# return m

_worker_ctx = None

def _init_worker(paths_by_shape, route_meta, decimation_step):
	# Runs once per process
	global _worker_ctx
	_worker_ctx = (paths_by_shape, route_meta, decimation_step)

def _pack_make_feature(rid_sids):
	# Top-level function -> picklable
	rid, sids = rid_sids
	print(f"Starting pack_make_feature for {rid}")
	global _worker_ctx
	paths_by_shape, route_meta, decimation_step = _worker_ctx
	paths = [paths_by_shape.get(sid) for sid in sids]
	paths = [p for p in paths if p is not None]	# for some reason this doesnt work because the sids are strings and not numbers, not sure why this works for the trains but not light rail?
	if decimation_step and decimation_step > 1:
		paths = [decimate_path(p, decimation_step) for p in paths]
	return _make_route_feature(rid, paths, route_meta.get(rid, {}))

def _build_features_parallel(route_to_shape_ids, paths_by_shape, route_meta, *,
							 decimation_step=None, max_workers=None):
	"""Return list of GeoJSON Features, built in parallel using processes."""
	items = list(route_to_shape_ids.items())

	from concurrent.futures import ProcessPoolExecutor
	with ProcessPoolExecutor(
		max_workers=max_workers,
		initializer=_init_worker,
		initargs=(paths_by_shape, route_meta, decimation_step),
	) as ex:
		return list(ex.map(_pack_make_feature, items))

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
	return None

def _paths_by_shape(shapes_df):
	"""Return dict: shape_id -> list[[lat, lon], ...], already ordered."""
	# Convert to Python lists once (no pandas in the hot loop later)
	grp = shapes_df.groupby("shape_id", sort=False)[["shape_pt_lat", "shape_pt_lon"]]
	return {sid: g.to_numpy().tolist() for sid, g in grp}

def _route_index(routes_df):
	"""Return dict: route_id -> dict(color, short_name, long_name)."""
	r = routes_df.copy()
	cols = ["route_color", "route_short_name", "route_long_name"]
	for c in cols:
		if c not in r.columns:
			r[c] = None
	return r.set_index("route_id")[cols].fillna("").to_dict("index")

def _route_to_shapes(trips_df):
	"""Return dict: route_id -> list(shape_id) without duplicates."""
	t = trips_df.dropna(subset=["route_id", "shape_id"])[["route_id", "shape_id"]]
	t = t.astype({"route_id": str, "shape_id": str}).drop_duplicates()
	return t.groupby("route_id")["shape_id"].apply(list).to_dict()

def _swap_latlon_to_lonlat(seq):
	"""Leaflet PolyLine uses [lat, lon], GeoJSON wants [lon, lat]."""
	# seq is [[lat, lon], ...]
	# Use numpy for speed; falls back to Python if needed.
	a = np.asarray(seq, dtype=float)
	return a[:, ::-1].tolist()

def _make_route_feature(route_id, paths_for_route, props):
	lines = [_swap_latlon_to_lonlat(path) for path in paths_for_route]
	feature = {
		"type": "Feature",
		"properties": {
			"route_id": route_id,
			"route_short_name": props.get("route_short_name", ""),
			"route_long_name": props.get("route_long_name", ""),
			"route_color": props.get("route_color", "") or "",
			"label": f'{route_id} ({props.get("route_short_name","")}) – {props.get("route_long_name","")}'.strip(" –"),
		},
		"geometry": {
			"type": "MultiLineString",
			"coordinates": lines,  # lon, lat
		},
	}
	return feature

def decimate_path(path, step=2):
	# path: [[lat,lon], ...] -> keep every Nth point (and always last)
	if step <= 1 or len(path) <= 2:
		return path
	kept = path[::step]
	if kept[-1] != path[-1]:
		kept.append(path[-1])
	return kept