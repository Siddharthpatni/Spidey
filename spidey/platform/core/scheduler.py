"""Interval scheduler: persisted schedules that enqueue jobs when due.

A single daemon thread wakes every few seconds, finds enabled schedules whose
``next_run_at`` has passed, enqueues their job kind/payload on the queue, and
advances ``next_run_at`` by the interval. Schedules survive restarts (they're
rows), and a missed window fires once on the next tick rather than stampeding.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import db, metrics
from .queue import default_queue

_thread: Optional[threading.Thread] = None
_stop = threading.Event()
TICK_SECONDS = 3.0


def _tick() -> int:
    fired = 0
    due = db.query("SELECT * FROM schedules WHERE enabled=1 AND next_run_at<=?", (db.now(),))
    for s in due:
        default_queue().enqueue(s["kind"], db.json_loads(s["payload"], {}))
        nxt = (datetime.now(timezone.utc)
               + timedelta(seconds=s["interval_seconds"])).isoformat(timespec="seconds")
        db.execute("UPDATE schedules SET next_run_at=?, last_enqueued_at=? WHERE id=?",
                   (nxt, db.now(), s["id"]))
        metrics.inc("spidey_schedules_fired_total", {"name": s["name"]})
        fired += 1
    return fired


def _loop() -> None:
    while not _stop.is_set():
        try:
            _tick()
        except Exception:
            pass  # keep the scheduler alive through transient db errors
        _stop.wait(TICK_SECONDS)


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="spidey-scheduler", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
    if _thread:
        _thread.join(timeout=2)


# ------------------------------- REST API ---------------------------------- #
router = APIRouter(prefix="/api/schedules", tags=["Scheduler"])


class ScheduleIn(BaseModel):
    name: str
    kind: str = Field(description="Job kind to enqueue, e.g. 'webauto.scrape'.")
    payload: dict = Field(default_factory=dict)
    interval_seconds: int = Field(ge=5)
    enabled: bool = True


@router.post("")
def create_schedule(body: ScheduleIn) -> dict:
    first = (datetime.now(timezone.utc)
             + timedelta(seconds=body.interval_seconds)).isoformat(timespec="seconds")
    try:
        sid = db.execute(
            "INSERT INTO schedules(name, kind, payload, interval_seconds, next_run_at,"
            " enabled, created_at) VALUES(?,?,?,?,?,?,?)",
            (body.name, body.kind, db.json_dumps(body.payload), body.interval_seconds,
             first, int(body.enabled), db.now()))
    except Exception:
        raise HTTPException(409, f"a schedule named '{body.name}' already exists")
    return {"id": sid, "name": body.name, "next_run_at": first}


@router.get("")
def list_schedules() -> list:
    rows = db.query("SELECT * FROM schedules ORDER BY id")
    for r in rows:
        r["payload"] = db.json_loads(r["payload"], {})
    return rows


@router.patch("/{schedule_id}")
def toggle_schedule(schedule_id: int, body: dict) -> dict:
    if "enabled" not in body:
        raise HTTPException(422, "body must include 'enabled'")
    n = db.execute("UPDATE schedules SET enabled=? WHERE id=?",
                   (int(bool(body["enabled"])), schedule_id))
    if not n:
        raise HTTPException(404, "schedule not found")
    return {"id": schedule_id, "enabled": bool(body["enabled"])}


@router.delete("/{schedule_id}")
def delete_schedule(schedule_id: int) -> dict:
    db.execute("DELETE FROM schedules WHERE id=?", (schedule_id,))
    return {"deleted": schedule_id}
