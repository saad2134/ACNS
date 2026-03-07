"""
Flask Application Entry Point
==============================
Registers all blueprints and initializes Firebase.

Usage:
    1. Copy .env.example -> .env and fill in your values
    2. Run:  python app.py
    3. Or:   flask run
"""

import os

from dotenv import load_dotenv
load_dotenv()  # Load .env file (Firebase creds, Twilio keys, etc.)

from flask import Flask, jsonify, request
from flask_cors import CORS
from firebase_admin import db as fdb

from routing import routing_bp, init_firebase, fetch_nodes_from_firebase, a_star, find_nearest_node
from issues import issues_bp


# ---------------------------------------------------------------------------
# Location name -> coordinates lookup
# Used by the frontend which sends building names, not lat/lon
# ---------------------------------------------------------------------------
CAMPUS_LOCATIONS = {
    "Main Library":         {"lat": 35.2062, "lon": -97.4463, "node": "node_002"},
    "Science Building":     {"lat": 35.2058, "lon": -97.4457, "node": "node_001"},
    "Student Center":       {"lat": 35.2070, "lon": -97.4471, "node": "node_004"},
    "Engineering Hall":     {"lat": 35.2050, "lon": -97.4480, "node": "node_005"},
    "Arts Building":        {"lat": 35.2075, "lon": -97.4450, "node": "node_007"},
    "Sports Complex":       {"lat": 35.2040, "lon": -97.4495, "node": "node_010"},
    "Parking Garage A":     {"lat": 35.2045, "lon": -97.4490, "node": "node_006"},
    "Dormitory West":       {"lat": 35.2051, "lon": -97.4481, "node": "node_009"},
    "Administration Block": {"lat": 35.2074, "lon": -97.4448, "node": "node_008"},
    "Cafeteria":            {"lat": 35.2059, "lon": -97.4456, "node": "node_003"},
}

# Frontend issue types -> backend categories
ISSUE_TYPE_TO_CATEGORY = {
    "Broken Elevator":          "equipment_malfunction",
    "Blocked Ramp":             "obstruction",
    "Narrow Passage":           "missing_feature",
    "Construction Obstruction": "obstruction",
    "Damaged Pathway":          "structural_damage",
}


def create_app() -> Flask:
    app = Flask(__name__)
    CORS(app)  # Allow frontend to call the API

    # ---- Firebase setup ----
    cred_path = os.environ.get(
        "FIREBASE_CRED_PATH", "serviceAccountKey.json"
    )
    db_url = os.environ.get(
        "FIREBASE_DB_URL",
        "https://your-project-id.firebaseio.com",  # <-- replace in .env
    )
    init_firebase(cred_path, db_url)

    # ---- Register blueprints ----
    app.register_blueprint(routing_bp)
    app.register_blueprint(issues_bp)

    # ---- Health check ----
    @app.route("/")
    def health():
        return {"status": "ok", "service": "accessible-routing-api"}

    # ================================================================
    # Frontend-compatible endpoints
    # ================================================================

    # --- POST /api/route (accepts building names from frontend) ---
    @app.route("/api/route", methods=["POST"])
    def frontend_route():
        """
        Accepts {start, destination} as building names from the frontend.
        Maps them to coordinates and runs A*.
        Returns the path with a GeoJSON LineString for the map.
        """
        data = request.get_json(force=True)

        start_name = data.get("start", "")
        dest_name = data.get("destination", "")

        start_loc = CAMPUS_LOCATIONS.get(start_name)
        dest_loc = CAMPUS_LOCATIONS.get(dest_name)

        if not start_loc:
            return jsonify({"success": False, "message": f"Unknown start location: {start_name}"}), 400
        if not dest_loc:
            return jsonify({"success": False, "message": f"Unknown destination: {dest_name}"}), 400

        nodes = fetch_nodes_from_firebase()
        if not nodes:
            return jsonify({"success": False, "message": "No nodes in database."}), 500

        # Use known node IDs if available, else find nearest
        start_id = start_loc.get("node") or find_nearest_node(start_loc["lat"], start_loc["lon"], nodes)
        end_id = dest_loc.get("node") or find_nearest_node(dest_loc["lat"], dest_loc["lon"], nodes)

        result = a_star(start_id, end_id, nodes)

        # Build a GeoJSON LineString for the Mapbox map
        if result["success"] and result["path_details"]:
            coordinates = [
                [d["longitude"], d["latitude"]] for d in result["path_details"]
            ]
            result["route"] = {
                "type": "LineString",
                "coordinates": coordinates,
            }

        status_code = 200 if result["success"] else 404
        return jsonify(result), status_code

    # --- POST /api/reportIssue (frontend form format) ---
    @app.route("/api/reportIssue", methods=["POST"])
    def frontend_report_issue():
        """
        Accepts the frontend IssueForm's FormData or JSON:
          { location: "Science Building", issueType: "Broken Elevator" }
        Maps it to the backend's issue format and saves.
        """
        # Handle both FormData and JSON
        if request.content_type and "multipart/form-data" in request.content_type:
            location = request.form.get("location", "")
            issue_type = request.form.get("issueType", "")
        else:
            data = request.get_json(force=True)
            location = data.get("location", "")
            issue_type = data.get("issueType", "")

        # Map location name to coordinates
        loc_data = CAMPUS_LOCATIONS.get(location, {})
        lat = loc_data.get("lat", 35.2058)
        lon = loc_data.get("lon", -97.4457)

        # Map frontend issue type to backend category
        category = ISSUE_TYPE_TO_CATEGORY.get(issue_type, "other")

        # Build backend-compatible issue payload
        issue_data = {
            "title": f"{issue_type} at {location}",
            "description": f"{issue_type} reported at {location}.",
            "category": category,
            "severity": "medium",
            "latitude": lat,
            "longitude": lon,
            "building": location,
            "reported_by": "anonymous",
        }

        # Delegate to the existing issues blueprint logic
        from issues import _validate_issue, _find_duplicate_issue, _save_issue_to_firebase, _award_report_points

        errors = _validate_issue(issue_data)
        if errors:
            return jsonify({"success": False, "errors": errors}), 400

        dup = _find_duplicate_issue(issue_data)
        if dup:
            return jsonify({
                "success": False,
                "duplicate": True,
                "existing_report_id": dup.get("report_id"),
                "message": "A similar open issue already exists nearby.",
            }), 409

        try:
            report_id = _save_issue_to_firebase(issue_data)
        except Exception as exc:
            return jsonify({"success": False, "message": str(exc)}), 500

        _award_report_points("anonymous", report_id)

        return jsonify({
            "success": True,
            "report_id": report_id,
            "message": "Issue reported successfully!",
        }), 201

    # --- GET /api/leaderboard ---
    @app.route("/api/leaderboard", methods=["GET"])
    def get_leaderboard():
        """
        Returns the leaderboard from Firebase gamification data.
        Format: { leaderboard: [{ rank, username, points }, ...] }
        """
        try:
            ref = fdb.reference("gamification/user_points")
            data = ref.get() or {}

            # 'data' is a dict of { user_id: { ... } }
            users = list(data.values())
            # Sort by total_points descending
            users.sort(key=lambda u: u.get("total_points", 0), reverse=True)

            leaderboard = []
            for i, entry in enumerate(users):
                leaderboard.append({
                    "rank": i + 1,
                    "username": entry.get("display_name", entry.get("user_id", "Unknown")),
                    "points": entry.get("total_points", 0),
                })

            return jsonify({"leaderboard": leaderboard}), 200

        except Exception as exc:
            return jsonify({"leaderboard": [], "error": str(exc)}), 200

    # --- POST /api/login (simple placeholder) ---
    @app.route("/api/login", methods=["POST"])
    def login():
        """
        Simple login placeholder.
        Accepts { username, password } and returns a success token.
        In a real app, this would validate against Firebase Auth.
        """
        data = request.get_json(force=True)
        username = data.get("username", "")
        password = data.get("password", "")

        if not username or not password:
            return jsonify({"success": False, "message": "Username and password required."}), 400

        # Placeholder: accept any login for hackathon demo
        return jsonify({
            "success": True,
            "user_id": username,
            "display_name": username,
            "message": "Login successful.",
        }), 200

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, host="0.0.0.0", port=5000)
