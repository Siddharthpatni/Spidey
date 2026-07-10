import { useCallback, useEffect, useRef, useState } from 'react'
import { wsUrl } from './useSpideySocket.js'

// Offline voice, browser side. The mic is captured with WebAudio, downsampled
// to 16 kHz PCM16 and streamed over /ws/voice to the local server, where Vosk
// (running on the user's machine) does wake-word + speech-to-text. Replies are
// spoken with speechSynthesis, which uses the OS's local voices — so the whole
// loop works with the network cable unplugged.

const WORKLET_CODE = `
class SpideyCapture extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0]
    if (ch) this.port.postMessage(ch.slice(0))
    return true
  }
}
registerProcessor('spidey-capture', SpideyCapture)
`

function resampleTo16k(float32, inputRate) {
  if (inputRate === 16000) return float32
  const outLen = Math.max(1, Math.round((float32.length * 16000) / inputRate))
  const out = new Float32Array(outLen)
  for (let i = 0; i < outLen; i++) {
    const pos = (i * (float32.length - 1)) / (outLen - 1 || 1)
    const i0 = Math.floor(pos)
    const i1 = Math.min(i0 + 1, float32.length - 1)
    out[i] = float32[i0] + (float32[i1] - float32[i0]) * (pos - i0)
  }
  return out
}

function toPCM16(float32) {
  const out = new Int16Array(float32.length)
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]))
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff
  }
  return out
}

function pickVoice() {
  const voices = window.speechSynthesis?.getVoices() || []
  return (
    voices.find(v => v.localService && v.lang.startsWith('en') && /male|daniel|alex|fred/i.test(v.name)) ||
    voices.find(v => v.localService && v.lang.startsWith('en')) ||
    voices.find(v => v.lang.startsWith('en')) ||
    null
  )
}

// Short web-swing chime so hands-free users know Spidey woke up.
function chime(ctx) {
  try {
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.type = 'sine'
    osc.frequency.setValueAtTime(660, ctx.currentTime)
    osc.frequency.exponentialRampToValueAtTime(990, ctx.currentTime + 0.12)
    gain.gain.setValueAtTime(0.12, ctx.currentTime)
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.25)
    osc.connect(gain).connect(ctx.destination)
    osc.start()
    osc.stop(ctx.currentTime + 0.26)
  } catch {
    /* cosmetic only */
  }
}

// status: 'unavailable' | 'off' | 'starting' | 'listening' | 'awake'
export function useVoice({ onUtterance }) {
  const [serverStatus, setServerStatus] = useState(null) // /api/voice/status payload
  const [status, setStatus] = useState('off')
  const [partial, setPartial] = useState('')
  const [heard, setHeard] = useState('') // wake-mode live transcript (diagnostic)
  const [speakReplies, setSpeakReplies] = useState(
    () => localStorage.getItem('spidey-speak') !== '0',
  )

  const wsRef = useRef(null)
  const ctxRef = useRef(null)
  const streamRef = useRef(null)
  const speakingRef = useRef(false)
  const onUtteranceRef = useRef(onUtterance)
  onUtteranceRef.current = onUtterance

  useEffect(() => {
    fetch('/api/voice/status')
      .then(r => r.json())
      .then(setServerStatus)
      .catch(() => setServerStatus({ available: false, hint: 'Server unreachable.' }))
  }, [])

  useEffect(() => {
    localStorage.setItem('spidey-speak', speakReplies ? '1' : '0')
  }, [speakReplies])

  const stop = useCallback((forget = true) => {
    if (forget) localStorage.setItem('spidey-voice-on', '0')
    wsRef.current?.close()
    wsRef.current = null
    streamRef.current?.getTracks().forEach(t => t.stop())
    streamRef.current = null
    ctxRef.current?.close().catch(() => {})
    ctxRef.current = null
    setPartial('')
    setHeard('')
    setStatus('off')
  }, [])

  const start = useCallback(async () => {
    if (!serverStatus?.available || !navigator.mediaDevices?.getUserMedia) return
    setStatus('starting')
    try {
      const ws = new WebSocket(wsUrl('/ws/voice'))
      ws.binaryType = 'arraybuffer'
      wsRef.current = ws

      const ready = new Promise((resolve, reject) => {
        ws.onmessage = e => {
          const ev = JSON.parse(e.data)
          if (ev.type === 'voice_ready') resolve()
          else if (ev.type === 'voice_unavailable') reject(new Error(ev.hint || 'voice unavailable'))
        }
        ws.onerror = () => reject(new Error('voice socket failed'))
        ws.onclose = () => reject(new Error('voice socket closed'))
      })
      await ready

      ws.onmessage = e => {
        const ev = JSON.parse(e.data)
        if (ev.type === 'wake') {
          setStatus('awake')
          setPartial('')
          setHeard('')
          if (ctxRef.current) chime(ctxRef.current)
        } else if (ev.type === 'heard') {
          setHeard(ev.text)
        } else if (ev.type === 'partial') {
          setPartial(ev.text)
        } else if (ev.type === 'utterance') {
          setPartial('')
          onUtteranceRef.current?.(ev.text)
        } else if (ev.type === 'sleep') {
          setStatus('listening')
          setPartial('')
        }
      }
      ws.onclose = () => stop()

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      })
      streamRef.current = stream

      let ctx
      try {
        ctx = new AudioContext({ sampleRate: 16000 })
      } catch {
        ctx = new AudioContext()
      }
      ctxRef.current = ctx
      const workletUrl = URL.createObjectURL(new Blob([WORKLET_CODE], { type: 'text/javascript' }))
      await ctx.audioWorklet.addModule(workletUrl)
      URL.revokeObjectURL(workletUrl)

      if (ctx.state === 'suspended') await ctx.resume().catch(() => {})

      const source = ctx.createMediaStreamSource(stream)
      const node = new AudioWorkletNode(ctx, 'spidey-capture')

      let buffer = []
      let buffered = 0
      node.port.onmessage = e => {
        // Don't let Spidey hear itself talk.
        if (speakingRef.current || ws.readyState !== WebSocket.OPEN) return
        const pcm = toPCM16(resampleTo16k(e.data, ctx.sampleRate))
        buffer.push(pcm)
        buffered += pcm.length
        if (buffered >= 4000) {
          const joined = new Int16Array(buffered)
          let off = 0
          for (const c of buffer) {
            joined.set(c, off)
            off += c.length
          }
          ws.send(joined.buffer)
          buffer = []
          buffered = 0
        }
      }
      source.connect(node)
      localStorage.setItem('spidey-voice-on', '1')
      setStatus('listening')
    } catch (err) {
      console.warn('voice start failed:', err)
      stop(false)
    }
  }, [serverStatus, stop])

  // If voice was on last time and the mic permission is already granted,
  // re-arm hands-free listening automatically — no click needed per visit.
  const autoTried = useRef(false)
  useEffect(() => {
    if (autoTried.current || !serverStatus?.available) return
    if (localStorage.getItem('spidey-voice-on') !== '1') return
    autoTried.current = true
    navigator.permissions
      ?.query({ name: 'microphone' })
      .then(p => p.state === 'granted' && start())
      .catch(() => {})
  }, [serverStatus, start])

  const toggle = useCallback(() => {
    if (status === 'off') start()
    else stop()
  }, [status, start, stop])

  useEffect(() => stop, [stop]) // teardown on unmount

  const speak = useCallback(
    text => {
      if (!speakReplies || !window.speechSynthesis || !text) return
      window.speechSynthesis.cancel()
      const spoken = text.replace(/[*_`#]/g, '').slice(0, 600)
      const utter = new SpeechSynthesisUtterance(spoken)
      const voice = pickVoice()
      if (voice) utter.voice = voice
      utter.rate = 1.05
      utter.onstart = () => (speakingRef.current = true)
      utter.onend = () => (speakingRef.current = false)
      utter.onerror = () => (speakingRef.current = false)
      window.speechSynthesis.speak(utter)
    },
    [speakReplies],
  )

  return {
    available: !!serverStatus?.available,
    hint: serverStatus?.hint,
    // Browsers expose the mic only in secure contexts (https or localhost).
    micSupported: !!navigator.mediaDevices?.getUserMedia,
    status: serverStatus && !serverStatus.available ? 'unavailable' : status,
    partial,
    heard,
    toggle,
    speak,
    speakReplies,
    setSpeakReplies,
  }
}
