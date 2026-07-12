"""The /platform Studio — a single-page AI suite in full Spider-Verse dress.

Matches the agent chat's look: the suit-red→suit-blue palette, the faint spider
web anchored top-left, the gradient header, web-line slide-in animations. A left
sidebar lists every AI tool; clicking one swaps the panel in place — no reloads,
no page jumps. A persistent session (shared across every device on the network,
because it lives in the DB) records every action into a History view. Vanilla
JS, one file, no build step — the React app at / stays the agent's chat home.
"""

DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Spidey Studio</title>
<style>
  :root {
    --red:#c81e24; --red-bright:#ef3a40; --blue:#2545a8; --blue-deep:#16204d;
    --bg:#09090e; --bg2:#0d0d14; --card:#14141d; --panel:#0f0f17; --line:#23232f;
    --text:#f1f1f6; --dim:#8a8a99; --green:#34d399; --amber:#fbbf24;
  }
  * { box-sizing:border-box; margin:0; }
  html,body { height:100%; }
  body { background:var(--bg); color:var(--text); display:flex;
         font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
  a { color:var(--red-bright); text-decoration:none; }
  ::-webkit-scrollbar { width:9px; height:9px; }
  ::-webkit-scrollbar-thumb { background:#2a2a38; border-radius:6px; }
  .webbg { background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='260' height='260'%3E%3Cg stroke='%238892b0' stroke-opacity='0.13' fill='none'%3E%3Cpath d='M0 0L260 0M0 0L260 65M0 0L260 156M0 0L195 260M0 0L104 260M0 0L0 260'/%3E%3Cpath d='M52 0Q48 24 0 39M113 0Q102 54 0 87M182 0Q163 87 0 143M252 8Q224 121 10 215'/%3E%3C/g%3E%3C/svg%3E");
           background-repeat:no-repeat; background-position:top left; }
  /* ---- sidebar ---- */
  aside { width:236px; flex-shrink:0; height:100vh; overflow-y:auto; position:sticky; top:0;
          background:linear-gradient(180deg,#0c0c13,#090910); padding:0 .55rem 1.5rem;
          border-right:1px solid transparent;
          border-image:linear-gradient(180deg,var(--red) 0%,#26262f 40%,#26262f 60%,var(--blue) 100%) 1; }
  .brand { position:sticky; top:0; z-index:2; padding:1rem .55rem .5rem;
           background:linear-gradient(180deg,#0c0c13 70%,transparent);
           display:flex; align-items:center; gap:.5rem; }
  .brand .logo { font-size:1.4rem; filter:drop-shadow(0 0 6px rgba(200,30,36,.6)); }
  .brand h1 { font-size:1.05rem; font-weight:800; letter-spacing:.2px; }
  .brand em { color:var(--red-bright); font-style:normal; }
  .sesspick { width:100%; margin:.2rem 0 .1rem; font-size:.72rem; padding:.35rem .5rem;
              background:var(--panel); color:var(--text); border:1px solid var(--line); border-radius:7px; }
  .apik { width:100%; font-size:.7rem; padding:.32rem .5rem; margin-top:.35rem;
          background:var(--panel); color:var(--text); border:1px solid var(--line); border-radius:7px; }
  .navsec { color:var(--dim); font-size:.66rem; text-transform:uppercase; letter-spacing:.09em;
            padding:.9rem .55rem .3rem; font-weight:700; }
  .navitem { display:flex; align-items:center; gap:.55rem; padding:.46rem .55rem; border-radius:9px;
             cursor:pointer; font-size:.86rem; color:var(--text); border:1px solid transparent;
             transition:background .12s,border-color .12s; }
  .navitem:hover { background:#171722; }
  .navitem.active { background:linear-gradient(135deg,var(--red) 0%,#8f1519 100%);
                    border-color:var(--red-bright); box-shadow:0 2px 12px rgba(200,30,36,.35); }
  .navitem .ico { width:1.2rem; text-align:center; font-size:.98rem; }
  /* ---- main ---- */
  main { flex:1; height:100vh; overflow-y:auto; }
  .topbar { position:sticky; top:0; z-index:3; padding:.85rem 1.6rem;
            background:rgba(9,9,14,.82); backdrop-filter:blur(12px);
            border-bottom:1px solid transparent;
            border-image:linear-gradient(90deg,var(--red) 0%,#3f3f46 35%,#3f3f46 65%,var(--blue) 100%) 1;
            display:flex; align-items:center; gap:.7rem; flex-wrap:wrap; }
  .topbar h2 { font-size:1.15rem; font-weight:800; }
  .content { padding:1.4rem 1.6rem; max-width:1000px; }
  .desc { color:var(--dim); font-size:.9rem; margin-bottom:1.2rem; max-width:70ch; }
  .pill { display:inline-block; padding:.14rem .62rem; border-radius:99px; font-size:.7rem;
          background:#20202c; color:var(--dim); border:1px solid var(--line); }
  .pill.red { background:rgba(200,30,36,.16); color:var(--red-bright); border-color:rgba(200,30,36,.4); }
  .ok{color:var(--green)} .bad{color:var(--red-bright)} .warn{color:var(--amber)}
  label { font-size:.76rem; color:var(--dim); display:block; margin:.55rem 0 .18rem; font-weight:600; }
  input,textarea,select { background:var(--panel); color:var(--text); border:1px solid var(--line);
     border-radius:9px; padding:.55rem .7rem; font:inherit; font-size:.88rem; width:100%; transition:border-color .12s; }
  input:focus,textarea:focus,select:focus { outline:none; border-color:var(--red); }
  textarea { min-height:120px; resize:vertical; line-height:1.5; }
  .row { display:flex; gap:.55rem; flex-wrap:wrap; align-items:flex-end; }
  .row > * { flex:1; min-width:120px; }
  button { background:linear-gradient(135deg,var(--red-bright) 0%,var(--red) 100%); color:#fff;
           border:0; border-radius:9px; padding:.58rem 1.05rem; font:700 .85rem/1 inherit;
           cursor:pointer; white-space:nowrap; transition:filter .12s,transform .06s; }
  button:hover { filter:brightness(1.13); } button:active { transform:translateY(1px); }
  button:disabled { opacity:.5; cursor:default; }
  button.ghost { background:linear-gradient(135deg,#242433,#1a1a25); border:1px solid var(--line); }
  button.wide { flex:0 0 auto; }
  .out { background:var(--panel); border:1px solid var(--line); border-radius:11px; padding:.85rem;
         margin-top:1.1rem; font-size:.82rem; white-space:pre-wrap; word-break:break-word;
         max-height:62vh; overflow:auto; animation:slidein .22s ease-out both; }
  .out:empty { display:none; }
  @keyframes slidein { from{opacity:0;transform:translateY(6px)} to{opacity:1;transform:none} }
  .card { background:linear-gradient(160deg,var(--card),#101019); border:1px solid var(--line);
          border-radius:14px; padding:.9rem 1.05rem; animation:slidein .22s ease-out both; }
  .stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:.75rem; margin-bottom:1.3rem; }
  .stat { background:linear-gradient(160deg,var(--card),#101019); border:1px solid var(--line);
          border-radius:13px; padding:.75rem 1rem; position:relative; overflow:hidden; }
  .stat::before { content:""; position:absolute; left:0; top:0; bottom:0; width:3px;
                  background:linear-gradient(var(--red),var(--blue)); }
  .stat b { font-size:1.3rem; display:block; font-weight:800; } .stat span { color:var(--dim); font-size:.72rem; }
  .tiles { display:grid; grid-template-columns:repeat(auto-fill,minmax(230px,1fr)); gap:.85rem; }
  .tile { background:linear-gradient(160deg,var(--card),#101019); border:1px solid var(--line);
          border-radius:14px; padding:1rem; cursor:pointer; transition:transform .12s,border-color .12s,box-shadow .12s;
          animation:slidein .22s ease-out both; }
  .tile:hover { transform:translateY(-3px); border-color:var(--red); box-shadow:0 8px 24px rgba(0,0,0,.4); }
  .tile .ti { font-size:1.6rem; } .tile b { display:block; margin:.35rem 0 .2rem; font-size:.95rem; }
  .tile span { color:var(--dim); font-size:.76rem; line-height:1.4; }
  table { width:100%; border-collapse:collapse; font-size:.8rem; }
  td,th { padding:.34rem .5rem; border-bottom:1px solid var(--line); text-align:left; }
  th { color:var(--dim); font-weight:600; }
  .dl { display:inline-block; margin-top:.7rem; background:linear-gradient(135deg,var(--green),#12a06b);
        color:#04120b; padding:.5rem .95rem; border-radius:9px; font-weight:800; font-size:.85rem; }
  .grid2 { display:grid; grid-template-columns:1fr 1fr; gap:1rem; }
  .barbg { height:8px; background:#20202c; border-radius:5px; overflow:hidden; margin-top:.6rem; }
  .barfg { height:100%; background:linear-gradient(90deg,var(--red),var(--red-bright)); transition:width .3s; }
  .chip { font-size:.72rem; padding:.13rem .55rem; border-radius:7px; background:#20202c; color:var(--dim);
          margin:.18rem .22rem 0 0; display:inline-block; border:1px solid var(--line); }
  .chip.done { background:rgba(52,211,153,.14); color:var(--green); border-color:rgba(52,211,153,.4); }
  #burger { display:none; }
  @media (max-width:760px){ aside{position:fixed;z-index:40;transform:translateX(-100%);transition:.2s}
    aside.open{transform:none} .grid2{grid-template-columns:1fr} .content{padding:1rem}
    #burger{display:inline-block;position:fixed;top:.55rem;right:.6rem;z-index:50} }
</style>
</head>
<body>
<button id="burger" class="ghost" onclick="document.querySelector('aside').classList.toggle('open')">☰ Tools</button>
<aside class="webbg">
  <div class="brand"><span class="logo">🕷️</span><h1>Spidey <em>Studio</em></h1></div>
  <div style="padding:0 .55rem">
    <select id="sesspick" class="sesspick" title="Sessions are shared across every device on your network"></select>
    <input id="apikey" class="apik" placeholder="API key (only if enabled)" type="password">
  </div>
  <div id="nav"></div>
  <div class="navsec">Links</div>
  <div class="navitem" onclick="location.href='/'"><span class="ico">💬</span> Agent chat</div>
  <div class="navitem" onclick="location.href='/docs'"><span class="ico">📖</span> API docs</div>
  <div class="navitem" onclick="location.href='/metrics'"><span class="ico">📊</span> Metrics</div>
</aside>
<main>
  <div class="topbar">
    <button id="tb-back" class="ghost" title="Back" style="padding:.4rem .7rem">←</button>
    <button id="tb-reload" class="ghost" title="Reload this tool" style="padding:.4rem .7rem">⟳</button>
    <span id="tb-ico" style="font-size:1.3rem">🏠</span>
    <h2 id="tb-name">Overview</h2><span id="tb-sec" class="pill"></span>
    <span style="margin-left:auto" id="tb-status" class="pill">…</span></div>
  <div class="content webbg" id="content"></div>
</main>

<script>
const $ = s => document.querySelector(s);
const key = () => localStorage.getItem("spidey_api_key") || "";
$("#apikey").value = key();
$("#apikey").onchange = e => localStorage.setItem("spidey_api_key", e.target.value);
const hdrs = ex => ({ ...(key() ? {"X-API-Key": key()} : {}), ...(ex||{}) });
async function api(method, path, body, raw) {
  const o = { method, headers: hdrs(body && !raw ? {"content-type":"application/json"} : {}) };
  if (body !== undefined) o.body = raw ? body : JSON.stringify(body);
  const r = await fetch(path, o);
  let d; try { d = await r.json(); } catch { d = null; }
  if (!r.ok) throw new Error(d && typeof d === "object" ? (d.detail || JSON.stringify(d)) : "HTTP " + r.status);
  return d;
}
const esc = s => (s+"").replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
const jj = d => typeof d === "string" ? d : JSON.stringify(d, null, 2);

/* ---- sessions: shared across devices via the DB; picker in the sidebar ---- */
let SID = localStorage.getItem("spidey_session_id");
async function refreshSessionPicker() {
  try {
    const ss = await api("GET", "/api/sessions");
    if (!ss.length || !ss.find(s => String(s.id) === SID)) {
      const s = await api("POST", "/api/sessions", { name: "Studio " + new Date().toLocaleString() });
      SID = String(s.id); localStorage.setItem("spidey_session_id", SID);
      return refreshSessionPicker();
    }
    $("#sesspick").innerHTML = ss.map(s =>
      `<option value="${s.id}" ${String(s.id)===SID?"selected":""}>${esc(s.name)} · ${s.items} items</option>`).join("")
      + `<option value="__new">+ New session</option>`;
  } catch {}
}
$("#sesspick").onchange = async e => {
  if (e.target.value === "__new") {
    const s = await api("POST", "/api/sessions", { name: "Studio " + new Date().toLocaleString() });
    SID = String(s.id);
  } else SID = e.target.value;
  localStorage.setItem("spidey_session_id", SID);
  await refreshSessionPicker();
  if (location.hash === "#history") select("history");
};
async function log(module, action, input, output, ref_id) {
  try { await api("POST", `/api/sessions/${SID}/items`,
    { module, action, input:(input||"").slice(0,1000), output:jj(output).slice(0,2000), ref_id:ref_id||null }); }
  catch {}
}
async function run(btn, outEl, module, action, fn, render) {
  const t = btn.textContent; btn.disabled = true; btn.textContent = "Working…";
  try { const res = await fn();
    outEl.innerHTML = render ? render(res) : `<pre style="margin:0;white-space:pre-wrap">${esc(jj(res))}</pre>`;
    log(module, action, "", res, res && res.id);
  } catch (e) { outEl.innerHTML = `<span class="bad">✗ ${esc(e.message)}</span>`; }
  btn.disabled = false; btn.textContent = t; refreshSessionPicker();
}
async function uploadBody(path, file) {
  const r = await fetch(path, { method:"PUT", headers:hdrs(), body:file });
  const d = await r.json().catch(() => null);
  if (!r.ok) throw new Error(d && d.detail || "upload failed"); return d;
}

/* =====================  TOOLS  ===================== */
const TOOLS = [
{ id:"home", sec:"", ico:"🏠", name:"Overview", render: homeView },

{ id:"docstudio", sec:"Create", ico:"📝", name:"Document Studio",
  desc:"Generate a résumé, CV, cover letter, presentation, report, letter, README or proposal — then download it as .docx, .pptx, .pdf, .html, .md or .txt. The AI works only from facts you give it.",
  view: el => {
    el.innerHTML = `<div class="card">
     <div class="row"><div style="flex:2"><label>What to make</label><select id="dg-kind"></select></div>
       <div><label>Format</label><select id="dg-fmt"></select></div></div>
     <label>Title (optional)</label><input id="dg-title" placeholder="e.g. Siddharth Patni — Résumé">
     <label>Brief — describe it in your words</label>
     <textarea id="dg-prompt" placeholder="e.g. Résumé for an AI/backend engineer role in Germany. 3 years Python, FastAPI, Docker, PyTorch. Highlight the Spidey and vergabepilot projects."></textarea>
     <label>Source facts (optional — paste real details; the AI won't invent facts)</label>
     <textarea id="dg-details" style="min-height:80px" placeholder="Paste your current resume text, achievements, dates…"></textarea>
     <div class="row" style="margin-top:.85rem"><button id="dg-go" class="wide">Generate document</button>
       <button id="dg-list" class="ghost wide">My documents</button></div></div>
     <div class="out" id="dg-out"></div>`;
    api("GET","/api/docgen/kinds").then(k => {
      $("#dg-kind").innerHTML = k.kinds.map(x=>`<option value="${x.kind}">${x.label}</option>`).join("");
      $("#dg-fmt").innerHTML = k.formats.map(f=>`<option ${f==='docx'?'selected':''}>${f}</option>`).join("");
    });
    const dlRender = d => `<b>${esc(d.title)}</b> · ${d.format.toUpperCase()} · ${(d.size/1024).toFixed(1)} KB
      · <span class="pill red">${d.mode}</span>
      <a class="dl" href="${d.download_url}">⬇ Download .${d.format}</a>
      <details style="margin-top:.7rem"><summary style="cursor:pointer;color:var(--red-bright)">Preview</summary>
      <pre style="white-space:pre-wrap;margin-top:.5rem">${esc(d.markdown||"")}</pre></details>`;
    $("#dg-go").onclick = e => run(e.target,$("#dg-out"),"docgen","create",()=>
      api("POST","/api/docgen/create",{kind:$("#dg-kind").value,format:$("#dg-fmt").value,
        title:$("#dg-title").value,prompt:$("#dg-prompt").value,details:$("#dg-details").value}), dlRender);
    $("#dg-list").onclick = e => run(e.target,$("#dg-out"),"docgen","list",()=>
      api("GET","/api/docgen/files"), rows => rows.length ? `<table><tr><th>title</th><th>kind</th><th>fmt</th><th></th></tr>`+
        rows.map(r=>`<tr><td>${esc(r.title)}</td><td>${r.kind}</td><td>${r.format}</td>
        <td><a class="dl" style="padding:.2rem .6rem;margin:0" href="/api/docgen/files/${r.id}/download">⬇</a></td></tr>`).join("")+`</table>` : "No documents yet."); } },

{ id:"paper", sec:"Create", ico:"🔬", name:"Research Paper (IEEE)",
  desc:"Give a topic; Spidey fetches real references (Crossref + Wikipedia) and writes a full IEEE-format paper section by section. A heavy task — watch it build live below.",
  view: el => {
    el.innerHTML = `<div class="card">
     <div class="row"><div style="flex:3"><label>Research topic</label>
       <input id="pp-topic" placeholder="e.g. Reliable tool-calling in small on-device language models"></div>
       <div><label>Format</label><select id="pp-fmt"><option>pdf</option><option>docx</option><option>html</option><option>md</option></select></div>
       <button id="pp-go" class="wide">Write paper</button></div></div>
     <div id="pp-prog"></div><div class="out" id="pp-out"></div>`;
    $("#pp-go").onclick = async e => {
      const topic = $("#pp-topic").value.trim();
      if (!topic) { $("#pp-out").innerHTML='<span class="bad">enter a topic</span>'; return; }
      e.target.disabled = true; e.target.textContent = "Researching…";
      try { const r0 = await api("POST","/api/docgen/paper",{topic,format:$("#pp-fmt").value});
        const stages = ["Abstract","I. Introduction","II. Related Work","III. Methodology","IV. Results and Discussion","V. Conclusion"];
        for (let i=0;i<600;i++){ await new Promise(r=>setTimeout(r,2500));
          const s = await api("GET",`/api/docgen/paper/${r0.id}`);
          const done=(s.progress&&s.progress.sections_done)||[]; const pct=Math.round(done.length/stages.length*100);
          $("#pp-prog").innerHTML = `<div class="card"><div class="barbg"><div class="barfg" style="width:${s.status==='done'?100:pct}%"></div></div>
            <div style="margin:.55rem 0"><span class="pill red">${s.status}</span> ${(s.progress&&s.progress.stage)?esc(s.progress.stage):""}</div>
            ${stages.map(x=>`<span class="chip ${done.includes(x)?'done':''}">${done.includes(x)?'✓ ':''}${x}</span>`).join("")}
            <div style="margin-top:.45rem;color:var(--dim);font-size:.78rem">${(s.sources||[]).length} references fetched</div></div>`;
          if (s.status==="done"){ $("#pp-out").innerHTML=`<a class="dl" href="${s.download_url}">⬇ Download the paper</a>
            <pre style="white-space:pre-wrap;margin-top:.8rem">${esc(s.markdown||"")}</pre>`; log("docgen","paper",topic,"done",s.doc_id); break; }
          if (s.status==="failed"){ $("#pp-out").innerHTML=`<span class="bad">✗ ${esc(s.error||"failed")}</span>`; break; } }
      } catch(err){ $("#pp-out").innerHTML=`<span class="bad">✗ ${esc(err.message)}</span>`; }
      e.target.disabled=false; e.target.textContent="Write paper"; }; } },

{ id:"llm", sec:"Create", ico:"🤖", name:"AI Chat / Gateway",
  desc:"One traced endpoint for any model. Runs on your local Ollama by default; every call logs latency, tokens and cost.",
  view: el => {
    el.innerHTML = `<div class="card"><label>Prompt</label><textarea id="lm-p" placeholder="Ask anything…"></textarea>
     <div class="row"><div><label>Provider</label><select id="lm-prov"><option>ollama</option><option>anthropic</option><option>gemini</option><option>openai</option></select></div>
       <div><label>Model (blank=default)</label><input id="lm-model" placeholder="gemma4:12b"></div>
       <div><label>API key (hosted only)</label><input id="lm-key" type="password"></div>
       <button id="lm-go" class="wide">Send</button></div></div><div class="out" id="lm-out"></div>`;
    $("#lm-go").onclick = e => run(e.target,$("#lm-out"),"llm","chat",()=>
      api("POST","/api/llm/chat",{prompt:$("#lm-p").value,provider:$("#lm-prov").value,model:$("#lm-model").value||null,api_key:$("#lm-key").value||null}),
      r => `<div style="margin-bottom:.5rem"><span class="pill red">${r.provider}/${r.model}</span>
        <span class="pill">${r.latency_ms} ms</span><span class="pill">$${r.cost_usd}</span></div>
        <div style="white-space:pre-wrap">${esc(r.response)}</div>`); } },

{ id:"scrape", sec:"Extract", ico:"🕸", name:"Web Scraper",
  desc:"Pull data from any website — structured metadata, tables, links, readable text, or AI-extracted JSON.",
  view: el => {
    el.innerHTML = `<div class="card"><label>URL</label><input id="sc-url" placeholder="https://news.ycombinator.com">
     <div class="row"><div><label>Strategy</label><select id="sc-strat">
       <option>auto</option><option>structured</option><option>tables</option><option>links</option><option>text</option><option>ai</option></select></div>
       <div style="flex:2"><label>AI instruction (for ai/auto)</label><input id="sc-instr" placeholder="e.g. top 5 story titles + points"></div>
       <button id="sc-go" class="wide">Scrape</button></div></div><div class="out" id="sc-out"></div>`;
    $("#sc-go").onclick = e => run(e.target,$("#sc-out"),"webauto","scrape",()=>
      api("POST","/api/webauto/scrape-now",{url:$("#sc-url").value,strategy:$("#sc-strat").value,instruction:$("#sc-instr").value})); } },

{ id:"research", sec:"Extract", ico:"📚", name:"Research & Docs",
  desc:"Upload a PDF/DOCX/paper (or paste text) → ask questions with citations, summarize, or extract deadlines, amounts, contacts and requirements.",
  view: el => {
    el.innerHTML = `<div class="card"><div class="row"><div style="flex:2"><label>Upload a document (PDF, DOCX, HTML, TXT, MD)</label>
       <input type="file" id="rs-file"></div><button id="rs-up" class="wide ghost">Upload & index</button></div>
     <label>…or paste text</label><textarea id="rs-text" placeholder="Paste a paper, contract, notes…"></textarea>
     <button id="rs-add" class="ghost" style="margin-top:.5rem">Index pasted text</button>
     <div class="row" style="margin-top:.85rem"><input id="rs-q" placeholder="Ask a question about the doc" style="flex:2">
       <button id="rs-ask">Ask</button><button id="rs-sum" class="ghost">Summary</button><button id="rs-an" class="ghost">Analyze fields</button></div></div>
     <div class="out" id="rs-out"></div>`;
    let did=null; const need=()=>{ if(!did)throw new Error("upload or index a document first"); return did; };
    $("#rs-up").onclick = e => run(e.target,$("#rs-out"),"research","upload",async()=>{
      const f=$("#rs-file").files[0]; if(!f)throw new Error("choose a file");
      const r=await uploadBody("/api/research/docs/upload?title="+encodeURIComponent(f.name),f); did=r.id; return r; });
    $("#rs-add").onclick = e => run(e.target,$("#rs-out"),"research","add",async()=>{
      const r=await api("POST","/api/research/docs",{title:"Pasted",text:$("#rs-text").value}); did=r.id; return r; });
    $("#rs-ask").onclick = e => run(e.target,$("#rs-out"),"research","ask",()=>
      api("POST","/api/research/ask",{question:$("#rs-q").value,doc_id:need()}),
      r=>`<div style="white-space:pre-wrap">${esc(r.answer)}</div><div style="margin-top:.5rem;color:var(--dim);font-size:.78rem">${(r.citations||[]).map(c=>"chunk "+c.chunk).join(", ")}</div>`);
    $("#rs-sum").onclick = e => run(e.target,$("#rs-out"),"research","summary",async()=>(await api("GET",`/api/research/docs/${need()}/summary`)).summary);
    $("#rs-an").onclick = e => run(e.target,$("#rs-out"),"research","analyze",()=>api("GET",`/api/research/docs/${need()}/analyze`)); } },

{ id:"match", sec:"Career", ico:"🎯", name:"Resume & Jobs",
  desc:"Upload your resume, paste a job → ranked match, brutal ATS report, and an AI-written cover letter.",
  view: el => {
    el.innerHTML = `<div class="card"><div class="row"><div style="flex:2"><label>Upload resume (PDF/DOCX/TXT)</label><input type="file" id="mt-file"></div>
       <button id="mt-up" class="ghost wide">Upload</button></div>
     <label>…or paste resume text</label><textarea id="mt-resume" placeholder="Paste your resume…"></textarea>
     <label>Job description</label><textarea id="mt-job" placeholder="Paste the job ad…"></textarea>
     <div class="row" style="margin-top:.7rem"><button id="mt-match">Match & ATS</button>
       <button id="mt-cover" class="ghost">Cover letter</button></div></div><div class="out" id="mt-out"></div>`;
    let rid=null,jid=null;
    $("#mt-up").onclick = e => run(e.target,$("#mt-out"),"match","upload",async()=>{
      const f=$("#mt-file").files[0]; if(!f)throw new Error("choose a file");
      const r=await uploadBody("/api/match/resumes/upload?name="+encodeURIComponent(f.name),f); rid=r.id; return r; });
    const ensure=async()=>{ if(!rid){const t=$("#mt-resume").value; if(!t)throw new Error("upload or paste your resume");
        rid=(await api("POST","/api/match/resumes",{name:"Me",text:t})).id;}
      if(!jid){const t=$("#mt-job").value; if(!t)throw new Error("paste a job description");
        jid=(await api("POST","/api/match/jobs",[{title:t.split("\n")[0].slice(0,60)||"Job",description:t}])).ids[0];} return [rid,jid]; };
    $("#mt-match").onclick = e => run(e.target,$("#mt-out"),"match","ats",async()=>{await ensure(); return api("GET",`/api/match/resumes/${rid}/ats/${jid}`);});
    $("#mt-cover").onclick = e => run(e.target,$("#mt-out"),"match","cover",async()=>{await ensure(); return (await api("POST",`/api/match/resumes/${rid}/cover-letter?job_id=${jid}`)).markdown;}); } },

{ id:"code", sec:"Engineer", ico:"💻", name:"Code Assistant",
  desc:"Paste code to hunt bugs (AST analysis) or generate pytest tests.",
  view: el => {
    el.innerHTML = `<div class="card"><label>Code</label><textarea id="cd-code" style="font-family:ui-monospace,monospace" placeholder="Paste Python…"></textarea>
     <div class="row" style="margin-top:.5rem"><button id="cd-bugs">Find bugs</button><button id="cd-tests" class="ghost">Generate tests</button></div></div>
     <div class="out" id="cd-out"></div>`;
    const code=()=>{const c=$("#cd-code").value; if(!c)throw new Error("paste code"); return c;};
    $("#cd-bugs").onclick = e => run(e.target,$("#cd-out"),"code","bugs",()=>api("POST","/api/code/bugs",{code:code()}),
      r=>r.findings.length?`<table><tr><th>line</th><th>kind</th><th>message</th></tr>`+
        r.findings.map(f=>`<tr><td>${f.line}</td><td class="warn">${f.kind}</td><td>${esc(f.message)}</td></tr>`).join("")+`</table>`:"No issues found.");
    $("#cd-tests").onclick = e => run(e.target,$("#cd-out"),"code","tests",async()=>(await api("POST","/api/code/gen-tests",{code:code()})).tests); } },

{ id:"team", sec:"Engineer", ico:"🤝", name:"AI Dev Team",
  desc:"Planner → Researcher → Coder → Reviewer → Tester → Docs. Give a goal, watch six roles build on each other. Heavy task; needs a model.",
  view: el => {
    el.innerHTML = `<div class="card"><label>Goal</label><input id="tm-goal" placeholder="e.g. build a CLI URL shortener in Python">
     <button id="tm-go" style="margin-top:.6rem">Run the team</button></div><div class="out" id="tm-out"></div>`;
    $("#tm-go").onclick = async e => {
      const goal=$("#tm-goal").value.trim(); if(!goal){$("#tm-out").innerHTML='<span class="bad">enter a goal</span>';return;}
      e.target.disabled=true; e.target.textContent="Running…";
      try { const r0=await api("POST","/api/team/runs",{goal});
        for(let i=0;i<600;i++){ await new Promise(r=>setTimeout(r,2500));
          const s=await api("GET","/api/team/runs/"+r0.id);
          $("#tm-out").innerHTML=(s.transcript||[]).map(m=>`<b class="warn">### ${m.role.toUpperCase()}</b>\n${esc(m.output)}`).join("\n\n")||(s.status+"…");
          if(s.status==="done"){log("team","run",goal,"done",r0.id);break;}
          if(s.status==="failed"){$("#tm-out").innerHTML=`<span class="bad">✗ needs a model — run \`spidey up\`</span>`;break;} }
      } catch(err){ $("#tm-out").innerHTML=`<span class="bad">✗ ${esc(err.message)}</span>`; }
      e.target.disabled=false; e.target.textContent="Run the team"; }; } },

{ id:"files", sec:"Data", ico:"📁", name:"File Pipeline",
  desc:"Upload any file → it's stored, queued, and profiled (CSV columns, zip contents, image size, PDF text).",
  view: el => {
    el.innerHTML = `<div class="card"><div class="row"><div style="flex:2"><label>Any file</label><input type="file" id="fp-file"></div>
       <button id="fp-go" class="wide">Upload & process</button></div></div><div class="out" id="fp-out"></div>`;
    $("#fp-go").onclick = e => run(e.target,$("#fp-out"),"files","upload",async()=>{
      const f=$("#fp-file").files[0]; if(!f)throw new Error("choose a file");
      const up=await uploadBody("/api/files/upload?name="+encodeURIComponent(f.name),f);
      for(let i=0;i<30;i++){await new Promise(r=>setTimeout(r,500)); const row=await api("GET","/api/files/"+up.id); if(row.status!=="queued")return row;} return up; }); } },

{ id:"analytics", sec:"Data", ico:"📈", name:"Analytics",
  desc:"Send events, get percentiles and timeseries. A mini-Datadog.",
  view: el => {
    el.innerHTML = `<div class="card"><div class="row"><input id="an-name" value="demo.latency"><button id="an-demo" class="ghost">Send 20 demo events</button>
       <button id="an-stat">Stats</button></div></div><div class="out" id="an-out"></div>`;
    $("#an-demo").onclick = e => run(e.target,$("#an-out"),"analytics","events",()=>
      api("POST","/api/analytics/events",Array.from({length:20},()=>({name:$("#an-name").value,value:Math.round(50+Math.random()*450)}))));
    $("#an-stat").onclick = e => run(e.target,$("#an-out"),"analytics","stats",()=>api("GET","/api/analytics/stats?name="+$("#an-name").value)); } },

{ id:"fleet", sec:"Data", ico:"🚚", name:"Fleet",
  desc:"Seed a demo vehicle and get fuel/maintenance analytics, or optimize a multi-stop route.",
  view: el => {
    el.innerHTML = `<div class="card"><div class="row"><button id="fl-seed" class="ghost">Seed demo vehicle</button>
       <button id="fl-ana">Analytics</button><button id="fl-route" class="ghost">Optimize route</button></div></div><div class="out" id="fl-out"></div>`;
    let vid=null;
    $("#fl-seed").onclick = e => run(e.target,$("#fl-out"),"fleet","seed",async()=>{
      const v=await api("POST","/api/fleet/vehicles",{name:"Van "+Date.now()%1000,plate:"B-SP "+(100+Math.floor(Math.random()*899)),odometer_km:14500,service_interval_km:15000}); vid=v.id;
      const t=h=>new Date(Date.now()-h*3600e3).toISOString();
      await api("POST","/api/fleet/pings",[{vehicle_id:vid,speed_kmh:40,fuel_l:60,odometer_km:14500,ts:t(30)},
        {vehicle_id:vid,speed_kmh:145,fuel_l:45,odometer_km:14800,ts:t(10)},{vehicle_id:vid,speed_kmh:0,fuel_l:31,odometer_km:15100,ts:t(1)}]);
      return "seeded vehicle "+vid+" — press Analytics"; });
    $("#fl-ana").onclick = e => run(e.target,$("#fl-out"),"fleet","analytics",async()=>{
      if(!vid){const vs=await api("GET","/api/fleet/vehicles");if(!vs.length)throw new Error("seed first");vid=vs[vs.length-1].id;} return api("GET",`/api/fleet/vehicles/${vid}/analytics`); });
    $("#fl-route").onclick = e => run(e.target,$("#fl-out"),"fleet","route",()=>
      api("POST","/api/fleet/routes/optimize",{stops:[{lat:52.52,lon:13.40},{lat:48.13,lon:11.58},{lat:50.11,lon:8.68},{lat:53.55,lon:9.99},{lat:51.34,lon:12.37}]})); } },

{ id:"driving", sec:"Data", ico:"🚗", name:"Driving Data",
  desc:"Load a demo drive with a closing vehicle → time-to-collision prediction and a behavior report.",
  view: el => {
    el.innerHTML = `<div class="card"><div class="row"><button id="dv-demo" class="ghost">Load demo drive</button><button id="dv-ana">Collision analytics</button></div></div><div class="out" id="dv-out"></div>`;
    let sid=null;
    $("#dv-demo").onclick = e => run(e.target,$("#dv-out"),"driving","demo",async()=>{
      sid=(await api("POST","/api/driving/sessions",{name:"Demo "+Date.now()%1000})).id;
      const frames=[]; let sp=60;
      for(let t=0;t<20;t++){const obj=t>8&&t<14?[{id:"car",distance_m:60-(t-8)*9,rel_speed_ms:-9}]:[];if(t>=13)sp=Math.max(10,sp-15);frames.push({ts:t,speed_kmh:sp,objects:obj});}
      await api("POST",`/api/driving/sessions/${sid}/frames`,frames); return "20 frames loaded — press Collision analytics"; });
    $("#dv-ana").onclick = e => run(e.target,$("#dv-out"),"driving","analytics",async()=>{if(!sid)throw new Error("load demo first"); return api("GET",`/api/driving/sessions/${sid}/analytics`);}); } },

{ id:"email", sec:"Data", ico:"✉️", name:"Email Assistant",
  desc:"Paste a raw email → category, priority, a drafted reply and calendar suggestions.",
  view: el => {
    el.innerHTML = `<div class="card"><label>Raw email</label><textarea id="em-raw"></textarea>
     <div class="row" style="margin-top:.5rem"><button id="em-sample" class="ghost">Sample</button><button id="em-go">Import & classify</button><button id="em-reply" class="ghost">Draft reply</button></div></div><div class="out" id="em-out"></div>`;
    let eid=null;
    $("#em-sample").onclick = () => $("#em-raw").value =
`From: Recruiter <talent@rocket.tech>
Subject: Interview invitation — Backend Engineer
Date: Fri, 10 Jul 2026 10:00:00 +0000
Content-Type: text/plain

Hi! Could you join an interview on 2026-07-20 at 11:00? Please confirm by tomorrow — deadline EOD.`;
    $("#em-go").onclick = e => run(e.target,$("#em-out"),"email","import",async()=>{const r=await api("POST","/api/email/import",{raw:$("#em-raw").value});eid=r.id;return r;});
    $("#em-reply").onclick = e => run(e.target,$("#em-out"),"email","reply",async()=>{if(!eid)throw new Error("import first");return (await api("POST",`/api/email/messages/${eid}/reply`)).draft;}); } },

{ id:"brain", sec:"", ico:"🧠", name:"Knowledge Graph",
  desc:"Spidey's connected memory. Every doc, repo, resume and remembered fact becomes nodes linked by how they relate — so the AI reasons over connections, not just text. It grows on its own as you use the Studio.",
  render: brainView },

{ id:"history", sec:"", ico:"🕘", name:"History", render: historyView },
];

/* ---- sidebar + navigation with history stack ---- */
const HIST = [];   // visited tool ids, for the Back button
function renderNav() {
  const secs={}; TOOLS.forEach(t=>{(secs[t.sec]=secs[t.sec]||[]).push(t);});
  let html="";
  for (const [sec,items] of Object.entries(secs)) {
    if (sec) html += `<div class="navsec">${sec}</div>`;
    html += items.map(t=>`<div class="navitem" data-id="${t.id}"><span class="ico">${t.ico}</span> ${t.name}</div>`).join("");
  }
  $("#nav").innerHTML = html;
  $("#nav").querySelectorAll(".navitem").forEach(el=>el.onclick=()=>select(el.dataset.id));
}
let CURRENT = null;
function select(id, opts) {
  opts = opts || {};
  if (CURRENT && CURRENT !== id && !opts.noPush) HIST.push(CURRENT);
  CURRENT = id;
  if (location.hash.slice(1) !== id) location.hash = id;
  $("#nav").querySelectorAll(".navitem").forEach(el=>el.classList.toggle("active",el.dataset.id===id));
  document.querySelector("aside").classList.remove("open");
  const tool = TOOLS.find(t=>t.id===id) || TOOLS[0];
  $("#tb-ico").textContent = tool.ico; $("#tb-name").textContent = tool.name;
  $("#tb-sec").textContent = tool.sec || ""; $("#tb-sec").style.display = tool.sec ? "" : "none";
  $("#tb-back").style.visibility = HIST.length ? "visible" : "hidden";
  const c = $("#content");
  c.innerHTML = `${tool.desc?`<p class="desc">${tool.desc}</p>`:""}<div id="body"></div>`;
  $("main").scrollTop = 0;
  if (tool.render) tool.render($("#body")); else tool.view($("#body"));
}
$("#tb-back").onclick = () => { const prev = HIST.pop(); if (prev != null) select(prev, {noPush:true}); };
$("#tb-reload").onclick = () => select(CURRENT || "home", {noPush:true});

async function homeView(el) {
  el.innerHTML = `<div class="stats" id="hstats"></div>
    <p class="desc">Your friendly neighborhood AI suite — every tool runs on <b>this machine</b>, and because your session lives in the database it follows you to any device on the same Wi-Fi. Pick a tool on the left; files you generate download straight to your computer.</p>
    <div class="tiles">${TOOLS.filter(t=>t.desc).map(t=>`<div class="tile" data-id="${t.id}"><div class="ti">${t.ico}</div>
      <b>${t.name}</b><span>${t.desc.split(".")[0]}.</span></div>`).join("")}</div>`;
  el.querySelectorAll(".tile").forEach(t=>t.onclick=()=>select(t.dataset.id));
  try { const [h,llm]=await Promise.all([api("GET","/api/health"),api("GET","/api/llm/stats")]); const q=h.queue||{};
    $("#hstats").innerHTML=[[h.modules.length,"AI modules"],[q.done||0,"jobs done"],[llm.totals.calls||0,"LLM calls"],
      ["$"+(llm.totals.cost_usd||0),"est. spend"],[Object.values(h.optional).filter(Boolean).length+"/"+Object.keys(h.optional).length,"extras on"]]
      .map(([v,l])=>`<div class="stat"><b>${v}</b><span>${l}</span></div>`).join("");
  } catch(e){ $("#hstats").innerHTML=`<span class="bad">server unreachable — is spidey serve running?</span>`; }
}
const TYPE_COLORS = { language:"#5b9bff", framework:"#ef3a40", tool:"#34d399",
  concept:"#fbbf24", project:"#c81e24", paper:"#a78bfa", person:"#f472b6",
  topic:"#8a8a99", skill:"#22d3ee", company:"#fb923c" };
async function brainView(el) {
  el.innerHTML = `<div class="card">
    <div class="row"><input id="bn-text" placeholder="Teach the graph: paste text / notes / a concept…" style="flex:3">
      <button id="bn-ingest">Learn it</button><button id="bn-sync" class="ghost">Sync my memory</button></div>
    <div class="row" style="margin-top:.5rem">
      <input id="bn-a" placeholder="Concept A (e.g. ROS2)"><input id="bn-b" placeholder="Concept B (e.g. YOLO)">
      <button id="bn-path" class="ghost">Find connection</button></div></div>
    <div id="bn-stats" class="stats" style="margin-top:1rem"></div>
    <div class="card"><svg id="bn-svg" width="100%" height="440" style="display:block"></svg>
      <div id="bn-legend" style="margin-top:.5rem"></div></div>
    <div class="out" id="bn-out"></div>`;
  const draw = g => {
    const svg = $("#bn-svg"); const W = svg.clientWidth || 900, H = 440;
    if (!g.nodes.length) { svg.innerHTML = `<text x="20" y="30" fill="#8a8a99">Graph is empty — use the Studio (index a repo, add a doc, chat) and it fills itself. Or type a concept above and press "Learn it".</text>`; return; }
    const idx = {}; g.nodes.forEach((n,i)=>idx[n.id]=i);
    const maxW = Math.max(...g.nodes.map(n=>n.weight));
    // simple circular + weight-radius layout (deterministic, no physics lib)
    const cx=W/2, cy=H/2, R=Math.min(W,H)/2-50;
    const pos = g.nodes.map((n,i)=>{ const a=i/g.nodes.length*2*Math.PI;
      const r = R*(0.35+0.65*(1-n.weight/maxW)); return {x:cx+r*Math.cos(a), y:cy+r*Math.sin(a)}; });
    let s = "";
    g.edges.forEach(e=>{ const a=pos[idx[e.src]], b=pos[idx[e.dst]]; if(a&&b)
      s += `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" stroke="#2a2a38" stroke-width="${Math.min(3,e.weight)}"/>`; });
    g.nodes.forEach((n,i)=>{ const p=pos[i]; const rad=6+Math.min(16,n.weight*1.5);
      const col=TYPE_COLORS[n.type]||"#8a8a99";
      s += `<circle cx="${p.x}" cy="${p.y}" r="${rad}" fill="${col}" fill-opacity="0.85" stroke="#0b0b10" stroke-width="1.5"><title>${esc(n.name)} (${n.type}, w=${n.weight.toFixed(1)})</title></circle>`;
      if (n.weight > maxW*0.45 || i%2===0) s += `<text x="${p.x+rad+2}" y="${p.y+4}" fill="#e9e9f0" font-size="11">${esc(n.name.slice(0,22))}</text>`; });
    svg.innerHTML = s;
    $("#bn-legend").innerHTML = Object.entries(TYPE_COLORS).map(([t,c])=>
      `<span class="chip" style="border-color:${c}"><span style="color:${c}">●</span> ${t}</span>`).join("");
  };
  const refresh = async () => {
    try { const [g,st]=await Promise.all([api("GET","/api/brain/graph"),api("GET","/api/brain/stats")]);
      $("#bn-stats").innerHTML = [[st.nodes,"nodes"],[st.edges,"connections"],
        [(st.by_type[0]||{}).type||"—","biggest type"],[(st.top_concepts[0]||{}).name||"—","top concept"]]
        .map(([v,l])=>`<div class="stat"><b>${v}</b><span>${l}</span></div>`).join("");
      draw(g); } catch(e){ $("#bn-out").innerHTML=`<span class="bad">${esc(e.message)}</span>`; }
  };
  $("#bn-ingest").onclick = e => run(e.target,$("#bn-out"),"brain","ingest",async()=>{
    const r=await api("POST","/api/brain/ingest",{text:$("#bn-text").value,source:"studio"}); await refresh(); return r; });
  $("#bn-sync").onclick = e => run(e.target,$("#bn-out"),"brain","sync",async()=>{
    const r=await api("POST","/api/brain/sync-memory"); await refresh(); return {nodes:r.nodes,edges:r.edges,lines:r.lines_ingested}; });
  $("#bn-path").onclick = e => run(e.target,$("#bn-out"),"brain","path",()=>
    api("GET",`/api/brain/path?from_=${encodeURIComponent($("#bn-a").value)}&to=${encodeURIComponent($("#bn-b").value)}`),
    r => r.found ? `<b class="ok">Connected in ${r.hops} hops:</b>\n`+r.path.map(p=>p.via?`  →(${p.via})→ ${p.name}`:p.name).join("\n") : `<span class="warn">${esc(r.reason||"no path")}</span>`);
  refresh();
}
async function historyView(el) {
  el.innerHTML = `<p class="desc">Every action in this session, newest first — saved in the database, still here after a restart and visible from any device that opens this session.</p><div id="hist"></div>`;
  try { const items = await api("GET",`/api/sessions/${SID}/items`);
    $("#hist").innerHTML = items.length ? `<div class="card"><table><tr><th>when</th><th>tool</th><th>action</th><th>result</th></tr>`+
      items.map(i=>`<tr><td>${(i.ts||"").slice(11,19)}</td><td>${i.module}</td><td>${i.action}</td>
        <td>${i.ref_id?`<a href="/api/docgen/files/${i.ref_id}/download">artifact #${i.ref_id}</a>`:esc((i.output||"").slice(0,60))}</td></tr>`).join("")+`</table></div>`
      : `<div class="card">Nothing yet — use a tool and it'll appear here.</div>`;
  } catch(e){ $("#hist").innerHTML=`<span class="bad">${esc(e.message)}</span>`; }
}

async function statusPing() {
  try { const h=await api("GET","/api/health");
    $("#tb-status").innerHTML = `<span class="ok">● online</span> · ${h.modules.length} modules`;
  } catch { $("#tb-status").innerHTML = `<span class="bad">● offline</span>`; }
}

(async () => {
  renderNav();
  await refreshSessionPicker();
  select((location.hash||"#home").slice(1));
  statusPing(); setInterval(statusPing, 8000);
})();
window.addEventListener("hashchange", () => select((location.hash||"#home").slice(1)));
</script>
</body>
</html>"""
