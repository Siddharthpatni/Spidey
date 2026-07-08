import { useCallback, useEffect, useRef, useState } from 'react'
import AgentGraph, { styleFor } from './AgentGraph.jsx'
import Chat from './Chat.jsx'
import History, { deleteSession, loadHistory, saveSession } from './History.jsx'
import Onboarding from './Onboarding.jsx'
import Settings, { PROVIDERS, loadConfig, saveConfig } from './Settings.jsx'
import { useSpideySocket } from './useSpideySocket.js'
import { useVoice } from './useVoice.js'

function Badge({ children, tone = 'zinc' }) {
  const tones = {
    zinc: 'border-zinc-700 text-zinc-400',
    green: 'border-emerald-600/60 text-emerald-400',
    amber: 'border-amber-600/60 text-amber-300',
    red: 'border-[var(--spidey-red)]/70 text-[var(--spidey-red-bright)]',
  }
  return (
    <span className={`rounded-full border px-2 py-0.5 font-mono text-[11px] ${tones[tone]}`}>
      {children}
    </span>
  )
}

function Splash({ fading }) {
  return (
    <div
      className={`fixed inset-0 z-[100] flex flex-col items-center justify-center bg-zinc-950 transition-opacity duration-700 ${
        fading ? 'pointer-events-none opacity-0' : 'opacity-100'
      }`}
    >
      <div className="flex flex-col items-center">
        <div className="spidey-splash-thread w-px bg-zinc-600" />
        <div className="spidey-splash-spider text-6xl">🕷️</div>
      </div>
      <h1 className="spidey-splash-quote mt-6 text-2xl font-bold tracking-[0.3em] text-[var(--spidey-red-bright)]">
        SPIDEY
      </h1>
      <p className="spidey-splash-quote mt-3 max-w-sm text-center text-sm italic text-zinc-400">
        “With great power comes great responsibility.”
      </p>
      <p className="spidey-splash-quote mt-1 text-xs text-zinc-600">
        your friendly neighborhood AI — offline, private, yours
      </p>
    </div>
  )
}

function TokenGate() {
  const [token, setToken] = useState('')
  const unlock = () => {
    if (!token.trim()) return
    localStorage.setItem('spidey-token', token.trim())
    location.reload()
  }
  return (
    <div className="fixed inset-0 z-[95] flex items-center justify-center bg-black/80 p-4">
      <div className="w-full max-w-sm rounded-2xl border border-[var(--spidey-red)]/40 bg-zinc-950 p-6 shadow-2xl">
        <div className="mb-1 flex items-center gap-2 text-lg font-bold">🔐 Access token needed</div>
        <p className="mb-4 text-sm text-zinc-400">
          This Spidey server was started with <code className="text-zinc-300">--token</code>.
          Paste the token from the terminal where <code className="text-zinc-300">spidey serve</code> is
          running (it's printed in the URL after <code className="text-zinc-300">?token=</code>).
        </p>
        <input
          autoFocus
          value={token}
          onChange={e => setToken(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && unlock()}
          placeholder="access token"
          className="mb-3 w-full rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-[var(--spidey-red)]"
        />
        <button onClick={unlock} className="spidey-btn-primary w-full rounded-lg py-2 text-sm font-semibold">
          Unlock
        </button>
      </div>
    </div>
  )
}

function StepSheet({ step, onClose }) {
  const s = styleFor(step)
  return (
    <div className="absolute inset-y-0 right-0 z-40 w-96 max-w-full overflow-y-auto border-l border-zinc-800 bg-zinc-950/95 p-4 backdrop-blur">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2 font-mono text-sm font-semibold" style={{ color: s.color }}>
          <span>{s.icon}</span>
          {step.type === 'tool' ? step.tool : step.type}
        </div>
        <button onClick={onClose} className="text-zinc-500 hover:text-zinc-200">✕</button>
      </div>
      {step.args && (
        <>
          <div className="mb-1 text-xs font-semibold text-zinc-500">arguments</div>
          <pre className="mb-3 overflow-x-auto rounded-lg bg-zinc-900 p-3 text-[11px] leading-relaxed text-zinc-300">
            {JSON.stringify(step.args, null, 2)}
          </pre>
        </>
      )}
      {(step.observation || step.text) && (
        <>
          <div className="mb-1 text-xs font-semibold text-zinc-500">
            {step.observation ? 'observation' : 'text'}
          </div>
          <pre className="overflow-x-auto whitespace-pre-wrap rounded-lg bg-zinc-900 p-3 text-[11px] leading-relaxed text-zinc-300">
            {step.observation || step.text}
          </pre>
        </>
      )}
    </div>
  )
}

export default function App() {
  const { state, startRun, answerApproval, stopRun, restore, newChat } = useSpideySocket()
  const [config, setConfig] = useState(loadConfig)
  const [showSettings, setShowSettings] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [history, setHistory] = useState(loadHistory)
  const [selected, setSelected] = useState(null)
  const [view, setView] = useState('chat') // mobile: chat | web
  const [splash, setSplash] = useState('show') // show -> fading -> gone
  const [showOnboarding, setShowOnboarding] = useState(
    () => localStorage.getItem('spidey-onboarded') !== '1',
  )
  const sessionIdRef = useRef(Date.now())

  // Refs so the voice callback always sees the current run state and config.
  const stateRef = useRef(state)
  stateRef.current = state
  const configRef = useRef(config)
  configRef.current = config

  const handleUtterance = useCallback(
    text => {
      const s = stateRef.current
      if (s.approval) {
        if (/\b(approve|yes|go ahead|do it)\b/i.test(text)) answerApproval(s.approval.id, true)
        else if (/\b(deny|no|stop|don't)\b/i.test(text)) answerApproval(s.approval.id, false)
        return
      }
      if (s.status === 'running') {
        if (/^(stop|cancel|abort)\b/i.test(text)) stopRun()
        return
      }
      setSelected(null)
      startRun(text, configRef.current)
    },
    [startRun, stopRun, answerApproval],
  )

  const voice = useVoice({ onUtterance: handleUtterance })

  // Speak what matters for hands-free use: final answers and approval asks.
  const voiceRef = useRef(voice)
  voiceRef.current = voice
  const spokenRef = useRef(new Set())
  useEffect(() => {
    const last = state.chat[state.chat.length - 1]
    if (!last || spokenRef.current.has(last.id)) return
    if (last.kind === 'agent' || last.kind === 'finish') {
      spokenRef.current.add(last.id)
      voiceRef.current.speak(last.text)
    } else if (last.kind === 'approval' && last.resolved === null) {
      spokenRef.current.add(last.id)
      voiceRef.current.speak('My spidey-sense is tingling — I need your approval to run a risky command. Say approve or deny.')
    }
  }, [state.chat])

  useEffect(() => {
    const fade = setTimeout(() => setSplash('fading'), 2400)
    const gone = setTimeout(() => setSplash('gone'), 3200)
    return () => {
      clearTimeout(fade)
      clearTimeout(gone)
    }
  }, [])

  // Auto-save the session whenever a run finishes (client-side only).
  useEffect(() => {
    if (state.status !== 'idle' || state.chat.length === 0) return
    saveSession({
      id: sessionIdRef.current,
      ts: Date.now(),
      task: state.chat.find(m => m.kind === 'user')?.text?.slice(0, 90) || '(untitled)',
      chat: state.chat,
      steps: state.steps,
    })
    setHistory(loadHistory())
  }, [state.status, state.chat, state.steps])

  const openSession = entry => {
    // Re-key restored messages so ids never collide with live ones, and mark
    // them spoken so restoring a chat doesn't trigger TTS.
    const chat = entry.chat.map((m, i) => ({ ...m, id: `h${entry.id}-c${i}` }))
    const steps = (entry.steps || []).map((s, i) => ({ ...s, id: `h${entry.id}-s${i}` }))
    chat.forEach(m => spokenRef.current.add(m.id))
    sessionIdRef.current = entry.id
    restore(chat, steps)
    setSelected(null)
    setShowHistory(false)
  }

  const removeSession = id => {
    deleteSession(id)
    setHistory(loadHistory())
  }

  const startNewChat = () => {
    sessionIdRef.current = Date.now()
    newChat()
    setSelected(null)
    setShowHistory(false)
  }

  const provider = PROVIDERS.find(p => p.id === config.provider) || PROVIDERS[0]

  const handleSave = cfg => {
    setConfig(cfg)
    saveConfig(cfg)
  }

  const start = task => {
    setSelected(null)
    startRun(task, config)
  }

  const dismissOnboarding = () => {
    localStorage.setItem('spidey-onboarded', '1')
    setShowOnboarding(false)
  }

  const onboardingSettings = () => {
    dismissOnboarding()
    setShowSettings(true)
  }

  return (
    <div className="flex h-screen flex-col">
      <header className="spidey-header flex items-center gap-2 px-3 py-2.5 sm:gap-3 sm:px-4">
        <span className="text-lg">🕷️</span>
        <h1 className="text-sm font-bold tracking-wide">Spidey</h1>
        <span className="hidden text-xs text-zinc-600 lg:inline">
          your friendly neighborhood AI · runs on your machine
        </span>
        <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
          {voice.status === 'listening' && <Badge tone="red">🎙 “hey spidey”</Badge>}
          {voice.status === 'awake' && <Badge tone="red">🎙 listening…</Badge>}
          {state.status === 'running' && <Badge tone="amber">running</Badge>}
          <Badge tone={state.connected ? 'green' : 'red'}>
            {state.connected ? '● connected' : '○ offline'}
          </Badge>
          <span className="hidden md:inline-flex gap-2">
            <Badge>{state.runMeta?.model || provider.name}</Badge>
            <Badge>safety: {config.safety}</Badge>
          </span>
          {state.status !== 'running' && state.chat.length > 0 && (
            <button
              onClick={startNewChat}
              className="rounded-lg border border-zinc-700 px-2.5 py-1 text-xs font-semibold text-zinc-300 hover:bg-zinc-800"
            >
              ＋<span className="hidden sm:inline"> New</span>
            </button>
          )}
          <button
            onClick={() => setShowHistory(h => !h)}
            className="rounded-lg border border-zinc-700 px-2.5 py-1 text-xs font-semibold text-zinc-300 hover:bg-zinc-800"
          >
            🕘<span className="hidden sm:inline"> History</span>
          </button>
          <button
            onClick={() => setShowSettings(true)}
            className="rounded-lg border border-zinc-700 px-2.5 py-1 text-xs font-semibold text-zinc-300 hover:bg-zinc-800"
          >
            ⚙<span className="hidden sm:inline"> Settings</span>
          </button>
        </div>
      </header>

      <main className="relative flex min-h-0 flex-1">
        {/* On phones the two panels become tabs; from md up they sit side by side. */}
        <section
          className={`${view === 'chat' ? 'flex' : 'hidden'} w-full flex-col md:flex md:w-[380px] md:shrink-0 md:border-r md:border-zinc-800`}
        >
          <Chat state={state} voice={voice} onStart={start} onStop={stopRun} onAnswer={answerApproval} />
        </section>
        <section className={`${view === 'web' ? 'block' : 'hidden'} relative min-w-0 flex-1 md:block`}>
          <AgentGraph steps={state.steps} onSelect={setSelected} />
          {selected && <StepSheet step={selected} onClose={() => setSelected(null)} />}
        </section>
        {showHistory && (
          <History
            entries={history}
            onOpen={openSession}
            onDelete={removeSession}
            onClose={() => setShowHistory(false)}
          />
        )}
      </main>

      <nav className="flex border-t border-zinc-800 md:hidden">
        {[
          { id: 'chat', label: '💬 Chat' },
          { id: 'web', label: '🕸 Web' },
        ].map(t => (
          <button
            key={t.id}
            onClick={() => setView(t.id)}
            className={`flex-1 py-2.5 text-sm font-semibold ${
              view === t.id
                ? 'border-t-2 border-[var(--spidey-red)] text-zinc-100'
                : 'text-zinc-500'
            }`}
          >
            {t.label}
            {t.id === 'web' && state.status === 'running' && view !== 'web' && (
              <span className="ml-1 animate-pulse text-[var(--spidey-red-bright)]">●</span>
            )}
          </button>
        ))}
      </nav>

      {showSettings && (
        <Settings config={config} onSave={handleSave} onClose={() => setShowSettings(false)} />
      )}

      {state.authDenied && <TokenGate />}

      {splash === 'gone' && showOnboarding && (
        <Onboarding onSettings={onboardingSettings} onClose={dismissOnboarding} />
      )}

      {splash !== 'gone' && <Splash fading={splash === 'fading'} />}
    </div>
  )
}
