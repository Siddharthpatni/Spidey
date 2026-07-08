import { useState } from 'react'

// Voice controls for the chat panel: a mic toggle (hands-free "Hey Spidey"
// mode), a speak-replies toggle, and a status strip with the live transcript.
// Everything behind these buttons runs on-device — see useVoice.js.

export function MicButton({ voice }) {
  const [showHint, setShowHint] = useState(false)
  const { status } = voice

  // Secure-context wall: the browser hides the mic on plain http:// pages
  // (localhost excepted). Tapping the mic explains the one-flag fix.
  if (status !== 'unavailable' && !voice.micSupported) {
    return (
      <div className="relative">
        <button
          onClick={() => setShowHint(s => !s)}
          title="Mic needs HTTPS on this device"
          className="rounded-lg border border-zinc-700 px-3 py-2 text-sm text-zinc-500 hover:bg-zinc-800"
        >
          🎙
        </button>
        {showHint && (
          <div className="absolute bottom-12 right-0 z-50 w-72 rounded-xl border border-[var(--spidey-blue)] bg-zinc-900 p-3 text-xs shadow-2xl">
            <div className="mb-1 font-semibold text-zinc-200">Mic needs HTTPS here</div>
            <p className="mb-2 text-zinc-400">
              Browsers only open the microphone on secure pages. Restart the server with:
            </p>
            <pre className="overflow-x-auto rounded-lg bg-zinc-950 p-2 text-[11px] leading-relaxed text-zinc-300">
{`spidey serve --host 0.0.0.0 \\
  --token <token> --https`}
            </pre>
            <p className="mt-2 text-zinc-500">
              Then open the https:// link, accept the one-time certificate warning, and
              “Hey Spidey” works from this device too.
            </p>
          </div>
        )}
      </div>
    )
  }

  if (status === 'unavailable') {
    return (
      <div className="relative">
        <button
          onClick={() => setShowHint(s => !s)}
          title="Offline voice isn't set up yet"
          className="rounded-lg border border-zinc-700 px-3 py-2 text-sm text-zinc-500 hover:bg-zinc-800"
        >
          🎙
        </button>
        {showHint && (
          <div className="absolute bottom-12 right-0 z-50 w-72 rounded-xl border border-[var(--spidey-blue)] bg-zinc-900 p-3 text-xs shadow-2xl">
            <div className="mb-1 font-semibold text-zinc-200">Enable offline voice</div>
            <p className="mb-2 text-zinc-400">
              100% on-device — say <span className="font-semibold text-[var(--spidey-red-bright)]">“Hey Spidey”</span> to
              give tasks by voice.
            </p>
            <pre className="overflow-x-auto rounded-lg bg-zinc-950 p-2 text-[11px] leading-relaxed text-zinc-300">
{`pip install -e ".[voice]"
spidey setup --voice`}
            </pre>
            <p className="mt-2 text-zinc-500">{voice.hint}</p>
          </div>
        )}
      </div>
    )
  }

  const active = status === 'listening' || status === 'awake'
  return (
    <button
      onClick={voice.toggle}
      title={active ? 'Stop listening' : 'Start hands-free listening ("Hey Spidey")'}
      className={`rounded-lg px-3 py-2 text-sm transition-colors ${
        status === 'awake'
          ? 'spidey-mic-awake bg-[var(--spidey-red)] text-white'
          : status === 'listening'
            ? 'spidey-mic-listening border border-[var(--spidey-red)] text-[var(--spidey-red-bright)]'
            : status === 'starting'
              ? 'animate-pulse border border-zinc-600 text-zinc-400'
              : 'border border-zinc-700 text-zinc-400 hover:bg-zinc-800'
      }`}
    >
      🎙
    </button>
  )
}

export function SpeakerToggle({ voice }) {
  return (
    <button
      onClick={() => voice.setSpeakReplies(v => !v)}
      title={voice.speakReplies ? 'Spidey speaks replies (click to mute)' : 'Replies muted (click to unmute)'}
      className={`rounded-lg border px-3 py-2 text-sm transition-colors ${
        voice.speakReplies
          ? 'border-[var(--spidey-blue)] text-blue-300'
          : 'border-zinc-700 text-zinc-600 hover:bg-zinc-800'
      }`}
    >
      {voice.speakReplies ? '🔊' : '🔇'}
    </button>
  )
}

export function VoiceStrip({ voice }) {
  const { status, partial } = voice
  if (status !== 'listening' && status !== 'awake') return null
  return (
    <div
      className={`mx-3 mb-2 flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs ${
        status === 'awake'
          ? 'border-[var(--spidey-red)] bg-[var(--spidey-red)]/10 text-zinc-100'
          : 'border-zinc-800 bg-zinc-900/60 text-zinc-500'
      }`}
    >
      <span className={status === 'awake' ? 'spidey-orb-awake' : 'spidey-orb'}>●</span>
      {status === 'awake' ? (
        <span className="truncate">{partial || 'Listening… what can I do?'}</span>
      ) : (
        <span>
          Say <span className="font-semibold text-zinc-300">“Hey Spidey”</span> — mic stays on this device
        </span>
      )}
    </div>
  )
}
