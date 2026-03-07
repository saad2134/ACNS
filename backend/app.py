"""
Flask Application Entry Point
==============================
Registers the accessible routing blueprint and initializes Firebase.

Usage:
    1. Set env vars:  FIREBASE_CRED_PATH, FIREBASE_DB_URL
    2. Run:           python app.py
    3. Or:            flask run
"""

import os

from dotenv import load_dotenv
load_dotenv()  # Load .env file (Firebase creds, Twilio keys, etc.)

from flask import Flask
from flask_cors import CORS

from routing import routing_bp, init_firebase
from issues import issues_bp


def create_app() -> Flask:
    app = Flask(__name__)
    CORS(app)  # Allow frontend to call the API

    # ---- Firebase setup ----
    cred_path = os.environ.get(
        "FIREBASE_CRED_PATH", "serviceAccountKey.json"
    )
    db_url = os.environ.get(
        "FIREBASE_DB_URL",
        "https://your-project-id.firebaseio.com",  # <-- replace this
    )
    init_firebase(cred_path, db_url)

    # ---- Register blueprints ----
    app.register_blueprint(routing_bp)
    app.register_blueprint(issues_bp)

    # ---- Health check ----
    @app.route("/")
    def health():
        return {"status": "ok", "service": "accessible-routing-api"}

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, host="0.0.0.0", port=5000)
