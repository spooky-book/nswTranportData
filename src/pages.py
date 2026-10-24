"""
HTML pages blueprint.

Serves the browser UI (no URL prefix):
- GET /               home page linking to every page and the JSON API
- GET /map/transport  train and metro stations and lines (data from /api/rail-network)
- GET /map/isochrone  isochrone explorer (data from /api/isochrone and /api/network)
- GET /api/map        old isochrone URL, redirects to /map/isochrone
"""

from flask import Blueprint, redirect, render_template, url_for

pages_bp = Blueprint("pages", __name__)


@pages_bp.route("/", methods=["GET"])
def home():
    return render_template("home.html")


@pages_bp.route("/map/transport", methods=["GET"])
def transport_map():
    return render_template("transport_map.html")


@pages_bp.route("/map/isochrone", methods=["GET"])
def isochrone_map():
    return render_template("isochrone_map.html")


@pages_bp.route("/api/map", methods=["GET"])
def legacy_isochrone_map():
    return redirect(url_for("pages.isochrone_map"), code=301)
