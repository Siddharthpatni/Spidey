// Past conversations. Local runs auto-save to localStorage; on a shared instance
// the server also persists every conversation to the database, attributed to the
// device that made it — so five friends on one Spidey each see whose chat is whose.

import { useEffect, useState } from 'react'

const KEY = 'spidey-history'
const MAX = 20

export function loadHistory() {
  try {
    return JSON.parse(localStorage.getItem(KEY) || '[]')
  } catch {
    return []
  }
}

export function saveSession(entry) {
  try {
    const rest = loadHistory().filter(e => e.id !== entry.id)
    localStorage.setItem(KEY, JSON.stringify([entry, ...rest].slice(0, MAX)))
  } catch {
    /* quota exceeded — history is best-effort */
  }
}

export function deleteSession(id) {
  try {
    localStorage.setItem(KEY, JSON.stringify(loadHistory().filter(e => e.id !== id)))
  } catch {
    /* ignore */
  }
}

function when(ts) {
  const d = new Date(ts)
  const today = new Date().toDateString() === d.toDateString()
  return today
    ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

const hdrs = () => {
  const t = localStorage.getItem('spidey-token') || ''
  return t ? { 'X-API-Key': t } : {}
}

// The conversations saved server-side, grouped by device/person.
function SharedHistory({ onOpen }) {
  const [convs, setConvs] = useState(null)
  const myId = localStorage.getItem('spidey-device-id')
  const load = async () => {
    try {
      const r = await fetch('/api/chat/conversations', { headers: hdrs() })
      if (r.ok) setConvs(await r.json())
      else setConvs([])
    } catch { setConvs([]) }
  }
  useEffect(() => { load() }, [])
  const open = async (c) => {
    const r = await fetch(`/api/chat/conversations/${c.id}`, { headers: hdrs() })
    if (!r.ok) return
    const full = await r.json()
    const chat = full.messages.map((m, i) => ({
      id: 'db' + c.id + '_' + i, kind: m.role === 'user' ? 'user' : 'agent', text: m.content,
    }))
    onOpen({ id: 'db' + c.id, task: c.title, ts: c.updated_at, chat, steps: [] })
  }
  if (!convs) return <p className="px-2 py-3 text-center text-xs text-zinc-600">Loading shared history…</p>
  if (!convs.length) return null
  return (
    <div className="mt-2">
      <div className="px-2 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
        On this Spidey (all devices)
      </div>
      {convs.map(c => (
        <button key={c.id} onClick={() => open(c)}
          className="mb-1 flex w-full items-start gap-2 rounded-lg border border-zinc-800 bg-zinc-900/40 px-3 py-2 text-left hover:border-[var(--spidey-red)]/50">
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm text-zinc-200">{c.title}</div>
            <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-zinc-500">
              <span className={`rounded px-1.5 py-px text-[10px] font-semibold ${c.device_id === myId ? 'bg-[var(--spidey-red)]/20 text-rose-300' : 'bg-zinc-800 text-zinc-400'}`}>
                {c.device_label || c.device_id || 'unknown'}{c.device_id === myId ? ' · you' : ''}
              </span>
              {when(c.updated_at)} · {c.messages} msgs
            </div>
          </div>
        </button>
      ))}
    </div>
  )
}

export default function History({ entries, onOpen, onDelete, onClose }) {
  return (
    <div className="spidey-slide-right absolute inset-y-0 left-0 z-40 flex w-[380px] max-w-full flex-col border-r border-zinc-800 bg-zinc-950/97 backdrop-blur">
      <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-2.5">
        <div className="text-sm font-semibold">🕘 Past conversations</div>
        <button onClick={onClose} className="text-zinc-500 hover:text-zinc-200">✕</button>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        <div className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
          This device
        </div>
        {entries.length === 0 && (
          <p className="px-2 py-2 text-center text-xs text-zinc-600">Nothing saved on this device yet.</p>
        )}
        <div className="space-y-1">
          {entries.map(e => (
            <div key={e.id}
              className="group flex items-start gap-2 rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 py-2 hover:border-[var(--spidey-red)]/50">
              <button onClick={() => onOpen(e)} className="min-w-0 flex-1 text-left">
                <div className="truncate text-sm text-zinc-200">{e.task}</div>
                <div className="mt-0.5 text-[11px] text-zinc-500">
                  {when(e.ts)} · {e.chat.length} messages · {e.steps?.length || 0} steps
                </div>
              </button>
              <button onClick={() => onDelete(e.id)} title="Delete"
                className="mt-0.5 text-zinc-600 opacity-0 hover:text-rose-400 group-hover:opacity-100">🗑</button>
            </div>
          ))}
        </div>
        <SharedHistory onOpen={onOpen} />
      </div>
    </div>
  )
}
