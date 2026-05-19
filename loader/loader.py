import os
import io
import zipfile
from dataclasses import dataclass
from typing import Dict, Optional, List
import pandas as pd
import requests

from constants import LocationTypeEnum

DEFAULT_TABLES = [
	"agency", "stops", "routes", "trips", "stop_times",
	"calendar", "calendar_dates", "shapes", "fare_attributes", "fare_rules"
]

TFNSW_STATIC_URL = "https://api.transport.nsw.gov.au/v1/publictransport/timetables/complete/gtfs"

def download_ttfnsw_gtfs(api_key: Optional[str] = None, dest_path: str = "nsw_gtfs.zip", url: str = TFNSW_STATIC_URL) -> str:
	api_key = api_key or os.getenv("TFNSW_API_KEY")
	if not api_key:
		raise ValueError("Provide api_key or set TFNSW_API_KEY environment variable.")
	headers = {"Authorization": f"apikey {api_key}"}
	resp = requests.get(url, headers=headers, timeout=120)
	resp.raise_for_status()
	with open(dest_path, "wb") as f:
		f.write(resp.content)
	return dest_path

@dataclass
class GTFSStatic:
	tables: Dict[str, pd.DataFrame]

	@property
	def agency(self) -> pd.DataFrame:
		return self.tables.get("agency", pd.DataFrame())

	@property
	def stops(self) -> pd.DataFrame:
		return self.tables.get("stops", pd.DataFrame())

	@property
	def routes(self) -> pd.DataFrame:
		return self.tables.get("routes", pd.DataFrame())

	@property
	def trips(self) -> pd.DataFrame:
		return self.tables.get("trips", pd.DataFrame())

	@property
	def stop_times(self) -> pd.DataFrame:
		return self.tables.get("stop_times", pd.DataFrame())

	@property
	def calendar(self) -> pd.DataFrame:
		return self.tables.get("calendar", pd.DataFrame())

	@property
	def calendar_dates(self) -> pd.DataFrame:
		return self.tables.get("calendar_dates", pd.DataFrame())

	@property
	def shapes(self) -> pd.DataFrame:
		return self.tables.get("shapes", pd.DataFrame())

	@classmethod
	def from_bytes(cls, content: bytes, tables: Optional[List[str]] = None) -> "GTFSStatic":
		tables = tables or DEFAULT_TABLES
		zf = zipfile.ZipFile(io.BytesIO(content))
		loaded = {}
		for name in tables:
			fname = f"{name}.txt"
			if fname in zf.namelist():
				with zf.open(fname) as f:
					try:
						match fname:
							case "shapes.txt":
								usecols = ["shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence", "shape_dist_traveled"]
								dtypes = {"shape_id": "string[pyarrow]", "shape_pt_lat": "float32", "shape_pt_lon": "float32", "shape_pt_sequence": "int32", "shape_dist_traveled": "float32"}
								df = pd.read_csv(f, usecols=usecols, dtype=dtypes, engine="pyarrow")
								df["shape_id"] = df["shape_id"].astype("category")
								df = df.sort_values(["shape_id", "shape_pt_sequence"])
							case _:
								df = pd.read_csv(f, dtype=str, low_memory=False)

					except UnicodeDecodeError:
						f.seek(0)
						df = pd.read_csv(f, dtype=str, encoding="latin1", low_memory=False)
				loaded[name] = cls._normalise_table(name, df)

		return cls(loaded)

	@staticmethod
	def _normalise_table(name: str, df: pd.DataFrame) -> pd.DataFrame:
		match name:
			case "stops":
				df["stop_lat"] = pd.to_numeric(df["stop_lat"], errors="coerce")
				df["stop_lon"] = pd.to_numeric(df["stop_lon"], errors="coerce")
				df["location_type_enum"] = pd.to_numeric(df["location_type"], errors="coerce").map(LocationTypeEnum, na_action="ignore")
			case "stop_times":
				df["stop_sequence"] = pd.to_numeric(df.get("stop_sequence"), errors="coerce")

		return df

	def search_stops(self, query: str, limit: int = 50) -> pd.DataFrame:
		if self.stops.empty:
			return pd.DataFrame()
		mask = self.stops.get("stop_name", pd.Series(dtype=str)).str.contains(query, case=False, na=False)
		return self.stops[mask].head(limit).copy()

	def routes_by_agency(self, agency_id: Optional[str] = None, limit: int = 50) -> pd.DataFrame:
		if self.routes.empty:
			return pd.DataFrame()
		df = self.routes
		if agency_id is not None and "agency_id" in df.columns:
			df = df[df["agency_id"] == agency_id]
		return df.head(limit)

	def trips_for_route(self, route_id: str, limit: int = 20) -> pd.DataFrame:
		if self.trips.empty:
			return pd.DataFrame()
		df = self.trips
		if "route_id" in df.columns:
			df = df[df["route_id"] == route_id]
		return df.head(limit)

	def stop_times_for_trip(self, trip_id: str) -> pd.DataFrame:
		if self.stop_times.empty:
			return pd.DataFrame()
		df = self.stop_times
		if "trip_id" in df.columns:
			df = df[df["trip_id"] == trip_id]
		if "stop_sequence" in df.columns:
			try:
				df = df.assign(_seq=pd.to_numeric(df["stop_sequence"], errors="coerce")).sort_values("_seq").drop(columns=["_seq"])
			except Exception:
				pass
		return df.reset_index(drop=True)
