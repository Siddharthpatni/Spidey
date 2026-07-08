# 🕷️ What Spidey can be — the capability matrix

"Spider-Man can do anything" — here's the honest version. Spidey is **one hero with
many hats**: a role router reads each task and puts the right specialist hats on
(you'll see `🕸 Web-team hats on this job: …` at the start of a run), on top of the
standing team roles (Leader plans, Editor/Devil's-Advocate reviews before finish,
Notetaker remembers, Harmonizer listens).

Legend: ✅ works today with local tools · 🔑 works today via a cloud key you provide ·
🔜 roadmap (needs a new tool/model) · ❌ out of scope on purpose.

| # | Role | Status | How / why |
|---|---|---|---|
| 1 | General Assistant | ✅ | chat, explain, brainstorm, summarize, draft — with memory of you |
| 2 | Coding Assistant | ✅ | generate/debug/refactor/test via file+shell tools; CODING hat |
| 3 | Research Agent (local docs) | ✅ | reads/searches your files; RESEARCHER hat cites paths. Web search: 🔜 (offline-first by design) |
| 4 | File Manager | ✅ | verified: organizes folders by type; rename/dedupe/archive via shell |
| 5 | System Administrator | ✅ | monitor CPU/RAM/disks, read logs, manage services — SYSADMIN hat, read-only first |
| 6 | DevOps Engineer | ✅ | writes Dockerfiles/CI/IaC as files; running deploys needs your approval per command |
| 7 | Data Analyst | ✅ | CSV/JSON cleaning + stats via Python it writes and runs; DATA hat recomputes to verify |
| 8 | Database Assistant | ✅ | SQL generation/explanation; runs queries via CLI clients if installed |
| 9 | AI/ML Engineer | ✅ | the training/ pipeline IS this role: SFT→DPO, eval harness, prompt engineering |
| 10 | Vision AI | 🔜 | Gemma 4 is multimodal — image input over the chat API is a planned tool |
| 11 | Speech AI | ✅ | offline STT (Vosk) + TTS (OS voices) shipped; cloning/diarization ❌ |
| 12 | Video AI | 🔜 | needs frame-extraction tooling first |
| 13 | Home Automation | 🔜 | a Home-Assistant tool is a natural fit (local API) |
| 14 | Personal Knowledge Manager | ✅ | ~/.spidey/memory.md + remember tool; semantic search 🔜 |
| 15 | Calendar & Scheduling | 🔜 | needs a calendar tool (local ICS or CalDAV) |
| 16 | Email Agent | 🔜 | needs an IMAP/SMTP tool; drafting text ✅ today |
| 17 | Finance Assistant | ✅ | expense/budget math on your local files; investment *analysis* only, never advice-as-execution |
| 18 | Cybersecurity Assistant | ✅ | log analysis, phishing-text review, SECURITY hat (villain doctrine: analyze, never execute) |
| 19 | Network Engineer | ✅ | diagnostics via shell (ping/traceroute/lsof); packet capture needs your tools installed |
| 20 | Software Tester | ✅ | writes and runs tests; Editor hat reviews results |
| 21–22 | Robotics / Autonomous vehicles | ❌ | wrong tool for a laptop assistant |
| 23 | Education Tutor | ✅ | TUTOR hat: step-by-step + check-understanding questions |
| 24 | Creative Assistant | ✅ | WRITER hat; six Spider voices to write in |
| 25–26 | Image-gen prompts / Music | ✅ | text-level help today; generation itself needs external models |
| 27–29 | Business / Support / HR | ✅ | analysis + drafting on your documents |
| 30–31 | Legal / Medical docs | ✅* | summarization/organization only — *always says it's not a lawyer/doctor* |
| 32 | Engineering Assistant | ✅ | docs, BOMs, requirements from your files |
| 33 | IoT Manager | 🔜 | MQTT tool would unlock it |
| 34 | Game AI | ✅ | NPC dialogue, quests, balancing docs — creative + code hats |
| 35 | Multi-Agent Coordinator | ✅ | the web-team: plan (Leader) → act → Editor review gate |
| 36 | Workflow Automation | ✅ | writes and runs scripts; scheduled jobs via cron it can set up (with approval) |
| 37 | Memory Agent | ✅ | long-term memory + per-session continuity; vector search 🔜 |
| 38 | RAG Agent | 🔜 | top of the roadmap — local embeddings over your documents |
| 39 | Tool-Using Agent | ✅ | terminal, Python, git, files — the core of Spidey |
| 40 | Supervisor / QA Agent | ✅ | the Editor/Devil's-Advocate pass validates work before finish |

**The design choice behind the ❌/🔜:** Spidey ships nothing it can't do honestly and
offline. Every 🔜 is a new *tool* (a Python function + JSON schema in
[spidey/tools.py](../spidey/tools.py)) — the agent, safety layer, voice, memory and
team machinery already handle the rest. Adding a role is a contribution-sized task,
not a rewrite.
