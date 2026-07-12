"""Every capability module, end to end through the real API — no model, no
network: the deterministic paths must carry the whole feature set."""

import json
import textwrap

from tests.conftest import wait_for_job

SAMPLE_HTML = """
<html><head><title>ACME Widgets</title>
<meta property="og:title" content="ACME Widgets">
<script type="application/ld+json">{"@type":"Product","name":"Widget","price":"9.99"}</script>
</head><body>
<table><tr><th>Model</th><th>Price</th></tr><tr><td>W-1</td><td>9.99</td></tr></table>
<a href="/buy">Buy now</a><p>The finest widgets on the internet.</p>
</body></html>"""


# ------------------------------ web automation ------------------------------ #
def test_webauto_strategies_offline():
    from spidey.platform.modules.webauto import (extract_links, extract_structured,
                                                 extract_tables)
    s = extract_structured(SAMPLE_HTML)
    assert s["title"] == "ACME Widgets" and s["json_ld"][0]["name"] == "Widget"
    tables = extract_tables(SAMPLE_HTML)
    assert tables[0][1] == ["W-1", "9.99"]
    links = extract_links(SAMPLE_HTML, "https://acme.test/")
    assert links[0]["url"] == "https://acme.test/buy"


def test_webauto_approval_queue(client):
    r = client.post("/api/webauto/scrapes",
                    json={"url": "https://example.test/x", "require_approval": True}).json()
    assert r["status"] == "pending_approval"
    assert any(s["id"] == r["id"] for s in client.get("/api/webauto/approvals").json())
    denied = client.post(f"/api/webauto/scrapes/{r['id']}/approve",
                         json={"approved": False}).json()
    assert denied["status"] == "denied"


# ------------------------------ file pipeline ------------------------------- #
def test_filepipe_upload_process_notify(client):
    csv_body = "name,score\nalice,10\nbob,20\n"
    up = client.put("/api/files/upload?name=scores.csv", content=csv_body).json()
    assert up["status"] == "queued"
    row = wait_for_job(client, _last_job_id(client, "files.process"))
    assert row["status"] == "done"
    file_row = client.get(f"/api/files/{up['id']}").json()
    assert file_row["result"]["rows"] == 2
    assert file_row["result"]["profile"]["score"]["mean"] == 15.0
    events = client.get("/api/queue/notifications").json()
    assert any(n["event"] == "file.processed" for n in events)


def _last_job_id(client, kind):
    jobs = client.get("/api/queue/jobs?limit=50").json()
    return next(j["id"] for j in jobs if j["kind"] == kind)


# -------------------------------- analytics --------------------------------- #
def test_analytics_pipeline_and_alerts(client):
    batch = [{"name": "latency_ms", "value": v} for v in (100, 200, 300, 400, 1000)]
    assert client.post("/api/analytics/events", json=batch).json()["ingested"] == 5
    wait_for_job(client, _last_job_id(client, "analytics.rollup"))
    stats = client.get("/api/analytics/stats?name=latency_ms").json()
    assert stats["count"] == 5 and stats["avg"] == 400 and stats["max"] == 1000
    ts = client.get("/api/analytics/timeseries?name=latency_ms").json()
    assert ts and ts[0]["count"] == 5

    client.post("/api/analytics/rules", json={
        "name": "hot", "metric": "latency_ms", "op": ">", "threshold": 50,
        "aggregate": "avg", "window_seconds": 3600})
    from spidey.platform.core.queue import default_queue
    result = default_queue().run_sync("analytics.check_alerts", {})
    assert result["rules_triggered"] == 1
    alerts = client.get("/api/analytics/alerts").json()
    assert any("hot" in a["message"] for a in alerts)


# ---------------------------------- fleet ----------------------------------- #
def test_fleet_tracking_analytics_routes(client):
    v = client.post("/api/fleet/vehicles", json={
        "name": "Van 1", "plate": "B-SP 2099", "driver": "Miles",
        "odometer_km": 14000, "last_service_km": 0, "service_interval_km": 15000}).json()
    pings = [
        {"vehicle_id": v["id"], "speed_kmh": 50, "fuel_l": 60, "odometer_km": 14000,
         "ts": "2026-07-10T08:00:00+00:00"},
        {"vehicle_id": v["id"], "speed_kmh": 90, "fuel_l": 52, "odometer_km": 14100,
         "ts": "2026-07-11T08:00:00+00:00"},
        {"vehicle_id": v["id"], "speed_kmh": 140, "fuel_l": 44, "odometer_km": 14200,
         "ts": "2026-07-12T08:00:00+00:00"},
        {"vehicle_id": v["id"], "speed_kmh": 0, "fuel_l": 30, "odometer_km": 15100,
         "ts": "2026-07-12T20:00:00+00:00"},
    ]
    assert client.post("/api/fleet/pings", json=pings).json()["ingested"] == 4
    a = client.get(f"/api/fleet/vehicles/{v['id']}/analytics").json()
    assert a["fuel"]["l_per_100km"] is not None
    assert a["maintenance"]["due"] is True
    assert any(e["type"] == "speeding" for e in a["driver_events"])
    assert any(x["type"] == "fuel_drop_while_parked" for x in a["anomalies"])
    assert any(al["source"] == "fleet" for al in client.get("/api/fleet/alerts").json())

    # route optimization: optimal order for points on a line is the line order
    stops = [{"lat": 52.50, "lon": 13.40}, {"lat": 52.53, "lon": 13.40},
             {"lat": 52.51, "lon": 13.40}, {"lat": 52.52, "lon": 13.40}]
    r = client.post("/api/fleet/routes/optimize", json={"stops": stops}).json()
    assert r["order"] == [0, 2, 3, 1]


# ------------------------------- job matching -------------------------------- #
def test_resume_matching_gap_interview(client):
    resume = client.post("/api/match/resumes", json={
        "name": "Sid", "text": "Python engineer: FastAPI, Docker, PostgreSQL, "
                                "PyTorch, computer vision, ROS2."}).json()
    assert "python" in resume["skills"] and "docker" in resume["skills"]
    client.post("/api/match/jobs", json=[
        {"title": "Backend Engineer", "company": "A",
         "description": "Python, FastAPI, Docker, PostgreSQL microservices."},
        {"title": "Frontend Developer", "company": "B",
         "description": "React, TypeScript, CSS, Next.js pixel-perfect UIs."}])
    matches = client.get(f"/api/match/resumes/{resume['id']}/matches").json()
    assert matches[0]["title"] == "Backend Engineer"
    assert matches[0]["match"] > matches[1]["match"]
    front_id = next(m["id"] for m in matches if m["title"] == "Frontend Developer")
    gap = client.get(f"/api/match/resumes/{resume['id']}/gap/{front_id}").json()
    assert "react" in gap["missing"]
    assert gap["roadmap"]["steps"]
    iq = client.get(f"/api/match/jobs/{front_id}/interview").json()
    assert len(iq["questions"]) >= 5


# --------------------------------- research ---------------------------------- #
def test_research_ingest_ask_flashcards_compare(client):
    paper_a = textwrap.dedent("""\
        Spiders and Distributed Systems

        A web crawler is a program that systematically browses the internet.
        Politeness is the practice of rate-limiting requests per host.

        Crawlers use a frontier queue to order URLs. The frontier is prioritized
        by page importance and freshness. [1] Brin & Page 1998 describe the anatomy
        of a large-scale search engine.""")
    a = client.post("/api/research/docs", json={"title": "Crawling", "text": paper_a}).json()
    assert a["chunks"] >= 1
    b = client.post("/api/research/docs", json={
        "title": "Cooking", "text": "Pasta is boiled in salted water. Sauce needs garlic. "
                                    "A rolling boil means large bubbles."}).json()
    ans = client.post("/api/research/ask",
                      json={"question": "What is politeness in crawling?",
                            "doc_id": a["id"]}).json()
    assert "rate-limiting" in ans["answer"] or "Politeness" in ans["answer"]
    assert ans["citations"]
    cards = client.get(f"/api/research/docs/{a['id']}/flashcards").json()
    assert any("crawler" in c["q"].lower() or "politeness" in c["q"].lower() for c in cards)
    cmp_ = client.get(f"/api/research/compare?a={a['id']}&b={b['id']}").json()
    assert cmp_["similarity"] < 0.9
    cites = client.get(f"/api/research/docs/{a['id']}/citations").json()
    assert cites["numbered"]
    summary = client.get(f"/api/research/docs/{a['id']}/summary").json()
    assert summary["summary"]


# ------------------------------- code assistant ------------------------------- #
BUGGY = textwrap.dedent("""\
    def load(path, cache=[]):
        f = open(path)
        data = f.read()
        if data == None:
            return []
        try:
            return parse(data)
        except:
            print("failed")  # TODO: handle properly
            return cache
    """)


def test_code_bugs_tests_diagram(client, tmp_path):
    findings = client.post("/api/code/bugs", json={"code": BUGGY}).json()["findings"]
    kinds = {f["kind"] for f in findings}
    assert {"mutable-default", "bare-except", "none-comparison",
            "unclosed-file", "debug-print", "todo"} <= kinds

    tests = client.post("/api/code/gen-tests", json={"code": BUGGY}).json()["tests"]
    assert "def test_load()" in tests and "pytest.raises" in tests

    # index a tiny repo and ask about it
    (tmp_path / "auth.py").write_text("def check_password(pw):\n    return pw == 'secret'\n")
    (tmp_path / "main.py").write_text("import auth\n\ndef run():\n    return auth.check_password('x')\n")
    idx = client.post("/api/code/index", json={"path": str(tmp_path)}).json()
    assert idx["files"] == 2 and idx["chunks"] >= 2
    ask = client.post("/api/code/ask", json={"repo": str(tmp_path),
                                             "question": "where is the password checked?"}).json()
    assert any("auth.py" in c["text"] for c in ask["chunks"])
    diagram = client.get(f"/api/code/diagram?path={tmp_path}").json()["mermaid"]
    assert "main[main] --> auth[auth]" in diagram


# ------------------------------- email assistant ------------------------------- #
EML = """From: Boss <boss@acme.test>
To: you@acme.test
Subject: URGENT: budget meeting tomorrow
Date: Fri, 10 Jul 2026 10:00:00 +0000
Content-Type: text/plain

Can you join the budget meeting on 2026-07-13 at 14:30? It's important —
deadline is EOD tomorrow. Please confirm today.
"""


def test_email_import_classify_reply_calendar_rag(client):
    imp = client.post("/api/email/import", json={"raw": EML}).json()
    assert imp["category"] == "meeting"
    assert imp["priority"] >= 0.5
    msgs = client.get("/api/email/messages").json()
    assert msgs[0]["id"] == imp["id"]  # highest priority first
    reply = client.post(f"/api/email/messages/{imp['id']}/reply").json()
    assert reply["draft"]
    cal = client.get(f"/api/email/messages/{imp['id']}/calendar").json()
    assert cal and cal[0]["start"].startswith("2026-07-13T14:30")
    assert "BEGIN:VCALENDAR" in cal[0]["ics"]
    ask = client.post("/api/email/ask", json={"question": "when is the budget meeting?"}).json()
    assert ask["sources"][0]["email"] == imp["id"]


# -------------------------------- driving data --------------------------------- #
def test_driving_ingest_replay_collision_report(client):
    s = client.post("/api/driving/sessions", json={"name": "test drive"}).json()
    frames = [
        {"ts": 0.0, "speed_kmh": 50, "objects": []},
        {"ts": 1.0, "speed_kmh": 50,
         "objects": [{"id": "car-1", "distance_m": 40, "rel_speed_ms": -15}]},
        {"ts": 2.0, "speed_kmh": 30,
         "objects": [{"id": "car-1", "distance_m": 25, "rel_speed_ms": -15}]},
        {"ts": 3.0, "speed_kmh": 10, "objects": []},
    ]
    r = client.post(f"/api/driving/sessions/{s['id']}/frames", json=frames).json()
    assert r["ingested"] == 4
    replay = client.get(f"/api/driving/sessions/{s['id']}/replay?start=1&count=2").json()
    assert replay[0]["seq"] == 1 and len(replay) == 2
    analytics = client.get(f"/api/driving/sessions/{s['id']}/analytics").json()
    assert analytics["collision"]["warnings"], "TTC 25/15≈1.7s must be flagged"
    assert analytics["collision"]["min_ttc_s"] < 3
    assert analytics["behavior"]["harsh_brakes"]
    report = client.get(f"/api/driving/sessions/{s['id']}/report")
    assert report.headers["content-type"].startswith("text/markdown")
    assert "CRITICAL" in report.text

    # CSV ingestion path
    csv_frames = "ts,speed_kmh\n4.0,20\n5.0,25\n"
    r2 = client.post(f"/api/driving/sessions/{s['id']}/frames", content=csv_frames,
                     headers={"content-type": "text/csv"}).json()
    assert r2["ingested"] == 2


# ------------------------------- multi-agent team ------------------------------- #
def test_team_run_without_model_fails_cleanly(client):
    import os
    os.environ["SPIDEY_LLM_PROVIDER"] = "ollama"
    os.environ["OLLAMA_HOST"] = "http://127.0.0.1:1"  # guaranteed unreachable
    try:
        run = client.post("/api/team/runs", json={"goal": "build a URL shortener",
                                                  "roles": ["planner"]}).json()
        row = wait_for_job(client, _last_job_id(client, "team.run"))
        assert row["status"] == "failed"
        assert "needs a model" in row["error"]
        status = client.get(f"/api/team/runs/{run['id']}").json()
        assert status["status"] == "failed"
    finally:
        os.environ.pop("OLLAMA_HOST", None)
    assert len(client.get("/api/team/roles").json()) == 6


# --------------------------------- dashboard ---------------------------------- #
def test_dashboard_and_openapi(client):
    page = client.get("/platform")
    assert page.status_code == 200 and "Spidey" in page.text
    spec = client.get("/openapi.json").json()
    tags = {t for p in spec["paths"].values() for op in p.values()
            for t in op.get("tags", [])}
    assert {"Web Automation", "File Pipeline", "Analytics", "Fleet", "Job Matching",
            "Research", "Code Assistant", "Email Assistant", "Driving Data",
            "Multi-Agent Team", "LLM Gateway", "Queue", "Scheduler", "Auth"} <= tags


# ------------------- LOGICS ports: gateway, writers, analyzer ------------------- #
def test_llm_gateway_traces_calls(client):
    """A call to a nonexistent model must 502 — and still land in the trace log."""
    r = client.post("/api/llm/chat", json={"prompt": "hi",
                                           "model": "definitely-not-a-model:0b"})
    assert r.status_code == 502
    calls = client.get("/api/llm/calls").json()
    assert calls and calls[0]["status"] == "error"
    assert calls[0]["model"] == "definitely-not-a-model:0b"
    stats = client.get("/api/llm/stats").json()
    assert stats["totals"]["calls"] >= 1


def test_llm_cost_estimation():
    from spidey.platform.core.llmutil import estimate_cost, estimate_tokens
    assert estimate_cost("ollama", "gemma4:12b", 1000, 1000) == 0.0
    hosted = estimate_cost("anthropic", "claude-sonnet-5", 1_000_000, 0)
    assert hosted == 3.00
    assert estimate_tokens("abcd" * 100) == 100


def test_resume_writer_and_ats(client):
    resume = client.post("/api/match/resumes", json={
        "name": "Sid", "text": "Python engineer. FastAPI, Docker, PostgreSQL."}).json()
    job = client.post("/api/match/jobs", json=[{
        "title": "ML Engineer", "company": "Rocket",
        "description": "PyTorch, TensorFlow, MLOps, Kubernetes required."}]).json()["ids"][0]
    ats = client.get(f"/api/match/resumes/{resume['id']}/ats/{job}").json()
    assert 0 <= ats["match_score"] <= 100
    assert "pytorch" in ats["missing"] and ats["advice"]
    cover = client.post(f"/api/match/resumes/{resume['id']}/cover-letter?job_id={job}").json()
    assert cover["markdown"] and cover["mode"] in ("llm", "template")
    written = client.post(f"/api/match/resumes/{resume['id']}/write").json()
    assert "Core Skills" in written["markdown"] or written["mode"] == "llm"


def test_document_analyzer_vergabepilot_port(client):
    tender = ("Tender for cloud migration services. The submission deadline is "
              "15.03.2099, 10:00 Uhr at the procurement office. Estimated contract "
              "value: 250.000,00 EUR over two years. All bidders must provide ISO "
              "27001 certification before award. Questions until 2099-03-01. "
              "Contact: vergabe@stadt.example.de or +49 30 1234567.")
    doc = client.post("/api/research/docs", json={"title": "Tender", "text": tender}).json()
    a = client.get(f"/api/research/docs/{doc['id']}/analyze").json()
    parsed = {d["raw"]: d for d in a["deadlines"]}
    assert any(d.startswith("15.03.2099") for d in parsed), a["deadlines"]
    dmy = next(v for k, v in parsed.items() if k.startswith("15.03.2099"))
    assert dmy["parsed"].startswith("2099-03-15T10:00") and dmy["is_future"]
    assert a["next_deadline"]["parsed"].startswith("2099-03-01T23:59")  # EOD default
    assert any("250.000,00" in amt for amt in a["amounts"])
    assert "vergabe@stadt.example.de" in a["contacts"]["emails"]
    assert any("must provide" in r for r in a["requirements"])
