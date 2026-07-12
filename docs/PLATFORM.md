# The Spidey Platform

Eleven production-style capability modules on one shared core. Everything below is
served by the same process as the agent (`spidey serve` / `spidey up`) — REST under
`/api/*`, interactive OpenAPI docs at **`/docs`**, Prometheus metrics at **`/metrics`**,
and the **Spider-Verse Studio at `/platform`**: a React single-page app (same
bundle as the agent chat, a Spider-Verse boot screen, a responsive sidebar of AI
tools that swap in place, back/reload buttons, and a cross-device session picker).
If you're new here, start at `/platform` — you can drive every feature below with
buttons before ever writing a curl command.

```
                          ┌───────────────────────────────┐
    browser / curl ──────▶│        FastAPI gateway        │──▶ /docs (OpenAPI)
                          └──────────────┬────────────────┘
                 ┌───────────────────────┼───────────────────────┐
                 ▼                       ▼                       ▼
        capability modules         shared core              agent (/ws)
   webauto · files · analytics   SQLite + migrations      chat + live graph
   fleet · match · research      job queue + retries
   code · email · driving        scheduler · API keys
   team                          metrics · webhooks
                                 embeddings/vector store
                                 LLM bridge (Ollama/BYOK)
```

**Design rule:** the platform runs on the standard library + `requests`. Optional
packages *unlock* extras (Playwright rendering, OCR, OpenCV vision, PDF parsing,
real embeddings) — and every AI-assisted feature has a deterministic fallback, so
nothing 500s just because no model is running. `GET /api/health` shows which
extras are active.

## The shared core

| Piece | What it gives every module |
|---|---|
| **SQLite + migrations** | one file at `~/.spidey/platform.db` (override `$SPIDEY_DB`); versioned migrations in `spidey/platform/core/migrations.py` |
| **Job queue + retry engine** | persistent jobs, 3 worker threads, exponential backoff (10s·n²), failed-job inspection + manual retry: `/api/queue/*` |
| **Scheduler** | recurring jobs (`interval_seconds`) that enqueue on the queue: `/api/schedules` |
| **Auth** | API keys (`POST /api/keys`, sent as `X-API-Key`); open with no keys+no `$SPIDEY_TOKEN` (local mode), enforced the moment a credential exists |
| **Metrics** | Prometheus text at `/metrics` — jobs, scrapes, LLM calls, alerts, webhooks |
| **Webhooks / notify** | `POST /api/queue/webhooks {event, url}` — `*` or e.g. `file.processed`, `alert.triggered`, `scrape.done`, `team.run_done` |
| **Vector store + embeddings** | hashed TF vectors (offline, deterministic); auto-upgrades if `sentence-transformers` is installed |
| **LLM bridge** | modules call the model through Spidey's backend stack (Ollama default; `SPIDEY_LLM_PROVIDER`/`SPIDEY_LLM_MODEL` for Claude/Gemini/GPT). Every call is observed: latency + status land in analytics (`llm.latency_ms`) and `/metrics` — the Sentinel idea, built in |

## Modules

### 1 · Web Automation — `/api/webauto`
Extraction ladder: `structured` (JSON-LD/OpenGraph) → `tables` → `links` → `text`
(readability) → `ai` (model turns page + instruction into JSON). Plus `selector`
(bs4), `regex`, `render` (Playwright), OCR (`/ocr`), screenshots with analysis
(`/screenshot`). Scrapes run on the queue (retries for free; schedule kind
`webauto.scrape` for recurring). `require_approval: true` holds a scrape in the
**human approval queue** (`GET /approvals`, `POST /scrapes/{id}/approve`).

```bash
curl -X POST localhost:8000/api/webauto/scrape-now \
  -H 'content-type: application/json' \
  -d '{"url": "https://news.ycombinator.com", "strategy": "links"}'
```

### 2 · Driving Data — `/api/driving`
Sessions + frame ingestion (JSON array or CSV; ROS 2 bags with `pip install rosbags`),
replay windows, behavior analytics (speed profile, harsh-brake detection),
**TTC collision prediction** (range/closing-speed per object, <3s flagged — the AEB
trigger metric), markdown/JSON reports, and with OpenCV: HOG pedestrian detection +
Canny/Hough lane finding on images.

### 3 · Resume + Job Matching — `/api/match`
Resume (text/PDF/DOCX) → skills (curated dictionary) + embedding → ranked matches
(60% cosine, 40% hard skill overlap — the jobflow formula) → skill gap → learning
roadmap → interview questions.

### 4 · Code Assistant — `/api/code`
`index` a repo (60-line chunks → vector store) then `ask` it questions; `explain`
files; `bugs` (AST: mutable defaults, bare except, `== None`, unclosed files, debug
prints, TODOs); `review` (git diff + heuristics + model); `gen-tests` (pytest
skeletons from real signatures); `diagram` (Mermaid import graph).

### 5 · Research Assistant — `/api/research`
Ingest PDFs/DOCX/text → chunk + embed; `ask` with citations (model answer, or
extractive top-sentences offline); per-doc `summary`, `notes` (outline),
`flashcards`, `citations` (numbered + author-year), and `compare?a=&b=`.

### 6 · Fleet — `/api/fleet`
Vehicles + telemetry pings → track history, fuel analytics (L/100km, refuel log),
maintenance prediction (km/day → days-until-service; auto-alert when due), driver
events (harsh accel/brake, speeding), anomaly detection (speed z-scores, fuel drops
while parked), and route optimization (nearest-neighbor + 2-opt, ≤40 stops).

### 7 · File Pipeline — `/api/files`
`PUT /upload?name=x.csv` (raw body — `curl -T` works) → content-addressed storage →
queue → processor by type (CSV column profiling, JSON shape, zip inventory, image
dimensions from header bytes, PDF text, text stats) → `file.processed` webhook.

### 8 · Email Assistant — `/api/email`
IMAP `sync` (Gmail app passwords work; credentials used once, never stored) or
offline `.eml` `import` → rule+model categorization (meeting/billing/recruiting/…),
priority scoring (urgency words, questions, sender history), smart `reply` drafts,
`calendar` suggestions (datetime detection → ready ICS), and `ask` = RAG over your mail.

### 9 · Analytics — `/api/analytics`
`POST /events` (single/batch) → raw store + minute rollups on the queue →
`timeseries`, `stats` (count/avg/min/max/p50/p95/p99), alert `rules`
(avg/sum/count/min/max over a window, evaluated every 60s by the scheduler) →
`alerts` + `alert.triggered` webhooks.

### 10 · Multi-Agent Team — `/api/team`
`POST /runs {goal}` → **Planner → Researcher → Coder → Reviewer → Tester →
Documentation**, each role a focused model call receiving everything before it
(shared memory). Runs execute on the queue; `GET /runs/{id}` streams the growing
transcript. Requires a model (this one has no offline fallback — it *is* the model).

### 11 · LLM Gateway — `/api/llm` *(the Sentinel port)*
`POST /chat {prompt, provider?, model?, api_key?}` proxies through Spidey's backend
stack and traces the call: latency, estimated tokens, estimated USD cost (static
cost tables; **$0 on Ollama/local**). `GET /calls` browses the trace log (internal
module calls are traced too, tagged `source=internal`), `GET /stats` aggregates
calls/errors/latency/spend per provider+model — a self-hosted LLM observability
plane. Keys are used per-call and never stored.

**Job Matching extras (jobflow ports):** `POST /api/match/resumes/{id}/write`
(ATS résumé in Markdown, optionally `?job_id=` tailored),
`POST .../cover-letter?job_id=` (250–350-word human letter),
`GET .../ats/{job_id}` (brutally honest fit report: score, verdict, missing
keywords, concrete advice).

**Research extras (vergabepilot port):** `GET /api/research/docs/{id}/analyze` —
deadlines (German `15.03.2026, 10:00 Uhr` **and** ISO, end-of-day default when no
time given), next-deadline pick, money amounts, contact extraction, and
requirement sentences (must/shall/muss/erforderlich…). Pure regex, works offline.

## The agent meets the platform

Two new tools in the agent's registry:
- **`scrape_page`** — the agent can pull live web data mid-task (through the same
  extraction ladder, with user approval per fetch).
- **`platform_status`** — queue depth + active alerts, so "how's the system doing?"
  has a real answer.

## Ops checklist

```bash
pip install -e ".[server]"          # platform included — stdlib core
pip install -e ".[scrape,pdf,ocr,vision,embeddings]"   # optional power-ups
spidey serve                        # → /platform, /docs, /metrics
pytest tests/ -q                    # 21 tests, all offline
```

Auth: `curl -X POST localhost:8000/api/keys -d '{"name":"me"}' -H 'content-type: application/json'`
→ send the returned key as `X-API-Key` on every request (and paste it into /platform).

Prometheus scrape config: target `host:8000`, path `/metrics`. Grafana reads the
same counters (`spidey_jobs_processed_total`, `spidey_llm_calls_total`,
`spidey_scrapes_total`, `spidey_alerts_triggered_total`, …).
