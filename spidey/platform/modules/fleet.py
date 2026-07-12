"""Fleet management: vehicles, live tracking, maintenance prediction, fuel
analytics, route optimization, driver monitoring and anomaly detection.

Telemetry arrives as pings (position, speed, fuel, odometer). Analytics are
computed from consecutive pings: fuel burn per 100 km, harsh braking/
acceleration (speed deltas), z-score anomalies (sudden fuel drops read as
possible theft/leak), and km-based maintenance forecasting from each vehicle's
average daily distance. Route optimization is nearest-neighbor + 2-opt over
haversine distances — the classic dispatch heuristic.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core import db, notify

SPEED_LIMIT_KMH = 130.0
HARSH_DELTA_KMH = 30.0  # speed change between consecutive pings that counts as harsh


class VehicleIn(BaseModel):
    name: str
    plate: Optional[str] = None
    driver: Optional[str] = None
    odometer_km: float = 0
    last_service_km: float = 0
    service_interval_km: float = 15000


class PingIn(BaseModel):
    vehicle_id: int
    lat: Optional[float] = None
    lon: Optional[float] = None
    speed_kmh: Optional[float] = None
    fuel_l: Optional[float] = None
    odometer_km: Optional[float] = None
    ts: Optional[str] = None


def haversine_km(a: tuple, b: tuple) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 6371.0 * 2 * math.asin(math.sqrt(h))


# ------------------------------ analytics ----------------------------------- #
def fuel_analytics(vehicle_id: int) -> Dict[str, Any]:
    rows = db.query("SELECT fuel_l, odometer_km, ts FROM pings WHERE vehicle_id=?"
                    " AND fuel_l IS NOT NULL AND odometer_km IS NOT NULL ORDER BY ts",
                    (vehicle_id,))
    if len(rows) < 2:
        return {"note": "need at least 2 pings with fuel + odometer"}
    burned = 0.0
    distance = 0.0
    refuels = []
    for prev, cur in zip(rows, rows[1:]):
        dfuel = cur["fuel_l"] - prev["fuel_l"]
        dkm = cur["odometer_km"] - prev["odometer_km"]
        if dfuel < 0:
            burned += -dfuel
            distance += max(dkm, 0)
        elif dfuel > 1:
            refuels.append({"ts": cur["ts"], "litres": round(dfuel, 1)})
    per100 = round(burned / distance * 100, 2) if distance else None
    return {"litres_burned": round(burned, 1), "distance_km": round(distance, 1),
            "l_per_100km": per100, "refuels": refuels}


def maintenance_prediction(vehicle: dict) -> Dict[str, Any]:
    rows = db.query("SELECT odometer_km, ts FROM pings WHERE vehicle_id=?"
                    " AND odometer_km IS NOT NULL ORDER BY ts", (vehicle["id"],))
    odometer = rows[-1]["odometer_km"] if rows else vehicle["odometer_km"]
    since_service = odometer - vehicle["last_service_km"]
    remaining = vehicle["service_interval_km"] - since_service
    result: Dict[str, Any] = {
        "odometer_km": odometer, "km_since_service": round(since_service, 1),
        "km_until_service": round(remaining, 1), "due": remaining <= 0}
    if len(rows) >= 2:
        try:
            t0 = datetime.fromisoformat(rows[0]["ts"])
            t1 = datetime.fromisoformat(rows[-1]["ts"])
            days = max((t1 - t0).total_seconds() / 86400, 0.01)
            km_per_day = (rows[-1]["odometer_km"] - rows[0]["odometer_km"]) / days
            if km_per_day > 0 and remaining > 0:
                result["km_per_day"] = round(km_per_day, 1)
                result["days_until_service"] = round(remaining / km_per_day, 1)
        except ValueError:
            pass
    return result


def anomalies(vehicle_id: int) -> List[Dict[str, Any]]:
    """Z-score outliers on speed + abrupt fuel drops while parked."""
    rows = db.query("SELECT speed_kmh, fuel_l, ts FROM pings WHERE vehicle_id=? ORDER BY ts",
                    (vehicle_id,))
    found: List[Dict[str, Any]] = []
    speeds = [r["speed_kmh"] for r in rows if r["speed_kmh"] is not None]
    if len(speeds) >= 5:
        mean = sum(speeds) / len(speeds)
        std = math.sqrt(sum((s - mean) ** 2 for s in speeds) / len(speeds)) or 1.0
        for r in rows:
            s = r["speed_kmh"]
            if s is not None and abs(s - mean) / std > 3:
                found.append({"type": "speed_outlier", "ts": r["ts"], "value": s,
                              "z": round((s - mean) / std, 1)})
    for prev, cur in zip(rows, rows[1:]):
        if (prev["fuel_l"] is not None and cur["fuel_l"] is not None
                and (cur["speed_kmh"] or 0) < 2
                and prev["fuel_l"] - cur["fuel_l"] > 5):
            found.append({"type": "fuel_drop_while_parked", "ts": cur["ts"],
                          "litres": round(prev["fuel_l"] - cur["fuel_l"], 1)})
    return found


def driver_events(vehicle_id: int) -> List[Dict[str, Any]]:
    rows = db.query("SELECT speed_kmh, ts FROM pings WHERE vehicle_id=?"
                    " AND speed_kmh IS NOT NULL ORDER BY ts", (vehicle_id,))
    events = []
    for prev, cur in zip(rows, rows[1:]):
        delta = cur["speed_kmh"] - prev["speed_kmh"]
        if abs(delta) >= HARSH_DELTA_KMH:
            events.append({"type": "harsh_brake" if delta < 0 else "harsh_acceleration",
                           "ts": cur["ts"], "delta_kmh": round(delta, 1)})
        if cur["speed_kmh"] > SPEED_LIMIT_KMH:
            events.append({"type": "speeding", "ts": cur["ts"],
                           "speed_kmh": cur["speed_kmh"]})
    return events


def optimize_route(stops: List[Dict[str, float]]) -> Dict[str, Any]:
    """Nearest-neighbor construction + 2-opt improvement."""
    if len(stops) < 2:
        return {"order": list(range(len(stops))), "distance_km": 0.0}
    pts = [(s["lat"], s["lon"]) for s in stops]
    n = len(pts)
    unvisited = set(range(1, n))
    order = [0]
    while unvisited:
        last = pts[order[-1]]
        nxt = min(unvisited, key=lambda i: haversine_km(last, pts[i]))
        order.append(nxt)
        unvisited.remove(nxt)

    def total(o: List[int]) -> float:
        return sum(haversine_km(pts[a], pts[b]) for a, b in zip(o, o[1:]))

    improved = True
    while improved:
        improved = False
        for i in range(1, n - 1):
            for j in range(i + 1, n):
                candidate = order[:i] + order[i:j + 1][::-1] + order[j + 1:]
                if total(candidate) < total(order) - 1e-9:
                    order = candidate
                    improved = True
    return {"order": order, "distance_km": round(total(order), 2),
            "stops": [stops[i] for i in order]}


# ------------------------------- REST API ---------------------------------- #
router = APIRouter(prefix="/api/fleet", tags=["Fleet"])


@router.post("/vehicles")
def create_vehicle(body: VehicleIn) -> dict:
    try:
        vid = db.execute(
            "INSERT INTO vehicles(name, plate, driver, odometer_km, last_service_km,"
            " service_interval_km, created_at) VALUES(?,?,?,?,?,?,?)",
            (body.name, body.plate, body.driver, body.odometer_km, body.last_service_km,
             body.service_interval_km, db.now()))
    except Exception:
        raise HTTPException(409, f"plate '{body.plate}' already registered")
    return {"id": vid, "name": body.name}


@router.get("/vehicles")
def list_vehicles() -> list:
    return db.query("SELECT * FROM vehicles ORDER BY id")


@router.post("/pings")
def add_pings(body: List[PingIn]) -> dict:
    for p in body:
        if not db.one("SELECT id FROM vehicles WHERE id=?", (p.vehicle_id,)):
            raise HTTPException(404, f"vehicle {p.vehicle_id} not found")
    with db.connect() as conn:
        conn.executemany(
            "INSERT INTO pings(vehicle_id, lat, lon, speed_kmh, fuel_l, odometer_km, ts)"
            " VALUES(?,?,?,?,?,?,?)",
            [(p.vehicle_id, p.lat, p.lon, p.speed_kmh, p.fuel_l, p.odometer_km,
              p.ts or db.now()) for p in body])
    # Maintenance alert on fresh odometer readings.
    for p in body:
        if p.odometer_km is None:
            continue
        v = db.one("SELECT * FROM vehicles WHERE id=?", (p.vehicle_id,))
        if p.odometer_km - v["last_service_km"] >= v["service_interval_km"]:
            msg = f"{v['name']}: service due ({p.odometer_km - v['last_service_km']:.0f} km since last)"
            db.execute("INSERT INTO alerts(source, message, value, ts) VALUES(?,?,?,?)",
                       ("fleet", msg, p.odometer_km, db.now()))
            notify.emit("fleet.maintenance_due", {"vehicle_id": v["id"], "message": msg})
    return {"ingested": len(body)}


@router.get("/vehicles/{vehicle_id}/track")
def track(vehicle_id: int, limit: int = 200) -> list:
    return db.query("SELECT lat, lon, speed_kmh, fuel_l, odometer_km, ts FROM pings"
                    " WHERE vehicle_id=? ORDER BY ts DESC LIMIT ?", (vehicle_id, limit))[::-1]


@router.get("/vehicles/{vehicle_id}/analytics")
def vehicle_analytics(vehicle_id: int) -> dict:
    v = db.one("SELECT * FROM vehicles WHERE id=?", (vehicle_id,))
    if not v:
        raise HTTPException(404, "vehicle not found")
    return {"vehicle": v, "fuel": fuel_analytics(vehicle_id),
            "maintenance": maintenance_prediction(v),
            "driver_events": driver_events(vehicle_id),
            "anomalies": anomalies(vehicle_id)}


@router.post("/routes/optimize")
def route_optimize(body: dict) -> dict:
    stops = body.get("stops") or []
    if not all(isinstance(s, dict) and "lat" in s and "lon" in s for s in stops):
        raise HTTPException(422, "stops must be [{lat, lon, ...}, ...]")
    if len(stops) > 40:
        raise HTTPException(422, "2-opt is O(n²) — cap is 40 stops")
    return optimize_route(stops)


@router.get("/alerts")
def fleet_alerts(limit: int = 50) -> list:
    return db.query("SELECT * FROM alerts WHERE source='fleet' ORDER BY id DESC LIMIT ?",
                    (limit,))
