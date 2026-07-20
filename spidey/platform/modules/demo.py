"""Demo mode — populate a fresh instance with realistic sample data in one click.

For a portfolio/LinkedIn link, an empty platform is a bad first impression. This
seeds every module with believable data (a small crawled corpus + knowledge
graph, memories, analytics, a fleet, a drive with a near-collision, a generated
document) so a visitor immediately sees a *populated, working* platform — every
number on the dashboard is real, computed from this seed. Idempotent and clearly
labelled; ``/reset`` clears it again.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from ..core import db, graph

router = APIRouter(prefix="/api/demo", tags=["Demo"])

_SEED_DOCS = [
    ("Transformers and Attention",
     "The Transformer architecture relies on self-attention to relate every token "
     "to every other token in a sequence. It removed recurrence, enabling massive "
     "parallelism, and now underpins large language models such as BERT and GPT. "
     "Multi-head attention lets the model attend to different representation "
     "subspaces. Positional encodings inject order. Docker and Kubernetes are "
     "commonly used to serve these models with PyTorch."),
    ("Retrieval-Augmented Generation",
     "RAG grounds a language model in an external corpus: a retriever finds "
     "relevant chunks with vector search or BM25, and the generator conditions on "
     "them. Hybrid search combines keyword and semantic signals. Qdrant and "
     "Elasticsearch are typical backends; Python and FastAPI wire the pipeline."),
    ("Robotic Grasping",
     "Dexterous robotic hands with tactile sensing enable manipulation beyond a "
     "parallel gripper. ROS2 coordinates the arm and hand; OpenCV and YOLO handle "
     "perception. Reinforcement learning and imitation learning are used to acquire "
     "grasp policies for autonomous driving warehouses and assembly."),
]

_SEED_MEMORIES = [
    ("I'm building an AI operating system called Spidey", "project"),
    ("I prefer Python, FastAPI and TypeScript", "preference"),
    ("Goal: an AI/robotics engineering role", "goal"),
    ("I work with ROS2, PyTorch and Docker", "skill"),
]


@router.post("/seed")
def seed() -> dict:
    created: Dict[str, Any] = {}

    # 1) Research corpus + knowledge graph (documents become connected nodes)
    from .research import ingest
    if not db.one("SELECT id FROM docs LIMIT 1"):
        for title, text in _SEED_DOCS:
            ingest(title, text, "demo")
        created["docs"] = len(_SEED_DOCS)

    # 2) Typed memories
    from .memory_engine import remember
    for content, kind in _SEED_MEMORIES:
        remember(content, kind=kind, source="demo")
    created["memories"] = len(_SEED_MEMORIES)

    # 3) A few extra graph relationships so the neural-net view is rich
    for a, rel, b in [("ROS2", "uses", "Python"), ("Python", "uses", "PyTorch"),
                      ("PyTorch", "powers", "Computer Vision"),
                      ("Computer Vision", "used_in", "Autonomous Driving"),
                      ("Docker", "deploys", "FastAPI")]:
        graph.relate("concept", a, rel, "concept", b, weight=2.0)

    # 4) Analytics events (so timeseries + percentiles are populated)
    import random
    from .analytics import ingest as ingest_events, EventIn
    ingest_events([EventIn(name="api.latency_ms", value=random.randint(60, 480))
                   for _ in range(60)])
    created["events"] = 60

    # 5) A fleet vehicle with telemetry
    if not db.one("SELECT id FROM vehicles LIMIT 1"):
        from datetime import datetime, timedelta, timezone
        vid = db.execute("INSERT INTO vehicles(name, plate, driver, odometer_km,"
                         " last_service_km, service_interval_km, created_at)"
                         " VALUES(?,?,?,?,?,?,?)",
                         ("Demo Van", "B-SP 2099", "Miles", 14200, 0, 15000, db.now()))
        t = lambda h: (datetime.now(timezone.utc) - timedelta(hours=h)).isoformat()
        with db.connect() as conn:
            conn.executemany(
                "INSERT INTO pings(vehicle_id, lat, lon, speed_kmh, fuel_l, odometer_km, ts)"
                " VALUES(?,?,?,?,?,?,?)",
                [(vid, 52.52, 13.40, 45, 60, 14200, t(30)),
                 (vid, 52.6, 13.3, 138, 50, 14400, t(18)),
                 (vid, 52.7, 13.2, 0, 32, 15050, t(2))])
        created["fleet"] = 1

    # 6) A drive session with a near-collision (TTC demo)
    if not db.one("SELECT id FROM drive_sessions LIMIT 1"):
        sid = db.execute("INSERT INTO drive_sessions(name, meta, created_at) VALUES(?,?,?)",
                         ("Demo drive", "{}", db.now()))
        frames, sp = [], 60
        for k in range(20):
            objs = ([{"id": "car", "distance_m": 60 - (k - 8) * 9, "rel_speed_ms": -9}]
                    if 8 < k < 14 else [])
            if k >= 13:
                sp = max(10, sp - 15)
            frames.append({"seq": k, "ts": float(k), "speed_kmh": sp, "objects": objs})
        with db.connect() as conn:
            conn.executemany("INSERT INTO drive_frames(session_id, seq, ts, data)"
                             " VALUES(?,?,?,?)",
                             [(sid, f["seq"], f["ts"], db.json_dumps(f)) for f in frames])
        created["drive"] = 1

    # 7) A generated résumé document so "My documents" isn't empty
    try:
        from .docgen import create_document
        if not db.one("SELECT id FROM generated_docs LIMIT 1"):
            create_document("resume", "pdf", "Demo — AI Engineer Résumé",
                            "AI/robotics engineer: Python, FastAPI, PyTorch, ROS2, Docker.",
                            "")
            created["document"] = 1
    except Exception:
        pass

    return {"seeded": created, "note": "Demo data loaded — explore every tab; the "
            "dashboard numbers are all computed from this."}


@router.get("/status")
def status() -> dict:
    return {"docs": db.one("SELECT COUNT(*) AS n FROM docs")["n"],
            "memories": db.one("SELECT COUNT(*) AS n FROM memories")["n"],
            "graph_nodes": graph.stats()["nodes"],
            "vehicles": db.one("SELECT COUNT(*) AS n FROM vehicles")["n"],
            "events": db.one("SELECT COUNT(*) AS n FROM events")["n"]}


@router.post("/reset")
def reset() -> dict:
    """Clear demo data (everything the seed created)."""
    for tbl in ("doc_chunks", "docs", "memories", "kg_edges", "kg_nodes", "events",
                "rollups", "pings", "vehicles", "drive_frames", "drive_sessions"):
        db.execute(f"DELETE FROM {tbl}")
    return {"reset": True}
