import React, { useEffect, useRef, useState } from 'react'
import './studio.css'

/* ---------------- API + session helpers ---------------- */
// Unify the credential across the whole app: a ?token= in the URL, the chat's
// token, or a Studio-set key — so opening /platform from chat is authorized.
const apiKey = () => {
  try {
    const fromUrl = new URLSearchParams(window.location.search).get('token')
    if (fromUrl) localStorage.setItem('spidey_api_key', fromUrl)
  } catch { /* ignore */ }
  return localStorage.getItem('spidey_api_key') || localStorage.getItem('spidey-token') || ''
}
const hdrs = (extra) => ({ ...(apiKey() ? { 'X-API-Key': apiKey() } : {}), ...(extra || {}) })
async function api(method, path, body, raw) {
  const o = { method, headers: hdrs(body && !raw ? { 'content-type': 'application/json' } : {}) }
  if (body !== undefined) o.body = raw ? body : JSON.stringify(body)
  const r = await fetch(path, o)
  let d = null; try { d = await r.json() } catch { /* non-json */ }
  if (!r.ok) throw new Error(d && typeof d === 'object' ? (d.detail || JSON.stringify(d)) : 'HTTP ' + r.status)
  return d
}
async function uploadBody(path, file) {
  const r = await fetch(path, { method: 'PUT', headers: hdrs(), body: file })
  const d = await r.json().catch(() => null)
  if (!r.ok) throw new Error((d && d.detail) || 'upload failed')
  return d
}
const pretty = (d) => (typeof d === 'string' ? d : JSON.stringify(d, null, 2))
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

/* ---------------- generic tool panel ---------------- */
function Field({ f, val, set }) {
  if (f.type === 'textarea') return <><label>{f.label}</label><textarea placeholder={f.placeholder} value={val || ''} onChange={(e) => set(e.target.value)} style={f.style} /></>
  if (f.type === 'select') return <div style={{ flex: f.flex || 1 }}><label>{f.label}</label><select value={val || f.options[0]} onChange={(e) => set(e.target.value)}>{f.options.map((o) => <option key={o}>{o}</option>)}</select></div>
  if (f.type === 'file') return <div style={{ flex: f.flex || 2 }}><label>{f.label}</label><input type="file" onChange={(e) => set(e.target.files[0])} /></div>
  return <div style={{ flex: f.flex || 1 }}><label>{f.label}</label><input placeholder={f.placeholder} value={val || ''} type={f.password ? 'password' : 'text'} onChange={(e) => set(e.target.value)} /></div>
}

function ToolRunner({ tool, log }) {
  const [vals, setVals] = useState({})
  const [out, setOut] = useState(null)
  const [busy, setBusy] = useState(null)
  const ctx = useRef({})
  const set = (k) => (v) => setVals((s) => ({ ...s, [k]: v }))
  ctx.current._setField = (k, v) => setVals((s) => ({ ...s, [k]: v }))

  const doAction = async (a) => {
    setBusy(a.label)
    try {
      const res = await a.run(vals, ctx.current)
      setOut({ ok: true, node: a.render ? a.render(res) : <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{pretty(res)}</pre> })
      if (log) log(tool.id, a.label, '', res, res && res.id)
    } catch (e) {
      setOut({ ok: false, node: <span className="bad">✗ {e.message}</span> })
    }
    setBusy(null)
  }

  // group standalone fields vs. field-rows
  return (
    <>
      <div className="card">
        {tool.fields?.map((f) => <Field key={f.key} f={f} val={vals[f.key]} set={set(f.key)} />)}
        {tool.rows?.map((row, i) => (
          <div className="row" key={i} style={{ marginTop: '.5rem' }}>
            {row.map((f) => <Field key={f.key} f={f} val={vals[f.key]} set={set(f.key)} />)}
          </div>
        ))}
        <div className="row" style={{ marginTop: '.8rem' }}>
          {tool.actions.map((a) => (
            <button key={a.label} className={(a.ghost ? 'ghost ' : '') + 'wide'} disabled={!!busy} onClick={() => doAction(a)}>
              {busy === a.label ? 'Working…' : a.label}
            </button>
          ))}
        </div>
      </div>
      {out && <div className="out">{out.node}</div>}
    </>
  )
}

/* ---------------- declarative standard tools ---------------- */
const TYPE_COLORS = { language: '#5b9bff', framework: '#ef3a40', tool: '#34d399', concept: '#fbbf24', project: '#c81e24', paper: '#a78bfa', person: '#f472b6', topic: '#8a8a99', skill: '#22d3ee', company: '#fb923c' }

function docRender(d) {
  return (<div>
    <b>{d.title}</b> · {d.format.toUpperCase()} · {(d.size / 1024).toFixed(1)} KB · <span className="pill red">{d.mode}</span>
    <div><a className="dl" href={d.download_url}>⬇ Download .{d.format}</a></div>
    <details style={{ marginTop: '.7rem' }}><summary style={{ cursor: 'pointer', color: 'var(--red-bright)' }}>Preview</summary>
      <pre style={{ whiteSpace: 'pre-wrap', marginTop: '.5rem' }}>{d.markdown || ''}</pre></details>
  </div>)
}

const STD_TOOLS = [
  {
    id: 'docstudio', sec: 'Create', ico: '📝', name: 'Document Studio',
    desc: 'Generate a résumé, CV, cover letter, slide deck, report, letter, README or proposal — download as .docx, .pptx, .pdf, .html, .md or .txt. The AI works only from facts you give it.',
    rows: [[
      { key: 'kind', type: 'select', label: 'What to make', flex: 2, options: ['resume', 'cv', 'cover_letter', 'presentation', 'report', 'letter', 'readme', 'proposal', 'meeting_minutes', 'custom'] },
      { key: 'format', type: 'select', label: 'Format', options: ['docx', 'pptx', 'pdf', 'html', 'md', 'txt'] },
    ]],
    fields: [
      { key: 'title', type: 'text', label: 'Title (optional)', placeholder: 'e.g. Siddharth Patni — Résumé' },
      { key: 'prompt', type: 'textarea', label: 'Brief — describe it in your words', placeholder: 'e.g. Résumé for an AI/backend engineer role. Python, FastAPI, Docker, PyTorch. Highlight the Spidey project.' },
      { key: 'details', type: 'textarea', label: "Source facts (optional — the AI won't invent facts)", style: { minHeight: 80 }, placeholder: 'Paste your real experience, dates, achievements…' },
    ],
    actions: [
      { label: 'Generate document', render: docRender, run: (v) => api('POST', '/api/docgen/create', { kind: v.kind || 'resume', format: v.format || 'docx', title: v.title || '', prompt: v.prompt || '', details: v.details || '' }) },
      { label: 'My documents', ghost: true, render: (rows) => rows.length ? <div className="tablewrap"><table><tbody><tr><th>title</th><th>kind</th><th>fmt</th><th></th></tr>{rows.map((r) => <tr key={r.id}><td>{r.title}</td><td>{r.kind}</td><td>{r.format}</td><td><a className="dl" style={{ padding: '.2rem .6rem', margin: 0 }} href={`/api/docgen/files/${r.id}/download`}>⬇</a></td></tr>)}</tbody></table></div> : 'No documents yet.', run: () => api('GET', '/api/docgen/files') },
    ],
  },
  {
    id: 'llm', sec: 'Create', ico: '🤖', name: 'AI Chat / Gateway',
    desc: 'One traced endpoint for any model. Runs on your local Ollama by default; every call logs latency, tokens and cost.',
    fields: [{ key: 'prompt', type: 'textarea', label: 'Prompt', placeholder: 'Ask anything…' }],
    rows: [[
      { key: 'provider', type: 'select', label: 'Provider', options: ['ollama', 'anthropic', 'gemini', 'openai'] },
      { key: 'model', type: 'text', label: 'Model (blank=default)', placeholder: 'gemma4:12b' },
      { key: 'akey', type: 'text', password: true, label: 'API key (hosted only)' },
    ]],
    actions: [{
      label: 'Send',
      render: (r) => <div><div style={{ marginBottom: '.5rem' }}><span className="pill red">{r.provider}/{r.model}</span> <span className="pill">{r.latency_ms} ms</span> <span className="pill">${r.cost_usd}</span></div><div style={{ whiteSpace: 'pre-wrap' }}>{r.response}</div></div>,
      run: (v) => api('POST', '/api/llm/chat', { prompt: v.prompt || '', provider: v.provider || 'ollama', model: v.model || null, api_key: v.akey || null }),
    }],
  },
  {
    id: 'scrape', sec: 'Extract', ico: '🕸', name: 'Web Scraper',
    desc: 'Pull data from any website — structured metadata, tables, links, readable text, or AI-extracted JSON.',
    fields: [{ key: 'url', type: 'text', label: 'URL', placeholder: 'https://news.ycombinator.com' }],
    rows: [[
      { key: 'strategy', type: 'select', label: 'Strategy', options: ['auto', 'structured', 'tables', 'links', 'text', 'ai'] },
      { key: 'instruction', type: 'text', flex: 2, label: 'AI instruction (for ai/auto)', placeholder: 'e.g. top 5 story titles + points' },
    ]],
    actions: [{ label: 'Scrape', run: (v) => api('POST', '/api/webauto/scrape-now', { url: v.url || '', strategy: v.strategy || 'auto', instruction: v.instruction || '' }) }],
  },
  {
    id: 'research', sec: 'Extract', ico: '📚', name: 'Research & Docs',
    desc: 'Upload a PDF/DOCX/paper (or paste text) → ask questions with citations, summarize, or extract deadlines, amounts, contacts and requirements.',
    rows: [[
      { key: 'file', type: 'file', flex: 2, label: 'Upload a document (PDF, DOCX, HTML, TXT, MD)' },
    ]],
    fields: [{ key: 'text', type: 'textarea', label: '…or paste text', placeholder: 'Paste a paper, contract, notes…' }],
    extraRows: [[{ key: 'q', type: 'text', flex: 2, label: 'Ask a question', placeholder: 'What is this about?' }]],
    actions: [
      { label: 'Upload & index', ghost: true, run: async (v, ctx) => { if (!v.file) throw new Error('choose a file'); const r = await uploadBody('/api/research/docs/upload?title=' + encodeURIComponent(v.file.name), v.file); ctx.did = r.id; return r } },
      { label: 'Index text', ghost: true, run: async (v, ctx) => { if (!v.text) throw new Error('paste text'); const r = await api('POST', '/api/research/docs', { title: 'Pasted', text: v.text }); ctx.did = r.id; return r } },
      { label: 'Ask', render: (r) => <div><div style={{ whiteSpace: 'pre-wrap' }}>{r.answer}</div><div style={{ color: 'var(--dim)', fontSize: '.78rem', marginTop: '.4rem' }}>{(r.citations || []).map((c) => 'chunk ' + c.chunk).join(', ')}</div></div>, run: (v, ctx) => { if (!ctx.did) throw new Error('upload or index a document first'); return api('POST', '/api/research/ask', { question: v.q || '', doc_id: ctx.did }) } },
      { label: 'Analyze fields', ghost: true, run: (v, ctx) => { if (!ctx.did) throw new Error('upload a document first'); return api('GET', `/api/research/docs/${ctx.did}/analyze`) } },
      { label: 'Deep research (web)', run: (v) => { if (!v.q) throw new Error('type a question in the box above'); return api('POST', '/api/research/deep', { question: v.q, scholarly: true }) }, render: (r) => <div><div style={{ whiteSpace: 'pre-wrap' }}>{r.answer}</div><div style={{ marginTop: '.5rem' }}>{(r.sources || []).map((s) => <div key={s.n} style={{ fontSize: '.78rem' }}>[{s.n}] <a href={s.url} target="_blank" rel="noreferrer">{s.title}</a> <span className="chip">{s.source}</span></div>)}</div></div> },
    ],
  },
  {
    id: 'match', sec: 'Career', ico: '🎯', name: 'Resume & Jobs',
    desc: 'Upload your resume, paste a job → ranked match, brutal ATS report, and an AI-written cover letter.',
    rows: [[{ key: 'file', type: 'file', flex: 2, label: 'Upload resume (PDF/DOCX/TXT)' }]],
    fields: [
      { key: 'resume', type: 'textarea', label: '…or paste resume text', placeholder: 'Paste your resume…' },
      { key: 'job', type: 'textarea', label: 'Job description', placeholder: 'Paste the job ad…' },
    ],
    actions: [
      { label: 'Upload resume', ghost: true, run: async (v, ctx) => { if (!v.file) throw new Error('choose a file'); const r = await uploadBody('/api/match/resumes/upload?name=' + encodeURIComponent(v.file.name), v.file); ctx.rid = r.id; return r } },
      { label: 'Match & ATS', run: async (v, ctx) => { await ensureMatch(v, ctx); return api('GET', `/api/match/resumes/${ctx.rid}/ats/${ctx.jid}`) } },
      { label: 'Cover letter', ghost: true, run: async (v, ctx) => { await ensureMatch(v, ctx); return (await api('POST', `/api/match/resumes/${ctx.rid}/cover-letter?job_id=${ctx.jid}`)).markdown } },
    ],
  },
  {
    id: 'media', sec: 'Create', ico: '🎨', name: 'Media Studio',
    desc: 'Generate images from a prompt using a local Stable Diffusion backend. (Ollama runs text only — install AUTOMATIC1111/ComfyUI with --api for images; audio/video backends wire in the same way.) Press Check backends to see what\'s available.',
    fields: [{ key: 'prompt', type: 'textarea', label: 'Image prompt', placeholder: 'e.g. a spider-web city skyline at dusk, cinematic, highly detailed' }],
    rows: [[
      { key: 'w', type: 'select', label: 'Width', options: ['512', '768', '1024'] },
      { key: 'h', type: 'select', label: 'Height', options: ['512', '768', '1024'] },
      { key: 'negative_prompt', type: 'text', flex: 2, label: 'Avoid (optional)', placeholder: 'blurry, low quality' },
    ]],
    actions: [
      { label: 'Generate image', render: (d) => <div><b>{d.title}</b> · {(d.size / 1024).toFixed(0)} KB<div><a className="dl" href={d.download_url}>⬇ Download image</a></div><div style={{ marginTop: '.6rem' }}><img src={d.download_url} alt="" style={{ maxWidth: '100%', borderRadius: 10, border: '1px solid var(--line)' }} /></div></div>, run: (v) => api('POST', '/api/media/image', { prompt: v.prompt || '', negative_prompt: v.negative_prompt || '', width: +(v.w || 512), height: +(v.h || 512) }) },
      { label: 'Check backends', ghost: true, run: () => api('GET', '/api/media/status') },
    ],
  },
  {
    id: 'memory', sec: 'Extract', ico: '🗄', name: 'Memory Engine',
    desc: "Typed long-term memory (preferences · goals · projects · facts · workflows) the AI carries across sessions. Semantic recall retrieves what's relevant, not just recent. Sync folds in Spidey's markdown memory + lessons.",
    rows: [[
      { key: 'kind', type: 'select', label: 'Type', options: ['preference', 'goal', 'project', 'fact', 'skill', 'workflow'] },
      { key: 'content', type: 'text', flex: 3, label: 'Remember this', placeholder: 'e.g. I prefer TypeScript and tabs over spaces' },
    ], [
      { key: 'q', type: 'text', flex: 3, label: 'Recall (semantic)', placeholder: 'what do you know about my preferences?' },
    ]],
    actions: [
      { label: 'Remember', run: (v) => api('POST', '/api/memory/remember', { content: v.content || '', kind: v.kind || 'fact' }) },
      { label: 'Recall', ghost: true, render: (r) => r.memories?.length ? <div>{r.memories.map((m) => <div className="card" key={m.id} style={{ marginBottom: '.4rem' }}><span className="pill red">{m.kind}</span> <span className="pill">{m.score}</span><div style={{ marginTop: '.3rem' }}>{m.content}</div></div>)}</div> : 'Nothing recalled yet.', run: (v) => api('GET', '/api/memory/recall?q=' + encodeURIComponent(v.q || '')) },
      { label: 'My profile', ghost: true, run: () => api('GET', '/api/memory/profile') },
      { label: 'Sync markdown memory', ghost: true, run: () => api('POST', '/api/memory/sync') },
    ],
  },
  {
    id: 'code', sec: 'Engineer', ico: '💻', name: 'Code Assistant',
    desc: 'Paste code to hunt bugs (AST analysis) or generate pytest tests.',
    fields: [{ key: 'code', type: 'textarea', label: 'Code', style: { fontFamily: 'ui-monospace,monospace' }, placeholder: 'Paste Python…' }],
    actions: [
      { label: 'Find bugs', render: (r) => r.findings.length ? <div className="tablewrap"><table><tbody><tr><th>line</th><th>kind</th><th>message</th></tr>{r.findings.map((f, i) => <tr key={i}><td>{f.line}</td><td className="warn">{f.kind}</td><td>{f.message}</td></tr>)}</tbody></table></div> : 'No issues found.', run: (v) => { if (!v.code) throw new Error('paste code'); return api('POST', '/api/code/bugs', { code: v.code }) } },
      { label: 'Generate tests', ghost: true, run: async (v) => { if (!v.code) throw new Error('paste code'); return (await api('POST', '/api/code/gen-tests', { code: v.code })).tests } },
    ],
  },
  {
    id: 'files', sec: 'Data', ico: '📁', name: 'File Pipeline',
    desc: 'Upload any file → stored, queued, and profiled (CSV columns, zip contents, image size, PDF text).',
    rows: [[{ key: 'file', type: 'file', flex: 2, label: 'Any file' }]],
    actions: [{ label: 'Upload & process', run: async (v) => { if (!v.file) throw new Error('choose a file'); const up = await uploadBody('/api/files/upload?name=' + encodeURIComponent(v.file.name), v.file); for (let i = 0; i < 30; i++) { await sleep(500); const row = await api('GET', '/api/files/' + up.id); if (row.status !== 'queued') return row } return up } }],
  },
  {
    id: 'analytics', sec: 'Data', ico: '📈', name: 'Analytics',
    desc: 'Send events, get percentiles and timeseries. A mini-Datadog.',
    rows: [[{ key: 'name', type: 'text', label: 'Metric name' }]],
    actions: [
      { label: 'Send 20 demo events', ghost: true, run: (v) => api('POST', '/api/analytics/events', Array.from({ length: 20 }, () => ({ name: v.name || 'demo.latency', value: Math.round(50 + Math.random() * 450) }))) },
      { label: 'Stats', run: (v) => api('GET', '/api/analytics/stats?name=' + (v.name || 'demo.latency')) },
    ],
  },
  {
    id: 'fleet', sec: 'Data', ico: '🚚', name: 'Fleet',
    desc: 'Seed a demo vehicle and get fuel/maintenance analytics, or optimize a multi-stop route.',
    actions: [
      { label: 'Seed demo vehicle', ghost: true, run: async (v, ctx) => { const veh = await api('POST', '/api/fleet/vehicles', { name: 'Van ' + (Date.now() % 1000), plate: 'B-SP ' + (100 + Math.floor(Math.random() * 899)), odometer_km: 14500, service_interval_km: 15000 }); ctx.vid = veh.id; const t = (h) => new Date(Date.now() - h * 3600e3).toISOString(); await api('POST', '/api/fleet/pings', [{ vehicle_id: ctx.vid, speed_kmh: 40, fuel_l: 60, odometer_km: 14500, ts: t(30) }, { vehicle_id: ctx.vid, speed_kmh: 145, fuel_l: 45, odometer_km: 14800, ts: t(10) }, { vehicle_id: ctx.vid, speed_kmh: 0, fuel_l: 31, odometer_km: 15100, ts: t(1) }]); return 'seeded vehicle ' + ctx.vid + ' — press Analytics' } },
      { label: 'Analytics', run: async (v, ctx) => { if (!ctx.vid) { const vs = await api('GET', '/api/fleet/vehicles'); if (!vs.length) throw new Error('seed first'); ctx.vid = vs[vs.length - 1].id } return api('GET', `/api/fleet/vehicles/${ctx.vid}/analytics`) } },
      { label: 'Optimize route', ghost: true, run: () => api('POST', '/api/fleet/routes/optimize', { stops: [{ lat: 52.52, lon: 13.40 }, { lat: 48.13, lon: 11.58 }, { lat: 50.11, lon: 8.68 }, { lat: 53.55, lon: 9.99 }, { lat: 51.34, lon: 12.37 }] }) },
    ],
  },
  {
    id: 'driving', sec: 'Data', ico: '🚗', name: 'Driving Data',
    desc: 'Load a demo drive with a closing vehicle → time-to-collision prediction and a behavior report.',
    actions: [
      { label: 'Load demo drive', ghost: true, run: async (v, ctx) => { ctx.sid = (await api('POST', '/api/driving/sessions', { name: 'Demo ' + (Date.now() % 1000) })).id; const frames = []; let sp = 60; for (let t = 0; t < 20; t++) { const obj = t > 8 && t < 14 ? [{ id: 'car', distance_m: 60 - (t - 8) * 9, rel_speed_ms: -9 }] : []; if (t >= 13) sp = Math.max(10, sp - 15); frames.push({ ts: t, speed_kmh: sp, objects: obj }) } await api('POST', `/api/driving/sessions/${ctx.sid}/frames`, frames); return '20 frames loaded — press Collision analytics' } },
      { label: 'Collision analytics', run: (v, ctx) => { if (!ctx.sid) throw new Error('load demo first'); return api('GET', `/api/driving/sessions/${ctx.sid}/analytics`) } },
    ],
  },
  {
    id: 'email', sec: 'Data', ico: '✉️', name: 'Email Assistant',
    desc: 'Paste a raw email → category, priority, a drafted reply and calendar suggestions.',
    fields: [{ key: 'raw', type: 'textarea', label: 'Raw email' }],
    actions: [
      { label: 'Sample', ghost: true, run: (v, ctx) => { ctx._setField('raw', 'From: Recruiter <talent@rocket.tech>\nSubject: Interview invitation — Backend Engineer\nDate: Fri, 10 Jul 2026 10:00:00 +0000\nContent-Type: text/plain\n\nHi! Could you join an interview on 2026-07-20 at 11:00? Please confirm by tomorrow — deadline EOD.'); return 'Sample loaded into the box above — now press Import & classify.' } },
      { label: 'Import & classify', run: async (v, ctx) => { const r = await api('POST', '/api/email/import', { raw: v.raw || '' }); ctx.eid = r.id; return r } },
      { label: 'Draft reply', ghost: true, run: async (v, ctx) => { if (!ctx.eid) throw new Error('import an email first'); return (await api('POST', `/api/email/messages/${ctx.eid}/reply`)).draft } },
    ],
  },
]

async function ensureMatch(v, ctx) {
  if (!ctx.rid) { if (!v.resume) throw new Error('upload or paste your resume'); ctx.rid = (await api('POST', '/api/match/resumes', { name: 'Me', text: v.resume })).id }
  if (!ctx.jid) { if (!v.job) throw new Error('paste a job description'); ctx.jid = (await api('POST', '/api/match/jobs', [{ title: (v.job.split('\n')[0] || 'Job').slice(0, 60), description: v.job }])).ids[0] }
}

/* research tool needs its question row appended after the paste box */
STD_TOOLS.find((t) => t.id === 'research').rows.push([{ key: 'q', type: 'text', flex: 2, label: 'Ask a question about the doc', placeholder: 'What is this about?' }])

/* ---------------- custom components ---------------- */
function PaperTool({ log }) {
  const [topic, setTopic] = useState('')
  const [fmt, setFmt] = useState('pdf')
  const [prog, setProg] = useState(null)
  const [out, setOut] = useState(null)
  const [busy, setBusy] = useState(false)
  const stages = ['Abstract', 'I. Introduction', 'II. Related Work', 'III. Methodology', 'IV. Results and Discussion', 'V. Conclusion']
  const go = async () => {
    if (!topic.trim()) { setOut(<span className="bad">enter a topic</span>); return }
    setBusy(true); setOut(null)
    try {
      const r0 = await api('POST', '/api/docgen/paper', { topic, format: fmt })
      for (let i = 0; i < 600; i++) {
        await sleep(2500)
        const s = await api('GET', `/api/docgen/paper/${r0.id}`)
        const done = (s.progress && s.progress.sections_done) || []
        const pct = s.status === 'done' ? 100 : Math.round((done.length / stages.length) * 100)
        setProg(<div className="card"><div className="barbg"><div className="barfg" style={{ width: pct + '%' }} /></div>
          <div style={{ margin: '.55rem 0' }}><span className="pill red">{s.status}</span> {s.progress && s.progress.stage}</div>
          {stages.map((x) => <span key={x} className={'chip ' + (done.includes(x) ? 'done' : '')}>{done.includes(x) ? '✓ ' : ''}{x}</span>)}
          <div style={{ marginTop: '.4rem', color: 'var(--dim)', fontSize: '.78rem' }}>{(s.sources || []).length} references fetched</div></div>)
        if (s.status === 'done') { setOut(<div><a className="dl" href={s.download_url}>⬇ Download the paper</a><pre style={{ whiteSpace: 'pre-wrap', marginTop: '.8rem' }}>{s.markdown}</pre></div>); log && log('docgen', 'paper', topic, 'done', s.doc_id); break }
        if (s.status === 'failed') { setOut(<span className="bad">✗ {s.error || 'failed'}</span>); break }
      }
    } catch (e) { setOut(<span className="bad">✗ {e.message}</span>) }
    setBusy(false)
  }
  return (<>
    <div className="card"><div className="row">
      <div style={{ flex: 3 }}><label>Research topic</label><input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="e.g. Reliable tool-calling in small on-device language models" /></div>
      <div><label>Format</label><select value={fmt} onChange={(e) => setFmt(e.target.value)}>{['pdf', 'docx', 'html', 'md'].map((f) => <option key={f}>{f}</option>)}</select></div>
      <button className="wide" disabled={busy} onClick={go}>{busy ? 'Researching…' : 'Write paper'}</button>
    </div></div>
    {prog}{out && <div className="out">{out}</div>}
  </>)
}

function TeamTool({ log }) {
  const [goal, setGoal] = useState('')
  const [out, setOut] = useState(null)
  const [busy, setBusy] = useState(false)
  const go = async () => {
    if (!goal.trim()) { setOut(<span className="bad">enter a goal</span>); return }
    setBusy(true); setOut(null)
    try {
      const r0 = await api('POST', '/api/team/runs', { goal })
      for (let i = 0; i < 600; i++) {
        await sleep(2500)
        const s = await api('GET', '/api/team/runs/' + r0.id)
        setOut(<div>{(s.transcript || []).map((m, k) => <div key={k}><b className="warn">### {m.role.toUpperCase()}</b><pre style={{ whiteSpace: 'pre-wrap', margin: '.2rem 0 1rem' }}>{m.output}</pre></div>)}{!s.transcript?.length && (s.status + '…')}</div>)
        if (s.status === 'done') { log && log('team', 'run', goal, 'done', r0.id); break }
        if (s.status === 'failed') { setOut(<span className="bad">✗ needs a model — run `spidey up`</span>); break }
      }
    } catch (e) { setOut(<span className="bad">✗ {e.message}</span>) }
    setBusy(false)
  }
  return (<>
    <div className="card"><label>Goal</label><input value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="e.g. build a CLI URL shortener in Python" />
      <button style={{ marginTop: '.6rem' }} disabled={busy} onClick={go}>{busy ? 'Running…' : 'Run the team'}</button></div>
    {out && <div className="out">{out}</div>}
  </>)
}

/* Live force-directed "neural network" of the knowledge graph, on a canvas:
   nodes repel, edges pull, signals pulse along connections like firing synapses.
   Polls the API so new nodes animate in as the graph learns. */
function NeuralGraph({ version }) {
  const canvasRef = useRef(null)
  const sim = useRef({ nodes: new Map(), edges: [], pulses: [], adj: new Map() })
  const raf = useRef(0)

  const load = async () => {
    try {
      const g = await api('GET', '/api/brain/graph')
      const S = sim.current
      const seen = new Set()
      const maxW = Math.max(1, ...g.nodes.map((n) => n.weight))
      g.nodes.forEach((n) => {
        seen.add(n.id)
        const cv = canvasRef.current
        const W = (cv && cv.clientWidth) || 800, H = (cv && cv.clientHeight) || 420
        if (!S.nodes.has(n.id)) S.nodes.set(n.id, { ...n, x: W / 2 + (Math.random() - 0.5) * 120, y: H / 2 + (Math.random() - 0.5) * 120, vx: 0, vy: 0, born: performance.now() })
        else Object.assign(S.nodes.get(n.id), { weight: n.weight, name: n.name, type: n.type })
        S.nodes.get(n.id).r = 4 + Math.min(18, (n.weight / maxW) * 18)
      })
      for (const id of [...S.nodes.keys()]) if (!seen.has(id)) S.nodes.delete(id)
      S.edges = g.edges.filter((e) => S.nodes.has(e.src) && S.nodes.has(e.dst))
      S.adj = new Map()
      S.edges.forEach((e) => { S.adj.set(e.src, [...(S.adj.get(e.src) || []), e.dst]); S.adj.set(e.dst, [...(S.adj.get(e.dst) || []), e.src]) })
    } catch { /* offline */ }
  }
  useEffect(() => { load() }, [version]) // eslint-disable-line
  useEffect(() => {
    const iv = setInterval(load, 5000)
    const cv = canvasRef.current
    const ctx = cv.getContext('2d')
    const fit = () => { const d = window.devicePixelRatio || 1; cv.width = cv.clientWidth * d; cv.height = cv.clientHeight * d; ctx.setTransform(d, 0, 0, d, 0, 0) }
    fit(); window.addEventListener('resize', fit)

    const step = () => {
      const S = sim.current
      const W = cv.clientWidth, H = cv.clientHeight
      const arr = [...S.nodes.values()]
      // forces: repulsion (all pairs), spring (edges), gravity to center
      for (let i = 0; i < arr.length; i++) {
        const a = arr[i]
        for (let j = i + 1; j < arr.length; j++) {
          const b = arr[j]
          let dx = a.x - b.x, dy = a.y - b.y; let d2 = dx * dx + dy * dy || 0.01
          const f = 900 / d2; const d = Math.sqrt(d2)
          const ux = dx / d, uy = dy / d
          a.vx += ux * f; a.vy += uy * f; b.vx -= ux * f; b.vy -= uy * f
        }
        a.vx += (W / 2 - a.x) * 0.0016; a.vy += (H / 2 - a.y) * 0.0016
      }
      const byId = S.nodes
      S.edges.forEach((e) => {
        const a = byId.get(e.src), b = byId.get(e.dst); if (!a || !b) return
        let dx = b.x - a.x, dy = b.y - a.y; const d = Math.sqrt(dx * dx + dy * dy) || 0.01
        const target = 90; const f = (d - target) * 0.006
        const ux = dx / d, uy = dy / d
        a.vx += ux * f; a.vy += uy * f; b.vx -= ux * f; b.vy -= uy * f
      })
      arr.forEach((n) => { n.vx *= 0.86; n.vy *= 0.86; n.x += n.vx; n.y += n.vy; n.x = Math.max(n.r, Math.min(W - n.r, n.x)); n.y = Math.max(n.r, Math.min(H - n.r, n.y)) })

      // spawn signal pulses along random edges (synapses firing)
      if (S.edges.length && Math.random() < 0.25 && S.pulses.length < 40) {
        const e = S.edges[Math.floor(Math.random() * S.edges.length)]
        S.pulses.push({ src: e.src, dst: e.dst, t: 0 })
      }
      S.pulses = S.pulses.filter((p) => { p.t += 0.02; if (p.t >= 1) { // arrive → sometimes fire onward
        if (Math.random() < 0.5) { const nb = (S.adj.get(p.dst) || []); if (nb.length) S.pulses.push({ src: p.dst, dst: nb[Math.floor(Math.random() * nb.length)], t: 0 }) }
        return false } return true })

      // ---- draw ----
      ctx.clearRect(0, 0, W, H)
      // edges
      ctx.lineWidth = 1
      S.edges.forEach((e) => { const a = byId.get(e.src), b = byId.get(e.dst); if (!a || !b) return; ctx.strokeStyle = 'rgba(120,120,140,0.14)'; ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke() })
      // pulses
      S.pulses.forEach((p) => { const a = byId.get(p.src), b = byId.get(p.dst); if (!a || !b) return; const x = a.x + (b.x - a.x) * p.t, y = a.y + (b.y - a.y) * p.t; ctx.beginPath(); ctx.arc(x, y, 2.6, 0, 7); ctx.fillStyle = '#ef3a40'; ctx.shadowColor = '#ef3a40'; ctx.shadowBlur = 12; ctx.fill(); ctx.shadowBlur = 0 })
      // nodes
      const now = performance.now()
      arr.forEach((n) => {
        const col = TYPE_COLORS[n.type] || '#8a8a92'
        const grow = Math.min(1, (now - n.born) / 500)
        const r = n.r * grow
        ctx.beginPath(); ctx.arc(n.x, n.y, r, 0, 7)
        ctx.fillStyle = col; ctx.shadowColor = col; ctx.shadowBlur = 10 + r; ctx.globalAlpha = 0.9; ctx.fill()
        ctx.globalAlpha = 1; ctx.shadowBlur = 0
        if (r > 8) { ctx.fillStyle = 'rgba(240,240,245,0.92)'; ctx.font = '11px ui-sans-serif,system-ui'; ctx.fillText(n.name.slice(0, 20), n.x + r + 3, n.y + 4) }
      })
      if (!arr.length) { ctx.fillStyle = '#8a8a92'; ctx.font = '13px ui-sans-serif'; ctx.fillText('Graph is empty — index a repo, add a doc, or type a concept below and press "Learn it".', 16, 28) }
      raf.current = requestAnimationFrame(step)
    }
    raf.current = requestAnimationFrame(step)
    return () => { cancelAnimationFrame(raf.current); clearInterval(iv); window.removeEventListener('resize', fit) }
  }, []) // eslint-disable-line
  return <canvas ref={canvasRef} className="bn-svg" />
}

// Knowledge Nexus — crawl the web into the AI's own searchable memory, then
// run hybrid (BM25 + vector + graph + recency) search over it. Live crawl stats.
function NexusTool({ log }) {
  const [url, setUrl] = useState(''); const [q, setQ] = useState('')
  const [st, setSt] = useState(null); const [out, setOut] = useState(null); const [busy, setBusy] = useState(null)
  const refresh = async () => { try { setSt(await api('GET', '/api/nexus/status')) } catch { /* offline */ } }
  useEffect(() => { refresh(); const iv = setInterval(refresh, 4000); return () => clearInterval(iv) }, [])
  const act = async (name, fn, render) => {
    setBusy(name)
    try { const r = await fn(); setOut(render ? render(r) : <pre style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{pretty(r)}</pre>); refresh(); log && log('nexus', name, url || q, r) }
    catch (e) { setOut(<span className="bad">✗ {e.message}</span>) }
    setBusy(null)
  }
  const results = (r) => r.results?.length ? r.results.map((h, i) => (
    <div className="card" key={i} style={{ marginBottom: '.5rem' }}>
      <div style={{ display: 'flex', gap: '.5rem', alignItems: 'baseline', flexWrap: 'wrap' }}>
        <span className="pill red">{h.score}</span><b>{h.title || h.url}</b></div>
      <a href={h.url} target="_blank" rel="noreferrer" style={{ fontSize: '.76rem' }}>{h.url}</a>
      <div style={{ color: 'var(--dim)', fontSize: '.82rem', marginTop: '.3rem' }}>{h.snippet}</div>
      <div style={{ marginTop: '.3rem' }}>{Object.entries(h.signals || {}).map(([k, v]) => <span className="chip" key={k}>{k}: {v}</span>)}</div>
    </div>)) : <span className="warn">No results — crawl a site first.</span>
  return (<>
    {st && <div className="stats">
      {[[st.indexed, 'pages indexed'], [st.chunks, 'chunks'], [st.duplicates_removed, 'dupes removed'], [st.vocabulary, 'vocabulary'], [st.domains, 'domains']].map(([v, l], i) => <div className="stat" key={i}><b>{v}</b><span>{l}</span></div>)}
    </div>}
    <div className="card">
      <label>Crawl a site — or a whole topic — into Spidey's knowledge base (deduplicated, entity-linked)</label>
      <div className="row"><input style={{ flex: 3 }} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.com  — or a topic like 'Inspire RH56 hand RS485'" />
        <button disabled={!!busy} onClick={() => act('crawl', () => url.startsWith('http') ? api('POST', '/api/nexus/crawl', { url, depth: 1, max_pages: 15 }) : api('POST', '/api/nexus/crawl-search', { query: url, max_pages: 6 }))}>Crawl</button></div>
      <label style={{ marginTop: '.7rem' }}>Hybrid search over everything indexed</label>
      <div className="row"><input style={{ flex: 3 }} value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. how does self-attention work" />
        <button disabled={!!busy} onClick={() => act('search', () => api('GET', '/api/nexus/search?q=' + encodeURIComponent(q)), results)}>Search</button>
        <button className="ghost" disabled={!!busy} onClick={() => act('answer', () => api('GET', '/api/nexus/answer?q=' + encodeURIComponent(q)), (r) => <div><div style={{ whiteSpace: 'pre-wrap' }}>{r.answer}</div><div style={{ marginTop: '.5rem' }}>{results(r)}</div></div>)}>Ask (RAG)</button></div>
    </div>
    {out && <div className="out">{out}</div>}
  </>)
}

function BrainTool({ log }) {
  const [a, setA] = useState(''); const [b, setB] = useState(''); const [text, setText] = useState('')
  const [st, setSt] = useState(null); const [out, setOut] = useState(null); const [busy, setBusy] = useState(null)
  const [version, setVersion] = useState(0)
  const refreshStats = async () => { try { setSt(await api('GET', '/api/brain/stats')) } catch { /* offline */ } }
  useEffect(() => { refreshStats(); const iv = setInterval(refreshStats, 5000); return () => clearInterval(iv) }, [])
  const act = async (name, fn, render) => {
    setBusy(name)
    try { const r = await fn(); setOut(render ? render(r) : <pre style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{pretty(r)}</pre>); refreshStats(); setVersion((v) => v + 1) }
    catch (e) { setOut(<span className="bad">✗ {e.message}</span>) }
    setBusy(null)
  }
  return (<>
    {st && <div className="stats">
      {[[st.nodes, 'neurons'], [st.edges, 'synapses'], [(st.by_type[0] || {}).type || '—', 'biggest type'], [(st.top_concepts[0] || {}).name || '—', 'top concept']].map(([v, l], i) => <div className="stat" key={i}><b>{v}</b><span>{l}</span></div>)}
    </div>}
    <div className="card" style={{ padding: '.4rem' }}>
      <NeuralGraph version={version} />
      <div style={{ margin: '.5rem .3rem 0' }}>{Object.entries(TYPE_COLORS).map(([t, c]) => <span className="chip" key={t} style={{ borderColor: c }}><span style={{ color: c }}>●</span> {t}</span>)}</div>
    </div>
    <div className="card" style={{ marginTop: '1rem' }}>
      <div className="row"><input style={{ flex: 3 }} value={text} onChange={(e) => setText(e.target.value)} placeholder="Teach the graph: paste text / notes / a concept…" />
        <button disabled={!!busy} onClick={() => act('learn', () => api('POST', '/api/brain/ingest', { text, source: 'studio' }))}>Learn it</button>
        <button className="ghost" disabled={!!busy} onClick={() => act('sync', () => api('POST', '/api/brain/sync-memory'))}>Sync my memory</button></div>
      <div className="row" style={{ marginTop: '.5rem' }}>
        <input value={a} onChange={(e) => setA(e.target.value)} placeholder="Concept A (e.g. ROS2)" />
        <input value={b} onChange={(e) => setB(e.target.value)} placeholder="Concept B (e.g. YOLO)" />
        <button className="ghost" disabled={!!busy} onClick={() => act('path', () => api('GET', `/api/brain/path?from_=${encodeURIComponent(a)}&to=${encodeURIComponent(b)}`), (r) => r.found ? <div><b className="ok">Connected in {r.hops} hops:</b>{'\n'}{r.path.map((p) => p.via ? `  →(${p.via})→ ${p.name}` : p.name).join('\n')}</div> : <span className="warn">{r.reason || 'no path'}</span>)}>Find connection</button></div>
    </div>
    {out && <div className="out">{out}</div>}
  </>)
}

/* ---------------- shell ---------------- */
function useSessions() {
  const [sid, setSid] = useState(localStorage.getItem('spidey_session_id'))
  const [sessions, setSessions] = useState([])
  const refresh = async () => {
    try {
      let ss = await api('GET', '/api/sessions')
      if (!ss.length || !ss.find((s) => String(s.id) === sid)) {
        const s = await api('POST', '/api/sessions', { name: 'Studio ' + new Date().toLocaleString() })
        localStorage.setItem('spidey_session_id', String(s.id)); setSid(String(s.id))
        ss = await api('GET', '/api/sessions')
      }
      setSessions(ss)
    } catch { /* offline */ }
  }
  useEffect(() => { refresh() }, []) // eslint-disable-line
  const pick = async (val) => {
    let id = val
    if (val === '__new') { const s = await api('POST', '/api/sessions', { name: 'Studio ' + new Date().toLocaleString() }); id = String(s.id) }
    localStorage.setItem('spidey_session_id', String(id)); setSid(String(id)); refresh()
  }
  const log = async (module, action, input, output, ref) => {
    try { await api('POST', `/api/sessions/${sid}/items`, { module, action, input: (input || '').slice(0, 1000), output: pretty(output).slice(0, 2000), ref_id: ref || null }); refresh() } catch { /* ignore */ }
  }
  return { sid, sessions, pick, log, refresh }
}

const CUSTOM = {
  home: HomeView, brain: BrainTool, history: HistoryView,
  paper: PaperTool, team: TeamTool, nexus: NexusTool,
}
const EXTRA_TOOLS = [
  { id: 'paper', sec: 'Create', ico: '🔬', name: 'Research Paper (IEEE)', desc: 'Give a topic; Spidey fetches real references (Crossref + Wikipedia) and writes a full IEEE-format paper section by section, live.' },
  { id: 'nexus', sec: 'Extract', ico: '🌐', name: 'Knowledge Nexus', desc: "The flagship: a mini search-engine for your AI. Crawls the web (distributed, deduplicated, entity-linked into the knowledge graph), then serves hybrid BM25 + vector + graph + recency search. Spidey's continuously-updating long-term web memory." },
  { id: 'team', sec: 'Engineer', ico: '🤝', name: 'AI Dev Team', desc: 'Planner → Researcher → Coder → Reviewer → Tester → Docs, with shared memory. Heavy task; needs a model.' },
  { id: 'brain', sec: '', ico: '🧠', name: 'Knowledge Graph', desc: "Spidey's connected memory. Every doc, repo, resume and remembered fact becomes nodes linked by how they relate — the AI reasons over connections, and it grows on its own." },
  { id: 'home', sec: '', ico: '🏠', name: 'Overview' },
  { id: 'history', sec: '', ico: '🕘', name: 'History' },
]
// ordering: Overview first, then Create/Extract/Career/Engineer/Data, then Graph/History
const ALL = [
  EXTRA_TOOLS.find((t) => t.id === 'home'),
  STD_TOOLS.find((t) => t.id === 'docstudio'),
  EXTRA_TOOLS.find((t) => t.id === 'paper'),
  STD_TOOLS.find((t) => t.id === 'media'),
  STD_TOOLS.find((t) => t.id === 'llm'),
  STD_TOOLS.find((t) => t.id === 'scrape'),
  EXTRA_TOOLS.find((t) => t.id === 'nexus'),
  STD_TOOLS.find((t) => t.id === 'research'),
  STD_TOOLS.find((t) => t.id === 'memory'),
  STD_TOOLS.find((t) => t.id === 'match'),
  STD_TOOLS.find((t) => t.id === 'code'),
  EXTRA_TOOLS.find((t) => t.id === 'team'),
  ...STD_TOOLS.filter((t) => t.sec === 'Data'),
  EXTRA_TOOLS.find((t) => t.id === 'brain'),
  EXTRA_TOOLS.find((t) => t.id === 'history'),
].filter(Boolean)   // a missing id must never blank out the whole sidebar

function HomeView({ select }) {
  const [st, setSt] = useState(null)
  useEffect(() => { (async () => { try { const [h, llm] = await Promise.all([api('GET', '/api/health'), api('GET', '/api/llm/stats')]); setSt({ h, llm }) } catch { setSt('err') } })() }, [])
  const cards = ALL.filter((t) => t.desc)
  return (<>
    {st && st !== 'err' && <div className="stats">{[[st.h.modules.length, 'AI modules'], [(st.h.queue || {}).done || 0, 'jobs done'], [st.llm.totals.calls || 0, 'LLM calls'], ['$' + (st.llm.totals.cost_usd || 0), 'est. spend'], [Object.values(st.h.optional).filter(Boolean).length + '/' + Object.keys(st.h.optional).length, 'extras on']].map(([v, l], i) => <div className="stat" key={i}><b>{v}</b><span>{l}</span></div>)}</div>}
    {st === 'err' && <div className="out"><span className="bad">server unreachable — is spidey serve running?</span></div>}
    <p className="desc">Your friendly neighborhood AI suite — every tool runs on <b>this machine</b>, and because your session lives in the database it follows you to any device on the same Wi-Fi. Pick a tool; files you generate download straight to your computer.</p>
    <div className="tiles">{cards.map((t) => <div className="tile" key={t.id} onClick={() => select(t.id)}><div className="ti">{t.ico}</div><b>{t.name}</b><span>{(t.desc || '').split('.')[0]}.</span></div>)}</div>
  </>)
}

function HistoryView({ sid }) {
  const [items, setItems] = useState(null)
  useEffect(() => { (async () => { try { setItems(await api('GET', `/api/sessions/${sid}/items`)) } catch (e) { setItems({ err: e.message }) } })() }, [sid])
  if (!items) return <div className="desc">Loading…</div>
  if (items.err) return <div className="out"><span className="bad">{items.err}</span></div>
  return (<>
    <p className="desc">Every action in this session, newest first — saved in the database, still here after a restart and visible from any device that opens this session.</p>
    {items.length ? <div className="card tablewrap"><table><tbody><tr><th>when</th><th>tool</th><th>action</th><th>result</th></tr>
      {items.map((it) => <tr key={it.id}><td>{(it.ts || '').slice(11, 19)}</td><td>{it.module}</td><td>{it.action}</td><td>{it.ref_id ? <a href={`/api/docgen/files/${it.ref_id}/download`}>artifact #{it.ref_id}</a> : (it.output || '').slice(0, 60)}</td></tr>)}
    </tbody></table></div> : <div className="card">Nothing yet — use a tool and it'll appear here.</div>}
  </>)
}

export default function Studio() {
  const [active, setActive] = useState((location.hash || '#home').slice(1) || 'home')
  const [drawer, setDrawer] = useState(false)
  const [hist, setHist] = useState([])
  const [status, setStatus] = useState('…')
  const [apik, setApik] = useState(apiKey())
  const { sid, sessions, pick, log } = useSessions()

  const select = (id, noPush) => {
    setActive((cur) => { if (cur && cur !== id && !noPush) setHist((h) => [...h, cur]); return id })
    location.hash = id; setDrawer(false)
  }
  useEffect(() => {
    const onHash = () => setActive((location.hash || '#home').slice(1) || 'home')
    window.addEventListener('hashchange', onHash); return () => window.removeEventListener('hashchange', onHash)
  }, [])
  useEffect(() => {
    const ping = async () => { try { const h = await api('GET', '/api/health'); setStatus(<span className="ok">● online · {h.modules.length} modules</span>) } catch { setStatus(<span className="bad">● offline</span>) } }
    ping(); const iv = setInterval(ping, 8000); return () => clearInterval(iv)
  }, [])

  const tool = ALL.find((t) => t.id === active) || ALL[0]
  const back = () => { setHist((h) => { if (!h.length) return h; const prev = h[h.length - 1]; select(prev, true); return h.slice(0, -1) }) }

  const sections = {}
  ALL.forEach((t) => { (sections[t.sec] = sections[t.sec] || []).push(t) })

  const Body = () => {
    if (CUSTOM[tool.id]) { const C = CUSTOM[tool.id]; return <C key={tool.id} select={select} log={log} sid={sid} /> }
    return <ToolRunner key={tool.id} tool={tool} log={log} />
  }

  return (
    <div className={'studio' + (drawer ? ' drawer' : '')}>
      <div className="shell">
        <header className="appbar">
          <button className="iconbtn ghost menu" onClick={() => setDrawer(true)} aria-label="Menu">☰</button>
          <span className="logo">🕷️</span><h1>Spidey <em>Studio</em></h1>
        </header>
        <aside className="webbg">
          <div className="brand"><span className="logo">🕷️</span><h1>Spidey <em>Studio</em></h1>
            <button className="x" onClick={() => setDrawer(false)}>×</button></div>
          <div style={{ padding: '0 .55rem' }}>
            <select className="sesspick" value={sid || ''} onChange={(e) => pick(e.target.value)} title="Sessions are shared across every device on your network">
              {sessions.map((s) => <option key={s.id} value={s.id}>{s.name} · {s.items} items</option>)}
              <option value="__new">+ New session</option>
            </select>
            <input className="apik" type="password" placeholder="API key (only if enabled)" value={apik}
              onChange={(e) => { setApik(e.target.value); localStorage.setItem('spidey_api_key', e.target.value) }} />
          </div>
          {Object.entries(sections).map(([sec, items]) => (
            <div key={sec || 'top'}>
              {sec && <div className="navsec">{sec}</div>}
              {items.map((t) => <div key={t.id} className={'navitem' + (t.id === active ? ' active' : '')} onClick={() => select(t.id)}><span className="ico">{t.ico}</span> {t.name}</div>)}
            </div>
          ))}
          <div className="navsec">Links</div>
          <div className="navitem" onClick={() => { location.href = '/' }}><span className="ico">💬</span> Agent chat</div>
          <div className="navitem" onClick={() => { location.href = '/docs' }}><span className="ico">📖</span> API docs</div>
          <div className="navitem" onClick={() => { location.href = '/metrics' }}><span className="ico">📊</span> Metrics</div>
        </aside>
        <main>
          <div className="topbar">
            <button className="iconbtn ghost" style={{ visibility: hist.length ? 'visible' : 'hidden' }} onClick={back} title="Back">←</button>
            <button className="iconbtn ghost" onClick={() => select(active, true)} title="Reload">⟳</button>
            <span className="tb-ico">{tool.ico}</span>
            <h2>{tool.name}</h2>{tool.sec && <span className="pill">{tool.sec}</span>}
            <span style={{ marginLeft: 'auto' }} className="pill">{status}</span>
          </div>
          <div className="scroll"><div className="content webbg">
            {tool.desc && <p className="desc">{tool.desc}</p>}
            <Body />
          </div></div>
        </main>
        <div className="backdrop" onClick={() => setDrawer(false)} />
      </div>
    </div>
  )
}
