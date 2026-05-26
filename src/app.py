"""
Flask application entry point.

Creates and runs the Flask app with the stations and stops API blueprints.
"""

from flask import Flask

from api.stations import stations_bp
from api.stops import stops_bp
from api.stop_stats import stop_stats_bp
from api.route_stats import route_stats_bp
from api.isochrone import isochrone_bp
from config import FLASK_PORT


def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)

    # Register blueprints
    app.register_blueprint(stations_bp)
    app.register_blueprint(stops_bp)
    app.register_blueprint(stop_stats_bp)
    app.register_blueprint(route_stats_bp)
    app.register_blueprint(isochrone_bp)

    @app.route("/")
    def index():
        return {
            "name": "NSW Transport Data API",
            "version": "0.1.0",
            "endpoints": {
                # Stations endpoint (location_type = 1 only, with smart fallback)
                "stations": "/api/stations",
                "stations_search": "/api/stations?search=<query>",
                "stations_mode": "/api/stations?mode=<transport_mode>",
                # Generic stops endpoint (all location types)
                "stops": "/api/stops",
                "stops_platforms": "/api/stops?location_type=0",
                "stops_stations": "/api/stops?location_type=1",
                "stops_entrances": "/api/stops?location_type=2",
                "stops_search": "/api/stops?search=<query>",
                "stops_mode": "/api/stops?mode=<transport_mode>&location_type=<0-4>",
                # Stop statistics endpoint
                "stop_stats": "POST /api/stop-stats",
                "stop_stats_docs": "See endpoint docstring for full request/response schema",
                # Route statistics endpoint
                "route_stats": "POST /api/route-stats",
                "route_stats_docs": "See endpoint docstring for full request/response schema",
                # Isochrone endpoint
                "isochrone": "POST /api/isochrone",
                "isochrone_docs": "See endpoint docstring for full request/response schema",
            },
        }

    return app


if __name__ == "__main__":
    app = create_app()
    print(f"Starting NSW Transport Data API on port {FLASK_PORT}...")
    app.run(debug=True, port=FLASK_PORT)
