"""The /platform dashboard — a self-contained interactive playground.

Every module gets a working "Try it" panel (forms → live API calls → results),
so the platform is usable without curl or Swagger. Includes a ⌘K command
palette (ported from the author's portfolio site), live stat tiles, the job
queue, alerts, and the LLM call trace. One file, vanilla JS, no build step;
the React app at / stays the agent's home.
"""

DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Spidey Platform</title>
<style>
  :root { --bg:#0b0b10; --card:#15151d; --panel:#101018; --line:#262633;
          --text:#e9e9f0; --dim:#9a9aa8; --red:#e62429; --blue:#5b9bff;
          --green:#34d399; --amber:#fbbf24; }
  * { box-sizing:border-box; margin:0; }
  body { background:var(--bg); color:var(--text);
         font:14px/1.55 -apple-system,"Segoe UI",Roboto,sans-serif; padding:1.5rem; }
  a { color:var(--blue); text-decoration:none; }
  h1 { font-size:1.4rem; } h1 em { color:var(--red); font-style:normal; }
  .sub { color:var(--dim); margin:.2rem 0 1rem; font-size:.9rem; }
  .topbar { display:flex; flex-wrap:wrap; gap:.6rem; align-items:center; margin-bottom:1.2rem; }
  .pill { display:inline-block; padding:.12rem .6rem; border-radius:99px; font-size:.75rem;
          background:#22222e; color:var(--dim); }
  .ok { color:var(--green); } .bad { color:var(--red); } .warn { color:var(--amber); }
  input, textarea, select {
    background:var(--panel); color:var(--text); border:1px solid var(--line);
    border-radius:8px; padding:.45rem .6rem; font:inherit; }
  input, select { height:34px; }
  textarea { width:100%; min-height:70px; resize:vertical; }
  button { background:var(--red); color:#fff; border:0; border-radius:8px;
           padding:.45rem .9rem; font:600 .82rem/1 inherit; cursor:pointer; }
  button.ghost { background:#22222e; color:var(--text); }
  button:hover { filter:brightness(1.15); }
  .stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
           gap:.8rem; margin-bottom:1.2rem; }
  .stat { background:var(--card); border:1px solid var(--line); border-radius:12px;
          padding:.7rem 1rem; }
  .stat b { font-size:1.25rem; display:block; }
  .stat span { color:var(--dim); font-size:.75rem; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(340px,1fr)); gap:1rem; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:14px;
          padding:1rem 1.1rem; }
  .card h3 { font-size:.95rem; margin-bottom:.2rem; }
  .card > p { color:var(--dim); font-size:.8rem; margin-bottom:.6rem; }
  details summary { cursor:pointer; color:var(--blue); font-size:.82rem;
                    font-weight:600; user-select:none; }
  details[open] summary { margin-bottom:.6rem; }
  .form { display:flex; flex-direction:column; gap:.45rem; }
  .row { display:flex; gap:.45rem; flex-wrap:wrap; }
  .row > * { flex:1; min-width:110px; }
  .row > button { flex:0; min-width:auto; }
  pre.out { background:var(--panel); border:1px solid var(--line); border-radius:8px;
            padding:.6rem; font-size:.75rem; max-height:260px; overflow:auto;
            white-space:pre-wrap; word-break:break-word; margin-top:.4rem; }
  pre.out:empty { display:none; }
  table { width:100%; border-collapse:collapse; font-size:.8rem; margin-top:.5rem; }
  td, th { padding:.28rem .5rem; border-bottom:1px solid var(--line); text-align:left; }
  th { color:var(--dim); font-weight:500; }
  .row2 { display:grid; grid-template-columns:1fr 1fr; gap:1rem; margin-top:1rem; }
  @media (max-width:860px){ .row2 { grid-template-columns:1fr; } }
  #palette { position:fixed; inset:0; background:rgba(0,0,0,.6); display:none;
             align-items:flex-start; justify-content:center; padding-top:14vh; z-index:50; }
  #palette.open { display:flex; }
  #palette .box { background:var(--card); border:1px solid var(--line); border-radius:14px;
                  width:min(560px,92vw); overflow:hidden; }
  #palette input { width:100%; border:0; border-bottom:1px solid var(--line);
                   border-radius:0; height:46px; font-size:1rem; }
  #palette .item { padding:.55rem .9rem; cursor:pointer; font-size:.88rem; }
  #palette .item small { color:var(--dim); margin-left:.5rem; }
  #palette .item.sel, #palette .item:hover { background:#22222e; }
  .kbd { border:1px solid var(--line); border-radius:5px; padding:0 .35rem;
         font-size:.72rem; color:var(--dim); }
</style>
</head>
<body>
<div class="topbar">
  <h1>🕷️ Spidey <em>Platform</em></h1>
  <span id="status" class="pill">checking…</span>
  <span style="margin-left:auto" class="row" >
    <span class="kbd">⌘K</span>
    <a class="pill" href="/">← Agent chat</a>
    <a class="pill" href="/docs">API docs</a>
    <a class="pill" href="/metrics">Prometheus</a>
  </span>
</div>
<p class="sub">Eleven capability modules · one shared core. Open a card, press
<b>Try it</b>, fill the form — every result below comes from the real API on this machine.
<input id="apikey" placeholder="X-API-Key (only if auth enabled)" type="password"
 style="height:26px;font-size:.75rem;margin-left:.4rem"></p>

<div class="stats" id="stats"></div>
<div class="grid" id="modules"></div>

<div class="row2">
  <div class="card"><h3>Job queue</h3>
    <table id="jobs"><tr><th>id</th><th>kind</th><th>status</th><th>attempts</th></tr></table></div>
  <div class="card"><h3>LLM call trace <span class="pill">Sentinel-style</span></h3>
    <table id="llmcalls"><tr><th>model</th><th>status</th><th>ms</th><th>$</th></tr></table></div>
</div>

<div id="palette"><div class="box">
  <input id="palq" placeholder="Jump to a module or action…">
  <div id="palitems"></div>
</div></div>

<script>
const $ = s => document.querySelector(s);
const key = () => localStorage.getItem("spidey_api_key") || "";
$("#apikey").value = key();
$("#apikey").addEventListener("change", e => localStorage.setItem("spidey_api_key", e.target.value));
const hdrs = extra => ({ ...(key() ? {"X-API-Key": key()} : {}), ...(extra||{}) });
async function api(method, path, body, raw) {
  const opts = { method, headers: hdrs(body && !raw ? {"content-type":"application/json"} : {}) };
  if (body) opts.body = raw ? body : JSON.stringify(body);
  const r = await fetch(path, opts);
  let data; try { data = await r.json(); } catch { data = await r.text?.() || null; }
  if (!r.ok) throw new Error(typeof data === "object" ? (data.detail || JSON.stringify(data)) : r.status);
  return data;
}
const show = (el, data) => { el.textContent = typeof data === "string" ? data : JSON.stringify(data, null, 2); };
const busy = async (btn, el, fn) => {
  const t = btn.textContent; btn.textContent = "…"; btn.disabled = true;
  try { show(el, await fn()); } catch (e) { show(el, "✗ " + e.message); }
  btn.textContent = t; btn.disabled = false;
};

/* ---------- module cards: description + working Try-it form ---------- */
const M = [];
function card(title, tag, desc, formHTML, wire) {
  M.push({ title, id: M.length });
  return { title, tag, desc, formHTML, wire };
}
const MODULES = [

card("🕷 Web Automation", "scrape anything",
 "Strategy ladder: structured → tables → links → text, AI fallback to JSON, OCR, screenshots, approval queue, retries & schedules.",
 `<div class="row"><input data-f="url" placeholder="https://news.ycombinator.com" style="flex:2">
   <select data-f="strategy"><option>auto</option><option>structured</option><option>tables</option>
   <option>links</option><option>text</option><option>ai</option></select>
   <button data-b="go">Scrape</button></div>
  <input data-f="instr" placeholder="optional AI instruction, e.g. 'titles and points of top stories'">`,
 (el, out) => el.querySelector('[data-b=go]').onclick = ev => busy(ev.target, out, () =>
   api("POST", "/api/webauto/scrape-now", { url: el.querySelector('[data-f=url]').value,
     strategy: el.querySelector('[data-f=strategy]').value,
     instruction: el.querySelector('[data-f=instr]').value }))),

card("🤖 LLM Gateway", "Sentinel port",
 "Send any prompt to any provider through one traced endpoint — latency, token & cost estimates logged per call.",
 `<textarea data-f="prompt" placeholder="Ask anything… (runs on your local Ollama by default)"></textarea>
  <div class="row"><select data-f="provider"><option>ollama</option><option>anthropic</option>
   <option>gemini</option><option>openai</option></select>
   <input data-f="model" placeholder="model (blank = default)">
   <input data-f="akey" placeholder="api key (hosted only)" type="password">
   <button data-b="go">Send</button></div>`,
 (el, out) => el.querySelector('[data-b=go]').onclick = ev => busy(ev.target, out, () =>
   api("POST", "/api/llm/chat", { prompt: el.querySelector('[data-f=prompt]').value,
     provider: el.querySelector('[data-f=provider]').value,
     model: el.querySelector('[data-f=model]').value || null,
     api_key: el.querySelector('[data-f=akey]').value || null }))),

card("📁 File Pipeline", "upload → workers",
 "Any file → content-addressed store → queue → typed processing (CSV profiling, zip, images, PDF) → webhook.",
 `<div class="row"><input type="file" data-f="file"><button data-b="go">Upload & process</button></div>`,
 (el, out) => el.querySelector('[data-b=go]').onclick = ev => busy(ev.target, out, async () => {
   const f = el.querySelector('[data-f=file]').files[0];
   if (!f) throw new Error("pick a file first");
   const up = await api("PUT", "/api/files/upload?name=" + encodeURIComponent(f.name), f, true);
   for (let i = 0; i < 30; i++) {
     await new Promise(r => setTimeout(r, 500));
     const row = await api("GET", "/api/files/" + up.id);
     if (row.status !== "queued") return row;
   }
   return "still processing — check /api/files/" + up.id; })),

card("📈 Analytics", "mini-Datadog",
 "Events → minute rollups → percentiles → alert rules → webhooks.",
 `<div class="row"><button data-b="demo" class="ghost">Send 20 demo events</button>
   <input data-f="name" placeholder="metric name" value="demo.latency">
   <button data-b="stats">Stats</button></div>`,
 (el, out) => {
   el.querySelector('[data-b=demo]').onclick = ev => busy(ev.target, out, () =>
     api("POST", "/api/analytics/events", Array.from({length: 20}, () =>
       ({ name: "demo.latency", value: Math.round(50 + Math.random() * 450) }))));
   el.querySelector('[data-b=stats]').onclick = ev => busy(ev.target, out, () =>
     api("GET", "/api/analytics/stats?name=" + el.querySelector('[data-f=name]').value)); }),

card("🚚 Fleet", "telemetry + routes",
 "Vehicles, fuel & maintenance prediction, driver events, anomalies, 2-opt route optimizer.",
 `<div class="row"><button data-b="seed" class="ghost">Seed demo vehicle + pings</button>
   <button data-b="ana">Analytics</button><button data-b="route">Optimize 5-stop route</button></div>`,
 (el, out) => {
   let vid = null;
   el.querySelector('[data-b=seed]').onclick = ev => busy(ev.target, out, async () => {
     const v = await api("POST", "/api/fleet/vehicles", { name: "Demo Van " + Date.now() % 1000,
       plate: "B-SP " + (100 + Math.floor(Math.random() * 899)), driver: "Miles",
       odometer_km: 14500, service_interval_km: 15000 });
     vid = v.id;
     const t = h => new Date(Date.now() - h * 3600e3).toISOString();
     await api("POST", "/api/fleet/pings", [
       { vehicle_id: vid, speed_kmh: 40, fuel_l: 60, odometer_km: 14500, lat: 52.52, lon: 13.40, ts: t(30) },
       { vehicle_id: vid, speed_kmh: 95, fuel_l: 52, odometer_km: 14650, lat: 52.6, lon: 13.3, ts: t(20) },
       { vehicle_id: vid, speed_kmh: 145, fuel_l: 45, odometer_km: 14800, lat: 52.7, lon: 13.2, ts: t(10) },
       { vehicle_id: vid, speed_kmh: 0, fuel_l: 31, odometer_km: 15100, lat: 52.7, lon: 13.2, ts: t(1) }]);
     return "vehicle " + vid + " seeded with 4 pings — now press Analytics"; });
   el.querySelector('[data-b=ana]').onclick = ev => busy(ev.target, out, async () => {
     if (!vid) { const vs = await api("GET", "/api/fleet/vehicles"); if (!vs.length) throw new Error("seed first"); vid = vs[vs.length-1].id; }
     return api("GET", `/api/fleet/vehicles/${vid}/analytics`); });
   el.querySelector('[data-b=route]').onclick = ev => busy(ev.target, out, () =>
     api("POST", "/api/fleet/routes/optimize", { stops: [
       { lat: 52.52, lon: 13.40 }, { lat: 48.13, lon: 11.58 }, { lat: 50.11, lon: 8.68 },
       { lat: 53.55, lon: 9.99 }, { lat: 51.34, lon: 12.37 }] })); }),

card("🎯 Job Matching", "jobflow port",
 "Resume → skills + embedding → ranked matches → skill gap → ATS report → cover letter.",
 `<textarea data-f="resume" placeholder="Paste your resume text…"></textarea>
  <textarea data-f="job" placeholder="Paste a job description…"></textarea>
  <div class="row"><button data-b="match">Match</button>
   <button data-b="ats" class="ghost">Brutal ATS report</button>
   <button data-b="cover" class="ghost">Cover letter</button></div>`,
 (el, out) => {
   let rid = null, jid = null;
   const ensure = async () => {
     const rt = el.querySelector('[data-f=resume]').value, jt = el.querySelector('[data-f=job]').value;
     if (!rt || !jt) throw new Error("paste both resume and job text");
     if (!rid) rid = (await api("POST", "/api/match/resumes", { name: "Playground", text: rt })).id;
     if (!jid) jid = (await api("POST", "/api/match/jobs", [{ title: jt.split("\n")[0].slice(0, 60) || "Job", description: jt }])).ids[0];
     return [rid, jid]; };
   el.querySelector('[data-b=match]').onclick = ev => busy(ev.target, out, async () => {
     await ensure(); return api("GET", `/api/match/resumes/${rid}/matches`); });
   el.querySelector('[data-b=ats]').onclick = ev => busy(ev.target, out, async () => {
     await ensure(); return api("GET", `/api/match/resumes/${rid}/ats/${jid}`); });
   el.querySelector('[data-b=cover]').onclick = ev => busy(ev.target, out, async () => {
     await ensure(); return (await api("POST", `/api/match/resumes/${rid}/cover-letter?job_id=${jid}`)).markdown; }); }),

card("📚 Research", "RAG + analyzer",
 "Ingest documents → cited Q&A, summaries, flashcards; analyzer extracts deadlines, amounts, contacts, requirements (vergabepilot port).",
 `<textarea data-f="text" placeholder="Paste a document / paper / tender text…"></textarea>
  <div class="row"><input data-f="q" placeholder="Ask a question about it" style="flex:2">
   <button data-b="ask">Ask</button><button data-b="analyze" class="ghost">Analyze fields</button>
   <button data-b="cards" class="ghost">Flashcards</button></div>`,
 (el, out) => {
   let did = null;
   const ensure = async () => {
     if (did) return did;
     const t = el.querySelector('[data-f=text]').value;
     if (!t) throw new Error("paste a document first");
     did = (await api("POST", "/api/research/docs", { title: "Playground doc", text: t })).id;
     return did; };
   el.querySelector('[data-b=ask]').onclick = ev => busy(ev.target, out, async () =>
     api("POST", "/api/research/ask", { question: el.querySelector('[data-f=q]').value, doc_id: await ensure() }));
   el.querySelector('[data-b=analyze]').onclick = ev => busy(ev.target, out, async () =>
     api("GET", `/api/research/docs/${await ensure()}/analyze`));
   el.querySelector('[data-b=cards]').onclick = ev => busy(ev.target, out, async () =>
     api("GET", `/api/research/docs/${await ensure()}/flashcards`)); }),

card("💻 Code Assistant", "repo intelligence",
 "Index a repo → chat with it; AST bug hunting, pytest generation, Mermaid architecture diagram.",
 `<textarea data-f="code" placeholder="Paste Python code to hunt bugs / generate tests…"></textarea>
  <div class="row"><button data-b="bugs">Find bugs</button>
   <button data-b="tests" class="ghost">Generate tests</button></div>
  <div class="row"><input data-f="repo" placeholder="/path/to/repo on this machine" style="flex:2">
   <button data-b="diagram" class="ghost">Diagram</button></div>`,
 (el, out) => {
   const code = () => { const c = el.querySelector('[data-f=code]').value; if (!c) throw new Error("paste code first"); return c; };
   el.querySelector('[data-b=bugs]').onclick = ev => busy(ev.target, out, () => api("POST", "/api/code/bugs", { code: code() }));
   el.querySelector('[data-b=tests]').onclick = ev => busy(ev.target, out, async () => (await api("POST", "/api/code/gen-tests", { code: code() })).tests);
   el.querySelector('[data-b=diagram]').onclick = ev => busy(ev.target, out, async () =>
     (await api("GET", "/api/code/diagram?path=" + encodeURIComponent(el.querySelector('[data-f=repo]').value))).mermaid); }),

card("✉️ Email Assistant", "inbox brain",
 "IMAP sync or paste an .eml → category + priority, smart reply, calendar suggestions, mail RAG. Credentials never stored.",
 `<textarea data-f="eml" placeholder="Paste a raw email (or press Sample)"></textarea>
  <div class="row"><button data-b="sample" class="ghost">Sample</button>
   <button data-b="import">Import & classify</button><button data-b="reply" class="ghost">Draft reply</button></div>`,
 (el, out) => {
   let eid = null;
   el.querySelector('[data-b=sample]').onclick = () => {
     el.querySelector('[data-f=eml]').value =
`From: Recruiter <talent@rocket.tech>
Subject: Interview invitation — Backend Engineer
Date: Fri, 10 Jul 2026 10:00:00 +0000
Content-Type: text/plain

Hi! We loved your profile. Could you join an interview on 2026-07-20 at 11:00?
Please confirm by tomorrow — deadline for scheduling is EOD.`; };
   el.querySelector('[data-b=import]').onclick = ev => busy(ev.target, out, async () => {
     const r = await api("POST", "/api/email/import", { raw: el.querySelector('[data-f=eml]').value });
     eid = r.id; return r; });
   el.querySelector('[data-b=reply]').onclick = ev => busy(ev.target, out, async () => {
     if (!eid) throw new Error("import an email first");
     return (await api("POST", `/api/email/messages/${eid}/reply`)).draft; }); }),

card("🚗 Driving Data", "TTC prediction",
 "Drive-log replay, time-to-collision prediction (the AEB metric), behavior reports; OpenCV lane/pedestrian detection when installed.",
 `<div class="row"><button data-b="demo" class="ghost">Load demo drive</button>
   <button data-b="ana">Collision analytics</button><button data-b="rep" class="ghost">Report</button></div>`,
 (el, out) => {
   let sid = null;
   el.querySelector('[data-b=demo]').onclick = ev => busy(ev.target, out, async () => {
     sid = (await api("POST", "/api/driving/sessions", { name: "Demo drive " + Date.now() % 1000 })).id;
     const frames = []; let speed = 60;
     for (let t = 0; t < 20; t++) {
       const objects = t > 8 && t < 14 ? [{ id: "car-ahead", distance_m: 60 - (t - 8) * 9, rel_speed_ms: -9 }] : [];
       if (t >= 13) speed = Math.max(10, speed - 15);
       frames.push({ ts: t, speed_kmh: speed, objects });
     }
     await api("POST", `/api/driving/sessions/${sid}/frames`, frames);
     return "session " + sid + ": 20 frames with a closing vehicle — press Collision analytics"; });
   el.querySelector('[data-b=ana]').onclick = ev => busy(ev.target, out, async () => {
     if (!sid) throw new Error("load the demo drive first");
     return api("GET", `/api/driving/sessions/${sid}/analytics`); });
   el.querySelector('[data-b=rep]').onclick = ev => busy(ev.target, out, async () => {
     if (!sid) throw new Error("load the demo drive first");
     const r = await fetch(`/api/driving/sessions/${sid}/report`, { headers: hdrs() });
     return await r.text(); }); }),

card("🤝 Multi-Agent Team", "6 roles, one goal",
 "Planner → Researcher → Coder → Reviewer → Tester → Docs with shared memory. Needs a running model (spidey up).",
 `<div class="row"><input data-f="goal" placeholder="e.g. build a CLI URL shortener in Python" style="flex:3">
   <button data-b="run">Run team</button></div>`,
 (el, out) => el.querySelector('[data-b=run]').onclick = ev => busy(ev.target, out, async () => {
   const run = await api("POST", "/api/team/runs", { goal: el.querySelector('[data-f=goal]').value });
   for (let i = 0; i < 240; i++) {
     await new Promise(r => setTimeout(r, 2500));
     const row = await api("GET", "/api/team/runs/" + run.id);
     show(out, (row.transcript || []).map(m => `### ${m.role.toUpperCase()}\n${m.output}`).join("\n\n")
               || row.status + "…");
     if (row.status === "done") return "✔ done — full transcript above";
     if (row.status === "failed") throw new Error("run failed — is Ollama up? (spidey up)");
   }
   return "still running — GET /api/team/runs/" + run.id; })),
];

/* render cards */
$("#modules").innerHTML = MODULES.map((m, i) =>
  `<div class="card" id="mod${i}"><h3>${m.title} <span class="pill">${m.tag}</span></h3>
   <p>${m.desc}</p><details><summary>Try it</summary>
   <div class="form">${m.formHTML}</div><pre class="out"></pre></details></div>`).join("");
MODULES.forEach((m, i) => {
  const el = document.querySelector(`#mod${i} .form`);
  m.wire(el, document.querySelector(`#mod${i} pre.out`));
});

/* stats + tables */
async function refresh() {
  try {
    const [h, llm, jobs] = await Promise.all([
      api("GET", "/api/health"), api("GET", "/api/llm/stats"),
      api("GET", "/api/queue/jobs?limit=8")]);
    const q = h.queue || {};
    const feats = Object.entries(h.optional).filter(([, v]) => v).map(([k]) => k);
    $("#status").innerHTML = `<span class="ok">● healthy</span> · ${h.modules.length} modules` +
      (feats.length ? ` · extras: ${feats.join(", ")}` : "");
    $("#stats").innerHTML = [
      [q.done || 0, "jobs done"], [q.queued || 0, "jobs queued"],
      [(q.failed || 0), "jobs failed", q.failed ? "bad" : ""],
      [llm.totals.calls || 0, "LLM calls traced"],
      ["$" + (llm.totals.cost_usd || 0), "est. LLM spend"],
    ].map(([v, l, c]) => `<div class="stat"><b class="${c || ""}">${v}</b><span>${l}</span></div>`).join("");
    $("#jobs").innerHTML = "<tr><th>id</th><th>kind</th><th>status</th><th>attempts</th></tr>" +
      jobs.map(j => `<tr><td>${j.id}</td><td>${j.kind}</td>
       <td class="${j.status === 'failed' ? 'bad' : j.status === 'done' ? 'ok' : 'warn'}">${j.status}</td>
       <td>${j.attempts}/${j.max_attempts}</td></tr>`).join("");
    const calls = await api("GET", "/api/llm/calls?limit=6");
    $("#llmcalls").innerHTML = "<tr><th>model</th><th>status</th><th>ms</th><th>$</th></tr>" +
      (calls.length ? calls.map(c => `<tr><td>${c.provider}/${c.model}</td>
        <td class="${c.status === 'ok' ? 'ok' : 'bad'}">${c.status}</td>
        <td>${c.latency_ms}</td><td>${c.cost_usd}</td></tr>`).join("")
        : `<tr><td colspan="4" style="color:var(--dim)">none yet — try the LLM Gateway card</td></tr>`);
  } catch (e) {
    $("#status").innerHTML = `<span class="bad">● ${String(e.message).includes("401")
      ? "unauthorized — paste your API key (top right of the intro line)" : "unreachable"}</span>`;
  }
}
refresh(); setInterval(refresh, 5000);

/* ⌘K command palette (ported from the portfolio site) */
const ACTIONS = MODULES.map((m, i) => ({ label: m.title, hint: m.tag, go: () => {
  const c = $("#mod" + i); c.querySelector("details").open = true;
  c.scrollIntoView({ behavior: "smooth", block: "center" }); }}))
  .concat([{ label: "Open API docs", hint: "/docs", go: () => location.href = "/docs" },
           { label: "Open Prometheus metrics", hint: "/metrics", go: () => location.href = "/metrics" },
           { label: "Back to agent chat", hint: "/", go: () => location.href = "/" }]);
let sel = 0;
function renderPal() {
  const q = $("#palq").value.toLowerCase();
  const items = ACTIONS.filter(a => a.label.toLowerCase().includes(q));
  sel = Math.min(sel, Math.max(0, items.length - 1));
  $("#palitems").innerHTML = items.map((a, i) =>
    `<div class="item${i === sel ? " sel" : ""}" data-i="${i}">${a.label}<small>${a.hint}</small></div>`).join("");
  $("#palitems").querySelectorAll(".item").forEach(el =>
    el.onclick = () => { closePal(); items[+el.dataset.i].go(); });
  return items;
}
const openPal = () => { $("#palette").classList.add("open"); $("#palq").value = ""; sel = 0; renderPal(); $("#palq").focus(); };
const closePal = () => $("#palette").classList.remove("open");
document.addEventListener("keydown", e => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openPal(); }
  if (!$("#palette").classList.contains("open")) return;
  if (e.key === "Escape") closePal();
  if (e.key === "ArrowDown") { sel++; renderPal(); e.preventDefault(); }
  if (e.key === "ArrowUp") { sel = Math.max(0, sel - 1); renderPal(); e.preventDefault(); }
  if (e.key === "Enter") { const items = renderPal(); if (items[sel]) { closePal(); items[sel].go(); } }
});
$("#palq").addEventListener("input", () => { sel = 0; renderPal(); });
$("#palette").addEventListener("click", e => { if (e.target.id === "palette") closePal(); });
</script>
</body>
</html>"""
