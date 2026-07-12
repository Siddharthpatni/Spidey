"""Real-time analytics: events → queue → workers → store → dashboard → alerts.

POST events (single or batch); raw rows are stored immediately and a rollup
job aggregates them into per-minute buckets, so timeseries reads never scan
raw data. Alert rules ("error_rate avg > 5 over 300s") are evaluated on a
recurring schedule; breaches create alert rows and fire ``alert.triggered``
webhooks. A mini-Datadog, one file long.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core import db, metrics, notify

ALERT_CHECK_SCHEDULE = "analytics.check_alerts"


class EventIn(BaseModel):
    name: str
    value: float = 1
    props: Dict[str, Any] = Field(default_factory=dict)
    ts: Optional[str] = None


def _minute(ts: str) -> str:
    return ts[:16] + ":00"  # ISO stamp truncated to the minute


def ingest(events: List[EventIn]) -> int:
    with db.connect() as conn:
        conn.executemany(
            "INSERT INTO events(name, value, props, ts) VALUES(?,?,?,?)",
            [(e.name, e.value, db.json_dumps(e.props), e.ts or db.now()) for e in events])
    metrics.inc("spidey_analytics_events_total", by=len(events))
    return len(events)


# ------------------------------- queue workers ------------------------------- #
def _job_rollup(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Aggregate raw events into per-minute buckets (idempotent upsert)."""
    since = payload.get("since") or (datetime.now(timezone.utc)
                                     - timedelta(minutes=10)).isoformat(timespec="seconds")
    rows = db.query(
        "SELECT name, substr(ts,1,16)||':00' AS bucket, COUNT(*) AS n, SUM(value) AS s,"
        " MIN(value) AS mn, MAX(value) AS mx FROM events WHERE ts>=?"
        " GROUP BY name, bucket", (since,))
    with db.connect() as conn:
        for r in rows:
            conn.execute(
                "INSERT INTO rollups(name, bucket, count, sum, min, max) VALUES(?,?,?,?,?,?)"
                " ON CONFLICT(name, bucket) DO UPDATE SET count=excluded.count,"
                " sum=excluded.sum, min=excluded.min, max=excluded.max",
                (r["name"], r["bucket"], r["n"], r["s"], r["mn"], r["mx"]))
    return {"buckets": len(rows)}


def _job_check_alerts(payload: Dict[str, Any]) -> Dict[str, Any]:
    triggered = 0
    for rule in db.query("SELECT * FROM alert_rules WHERE enabled=1"):
        since = (datetime.now(timezone.utc)
                 - timedelta(seconds=rule["window_seconds"])).isoformat(timespec="seconds")
        row = db.one("SELECT COUNT(*) AS n, AVG(value) AS avg, SUM(value) AS sum,"
                     " MIN(value) AS min, MAX(value) AS max FROM events WHERE name=? AND ts>=?",
                     (rule["metric"], since)) or {}
        value = row.get(rule["aggregate"])
        if rule["aggregate"] == "count":
            value = row.get("n", 0)
        if value is None:
            continue
        breached = {"<": value < rule["threshold"], ">": value > rule["threshold"],
                    "<=": value <= rule["threshold"], ">=": value >= rule["threshold"]}[rule["op"]]
        if breached:
            msg = (f"{rule['name']}: {rule['aggregate']}({rule['metric']}) = {value:.2f} "
                   f"{rule['op']} {rule['threshold']} over {rule['window_seconds']}s")
            db.execute("INSERT INTO alerts(source, message, value, ts) VALUES(?,?,?,?)",
                       ("analytics", msg, value, db.now()))
            notify.emit("alert.triggered", {"rule": rule["name"], "message": msg, "value": value})
            metrics.inc("spidey_alerts_triggered_total", {"rule": rule["name"]})
            triggered += 1
    return {"rules_triggered": triggered}


def register_jobs(queue) -> None:
    queue.register("analytics.rollup", _job_rollup)
    queue.register(ALERT_CHECK_SCHEDULE, _job_check_alerts)


# ------------------------------- REST API ---------------------------------- #
router = APIRouter(prefix="/api/analytics", tags=["Analytics"])


@router.post("/events")
def post_events(body: Union[EventIn, List[EventIn]]) -> dict:
    events = body if isinstance(body, list) else [body]
    if not events:
        raise HTTPException(422, "no events")
    n = ingest(events)
    from ..core.queue import default_queue
    default_queue().enqueue("analytics.rollup", {})
    return {"ingested": n}


@router.get("/timeseries")
def timeseries(name: str, minutes: int = 60) -> list:
    since = _minute((datetime.now(timezone.utc)
                     - timedelta(minutes=minutes)).isoformat(timespec="seconds"))
    return db.query("SELECT bucket, count, sum, min, max FROM rollups"
                    " WHERE name=? AND bucket>=? ORDER BY bucket", (name, since))


@router.get("/stats")
def stats(name: str, minutes: int = 60) -> dict:
    since = (datetime.now(timezone.utc)
             - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    values = [r["value"] for r in db.query(
        "SELECT value FROM events WHERE name=? AND ts>=? ORDER BY value", (name, since))]
    if not values:
        return {"name": name, "count": 0}

    def pct(p: float) -> float:
        return values[min(len(values) - 1, int(p * len(values)))]

    return {"name": name, "count": len(values), "sum": sum(values),
            "avg": round(sum(values) / len(values), 4), "min": values[0],
            "max": values[-1], "p50": pct(0.50), "p95": pct(0.95), "p99": pct(0.99)}


@router.get("/names")
def metric_names() -> list:
    return [r["name"] for r in db.query("SELECT DISTINCT name FROM events ORDER BY name")]


class RuleIn(BaseModel):
    name: str
    metric: str
    op: str = Field(pattern=r"^(<|>|<=|>=)$")
    threshold: float
    window_seconds: int = 300
    aggregate: str = Field(default="avg", pattern=r"^(avg|sum|count|max|min)$")


@router.post("/rules")
def create_rule(body: RuleIn) -> dict:
    rid = db.execute(
        "INSERT INTO alert_rules(name, metric, op, threshold, window_seconds, aggregate,"
        " created_at) VALUES(?,?,?,?,?,?,?)",
        (body.name, body.metric, body.op, body.threshold, body.window_seconds,
         body.aggregate, db.now()))
    # Make sure the evaluator schedule exists (every 60s).
    if not db.one("SELECT id FROM schedules WHERE name='analytics-alert-check'"):
        db.execute("INSERT INTO schedules(name, kind, payload, interval_seconds, next_run_at,"
                   " created_at) VALUES('analytics-alert-check',?,?,60,?,?)",
                   (ALERT_CHECK_SCHEDULE, "{}", db.now(), db.now()))
    return {"id": rid, "name": body.name}


@router.get("/rules")
def list_rules() -> list:
    return db.query("SELECT * FROM alert_rules ORDER BY id")


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int) -> dict:
    db.execute("DELETE FROM alert_rules WHERE id=?", (rule_id,))
    return {"deleted": rule_id}


@router.get("/alerts")
def list_alerts(acked: Optional[bool] = None, limit: int = 50) -> list:
    if acked is None:
        return db.query("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,))
    return db.query("SELECT * FROM alerts WHERE acked=? ORDER BY id DESC LIMIT ?",
                    (int(acked), limit))


@router.post("/alerts/{alert_id}/ack")
def ack_alert(alert_id: int) -> dict:
    n = db.execute("UPDATE alerts SET acked=1 WHERE id=?", (alert_id,))
    if not n:
        raise HTTPException(404, "alert not found")
    return {"id": alert_id, "acked": True}
