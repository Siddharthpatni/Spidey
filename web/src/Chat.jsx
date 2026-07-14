import { useEffect, useRef, useState } from 'react'
import { styleFor } from './AgentGraph.jsx'
import { MicButton, SpeakerToggle, VoiceStrip } from './Voice.jsx'

// Minimal markdown for model replies — **bold**, *italic*, `code`, bullets —
// so answers read like a message, not like raw asterisk soup. Rendered as
// React elements (never innerHTML), so model output can't inject markup.
function inlineMd(text) {
  const parts = []
  const re = /(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`)/g
  let last = 0
  let m
  let i = 0
  while ((m = re.exec(text))) {
    if (m.index > last) parts.push(text.slice(last, m.index))
    const t = m[0]
    if (t.startsWith('**')) parts.push(<strong key={i++}>{t.slice(2, -2)}</strong>)
    else if (t.startsWith('`'))
      parts.push(
        <code key={i++} className="rounded bg-black/30 px-1 font-mono text-[0.9em]">
          {t.slice(1, -1)}
        </code>,
      )
    else parts.push(<em key={i++}>{t.slice(1, -1)}</em>)
    last = m.index + t.length
  }
  if (last < text.length) parts.push(text.slice(last))
  return parts
}

function Md({ text }) {
  return (
    <>
      {String(text).split('\n').map((line, i) => {
        if (!line.trim()) return <div key={i} className="h-2" />
        const bullet = /^\s*([-*•]|\d+\.)\s+/.exec(line)
        if (bullet)
          return (
            <div key={i} className="flex gap-1.5 pl-1">
              <span className="shrink-0">{/^\d/.test(bullet[1]) ? bullet[1] : '•'}</span>
              <span>{inlineMd(line.slice(bullet[0].length))}</span>
            </div>
          )
        return <div key={i}>{inlineMd(line.replace(/^#+\s+/, ''))}</div>
      })}
    </>
  )
}

// Pull a downloadable artifact (document / image) out of a tool result so it
// renders inline in chat — the chat becomes the one place everything shows up.
function artifactFrom(observation, tool) {
  if (!observation) return null
  const m = observation.match(/\/api\/(?:docgen\/files|media)\/\d+\/download/)
  if (!m) return null
  const url = m[0]
  const isImage = tool === 'generate_image' || /image/i.test(observation)
  return { url, isImage }
}

function ToolLine({ m }) {
  const [open, setOpen] = useState(false)
  const s = styleFor({ type: 'tool', tool: m.tool })
  const badge = m.status === 'ok' ? '✓' : m.status === 'err' ? '✗' : '⏳'
  const badgeColor =
    m.status === 'ok' ? 'text-emerald-400' : m.status === 'err' ? 'text-rose-400' : 'text-amber-300 animate-pulse'
  const art = artifactFrom(m.observation, m.tool)
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
      {art && (
        <div className="border-t border-zinc-800 p-3">
          {art.isImage && (
            <img src={art.url} alt="" className="mb-2 max-h-72 rounded-lg border border-zinc-800" />
          )}
          <a href={art.url} target="_blank" rel="noreferrer"
            className="inline-block rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-emerald-500">
            ⬇ Download
          </a>
        </div>
      )}
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
    <div className={`rounded-lg border border-amber-500/50 bg-amber-500/10 px-3 py-2 ${
      m.resolved === null && active ? 'spidey-approval' : ''
    }`}>
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

// The model's private reasoning, shown as a collapsible "thinking" block —
// open while it streams, tuck it away once the answer lands.
function Thinking({ text }) {
  const [open, setOpen] = useState(true)
  return (
    <div className="rounded-lg border border-indigo-500/25 bg-indigo-500/5 px-3 py-2">
      <button onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1.5 text-xs font-semibold text-indigo-300">
        <span>💭</span> Thinking <span className="text-indigo-400/60">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="mt-1.5 whitespace-pre-wrap text-xs leading-relaxed text-zinc-400">{text}</div>
      )}
    </div>
  )
}

function Message({ m, approval, onAnswer }) {
  switch (m.kind) {
    case 'user':
      return <div className="spidey-bubble-user ml-8 rounded-xl rounded-br-sm px-3 py-2 text-sm">{m.text}</div>
    case 'reasoning':
      return <Thinking text={m.text} />
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
          <Md text={m.text} />
        </div>
      )
    case 'agent':
      return (
        <div className="spidey-bubble-agent rounded-xl rounded-bl-sm px-3 py-2 text-sm">
          <Md text={m.text} />
        </div>
      )
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
      <div className="flex-1 overflow-y-auto p-3">
        {state.chat.length === 0 ? (
          <div className="mx-auto flex h-full max-w-2xl flex-col items-center justify-center gap-4 px-4 text-center">
            <div className="text-4xl">🕷️</div>
            <div>
              <p className="text-lg font-semibold text-zinc-200">Your friendly neighborhood AI.</p>
              <p className="mt-1 text-sm text-zinc-500">Ask anything, or say “Hey Spidey”. It can build files, crawl the web, write code, and remember you.</p>
            </div>
            <div className="grid w-full grid-cols-1 gap-2 sm:grid-cols-2">
              {[
                ['📄', 'Make me a one-page résumé for a backend role', "Make me a one-page résumé (.docx) for a Python/FastAPI backend engineer role"],
                ['🌐', 'Crawl a site into my knowledge base', 'Crawl https://example.com into the Knowledge Nexus, then tell me what it says'],
                ['💻', 'Find & explain the biggest file here', 'Find and explain the biggest file in this folder'],
                ['🧠', 'What do you remember about me?', 'What do you remember about me?'],
              ].map(([icon, label, prompt]) => (
                <button
                  key={label}
                  onClick={() => state.connected && onStart(prompt)}
                  className="flex items-center gap-2.5 rounded-xl border border-zinc-800 bg-zinc-900/50 px-3.5 py-3 text-left text-sm text-zinc-300 transition hover:border-[var(--spidey-red)]/60 hover:bg-zinc-900"
                >
                  <span className="text-lg">{icon}</span><span className="min-w-0 flex-1">{label}</span>
                </button>
              ))}
            </div>
            <p className="text-xs text-zinc-600">
              No model yet? Run <code className="text-zinc-400">spidey setup</code> once, or pick a
              provider in <span className="font-semibold text-zinc-400">⚙ Settings</span>.
            </p>
          </div>
        ) : (
          <div className="mx-auto w-full max-w-3xl space-y-2">
            {state.chat.map(m => (
              <div key={m.id} className="spidey-msg">
                <Message m={m} approval={state.approval} onAnswer={onAnswer} />
              </div>
            ))}
          </div>
        )}
        <div ref={endRef} />
      </div>
      <VoiceStrip voice={voice} />
      <div className="border-t border-zinc-800 p-3">
        <div className="mx-auto flex max-w-3xl gap-2">
          <textarea
            value={task}
            onChange={e => setTask(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                submit()
              }
            }}
            placeholder={
              !state.connected
                ? 'Connecting…'
                : voice.status === 'listening' || voice.status === 'awake'
                  ? 'Listening — say “Hey Spidey…” or type'
                  : 'Describe a task… (click 🎙 for voice)'
            }
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
