"""Persistent job queue with worker threads and a retry engine.

Jobs are rows in SQLite (they survive restarts); handlers are registered by
``kind``. Failures retry with exponential backoff (10s, 40s, 90s, ...) up to
``max_attempts``, then land in ``failed`` where the API exposes them for
inspection and manual retry. Completion/failure emits a webhook event and a
Prometheus counter — the same upload→queue→worker→store→notify shape as a
Celery/RabbitMQ deployment, in-process so it runs anywhere Spidey runs.
"""

from __future__ import annotations

import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, HTTPException

from . import db, metrics, notify

Handler = Callable[[Dict[str, Any]], Any]
BACKOFF_BASE = 10  # seconds; delay = BACKOFF_BASE * attempts^2


class JobQueue:
    def __init__(self, workers: int = 3, poll_interval: float = 0.5) -> None:
        self.workers = workers
        self.poll_interval = poll_interval
        self._handlers: Dict[str, Handler] = {}
        self._threads: list[threading.Thread] = []
        self._claim_lock = threading.Lock()
        self._stop = threading.Event()

    # -- registration / lifecycle ------------------------------------------ #
    def register(self, kind: str, handler: Handler) -> None:
        self._handlers[kind] = handler

    def start(self) -> None:
        if self._threads:
            return
        self._stop.clear()
        for i in range(self.workers):
            t = threading.Thread(target=self._work_loop, name=f"spidey-worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2)
        self._threads.clear()

    # -- producing ----------------------------------------------------------- #
    def enqueue(self, kind: str, payload: Optional[Dict[str, Any]] = None,
                max_attempts: int = 3, delay_seconds: int = 0) -> int:
        run_after = None
        if delay_seconds:
            run_after = (datetime.now(timezone.utc)
                         + timedelta(seconds=delay_seconds)).isoformat(timespec="seconds")
        job_id = db.execute(
            "INSERT INTO jobs(kind, payload, max_attempts, run_after, created_at)"
            " VALUES(?,?,?,?,?)",
            (kind, db.json_dumps(payload or {}), max_attempts, run_after, db.now()))
        metrics.inc("spidey_jobs_enqueued_total", {"kind": kind})
        return job_id

    def run_sync(self, kind: str, payload: Dict[str, Any]) -> Any:
        """Run a handler inline (used by tests and by the agent tools)."""
        return self._handlers[kind](payload)

    # -- consuming ------------------------------------------------------------ #
    def _claim(self) -> Optional[dict]:
        with self._claim_lock:
            row = db.one(
                "SELECT * FROM jobs WHERE status='queued'"
                " AND (run_after IS NULL OR run_after<=?) ORDER BY id LIMIT 1",
                (db.now(),))
            if not row:
                return None
            db.execute("UPDATE jobs SET status='running', started_at=?, attempts=attempts+1"
                       " WHERE id=?", (db.now(), row["id"]))
            row["attempts"] += 1
            return row

    def _work_loop(self) -> None:
        while not self._stop.is_set():
            job = None
            try:
                job = self._claim()
            except Exception:
                pass  # transient db contention — just poll again
            if not job:
                self._stop.wait(self.poll_interval)
                continue
            self._run_job(job)

    def _run_job(self, job: dict) -> None:
        kind, payload = job["kind"], db.json_loads(job["payload"], {})
        handler = self._handlers.get(kind)
        try:
            if handler is None:
                raise RuntimeError(f"no handler registered for job kind '{kind}'")
            result = handler(payload)
            db.execute("UPDATE jobs SET status='done', finished_at=?, result=? WHERE id=?",
                       (db.now(), db.json_dumps(result), job["id"]))
            metrics.inc("spidey_jobs_processed_total", {"kind": kind, "status": "done"})
            notify.emit("job.done", {"id": job["id"], "kind": kind})
        except Exception as e:
            err = f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}"
            if job["attempts"] < job["max_attempts"]:
                delay = BACKOFF_BASE * job["attempts"] ** 2
                run_after = (datetime.now(timezone.utc)
                             + timedelta(seconds=delay)).isoformat(timespec="seconds")
                db.execute("UPDATE jobs SET status='queued', run_after=?, error=? WHERE id=?",
                           (run_after, err, job["id"]))
                metrics.inc("spidey_jobs_retried_total", {"kind": kind})
            else:
                db.execute("UPDATE jobs SET status='failed', finished_at=?, error=? WHERE id=?",
                           (db.now(), err, job["id"]))
                metrics.inc("spidey_jobs_processed_total", {"kind": kind, "status": "failed"})
                notify.emit("job.failed", {"id": job["id"], "kind": kind, "error": str(e)})

    # -- introspection ----------------------------------------------------------- #
    def stats(self) -> Dict[str, int]:
        rows = db.query("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")
        return {r["status"]: r["n"] for r in rows}


_default: Optional[JobQueue] = None


def default_queue() -> JobQueue:
    global _default
    if _default is None:
        _default = JobQueue()
    return _default


# ------------------------------- REST API ---------------------------------- #
router = APIRouter(prefix="/api/queue", tags=["Queue"])


@router.get("/jobs")
def list_jobs(status: Optional[str] = None, limit: int = 50) -> list:
    if status:
        return db.query("SELECT id, kind, status, attempts, max_attempts, created_at,"
                        " finished_at, error FROM jobs WHERE status=? ORDER BY id DESC LIMIT ?",
                        (status, limit))
    return db.query("SELECT id, kind, status, attempts, max_attempts, created_at, finished_at,"
                    " error FROM jobs ORDER BY id DESC LIMIT ?", (limit,))


@router.get("/jobs/{job_id}")
def get_job(job_id: int) -> dict:
    row = db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
    if not row:
        raise HTTPException(404, "job not found")
    row["payload"] = db.json_loads(row["payload"], {})
    row["result"] = db.json_loads(row["result"])
    return row


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: int) -> dict:
    row = db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
    if not row:
        raise HTTPException(404, "job not found")
    if row["status"] != "failed":
        raise HTTPException(409, f"job is {row['status']}, only failed jobs can be retried")
    db.execute("UPDATE jobs SET status='queued', attempts=0, run_after=NULL, error=NULL"
               " WHERE id=?", (job_id,))
    return {"id": job_id, "status": "queued"}


@router.get("/notifications")
def notifications(limit: int = 50) -> list:
    return notify.recent(limit)


@router.post("/webhooks")
def add_webhook(body: dict) -> dict:
    event, url = body.get("event", "*"), body.get("url")
    if not url:
        raise HTTPException(422, "url is required")
    return {"id": notify.register_webhook(event, url), "event": event, "url": url}


@router.get("/webhooks")
def webhooks() -> list:
    return notify.list_webhooks()


@router.delete("/webhooks/{webhook_id}")
def remove_webhook(webhook_id: int) -> dict:
    notify.delete_webhook(webhook_id)
    return {"deleted": webhook_id}
