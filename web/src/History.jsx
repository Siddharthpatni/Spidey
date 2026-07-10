// Past conversations. Every finished run auto-saves the whole session (chat +
// reasoning graph) to localStorage; this drawer lists them for one-click
// restore. Purely client-side — nothing is sent or stored on the server.

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

export default function History({ entries, onOpen, onDelete, onClose }) {
  return (
    <div className="spidey-slide-right absolute inset-y-0 left-0 z-40 flex w-[380px] max-w-full flex-col border-r border-zinc-800 bg-zinc-950/97 backdrop-blur">
      <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-2.5">
        <div className="text-sm font-semibold">🕘 Past conversations</div>
        <button onClick={onClose} className="text-zinc-500 hover:text-zinc-200">✕</button>
      </div>
      <div className="flex-1 space-y-1 overflow-y-auto p-2">
        {entries.length === 0 && (
          <p className="mt-8 text-center text-xs text-zinc-600">
            Nothing yet — finished runs are saved here automatically,
            <br />
            in this browser only.
          </p>
        )}
        {entries.map(e => (
          <div
            key={e.id}
            className="group flex items-start gap-2 rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 py-2 hover:border-[var(--spidey-red)]/50"
          >
            <button onClick={() => onOpen(e)} className="min-w-0 flex-1 text-left">
              <div className="truncate text-sm text-zinc-200">{e.task}</div>
              <div className="mt-0.5 text-[11px] text-zinc-500">
                {when(e.ts)} · {e.chat.length} messages · {e.steps?.length || 0} steps
              </div>
            </button>
            <button
              onClick={() => onDelete(e.id)}
              title="Delete"
              className="mt-0.5 text-zinc-600 opacity-0 hover:text-rose-400 group-hover:opacity-100"
            >
              🗑
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
