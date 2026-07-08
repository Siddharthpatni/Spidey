import { useState } from 'react'

export const PROVIDERS = [
  { id: 'demo', name: 'Demo (no setup)', model: 'scripted stub', needsKey: false },
  { id: 'ollama', name: 'Ollama — local & free', model: 'qwen2.5-coder:7b', needsKey: false },
  { id: 'anthropic', name: 'Claude (Anthropic)', model: 'claude-sonnet-5', needsKey: true },
  { id: 'gemini', name: 'Gemini (Google)', model: 'gemini-2.5-flash', needsKey: true },
  { id: 'openai', name: 'OpenAI', model: 'gpt-5', needsKey: true },
  { id: 'custom', name: 'Custom (OpenAI-compatible URL)', model: '', needsKey: false },
]

export const defaultConfig = {
  provider: 'demo',
  model: '',
  api_key: '',
  base_url: '',
  workdir: '',
  safety: 'ask',
  max_steps: 25,
}

export function loadConfig() {
  try {
    return { ...defaultConfig, ...JSON.parse(localStorage.getItem('spidey-config') || '{}') }
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

const inputCls =
  'w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm outline-none focus:border-indigo-500'

export default function Settings({ config, onSave, onClose }) {
  const [cfg, setCfg] = useState(config)
  const provider = PROVIDERS.find(p => p.id === cfg.provider) || PROVIDERS[0]
  const set = patch => setCfg(c => ({ ...c, ...patch }))

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div
        className="w-full max-w-md space-y-3 rounded-2xl border border-zinc-700 bg-zinc-900 p-5 shadow-2xl"
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

        {cfg.provider !== 'demo' && (
          <Field label={`Model ${provider.model ? `(default: ${provider.model})` : ''}`}>
            <input
              value={cfg.model}
              onChange={e => set({ model: e.target.value })}
              placeholder={provider.model || 'model name'}
              className={inputCls}
            />
          </Field>
        )}

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

        {cfg.provider !== 'demo' && (
          <Field label="Working directory (where the agent may read/write)">
            <input
              value={cfg.workdir}
              onChange={e => set({ workdir: e.target.value })}
              placeholder="server default"
              className={inputCls}
            />
          </Field>
        )}

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

        <button
          onClick={() => {
            onSave(cfg)
            onClose()
          }}
          className="w-full rounded-lg bg-indigo-600 py-2 text-sm font-semibold hover:bg-indigo-500"
        >
          Save
        </button>
      </div>
    </div>
  )
}
