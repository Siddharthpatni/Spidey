"""Autonomous-driving data platform: upload drive logs, replay them, predict
collisions, analyze driving behavior and export reports.

Sessions ingest frames as JSON/CSV rows — ``ts, speed_kmh, lat/lon`` plus an
``objects`` list (``[{id, distance_m, rel_speed_ms}]``) the way a perception
stack would emit them. ROS 2 bags load directly when the optional ``rosbags``
package is installed. Collision prediction is time-to-collision (TTC = range /
closing-speed) per object per frame — the metric real AEB systems trigger on;
frames with TTC under 3s are flagged. Vision endpoints (object/lane detection
on images) light up with OpenCV installed: HOG pedestrian detection and
Canny+Hough lane finding, the classic pipeline.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..core import db

TTC_WARN_S = 3.0
HARSH_BRAKE_KMH_S = 12.0


class SessionIn(BaseModel):
    name: str
    meta: Dict[str, Any] = {}


# ------------------------------- ingestion ---------------------------------- #
def _normalize_frame(row: Dict[str, Any], seq: int) -> Dict[str, Any]:
    frame = {"seq": seq, "ts": float(row.get("ts") or seq * 0.1),
             "speed_kmh": _f(row.get("speed_kmh") or row.get("speed")),
             "lat": _f(row.get("lat")), "lon": _f(row.get("lon")),
             "yaw": _f(row.get("yaw")), "objects": row.get("objects") or []}
    if isinstance(frame["objects"], str):
        frame["objects"] = db.json_loads(frame["objects"], [])
    return frame


def _f(v: Any) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def ingest_frames(session_id: int, frames: List[Dict[str, Any]]) -> int:
    start = (db.one("SELECT COALESCE(MAX(seq),-1) AS m FROM drive_frames WHERE session_id=?",
                    (session_id,)) or {}).get("m", -1) + 1
    rows = []
    for i, row in enumerate(frames):
        frame = _normalize_frame(row, start + i)
        rows.append((session_id, frame["seq"], frame["ts"], db.json_dumps(frame)))
    with db.connect() as conn:
        conn.executemany("INSERT INTO drive_frames(session_id, seq, ts, data)"
                         " VALUES(?,?,?,?)", rows)
    return len(rows)


def load_rosbag(path: str) -> List[Dict[str, Any]]:
    """Odometry frames out of a ROS 2 bag (needs `pip install rosbags`)."""
    try:
        from rosbags.highlevel import AnyReader
        from pathlib import Path as P
    except ImportError:
        raise HTTPException(501, "ROS bag support needs `pip install rosbags` — "
                                 "or POST frames as JSON/CSV instead")
    frames = []
    with AnyReader([P(path)]) as reader:
        conns = [c for c in reader.connections if "odom" in c.topic.lower()]
        for conn, timestamp, raw in reader.messages(connections=conns):
            msg = reader.deserialize(raw, conn.msgtype)
            twist = getattr(getattr(msg, "twist", None), "twist", None)
            speed = getattr(getattr(twist, "linear", None), "x", 0.0) if twist else 0.0
            frames.append({"ts": timestamp / 1e9, "speed_kmh": speed * 3.6})
    return frames


# ------------------------------- analytics ----------------------------------- #
def _frames(session_id: int) -> List[Dict[str, Any]]:
    rows = db.query("SELECT data FROM drive_frames WHERE session_id=? ORDER BY seq",
                    (session_id,))
    if not rows:
        raise HTTPException(404, "session has no frames (or doesn't exist)")
    return [db.json_loads(r["data"], {}) for r in rows]


def collision_analysis(frames: List[Dict[str, Any]]) -> Dict[str, Any]:
    """TTC per object per frame; flag anything closing in under TTC_WARN_S."""
    warnings = []
    min_ttc = None
    for f in frames:
        for obj in f.get("objects", []):
            dist, rel = _f(obj.get("distance_m")), _f(obj.get("rel_speed_ms"))
            if not dist or not rel or rel >= 0:  # rel < 0 means closing
                continue
            ttc = dist / -rel
            if min_ttc is None or ttc < min_ttc:
                min_ttc = ttc
            if ttc < TTC_WARN_S:
                warnings.append({"ts": f["ts"], "object": obj.get("id", "?"),
                                 "distance_m": dist, "ttc_s": round(ttc, 2)})
    return {"min_ttc_s": round(min_ttc, 2) if min_ttc else None,
            "warnings": warnings[:100],
            "verdict": ("CRITICAL — braking window violated" if warnings
                        else "no predicted collisions")}


def behavior_analysis(frames: List[Dict[str, Any]]) -> Dict[str, Any]:
    speeds = [(f["ts"], f["speed_kmh"]) for f in frames if f.get("speed_kmh") is not None]
    if len(speeds) < 2:
        return {"note": "need frames with speed_kmh"}
    values = [s for _, s in speeds]
    harsh = []
    for (t0, v0), (t1, v1) in zip(speeds, speeds[1:]):
        dt = max(t1 - t0, 1e-3)
        accel = (v1 - v0) / dt
        if accel < -HARSH_BRAKE_KMH_S:
            harsh.append({"ts": t1, "decel_kmh_s": round(accel, 1)})
    duration = speeds[-1][0] - speeds[0][0]
    return {"duration_s": round(duration, 1), "frames": len(frames),
            "speed": {"avg_kmh": round(sum(values) / len(values), 1),
                      "max_kmh": round(max(values), 1)},
            "distance_km_est": round(sum(values) / len(values) * duration / 3600, 2),
            "harsh_brakes": harsh}


def report_markdown(session: dict, frames: List[Dict[str, Any]]) -> str:
    b = behavior_analysis(frames)
    c = collision_analysis(frames)
    lines = [f"# Drive Report — {session['name']}", "",
             f"*Session {session['id']} · {session['created_at']} · {len(frames)} frames*", "",
             "## Behavior", ""]
    if "speed" in b:
        lines += [f"- Duration: **{b['duration_s']} s** · est. distance **{b['distance_km_est']} km**",
                  f"- Speed: avg **{b['speed']['avg_kmh']} km/h**, max **{b['speed']['max_kmh']} km/h**",
                  f"- Harsh brake events: **{len(b['harsh_brakes'])}**"]
    lines += ["", "## Collision prediction", "",
              f"- Verdict: **{c['verdict']}**",
              f"- Minimum TTC: **{c['min_ttc_s']} s**" if c["min_ttc_s"] else "- No closing objects observed"]
    for w in c["warnings"][:10]:
        lines.append(f"  - t={w['ts']:.1f}s object `{w['object']}` at {w['distance_m']} m, "
                     f"TTC {w['ttc_s']} s")
    return "\n".join(lines)


# ------------------------------- vision (optional) ---------------------------- #
def detect_objects_image(path: str) -> Dict[str, Any]:
    try:
        import cv2
    except ImportError:
        raise HTTPException(501, "vision endpoints need `pip install opencv-python`")
    img = cv2.imread(path)
    if img is None:
        raise HTTPException(404, f"no readable image at {path}")
    hog = cv2.HOGDescriptor()
    hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    rects, weights = hog.detectMultiScale(img, winStride=(8, 8))
    return {"pedestrians": [{"x": int(x), "y": int(y), "w": int(w), "h": int(h),
                             "confidence": round(float(c), 3)}
                            for (x, y, w, h), c in zip(rects, weights)]}


def detect_lanes_image(path: str) -> Dict[str, Any]:
    try:
        import cv2
        import numpy as np
    except ImportError:
        raise HTTPException(501, "vision endpoints need `pip install opencv-python`")
    img = cv2.imread(path)
    if img is None:
        raise HTTPException(404, f"no readable image at {path}")
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    mask = np.zeros_like(edges)  # keep the road trapezoid only
    cv2.fillPoly(mask, [np.array([(0, h), (w, h), (int(w * .55), int(h * .6)),
                                  (int(w * .45), int(h * .6))])], 255)
    lines = cv2.HoughLinesP(cv2.bitwise_and(edges, mask), 1, np.pi / 180, 40,
                            minLineLength=40, maxLineGap=100)
    return {"lane_segments": [[int(v) for v in l[0]] for l in (lines if lines is not None else [])][:50]}


# ------------------------------- REST API ---------------------------------- #
router = APIRouter(prefix="/api/driving", tags=["Driving Data"])


@router.post("/sessions")
def create_session(body: SessionIn) -> dict:
    sid = db.execute("INSERT INTO drive_sessions(name, meta, created_at) VALUES(?,?,?)",
                     (body.name, db.json_dumps(body.meta), db.now()))
    return {"id": sid, "name": body.name}


@router.get("/sessions")
def list_sessions() -> list:
    return db.query(
        "SELECT s.id, s.name, s.created_at, COUNT(f.id) AS frames FROM drive_sessions s"
        " LEFT JOIN drive_frames f ON f.session_id=s.id GROUP BY s.id ORDER BY s.id")


@router.post("/sessions/{session_id}/frames")
async def upload_frames(session_id: int, request: Request) -> dict:
    """JSON array of frames, or CSV with a header row (content-type text/csv)."""
    if not db.one("SELECT id FROM drive_sessions WHERE id=?", (session_id,)):
        raise HTTPException(404, "session not found")
    body = await request.body()
    ctype = request.headers.get("content-type", "")
    if "csv" in ctype:
        reader = csv.DictReader(io.StringIO(body.decode(errors="replace")))
        frames = list(reader)
    else:
        try:
            frames = json.loads(body)
        except json.JSONDecodeError as e:
            raise HTTPException(422, f"body must be a JSON array or CSV: {e}")
        if isinstance(frames, dict):
            frames = frames.get("frames", [])
    if not frames:
        raise HTTPException(422, "no frames in body")
    return {"ingested": ingest_frames(session_id, frames)}


@router.post("/sessions/{session_id}/rosbag")
def upload_rosbag(session_id: int, body: dict) -> dict:
    path = body.get("path")
    if not path:
        raise HTTPException(422, "path (to a ROS 2 bag directory) is required")
    return {"ingested": ingest_frames(session_id, load_rosbag(path))}


@router.get("/sessions/{session_id}/replay")
def replay(session_id: int, start: int = 0, count: int = 100) -> list:
    rows = db.query("SELECT data FROM drive_frames WHERE session_id=? AND seq>=?"
                    " ORDER BY seq LIMIT ?", (session_id, start, count))
    return [db.json_loads(r["data"], {}) for r in rows]


@router.get("/sessions/{session_id}/analytics")
def analytics(session_id: int) -> dict:
    frames = _frames(session_id)
    return {"behavior": behavior_analysis(frames),
            "collision": collision_analysis(frames)}


@router.get("/sessions/{session_id}/report")
def report(session_id: int, fmt: str = "markdown") -> Any:
    session = db.one("SELECT * FROM drive_sessions WHERE id=?", (session_id,))
    if not session:
        raise HTTPException(404, "session not found")
    frames = _frames(session_id)
    if fmt == "json":
        return {"session": session, "behavior": behavior_analysis(frames),
                "collision": collision_analysis(frames)}
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(report_markdown(session, frames), media_type="text/markdown")


@router.post("/vision/objects")
def vision_objects(body: dict) -> dict:
    if not body.get("path"):
        raise HTTPException(422, "path (to an image) is required")
    return detect_objects_image(body["path"])


@router.post("/vision/lanes")
def vision_lanes(body: dict) -> dict:
    if not body.get("path"):
        raise HTTPException(422, "path (to an image) is required")
    return detect_lanes_image(body["path"])
