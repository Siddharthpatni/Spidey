// First-run overlay: three steps from "just installed" to "talking to it".
// Shown once (localStorage flag).

const STEPS = [
  {
    icon: '🧠',
    title: 'Give it a brain — local and private',
    body: 'Install Ollama, then one command pulls Gemma 4 (Google’s open-weight agent model) to your machine. After that: no internet, no cloud, no per-token bills.',
    cmd: 'spidey setup',
  },
  {
    icon: '🎙',
    title: 'Say “Hey Spidey”',
    body: 'Offline voice — wake word, speech-to-text and spoken replies all run on your device. Click the mic, say the magic words.',
    cmd: 'pip install -e ".[voice]"\nspidey setup --voice',
  },
  {
    icon: '🕸',
    title: 'Watch it think',
    body: 'Every thought and tool call is drawn live in the reasoning web, and risky commands pause for your approval — approve or deny by click or by voice.',
  },
]

export default function Onboarding({ onSettings, onClose }) {
  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div
        className="w-full max-w-lg rounded-2xl border border-[var(--spidey-red)]/40 bg-zinc-950 p-6 shadow-[0_0_60px_rgba(230,36,41,0.15)]"
        onClick={e => e.stopPropagation()}
      >
        <div className="mb-1 flex items-center gap-2 text-lg font-bold">
          <span>🕷️</span> Welcome to Spidey
        </div>
        <p className="mb-5 text-sm text-zinc-400">
          Your friendly neighborhood AI — an assistant that lives on <em>your</em> machine, shows its
          reasoning live, and never phones home.
        </p>
        <div className="space-y-4">
          {STEPS.map((s, i) => (
            <div key={i} className="flex gap-3">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-[var(--spidey-blue)] text-sm">
                {s.icon}
              </div>
              <div className="min-w-0">
                <div className="text-sm font-semibold text-zinc-100">{s.title}</div>
                <div className="mt-0.5 text-xs leading-relaxed text-zinc-400">{s.body}</div>
                {s.cmd && (
                  <pre className="mt-1.5 overflow-x-auto rounded-lg bg-zinc-900 px-3 py-1.5 font-mono text-[11px] text-emerald-300">
                    {s.cmd}
                  </pre>
                )}
              </div>
            </div>
          ))}
        </div>
        <div className="mt-6 flex gap-2">
          <button
            onClick={onClose}
            className="spidey-btn-primary flex-1 rounded-lg py-2 text-sm font-semibold"
          >
            Let's go
          </button>
          <button
            onClick={onSettings}
            className="rounded-lg border border-zinc-700 px-4 py-2 text-sm text-zinc-300 hover:bg-zinc-800"
          >
            ⚙ Choose model
          </button>
        </div>
      </div>
    </div>
  )
}
