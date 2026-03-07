"""
Accessible Routing Engine
=========================
A* pathfinding algorithm for the accessibility navigation app.
Fetches infrastructure nodes from Firebase Realtime Database and calculates
the optimal accessible path between two coordinates.

Accessibility weighting:
  - Ramps:     cost multiplier = 1.0x  (preferred)
  - Elevators: cost multiplier = 1.2x  (preferred, slight wait penalty)
  - Stairs:    cost multiplier = 50.0x (heavily penalized)
  - Nodes under maintenance: cost multiplier = 100.0x

When `avoid_stairs=True` (default), stair nodes are completely excluded
from the graph and will never appear in the route.
"""

import heapq
import math
from dataclasses import dataclass, field
from typing import Any

import firebase_admin
from firebase_admin import credentials, db
from flask import Blueprint, jsonify, request

# ---------------------------------------------------------------------------
# Blueprint — register this in your main Flask app via app.register_blueprint()
# ---------------------------------------------------------------------------
routing_bp = Blueprint("routing", __name__)

# ---------------------------------------------------------------------------
# Firebase Initialization Helper
# ---------------------------------------------------------------------------
_firebase_initialized = False


def init_firebase(cred_path: str, database_url: str) -> None:
    """Initialize Firebase Admin SDK (safe to call multiple times)."""
    global _firebase_initialized
    if not _firebase_initialized:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred, {"databaseURL": database_url})
        _firebase_initialized = True


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------
@dataclass
class Node:
    """Represents a single infrastructure node from Firebase."""
    node_id: str
    node_type: str          # "ramp" | "elevator" | "stairs"
    name: str
    latitude: float
    longitude: float
    building: str
    floor: int
    campus_zone: str
    status: str             # "active" | "maintenance"
    connected_nodes: list
    wheelchair_accessible: bool = True
    raw: dict = field(default_factory=dict, repr=False)


# ---------------------------------------------------------------------------
# Cost Configuration
# ---------------------------------------------------------------------------
# Multipliers applied to the geographic distance to form the edge cost.
# Lower = cheaper = preferred by the algorithm.
NODE_TYPE_COST_MULTIPLIER = {
    "ramp":     1.0,    # Best option, zero penalty
    "elevator": 1.2,    # Excellent option, marginal wait-time penalty
    "stairs":   50.0,   # Heavily penalized when not fully avoided
}

MAINTENANCE_COST_MULTIPLIER = 100.0  # Nodes under maintenance


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------
def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Return the great-circle distance in **meters** between two GPS points
    using the Haversine formula.
    """
    R = 6_371_000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _parse_node(node_id: str, data: dict) -> Node:
    """Convert a raw Firebase dict into a Node dataclass."""
    loc = data.get("location", {})
    acc = data.get("accessibility", {})
    return Node(
        node_id=node_id,
        node_type=data.get("type", "unknown"),
        name=data.get("name", ""),
        latitude=loc.get("latitude", 0.0),
        longitude=loc.get("longitude", 0.0),
        building=loc.get("building", ""),
        floor=loc.get("floor", 0),
        campus_zone=loc.get("campus_zone", ""),
        status=data.get("status", "active"),
        connected_nodes=data.get("connected_nodes", []),
        wheelchair_accessible=acc.get("wheelchair_accessible", True),
        raw=data,
    )


# ---------------------------------------------------------------------------
# Firebase Data Fetching
# ---------------------------------------------------------------------------
def fetch_nodes_from_firebase() -> dict[str, Node]:
    """
    Pull all infrastructure nodes from Firebase Realtime Database.
    Returns a dict mapping node_id -> Node.
    """
    ref = db.reference("infrastructure_nodes")
    snapshot = ref.get() or {}
    return {nid: _parse_node(nid, ndata) for nid, ndata in snapshot.items()}


# ---------------------------------------------------------------------------
# A* Pathfinding Algorithm
# ---------------------------------------------------------------------------
def find_nearest_node(
    lat: float, lon: float, nodes: dict[str, Node]
) -> str | None:
    """Return the node_id of the node closest to the given coordinates."""
    best_id, best_dist = None, float("inf")
    for nid, node in nodes.items():
        d = haversine(lat, lon, node.latitude, node.longitude)
        if d < best_dist:
            best_id, best_dist = nid, d
    return best_id


def _edge_cost(
    from_node: Node,
    to_node: Node,
    avoid_stairs: bool,
    wheelchair_mode: bool,
) -> float | None:
    """
    Compute the traversal cost from `from_node` to `to_node`.
    Returns None if the edge is impassable (node should be skipped entirely).
    """
    # ---- Hard exclusions ----
    if avoid_stairs and to_node.node_type == "stairs":
        return None  # Completely blocked

    if wheelchair_mode and not to_node.wheelchair_accessible:
        return None  # Cannot traverse

    # ---- Base cost = geographic distance in meters ----
    base = haversine(
        from_node.latitude, from_node.longitude,
        to_node.latitude, to_node.longitude,
    )

    # ---- Apply node-type multiplier ----
    multiplier = NODE_TYPE_COST_MULTIPLIER.get(to_node.node_type, 5.0)

    # ---- Maintenance penalty ----
    if to_node.status == "maintenance":
        multiplier *= MAINTENANCE_COST_MULTIPLIER

    return base * multiplier


def a_star(
    start_id: str,
    goal_id: str,
    nodes: dict[str, Node],
    avoid_stairs: bool = True,
    wheelchair_mode: bool = False,
) -> dict[str, Any]:
    """
    A* search over the infrastructure graph.

    Parameters
    ----------
    start_id : str
        Node ID of the starting node.
    goal_id : str
        Node ID of the destination node.
    nodes : dict[str, Node]
        All infrastructure nodes keyed by node_id.
    avoid_stairs : bool
        If True (default), stair nodes are completely excluded.
    wheelchair_mode : bool
        If True, nodes without wheelchair_accessible=True are excluded.

    Returns
    -------
    dict with keys:
        success     : bool
        path        : list[str]            — ordered node IDs
        path_details: list[dict]           — metadata per node in path
        total_cost  : float                — weighted cost of entire route
        distance_m  : float                — real-world distance in meters
        message     : str
    """
    if start_id not in nodes:
        return _fail(f"Start node '{start_id}' not found in database.")
    if goal_id not in nodes:
        return _fail(f"Goal node '{goal_id}' not found in database.")
    if start_id == goal_id:
        node = nodes[start_id]
        return _success([start_id], nodes, 0.0, 0.0)

    goal_node = nodes[goal_id]

    # Priority queue: (f_score, counter, node_id)
    counter = 0
    open_set: list[tuple[float, int, str]] = []
    heapq.heappush(open_set, (0.0, counter, start_id))

    came_from: dict[str, str] = {}
    g_score: dict[str, float] = {start_id: 0.0}
    f_score: dict[str, float] = {
        start_id: _heuristic(nodes[start_id], goal_node)
    }
    closed: set[str] = set()

    while open_set:
        _, _, current_id = heapq.heappop(open_set)

        if current_id == goal_id:
            path = _reconstruct_path(came_from, current_id)
            dist = _compute_real_distance(path, nodes)
            return _success(path, nodes, g_score[goal_id], dist)

        if current_id in closed:
            continue
        closed.add(current_id)

        current_node = nodes[current_id]

        for neighbor_id in current_node.connected_nodes:
            if neighbor_id not in nodes or neighbor_id in closed:
                continue

            neighbor_node = nodes[neighbor_id]
            cost = _edge_cost(
                current_node, neighbor_node, avoid_stairs, wheelchair_mode
            )
            if cost is None:
                continue  # Impassable edge

            tentative_g = g_score[current_id] + cost

            if tentative_g < g_score.get(neighbor_id, float("inf")):
                came_from[neighbor_id] = current_id
                g_score[neighbor_id] = tentative_g
                f = tentative_g + _heuristic(neighbor_node, goal_node)
                f_score[neighbor_id] = f
                counter += 1
                heapq.heappush(open_set, (f, counter, neighbor_id))

    return _fail(
        "No accessible path found. Try disabling 'avoid_stairs' or check "
        "that the graph is fully connected."
    )


# ---------------------------------------------------------------------------
# A* Helpers
# ---------------------------------------------------------------------------
def _heuristic(node: Node, goal: Node) -> float:
    """Admissible heuristic: straight-line distance (meters)."""
    return haversine(node.latitude, node.longitude,
                     goal.latitude, goal.longitude)


def _reconstruct_path(came_from: dict[str, str], current: str) -> list[str]:
    """Walk back through came_from to build the full path."""
    path = [current]
    while current in came_from:
        current = came_from[current]
        path.append(current)
    path.reverse()
    return path


def _compute_real_distance(path: list[str], nodes: dict[str, Node]) -> float:
    """Sum the actual geographic distances along the path (meters)."""
    total = 0.0
    for i in range(len(path) - 1):
        a, b = nodes[path[i]], nodes[path[i + 1]]
        total += haversine(a.latitude, a.longitude, b.latitude, b.longitude)
    return total


def _node_detail(node: Node) -> dict:
    """Serialize a Node for the API response."""
    return {
        "node_id": node.node_id,
        "type": node.node_type,
        "name": node.name,
        "latitude": node.latitude,
        "longitude": node.longitude,
        "building": node.building,
        "floor": node.floor,
        "campus_zone": node.campus_zone,
        "status": node.status,
        "wheelchair_accessible": node.wheelchair_accessible,
    }


def _success(
    path: list[str],
    nodes: dict[str, Node],
    total_cost: float,
    distance_m: float,
) -> dict:
    return {
        "success": True,
        "path": path,
        "path_details": [_node_detail(nodes[nid]) for nid in path],
        "total_cost": round(total_cost, 2),
        "distance_meters": round(distance_m, 2),
        "num_nodes": len(path),
        "accessibility_summary": {
            "ramps_used": sum(1 for n in path if nodes[n].node_type == "ramp"),
            "elevators_used": sum(
                1 for n in path if nodes[n].node_type == "elevator"
            ),
            "stairs_used": sum(
                1 for n in path if nodes[n].node_type == "stairs"
            ),
        },
        "message": "Accessible route found.",
    }


def _fail(message: str) -> dict:
    return {
        "success": False,
        "path": [],
        "path_details": [],
        "total_cost": 0.0,
        "distance_meters": 0.0,
        "num_nodes": 0,
        "accessibility_summary": {
            "ramps_used": 0,
            "elevators_used": 0,
            "stairs_used": 0,
        },
        "message": message,
    }


# ---------------------------------------------------------------------------
# Flask API Endpoints
# ---------------------------------------------------------------------------
@routing_bp.route("/api/route", methods=["POST"])
def calculate_route():
    """
    Calculate an accessible route between two coordinates.

    **POST JSON body:**
    ```json
    {
      "start_lat": 35.2058,
      "start_lon": -97.4457,
      "end_lat": 35.2074,
      "end_lon": -97.4448,
      "avoid_stairs": true,
      "wheelchair_mode": false
    }
    ```

    Alternatively, supply node IDs directly:
    ```json
    {
      "start_node": "node_001",
      "end_node": "node_008"
    }
    ```
    """
    data = request.get_json(force=True)
    avoid_stairs = data.get("avoid_stairs", True)
    wheelchair_mode = data.get("wheelchair_mode", False)

    # Fetch current graph from Firebase
    nodes = fetch_nodes_from_firebase()
    if not nodes:
        return jsonify(_fail("No infrastructure nodes found in database.")), 500

    # Resolve start / end nodes
    start_id = data.get("start_node")
    end_id = data.get("end_node")

    if not start_id:
        start_lat = data.get("start_lat")
        start_lon = data.get("start_lon")
        if start_lat is None or start_lon is None:
            return jsonify(
                _fail("Provide start_lat/start_lon or start_node.")
            ), 400
        start_id = find_nearest_node(start_lat, start_lon, nodes)

    if not end_id:
        end_lat = data.get("end_lat")
        end_lon = data.get("end_lon")
        if end_lat is None or end_lon is None:
            return jsonify(
                _fail("Provide end_lat/end_lon or end_node.")
            ), 400
        end_id = find_nearest_node(end_lat, end_lon, nodes)

    # Run A*
    result = a_star(start_id, end_id, nodes, avoid_stairs, wheelchair_mode)

    status_code = 200 if result["success"] else 404
    return jsonify(result), status_code


@routing_bp.route("/api/nodes", methods=["GET"])
def list_nodes():
    """Return all infrastructure nodes (optionally filtered by type)."""
    nodes = fetch_nodes_from_firebase()
    node_type = request.args.get("type")  # ?type=ramp

    result = []
    for node in nodes.values():
        if node_type and node.node_type != node_type:
            continue
        result.append(_node_detail(node))

    return jsonify({"count": len(result), "nodes": result}), 200


@routing_bp.route("/api/nodes/nearest", methods=["GET"])
def nearest_node():
    """
    Find the nearest infrastructure node to given coordinates.

    **Query params:** `?lat=35.2058&lon=-97.4457`
    """
    lat = request.args.get("lat", type=float)
    lon = request.args.get("lon", type=float)
    if lat is None or lon is None:
        return jsonify({"error": "Provide lat and lon query parameters."}), 400

    nodes = fetch_nodes_from_firebase()
    nearest_id = find_nearest_node(lat, lon, nodes)
    if not nearest_id:
        return jsonify({"error": "No nodes in database."}), 500

    node = nodes[nearest_id]
    distance = haversine(lat, lon, node.latitude, node.longitude)
    return jsonify({
        "node": _node_detail(node),
        "distance_meters": round(distance, 2),
    }), 200
