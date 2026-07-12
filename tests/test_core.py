"""Core infrastructure: migrations, queue + retry engine, scheduler math,
vectors, auth keys."""

import pytest

from spidey.platform.core import db
from spidey.platform.core.text import (chunk_text, cosine, embed,
                                       extractive_summary, match_score,
                                       strip_html, tokenize)


def test_migrations_applied(isolated_db):
    versions = [r["version"] for r in db.query("SELECT version FROM schema_migrations")]
    assert versions == [1, 2, 3, 4]
    tables = {r["name"] for r in db.query(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"jobs", "schedules", "events", "vehicles", "resumes", "docs",
            "repo_chunks", "emails", "drive_sessions", "team_runs",
            "llm_calls", "sessions", "generated_docs", "paper_runs",
            "kg_nodes", "kg_edges"} <= tables


def test_embed_cosine_ranking():
    py = embed("python fastapi backend developer with docker")
    ml = embed("deep learning pytorch computer vision engineer")
    q = embed("looking for a python backend engineer who knows fastapi")
    assert cosine(q, py) > cosine(q, ml)
    assert 0 <= match_score(cosine(q, py)) <= 100


def test_tokenize_and_chunks():
    assert "fastapi" in tokenize("The FastAPI framework!")
    assert "the" not in tokenize("the the the")
    chunks = chunk_text("para one\n\n" + "x" * 3000 + "\n\npara three", size=1200)
    assert len(chunks) >= 3
    assert all(len(c) <= 1200 for c in chunks)


def test_strip_html_and_summary():
    text = strip_html("<html><script>bad()</script><h1>Title</h1><p>Real text here.</p>")
    assert "bad()" not in text and "Real text here." in text
    long_text = " ".join(f"Sentence number {i} talks about spiders and webs." for i in range(30))
    summary = extractive_summary(long_text, 3)
    assert 0 < len(summary) < len(long_text)


def test_queue_retry_engine(client):
    """A handler that fails twice then succeeds must be retried and finish 'done'."""
    from spidey.platform.core.queue import default_queue
    q = default_queue()
    calls = {"n": 0}

    def flaky(payload):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("transient")
        return {"ok": True, "attempts": calls["n"]}

    q.register("test.flaky", flaky)
    job_id = q.enqueue("test.flaky", {}, max_attempts=5)
    # collapse the backoff so the test is fast
    for _ in range(40):
        import time
        db.execute("UPDATE jobs SET run_after=NULL WHERE id=? AND status='queued'", (job_id,))
        row = db.one("SELECT status FROM jobs WHERE id=?", (job_id,))
        if row["status"] == "done":
            break
        time.sleep(0.2)
    assert row["status"] == "done"
    assert calls["n"] == 3


def test_queue_failure_lands_in_failed_and_manual_retry(client):
    from spidey.platform.core.queue import default_queue
    q = default_queue()
    q.register("test.alwaysfails", lambda p: 1 / 0)
    job_id = q.enqueue("test.alwaysfails", {}, max_attempts=1)
    from tests.conftest import wait_for_job
    row = wait_for_job(client, job_id)
    assert row["status"] == "failed" and "ZeroDivisionError" in row["error"]
    assert client.post(f"/api/queue/jobs/{job_id}/retry").json()["status"] == "queued"


def test_auth_flow(client):
    # open by default (no keys, no token)
    assert client.get("/api/queue/jobs").status_code == 200
    key = client.post("/api/keys", json={"name": "ci"}).json()["key"]
    try:
        # now locked: same request without the key must 401
        assert client.get("/api/queue/jobs").status_code == 401
        assert client.get("/api/queue/jobs", headers={"X-API-Key": "wrong"}).status_code == 401
        ok = client.get("/api/queue/jobs", headers={"X-API-Key": key})
        assert ok.status_code == 200
    finally:  # unlock for the rest of the suite
        rows = client.get("/api/keys", headers={"X-API-Key": key}).json()
        for r in rows:
            client.delete(f"/api/keys/{r['id']}", headers={"X-API-Key": key})


def test_health_and_metrics(client):
    health = client.get("/api/health").json()
    assert health["status"] == "ok" and len(health["modules"]) == 15
    metrics = client.get("/metrics").text
    assert "spidey_uptime_seconds" in metrics


def test_scheduler_fires(client):
    import time
    from spidey.platform.core.queue import default_queue
    hits = []
    default_queue().register("test.tick", lambda p: hits.append(1) or {})
    client.post("/api/schedules", json={"name": "t1", "kind": "test.tick",
                                        "interval_seconds": 5})
    # force it due immediately instead of waiting the interval
    db.execute("UPDATE schedules SET next_run_at=? WHERE name='t1'", (db.now(),))
    deadline = time.time() + 12
    while not hits and time.time() < deadline:
        time.sleep(0.3)
    client.request("DELETE", "/api/schedules/1")
    assert hits, "scheduler never enqueued the due job"
