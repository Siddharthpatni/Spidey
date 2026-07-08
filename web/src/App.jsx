import { useEffect, useState } from 'react'
import AgentGraph, { styleFor } from './AgentGraph.jsx'
import Chat from './Chat.jsx'
import Settings, { PROVIDERS, loadConfig, saveConfig } from './Settings.jsx'
import { useSpideySocket } from './useSpideySocket.js'

function Badge({ children, tone = 'zinc' }) {
  const tones = {
    zinc: 'border-zinc-700 text-zinc-400',
    green: 'border-emerald-600/60 text-emerald-400',
    amber: 'border-amber-600/60 text-amber-300',
    red: 'border-rose-600/60 text-rose-400',
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
      <h1 className="spidey-splash-quote mt-6 text-2xl font-bold tracking-[0.3em]">SPIDEY</h1>
      <p className="spidey-splash-quote mt-3 max-w-sm text-center text-sm italic text-zinc-400">
        “With great power comes great responsibility.”
      </p>
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
  const { state, startRun, answerApproval, stopRun } = useSpideySocket()
  const [config, setConfig] = useState(loadConfig)
  const [showSettings, setShowSettings] = useState(false)
  const [selected, setSelected] = useState(null)
  const [splash, setSplash] = useState('show') // show -> fading -> gone

  useEffect(() => {
    const fade = setTimeout(() => setSplash('fading'), 2400)
    const gone = setTimeout(() => setSplash('gone'), 3200)
    return () => {
      clearTimeout(fade)
      clearTimeout(gone)
    }
  }, [])

  const provider = PROVIDERS.find(p => p.id === config.provider) || PROVIDERS[0]

  const handleSave = cfg => {
    setConfig(cfg)
    saveConfig(cfg)
  }

  const start = task => {
    setSelected(null)
    startRun(task, config)
  }

  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center gap-3 border-b border-zinc-800 px-4 py-2.5">
        <span className="text-lg">🕷️</span>
        <h1 className="text-sm font-bold tracking-wide">Spidey</h1>
        <span className="text-xs text-zinc-600">local AI agent · live reasoning web</span>
        <div className="ml-auto flex items-center gap-2">
          {state.status === 'running' && <Badge tone="amber">running</Badge>}
          <Badge tone={state.connected ? 'green' : 'red'}>
            {state.connected ? '● connected' : '○ offline'}
          </Badge>
          <Badge>{state.runMeta?.model || provider.name}</Badge>
          <Badge>safety: {config.safety}</Badge>
          {config.provider === 'demo' && state.status !== 'running' && (
            <button
              onClick={() => start('')}
              disabled={!state.connected}
              className="rounded-lg bg-emerald-600 px-3 py-1 text-xs font-semibold hover:bg-emerald-500 disabled:opacity-40"
            >
              ▶ Run demo
            </button>
          )}
          <button
            onClick={() => setShowSettings(true)}
            className="rounded-lg border border-zinc-700 px-3 py-1 text-xs font-semibold text-zinc-300 hover:bg-zinc-800"
          >
            ⚙ Settings
          </button>
        </div>
      </header>

      <main className="flex min-h-0 flex-1">
        <section className="w-[380px] shrink-0 border-r border-zinc-800">
          <Chat state={state} onStart={start} onStop={stopRun} onAnswer={answerApproval} />
        </section>
        <section className="relative min-w-0 flex-1">
          <AgentGraph steps={state.steps} onSelect={setSelected} />
          {selected && <StepSheet step={selected} onClose={() => setSelected(null)} />}
        </section>
      </main>

      {showSettings && (
        <Settings config={config} onSave={handleSave} onClose={() => setShowSettings(false)} />
      )}

      {splash !== 'gone' && <Splash fading={splash === 'fading'} />}
    </div>
  )
}
