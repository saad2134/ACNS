"""
Issue Reporting Module
======================
Flask blueprint that handles crowdsourced accessibility issue reports.

Workflow:
  1. Frontend POSTs a new issue (type, coordinates, description, optional image).
  2. The issue is saved to Firebase Realtime Database under `issue_reports/`.
  3. A WhatsApp message is sent to the supervisor via Twilio's WhatsApp API.

Environment variables required:
  TWILIO_ACCOUNT_SID      — Twilio Account SID
  TWILIO_AUTH_TOKEN        — Twilio Auth Token
  TWILIO_WHATSAPP_FROM    — Twilio sandbox/sender number  (e.g. "whatsapp:+14155238886")
  SUPERVISOR_WHATSAPP_TO  — Supervisor's WhatsApp number  (e.g. "whatsapp:+919876543210")
"""

import logging
import math
import os
import uuid
from datetime import datetime, timezone
from threading import Thread

from firebase_admin import db
from flask import Blueprint, jsonify, request
from twilio.rest import Client as TwilioClient

# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------
issues_bp = Blueprint("issues", __name__)

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Twilio Configuration (lazy-loaded from env vars)
# ---------------------------------------------------------------------------
_twilio_client: TwilioClient | None = None


def _get_twilio_client() -> TwilioClient:
    """Return a cached Twilio client, initializing on first call."""
    global _twilio_client
    if _twilio_client is None:
        sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
        token = os.environ.get("TWILIO_AUTH_TOKEN", "")
        if not sid or not token:
            raise RuntimeError(
                "TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN environment "
                "variables must be set for WhatsApp notifications."
            )
        _twilio_client = TwilioClient(sid, token)
    return _twilio_client


# ---------------------------------------------------------------------------
# Validation Helpers
# ---------------------------------------------------------------------------
VALID_CATEGORIES = {
    "structural_damage",
    "equipment_malfunction",
    "missing_feature",
    "hazard",
    "lighting",
    "wear_and_tear",
    "obstruction",
    "other",
}

VALID_SEVERITIES = {"low", "medium", "high", "critical"}


def _validate_issue(data: dict) -> list[str]:
    """Return a list of validation error messages (empty = valid)."""
    errors = []

    if not data.get("title"):
        errors.append("'title' is required.")
    if not data.get("description"):
        errors.append("'description' is required.")
    if not data.get("category"):
        errors.append("'category' is required.")
    elif data["category"] not in VALID_CATEGORIES:
        errors.append(
            f"'category' must be one of: {', '.join(sorted(VALID_CATEGORIES))}"
        )

    severity = data.get("severity", "medium")
    if severity not in VALID_SEVERITIES:
        errors.append(
            f"'severity' must be one of: {', '.join(sorted(VALID_SEVERITIES))}"
        )

    if data.get("latitude") is None or data.get("longitude") is None:
        errors.append("'latitude' and 'longitude' are required.")

    return errors


# ---------------------------------------------------------------------------
# Duplicate Detection
# ---------------------------------------------------------------------------
def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters between two GPS points."""
    R = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _find_duplicate_issue(data: dict, radius_m: float = 50.0) -> dict | None:
    """
    Check Firebase for an existing *open* issue that matches on
    title (case-insensitive) + category + location within `radius_m` meters.
    Returns the existing report dict if found, else None.
    """
    ref = db.reference("issue_reports")
    snapshot: dict = ref.get() or {}

    new_title = (data.get("title") or "").strip().lower()
    new_cat = data.get("category", "")
    new_lat = data.get("latitude", 0.0)
    new_lon = data.get("longitude", 0.0)

    for report_id, report in snapshot.items():
        # Only match against unresolved issues
        if report.get("status") == "resolved":
            continue

        if (report.get("title") or "").strip().lower() != new_title:
            continue
        if report.get("category") != new_cat:
            continue

        loc = report.get("location", {})
        dist = _haversine_m(
            new_lat, new_lon,
            loc.get("latitude", 0.0), loc.get("longitude", 0.0),
        )
        if dist <= radius_m:
            return report  # Duplicate found

    return None


# ---------------------------------------------------------------------------
# Firebase Persistence
# ---------------------------------------------------------------------------
def _save_issue_to_firebase(issue: dict) -> str:
    """
    Save an issue report to Firebase Realtime Database.

    Returns the generated report_id.
    """
    report_id = f"report_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()

    record = {
        "report_id": report_id,
        "title": issue["title"],
        "description": issue["description"],
        "category": issue["category"],
        "severity": issue.get("severity", "medium"),
        "location": {
            "latitude": issue["latitude"],
            "longitude": issue["longitude"],
            "building": issue.get("building", ""),
            "floor": issue.get("floor", 0),
            "campus_zone": issue.get("campus_zone", ""),
            "related_node_id": issue.get("related_node_id", ""),
        },
        "image_url": issue.get("image_url", ""),
        "status": "open",
        "reported_by": issue.get("reported_by", "anonymous"),
        "assigned_to": None,
        "upvotes": 0,
        "upvoted_by": [],
        "created_at": now,
        "updated_at": now,
        "resolved_at": None,
    }

    ref = db.reference(f"issue_reports/{report_id}")
    ref.set(record)
    logger.info("Issue %s saved to Firebase.", report_id)

    return report_id


# ---------------------------------------------------------------------------
# WhatsApp Notification via Twilio
# ---------------------------------------------------------------------------
def _build_whatsapp_message(issue: dict, report_id: str) -> str:
    """Build a human-readable WhatsApp alert for the supervisor."""
    severity_emoji = {
        "low": "🟢",
        "medium": "🟡",
        "high": "🟠",
        "critical": "🔴",
    }
    sev = issue.get("severity", "medium")
    emoji = severity_emoji.get(sev, "⚪")

    lines = [
        f"🚨 *New Accessibility Issue Reported*",
        f"",
        f"{emoji} *Severity:* {sev.upper()}",
        f"📌 *Title:* {issue['title']}",
        f"📝 *Description:* {issue['description']}",
        f"🏷️ *Category:* {issue['category'].replace('_', ' ').title()}",
        f"📍 *Location:* ({issue['latitude']}, {issue['longitude']})",
    ]

    if issue.get("building"):
        lines.append(f"🏢 *Building:* {issue['building']}")
    if issue.get("floor") is not None:
        lines.append(f"🔢 *Floor:* {issue['floor']}")
    if issue.get("image_url"):
        lines.append(f"🖼️ *Photo:* {issue['image_url']}")

    lines.extend([
        f"",
        f"🆔 *Report ID:* {report_id}",
        f"👤 *Reported by:* {issue.get('reported_by', 'anonymous')}",
        f"🕐 *Time:* {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
    ])

    return "\n".join(lines)


def _send_whatsapp_notification(issue: dict, report_id: str) -> dict:
    """
    Send a WhatsApp message to the supervisor via Twilio.

    Returns a dict with 'success', 'message_sid' (or 'error').
    """
    from_number = os.environ.get(
        "TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886"
    )
    to_number = os.environ.get(
        "SUPERVISOR_WHATSAPP_TO", "whatsapp:+919876543210"
    )

    body = _build_whatsapp_message(issue, report_id)

    try:
        client = _get_twilio_client()
        message = client.messages.create(
            body=body,
            from_=from_number,
            to=to_number,
        )
        logger.info(
            "WhatsApp notification sent — SID: %s", message.sid
        )
        return {"success": True, "message_sid": message.sid}

    except Exception as exc:
        logger.error("WhatsApp notification failed: %s", exc)
        return {"success": False, "error": str(exc)}


def _send_whatsapp_async(issue: dict, report_id: str) -> None:
    """Fire-and-forget WhatsApp notification in a background thread."""
    thread = Thread(
        target=_send_whatsapp_notification,
        args=(issue, report_id),
        daemon=True,
    )
    thread.start()


# ---------------------------------------------------------------------------
# Flask API Endpoints
# ---------------------------------------------------------------------------
@issues_bp.route("/api/issues", methods=["POST"])
def report_issue():
    """
    Submit a new accessibility issue report.

    **POST JSON body:**
    ```json
    {
      "title":            "Broken handrail on east ramp",
      "description":      "Left handrail is loose and wobbling, unsafe for ...",
      "category":         "structural_damage",
      "severity":         "high",
      "latitude":         35.2058,
      "longitude":        -97.4457,
      "building":         "Science Building",
      "floor":            0,
      "campus_zone":      "central",
      "related_node_id":  "node_001",
      "image_url":        "https://firebasestorage.example.com/...",
      "reported_by":      "user_042"
    }
    ```

    **Required fields:** title, description, category, latitude, longitude
    **Optional fields:** severity (default: "medium"), building, floor,
                         campus_zone, related_node_id, image_url, reported_by

    **Response (201):**
    ```json
    {
      "success": true,
      "report_id": "report_a1b2c3d4",
      "message": "Issue reported successfully. Supervisor notified.",
      "whatsapp_status": "sent"
    }
    ```
    """
    data = request.get_json(force=True)

    # ---- Validate ----
    errors = _validate_issue(data)
    if errors:
        return jsonify({
            "success": False,
            "errors": errors,
            "message": "Validation failed.",
        }), 400

    # ---- Duplicate check ----
    existing = _find_duplicate_issue(data)
    if existing:
        return jsonify({
            "success": False,
            "duplicate": True,
            "existing_report_id": existing.get("report_id"),
            "message": "A similar open issue already exists nearby.",
        }), 409

    # ---- Save to Firebase ----
    try:
        report_id = _save_issue_to_firebase(data)
    except Exception as exc:
        logger.error("Firebase save failed: %s", exc)
        return jsonify({
            "success": False,
            "message": f"Failed to save issue: {exc}",
        }), 500

    # ---- Send WhatsApp notification (non-blocking) ----
    whatsapp_status = "skipped"
    twilio_configured = bool(
        os.environ.get("TWILIO_ACCOUNT_SID")
        and os.environ.get("TWILIO_AUTH_TOKEN")
    )

    if twilio_configured:
        _send_whatsapp_async(data, report_id)
        whatsapp_status = "sent"
    else:
        logger.warning(
            "Twilio credentials not configured — WhatsApp notification "
            "skipped for report %s.",
            report_id,
        )
        whatsapp_status = "skipped_no_credentials"

    # ---- Award gamification points (fire & forget) ----
    _award_report_points(data.get("reported_by", "anonymous"), report_id)

    return jsonify({
        "success": True,
        "report_id": report_id,
        "message": "Issue reported successfully. Supervisor notified."
                   if whatsapp_status == "sent"
                   else "Issue reported successfully. WhatsApp notification skipped (Twilio not configured).",
        "whatsapp_status": whatsapp_status,
    }), 201


@issues_bp.route("/api/issues", methods=["GET"])
def list_issues():
    """
    List all issue reports, optionally filtered.

    **Query params:**
      ?status=open           — filter by status (open | in_progress | resolved)
      ?category=hazard       — filter by category
      ?severity=critical     — filter by severity
      ?node_id=node_001      — filter by related infrastructure node
    """
    ref = db.reference("issue_reports")
    snapshot: dict = ref.get() or {}

    # Apply filters
    status_filter = request.args.get("status")
    category_filter = request.args.get("category")
    severity_filter = request.args.get("severity")
    node_filter = request.args.get("node_id")

    results = []
    for report_id, report in snapshot.items():
        if status_filter and report.get("status") != status_filter:
            continue
        if category_filter and report.get("category") != category_filter:
            continue
        if severity_filter and report.get("severity") != severity_filter:
            continue
        if node_filter:
            loc = report.get("location", {})
            if loc.get("related_node_id") != node_filter:
                continue
        results.append(report)

    # Sort newest first
    results.sort(key=lambda r: r.get("created_at", ""), reverse=True)

    return jsonify({"count": len(results), "issues": results}), 200


@issues_bp.route("/api/issues/<report_id>", methods=["GET"])
def get_issue(report_id: str):
    """Fetch a single issue report by ID."""
    ref = db.reference(f"issue_reports/{report_id}")
    report = ref.get()
    if not report:
        return jsonify({"error": f"Report '{report_id}' not found."}), 404
    return jsonify(report), 200


@issues_bp.route("/api/issues/<report_id>/upvote", methods=["POST"])
def upvote_issue(report_id: str):
    """
    Upvote an issue report.

    **POST JSON body:**
    ```json
    { "user_id": "user_042" }
    ```
    """
    data = request.get_json(force=True)
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "'user_id' is required."}), 400

    ref = db.reference(f"issue_reports/{report_id}")
    report = ref.get()
    if not report:
        return jsonify({"error": f"Report '{report_id}' not found."}), 404

    upvoted_by = report.get("upvoted_by", [])
    if user_id in upvoted_by:
        return jsonify({
            "success": False,
            "message": "User has already upvoted this report.",
        }), 409

    upvoted_by.append(user_id)
    ref.update({
        "upvotes": len(upvoted_by),
        "upvoted_by": upvoted_by,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })

    return jsonify({
        "success": True,
        "upvotes": len(upvoted_by),
        "message": "Upvote recorded.",
    }), 200


@issues_bp.route("/api/issues/<report_id>/status", methods=["PATCH"])
def update_issue_status(report_id: str):
    """
    Update the status of an issue report.

    **PATCH JSON body:**
    ```json
    {
      "status": "in_progress",
      "assigned_to": "maintenance_team_A"
    }
    ```
    """
    data = request.get_json(force=True)
    new_status = data.get("status")
    if new_status not in {"open", "in_progress", "resolved"}:
        return jsonify({
            "error": "'status' must be one of: open, in_progress, resolved.",
        }), 400

    ref = db.reference(f"issue_reports/{report_id}")
    report = ref.get()
    if not report:
        return jsonify({"error": f"Report '{report_id}' not found."}), 404

    now = datetime.now(timezone.utc).isoformat()
    updates = {
        "status": new_status,
        "updated_at": now,
    }

    if data.get("assigned_to"):
        updates["assigned_to"] = data["assigned_to"]

    if new_status == "resolved":
        updates["resolved_at"] = now

    ref.update(updates)

    # Notify supervisor when status changes
    twilio_configured = bool(
        os.environ.get("TWILIO_ACCOUNT_SID")
        and os.environ.get("TWILIO_AUTH_TOKEN")
    )
    if twilio_configured and new_status == "resolved":
        _send_resolution_whatsapp_async(report, report_id)

    return jsonify({
        "success": True,
        "report_id": report_id,
        "new_status": new_status,
        "message": f"Status updated to '{new_status}'.",
    }), 200


# ---------------------------------------------------------------------------
# Resolution Notification
# ---------------------------------------------------------------------------
def _send_resolution_whatsapp_async(report: dict, report_id: str) -> None:
    """Send a WhatsApp message when an issue is resolved."""
    def _send():
        from_number = os.environ.get(
            "TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886"
        )
        to_number = os.environ.get(
            "SUPERVISOR_WHATSAPP_TO", "whatsapp:+919876543210"
        )
        body = (
            f"✅ *Issue Resolved*\n\n"
            f"🆔 *Report ID:* {report_id}\n"
            f"📌 *Title:* {report.get('title', 'N/A')}\n"
            f"🕐 *Resolved at:* "
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )
        try:
            client = _get_twilio_client()
            client.messages.create(body=body, from_=from_number, to=to_number)
            logger.info("Resolution WhatsApp sent for %s", report_id)
        except Exception as exc:
            logger.error("Resolution WhatsApp failed: %s", exc)

    Thread(target=_send, daemon=True).start()


# ---------------------------------------------------------------------------
# Gamification Hook
# ---------------------------------------------------------------------------
def _award_report_points(user_id: str, report_id: str) -> None:
    """
    Award gamification points for submitting a report.
    Updates the user's points in Firebase (fire-and-forget).
    """
    if user_id == "anonymous":
        return

    def _award():
        try:
            user_ref = db.reference(f"gamification/user_points/{user_id}")
            user_data = user_ref.get()

            points_to_award = 10  # matches points_config.report_submitted

            if user_data:
                new_total = user_data.get("total_points", 0) + points_to_award
                history = user_data.get("points_history", [])
                history.append({
                    "points": points_to_award,
                    "action": "report_submitted",
                    "reference_id": report_id,
                    "description": "Submitted a new issue report",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                user_ref.update({
                    "total_points": new_total,
                    "points_history": history,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                logger.info(
                    "Awarded %d points to %s (total: %d)",
                    points_to_award, user_id, new_total,
                )
            else:
                # Create a minimal profile for new users
                user_ref.set({
                    "user_id": user_id,
                    "display_name": user_id,
                    "total_points": points_to_award,
                    "level": 1,
                    "rank": "Newcomer",
                    "badges": [],
                    "points_history": [{
                        "points": points_to_award,
                        "action": "report_submitted",
                        "reference_id": report_id,
                        "description": "Submitted a new issue report",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }],
                    "streak_days": 1,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                logger.info(
                    "Created new user profile for %s with %d points.",
                    user_id, points_to_award,
                )
        except Exception as exc:
            logger.error("Gamification update failed for %s: %s", user_id, exc)

    Thread(target=_award, daemon=True).start()
