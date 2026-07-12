"""Numbered schema migrations. Append-only: never edit an applied block —
add a new ``(version, sql)`` pair instead. The runner in :mod:`.db` records
applied versions in ``schema_migrations``."""

MIGRATIONS = [
    (1, """
    -- platform core ------------------------------------------------------
    CREATE TABLE api_keys(
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, key_hash TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL, last_used_at TEXT);

    CREATE TABLE jobs(
        id INTEGER PRIMARY KEY, kind TEXT NOT NULL, payload TEXT,
        status TEXT NOT NULL DEFAULT 'queued',      -- queued|running|done|failed
        attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3,
        run_after TEXT, started_at TEXT, finished_at TEXT,
        result TEXT, error TEXT, created_at TEXT NOT NULL);
    CREATE INDEX idx_jobs_claim ON jobs(status, run_after, id);

    CREATE TABLE schedules(
        id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
        payload TEXT, interval_seconds INTEGER NOT NULL,
        next_run_at TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
        last_enqueued_at TEXT, created_at TEXT NOT NULL);

    CREATE TABLE webhooks(
        id INTEGER PRIMARY KEY, event TEXT NOT NULL, url TEXT NOT NULL,
        created_at TEXT NOT NULL);
    CREATE TABLE notifications(
        id INTEGER PRIMARY KEY, event TEXT NOT NULL, payload TEXT,
        delivered INTEGER NOT NULL DEFAULT 0, ts TEXT NOT NULL);

    -- web automation -------------------------------------------------------
    CREATE TABLE scrapes(
        id INTEGER PRIMARY KEY, url TEXT NOT NULL, strategy TEXT NOT NULL,
        instruction TEXT, status TEXT NOT NULL DEFAULT 'queued',
        -- pending_approval|queued|running|done|failed|denied
        data TEXT, error TEXT, created_at TEXT NOT NULL, finished_at TEXT);

    -- file pipeline ----------------------------------------------------------
    CREATE TABLE files(
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL,
        size INTEGER NOT NULL, sha256 TEXT NOT NULL, content_type TEXT,
        status TEXT NOT NULL DEFAULT 'queued', result TEXT, error TEXT,
        created_at TEXT NOT NULL);

    -- analytics ------------------------------------------------------------
    CREATE TABLE events(
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, value REAL NOT NULL DEFAULT 1,
        props TEXT, ts TEXT NOT NULL);
    CREATE INDEX idx_events_name_ts ON events(name, ts);
    CREATE TABLE rollups(
        name TEXT NOT NULL, bucket TEXT NOT NULL,   -- bucket = minute ISO stamp
        count INTEGER NOT NULL, sum REAL NOT NULL, min REAL NOT NULL, max REAL NOT NULL,
        PRIMARY KEY(name, bucket));
    CREATE TABLE alert_rules(
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, metric TEXT NOT NULL,
        op TEXT NOT NULL CHECK(op IN ('>', '<', '>=', '<=')),
        threshold REAL NOT NULL, window_seconds INTEGER NOT NULL DEFAULT 300,
        aggregate TEXT NOT NULL DEFAULT 'avg',      -- avg|sum|count|max|min
        enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
    CREATE TABLE alerts(
        id INTEGER PRIMARY KEY, source TEXT NOT NULL, message TEXT NOT NULL,
        value REAL, ts TEXT NOT NULL, acked INTEGER NOT NULL DEFAULT 0);

    -- fleet ------------------------------------------------------------------
    CREATE TABLE vehicles(
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, plate TEXT UNIQUE,
        driver TEXT, odometer_km REAL NOT NULL DEFAULT 0,
        last_service_km REAL NOT NULL DEFAULT 0,
        service_interval_km REAL NOT NULL DEFAULT 15000,
        created_at TEXT NOT NULL);
    CREATE TABLE pings(
        id INTEGER PRIMARY KEY, vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),
        lat REAL, lon REAL, speed_kmh REAL, fuel_l REAL, odometer_km REAL,
        ts TEXT NOT NULL);
    CREATE INDEX idx_pings_vehicle ON pings(vehicle_id, ts);

    -- resume / job matching ---------------------------------------------------
    CREATE TABLE resumes(
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, text TEXT NOT NULL,
        skills TEXT, vec TEXT, created_at TEXT NOT NULL);
    CREATE TABLE job_posts(
        id INTEGER PRIMARY KEY, title TEXT NOT NULL, company TEXT,
        description TEXT NOT NULL, skills TEXT, vec TEXT, created_at TEXT NOT NULL);

    -- research corpus ---------------------------------------------------------
    CREATE TABLE docs(
        id INTEGER PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL,
        source TEXT, created_at TEXT NOT NULL);
    CREATE TABLE doc_chunks(
        id INTEGER PRIMARY KEY, doc_id INTEGER NOT NULL REFERENCES docs(id),
        seq INTEGER NOT NULL, text TEXT NOT NULL, vec TEXT NOT NULL);
    CREATE INDEX idx_doc_chunks ON doc_chunks(doc_id, seq);

    -- code assistant -----------------------------------------------------------
    CREATE TABLE repo_chunks(
        id INTEGER PRIMARY KEY, repo TEXT NOT NULL, path TEXT NOT NULL,
        start_line INTEGER NOT NULL, text TEXT NOT NULL, vec TEXT NOT NULL);
    CREATE INDEX idx_repo_chunks ON repo_chunks(repo);

    -- email assistant -----------------------------------------------------------
    CREATE TABLE emails(
        id INTEGER PRIMARY KEY, uid TEXT, folder TEXT, sender TEXT, subject TEXT,
        date TEXT, body TEXT, category TEXT, priority REAL, vec TEXT,
        created_at TEXT NOT NULL, UNIQUE(uid, folder));

    -- driving data ---------------------------------------------------------------
    CREATE TABLE drive_sessions(
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, meta TEXT, created_at TEXT NOT NULL);
    CREATE TABLE drive_frames(
        id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES drive_sessions(id),
        seq INTEGER NOT NULL, ts REAL NOT NULL, data TEXT NOT NULL);
    CREATE INDEX idx_drive_frames ON drive_frames(session_id, seq);

    -- multi-agent team ---------------------------------------------------------
    CREATE TABLE team_runs(
        id INTEGER PRIMARY KEY, goal TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
        transcript TEXT, created_at TEXT NOT NULL, finished_at TEXT);
    """),

    (2, """
    -- LLM gateway: every model call, observed (the Sentinel port) ---------------
    CREATE TABLE llm_calls(
        id INTEGER PRIMARY KEY, provider TEXT NOT NULL, model TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'gateway',      -- gateway | internal
        prompt TEXT, response TEXT,
        prompt_tokens_est INTEGER, completion_tokens_est INTEGER,
        cost_usd REAL, latency_ms REAL,
        status TEXT NOT NULL,                         -- ok | error
        ts TEXT NOT NULL);
    CREATE INDEX idx_llm_calls_ts ON llm_calls(ts);
    """),

    (3, """
    -- workspaces: every action in the studio is recorded and restorable ---------
    CREATE TABLE sessions(
        id INTEGER PRIMARY KEY, name TEXT NOT NULL,
        created_at TEXT NOT NULL, last_active_at TEXT NOT NULL);
    CREATE TABLE session_items(
        id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id),
        module TEXT NOT NULL, action TEXT NOT NULL,
        input TEXT, output TEXT, ref_id INTEGER,      -- e.g. generated doc id
        ts TEXT NOT NULL);
    CREATE INDEX idx_session_items ON session_items(session_id, id);

    -- document studio: AI-generated files in every format ------------------------
    CREATE TABLE generated_docs(
        id INTEGER PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL,
        format TEXT NOT NULL, path TEXT NOT NULL, size INTEGER NOT NULL,
        prompt TEXT, markdown TEXT, mode TEXT,        -- llm | template | render
        created_at TEXT NOT NULL);

    -- deep-research papers: long jobs with visible per-section progress ----------
    CREATE TABLE paper_runs(
        id INTEGER PRIMARY KEY, topic TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued',        -- queued|researching|writing|done|failed
        progress TEXT,                                -- json: stage + sections done
        sources TEXT,                                 -- json: fetched references
        doc_id INTEGER REFERENCES generated_docs(id),
        error TEXT, created_at TEXT NOT NULL, finished_at TEXT);
    """),

    (4, """
    -- the knowledge graph: everything Spidey learns becomes connected -----------
    CREATE TABLE kg_nodes(
        id INTEGER PRIMARY KEY, type TEXT NOT NULL, name TEXT NOT NULL,
        props TEXT, weight REAL NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(type, name));
    CREATE INDEX idx_kg_nodes_name ON kg_nodes(name);
    CREATE TABLE kg_edges(
        id INTEGER PRIMARY KEY,
        src INTEGER NOT NULL REFERENCES kg_nodes(id),
        dst INTEGER NOT NULL REFERENCES kg_nodes(id),
        rel TEXT NOT NULL DEFAULT 'related_to', weight REAL NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL, UNIQUE(src, dst, rel));
    CREATE INDEX idx_kg_edges_src ON kg_edges(src);
    CREATE INDEX idx_kg_edges_dst ON kg_edges(dst);
    """),
]
