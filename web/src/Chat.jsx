import { useEffect, useRef, useState } from 'react'
import { styleFor } from './AgentGraph.jsx'
import { MicButton, SpeakerToggle, VoiceStrip } from './Voice.jsx'

function ToolLine({ m }) {
  const [open, setOpen] = useState(false)
  const s = styleFor({ type: 'tool', tool: m.tool })
  const badge = m.status === 'ok' ? '✓' : m.status === 'err' ? '✗' : '⏳'
  const badgeColor =
    m.status === 'ok' ? 'text-emerald-400' : m.status === 'err' ? 'text-rose-400' : 'text-amber-300 animate-pulse'
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/60">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left font-mono text-xs hover:bg-zinc-800/50"
      >
        <span>{s.icon}</span>
        <span style={{ color: s.color }}>{m.tool}</span>
        <span className="truncate text-zinc-500">{JSON.stringify(m.args)}</span>
        <span className={`ml-auto shrink-0 ${badgeColor}`}>{badge}</span>
      </button>
      {open && m.observation && (
        <pre className="max-h-48 overflow-auto border-t border-zinc-800 px-3 py-2 text-[11px] leading-relaxed text-zinc-400">
          {m.observation}
        </pre>
      )}
    </div>
  )
}

function ApprovalCard({ m, active, onAnswer }) {
  return (
    <div className="rounded-lg border border-amber-500/50 bg-amber-500/10 px-3 py-2">
      <div className="mb-1 text-xs font-semibold text-amber-300">⚠ Spidey-sense — approval needed</div>
      <pre className="whitespace-pre-wrap font-mono text-[11px] text-amber-100/90">{m.prompt}</pre>
      {m.resolved === null && active ? (
        <div className="mt-2 flex gap-2">
          <button
            onClick={() => onAnswer(m.id, true)}
            className="rounded-md bg-emerald-600 px-3 py-1 text-xs font-semibold text-white hover:bg-emerald-500"
          >
            Approve
          </button>
          <button
            onClick={() => onAnswer(m.id, false)}
            className="rounded-md bg-[var(--spidey-red)] px-3 py-1 text-xs font-semibold text-white hover:bg-[var(--spidey-red-bright)]"
          >
            Deny
          </button>
        </div>
      ) : (
        m.resolved !== null && (
          <div className={`mt-1 text-xs font-semibold ${m.resolved ? 'text-emerald-400' : 'text-rose-400'}`}>
            {m.resolved ? '✓ approved' : '✗ denied'}
          </div>
        )
      )}
    </div>
  )
}

function Message({ m, approval, onAnswer }) {
  switch (m.kind) {
    case 'user':
      return <div className="spidey-bubble-user ml-8 rounded-xl rounded-br-sm px-3 py-2 text-sm">{m.text}</div>
    case 'think':
      return <div className="px-1 text-sm italic text-zinc-400">🧠 {m.text}</div>
    case 'tool':
      return <ToolLine m={m} />
    case 'approval':
      return <ApprovalCard m={m} active={approval?.id === m.id} onAnswer={onAnswer} />
    case 'finish':
      return (
        <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-100">
          <span className="mr-1">🏁</span>
          {m.text}
        </div>
      )
    case 'agent':
      return <div className="spidey-bubble-agent rounded-xl rounded-bl-sm px-3 py-2 text-sm">{m.text}</div>
    case 'error':
      return (
        <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
          {m.text}
        </div>
      )
    default:
      return null
  }
}

export default function Chat({ state, voice, onStart, onStop, onAnswer }) {
  const [task, setTask] = useState('')
  const endRef = useRef(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [state.chat])

  const running = state.status === 'running'

  const submit = () => {
    if (!task.trim() || running || !state.connected) return
    onStart(task.trim())
    setTask('')
  }

  return (
    <div className="spidey-web-bg flex h-full flex-col">
      <div className="flex-1 space-y-2 overflow-y-auto p-3">
        {state.chat.length === 0 && (
          <div className="mt-10 space-y-2 text-center text-sm text-zinc-500">
            <div className="text-3xl">🕷️</div>
            <p className="font-semibold text-zinc-400">Your friendly neighborhood AI.</p>
            <p>Type a task — or turn on the mic and say “Hey Spidey”.</p>
            <p className="text-xs text-zinc-600">
              No model yet? Run <code className="text-zinc-400">spidey setup</code> once, or pick a
              provider in <span className="font-semibold text-zinc-400">⚙ Settings</span>.
            </p>
          </div>
        )}
        {state.chat.map(m => (
          <Message key={m.id} m={m} approval={state.approval} onAnswer={onAnswer} />
        ))}
        <div ref={endRef} />
      </div>
      <VoiceStrip voice={voice} />
      <div className="border-t border-zinc-800 p-3">
        <div className="flex gap-2">
          <textarea
            value={task}
            onChange={e => setTask(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                submit()
              }
            }}
            placeholder={state.connected ? 'Describe a task… or say “Hey Spidey”' : 'Connecting…'}
            rows={2}
            className="flex-1 resize-none rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none placeholder:text-zinc-600 focus:border-[var(--spidey-red)]"
          />
          <div className="flex flex-col gap-2">
            <MicButton voice={voice} />
            <SpeakerToggle voice={voice} />
          </div>
          {running ? (
            <button
              onClick={onStop}
              className="rounded-lg bg-[var(--spidey-red)] px-4 text-sm font-semibold hover:bg-[var(--spidey-red-bright)]"
            >
              Stop
            </button>
          ) : (
            <button
              onClick={submit}
              disabled={!state.connected || !task.trim()}
              className="spidey-btn-primary rounded-lg px-4 text-sm font-semibold disabled:opacity-40"
            >
              Run
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
