import { useState } from 'react'

export const PROVIDERS = [
  { id: 'ollama', name: 'Ollama — local, private, offline', model: 'gemma4:12b', needsKey: false },
  { id: 'anthropic', name: 'Claude (Anthropic)', model: 'claude-sonnet-5', needsKey: true },
  { id: 'gemini', name: 'Gemini (Google)', model: 'gemini-2.5-flash', needsKey: true },
  { id: 'openai', name: 'OpenAI', model: 'gpt-5', needsKey: true },
  { id: 'custom', name: 'Custom (OpenAI-compatible URL)', model: '', needsKey: false },
]

// The Spider-Verse: every offline brain is a Spider from across the timeline.
// All free, all open-weight, all fully offline via `ollama pull <tag>`.
export const SPIDER_VERSE = [
  {
    tag: '', id: 'auto', spider: 'The Web', emoji: '🕸',
    title: 'Auto-dispatch', size: 'smart',
    note: 'Peter leads: every task is classified and sent to the Spider who solves it most efficiently — coding swings to Miles, deep work stays with Peter.',
    colors: ['#c81e24', '#3b5bdb'],
  },
  {
    tag: 'gemma4:12b', id: 'peter', spider: 'Peter Parker', emoji: '🕷️',
    title: 'The Amazing Spider-Man', size: '7.6 GB',
    note: 'The definitive Spidey. Gemma 4 — native tool-calling, the smartest web on your machine.',
    colors: ['#c81e24', '#2545a8'],
  },
  {
    tag: 'qwen2.5-coder:7b', id: 'miles', spider: 'Miles Morales', emoji: '⚡',
    title: 'Ultimate Spider-Man', size: '4.7 GB',
    note: 'Young, fast, street-smart. The quickest swing on 16 GB machines — great with code.',
    colors: ['#111111', '#c81e24'],
  },
  {
    tag: 'gemma4:e4b', id: 'gwen', spider: 'Spider-Gwen', emoji: '🩰',
    title: 'Ghost-Spider', size: '9.6 GB',
    note: 'Light on her feet. Gemma 4 edge (4.5B effective) — graceful on lighter hardware.',
    colors: ['#f8fafc', '#e11d8f'],
  },
  {
    tag: 'llama3.1:8b', id: 'noir', spider: 'Spider-Man Noir', emoji: '🕵️',
    title: 'The Noir Timeline', size: '4.9 GB',
    note: 'Old-school detective. Llama 3.1 — a solid, seasoned general assistant.',
    colors: ['#3f3f46', '#a1a1aa'],
  },
  {
    tag: 'gemma4:26b', id: '2099', spider: 'Miguel O’Hara', emoji: '🔮',
    title: 'Spider-Man 2099', size: '18 GB',
    note: 'The future. Gemma 4 26B MoE — for 32 GB+ rigs that want frontier-feel offline.',
    colors: ['#1e3a8a', '#dc2626'],
  },
  {
    tag: 'qwen2.5-coder:1.5b', id: 'ham', spider: 'Peter Porker', emoji: '🐷',
    title: 'Spider-Ham', size: '1 GB',
    note: 'The cartoon timeline. Tiny, silly, surprisingly capable — old laptops welcome.',
    colors: ['#f472b6', '#fbbf24'],
  },
]

// Back-compat: plain tag list (datalist for the free-text input).
export const OLLAMA_MODELS = SPIDER_VERSE.filter(s => s.tag)
  .map(s => ({ tag: s.tag, note: `${s.spider} · ${s.size}` }))

export const defaultConfig = {
  provider: 'ollama',
  model: '',
  spider: 'peter',
  api_key: '',
  base_url: '',
  workdir: '',
  safety: 'ask',
  max_steps: 25,
}

export function loadConfig() {
  try {
    const cfg = { ...defaultConfig, ...JSON.parse(localStorage.getItem('spidey-config') || '{}') }
    if (!PROVIDERS.some(p => p.id === cfg.provider)) cfg.provider = defaultConfig.provider
    return cfg
  } catch {
    return { ...defaultConfig }
  }
}

// Keys stay in the browser's localStorage and travel only over this
// (local) socket with each run — the server never persists them.
export function saveConfig(cfg) {
  localStorage.setItem('spidey-config', JSON.stringify(cfg))
}

function Field({ label, children }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-zinc-400">{label}</span>
      {children}
    </label>
  )
}

// "Choose your Spider" — the offline models as characters across the
// Spider-Verse timeline. Clicking a card picks that brain.
function SpiderVersePicker({ value, onPick }) {
  return (
    <div>
      <div className="mb-1.5 text-xs font-medium text-zinc-400">
        Choose your Spider <span className="text-zinc-600">— every one runs 100% offline</span>
      </div>
      <div className="grid max-h-64 grid-cols-2 gap-2 overflow-y-auto pr-1">
        {SPIDER_VERSE.map(s => {
          const active = value === s.id
          return (
            <button
              key={s.id}
              type="button"
              onClick={() => onPick(s)}
              className={`rounded-xl border p-2.5 text-left transition-all ${
                active
                  ? 'border-transparent shadow-lg'
                  : 'border-zinc-700 hover:border-zinc-500'
              }`}
              style={{
                background: active
                  ? `linear-gradient(135deg, ${s.colors[0]}33, ${s.colors[1]}33)`
                  : undefined,
                boxShadow: active ? `0 0 0 1.5px ${s.colors[0]}, 0 0 18px ${s.colors[0]}55` : undefined,
              }}
            >
              <div className="flex items-center gap-2">
                <span
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-base"
                  style={{ background: `linear-gradient(135deg, ${s.colors[0]}, ${s.colors[1]})` }}
                >
                  {s.emoji}
                </span>
                <div className="min-w-0">
                  <div className="truncate text-xs font-bold text-zinc-100">{s.spider}</div>
                  <div className="truncate text-[10px] text-zinc-500">{s.title} · {s.size}</div>
                </div>
                {active && <span className="ml-auto text-emerald-400">✓</span>}
              </div>
              <p className="mt-1.5 line-clamp-2 text-[10px] leading-snug text-zinc-400">{s.note}</p>
            </button>
          )
        })}
      </div>
    </div>
  )
}

const inputCls =
  'w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm outline-none focus:border-[var(--spidey-red)]'

export default function Settings({ config, onSave, onClose }) {
  const [cfg, setCfg] = useState(config)
  const [token, setToken] = useState(() => localStorage.getItem('spidey-token') || '')
  const provider = PROVIDERS.find(p => p.id === cfg.provider) || PROVIDERS[0]
  const set = patch => setCfg(c => ({ ...c, ...patch }))

  const save = () => {
    const prevToken = localStorage.getItem('spidey-token') || ''
    localStorage.setItem('spidey-token', token.trim())
    onSave(cfg)
    onClose()
    if (token.trim() !== prevToken) location.reload() // reconnect sockets with the new token
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div
        className="spidey-overlay-in w-full max-w-md space-y-3 rounded-2xl border border-zinc-700 bg-zinc-900 p-5 shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">Model & run settings</h2>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-200">✕</button>
        </div>

        <Field label="Provider — bring your own model">
          <select
            value={cfg.provider}
            onChange={e => set({ provider: e.target.value })}
            className={inputCls}
          >
            {PROVIDERS.map(p => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </Field>

        {cfg.provider === 'ollama' && (
          <SpiderVersePicker
            value={cfg.spider || 'peter'}
            onPick={s => set({ model: s.tag, spider: s.id })}
          />
        )}

        <Field label={`Model ${provider.model ? `(default: ${provider.model})` : ''}`}>
          <input
            value={cfg.model}
            onChange={e => set({ model: e.target.value })}
            placeholder={provider.model || 'model name'}
            list={cfg.provider === 'ollama' ? 'ollama-models' : undefined}
            className={inputCls}
          />
          {cfg.provider === 'ollama' && (
            <>
              <datalist id="ollama-models">
                {OLLAMA_MODELS.map(m => (
                  <option key={m.tag} value={m.tag}>{m.note}</option>
                ))}
              </datalist>
              <p className="mt-1 text-[11px] text-zinc-500">
                Get your Spider with <code className="text-zinc-400">spidey setup --model &lt;tag&gt;</code>{' '}
                or <code className="text-zinc-400">ollama pull &lt;tag&gt;</code>.
              </p>
            </>
          )}
        </Field>

        {provider.needsKey && (
          <Field label="API key (stored only in this browser)">
            <input
              type="password"
              value={cfg.api_key}
              onChange={e => set({ api_key: e.target.value })}
              placeholder="sk-…"
              className={inputCls}
            />
          </Field>
        )}

        {cfg.provider === 'custom' && (
          <Field label="Base URL (OpenAI-compatible)">
            <input
              value={cfg.base_url}
              onChange={e => set({ base_url: e.target.value })}
              placeholder="http://localhost:8000/v1"
              className={inputCls}
            />
          </Field>
        )}

        <Field label="Working directory (where the agent may read/write)">
          <input
            value={cfg.workdir}
            onChange={e => set({ workdir: e.target.value })}
            placeholder="server default"
            className={inputCls}
          />
        </Field>

        <Field label="Server access token (only if the server runs with --token)">
          <input
            type="password"
            value={token}
            onChange={e => setToken(e.target.value)}
            placeholder="leave empty for localhost"
            className={inputCls}
          />
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Safety mode">
            <select value={cfg.safety} onChange={e => set({ safety: e.target.value })} className={inputCls}>
              <option value="ask">ask — approve risky commands</option>
              <option value="enforce">enforce — block them</option>
              <option value="off">off — no checks</option>
            </select>
          </Field>
          <Field label="Max steps">
            <input
              type="number"
              min="1"
              max="100"
              value={cfg.max_steps}
              onChange={e => set({ max_steps: Number(e.target.value) })}
              className={inputCls}
            />
          </Field>
        </div>

        <button onClick={save} className="w-full rounded-lg spidey-btn-primary py-2 text-sm font-semibold">
          Save
        </button>
      </div>
    </div>
  )
}
