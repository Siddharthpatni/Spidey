import { useCallback, useEffect, useReducer, useRef } from 'react'

// One reducer consumes the server's event stream and derives both views:
// `chat` (the conversation panel) and `steps` (the live graph).

// Access token for servers started with --token / $SPIDEY_TOKEN. Arrives once
// via the URL (?token=...), then lives in localStorage; both sockets send it.
export function authToken() {
  const url = new URL(window.location.href)
  const fromUrl = url.searchParams.get('token')
  if (fromUrl) {
    localStorage.setItem('spidey-token', fromUrl)
    url.searchParams.delete('token')
    window.history.replaceState(null, '', url.toString())
  }
  return localStorage.getItem('spidey-token') || ''
}

export function wsUrl(path) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const token = authToken()
  return `${proto}://${location.host}${path}${token ? `?token=${encodeURIComponent(token)}` : ''}`
}

let nextId = 1
const uid = () => `i${nextId++}`

export const initialState = {
  connected: false,
  status: 'idle', // idle | running
  runMeta: null, // {model, workdir, safety}
  chat: [],
  steps: [],
  approval: null, // {id, prompt}
  authDenied: false, // server requires a (different) access token
}

function patchLast(items, matches, patch) {
  for (let i = items.length - 1; i >= 0; i--) {
    if (matches(items[i])) {
      const copy = items.slice()
      copy[i] = { ...copy[i], ...patch }
      return copy
    }
  }
  return items
}

const isActiveStep = s => s.status === 'running' || s.status === 'awaiting'
const updateLastRunningStep = (steps, patch) => patchLast(steps, isActiveStep, patch)

export function reducer(state, action) {
  switch (action.type) {
    case 'connected':
      return { ...state, connected: true }
    case 'disconnected':
      return { ...state, connected: false, status: 'idle', approval: null }
    case 'user_task':
      return {
        ...state,
        status: 'running',
        chat: [...state.chat, { id: uid(), kind: 'user', text: action.task }],
        steps: [],
        approval: null,
      }
    case 'restore': // load a past conversation (read-only until the next run)
      return { ...state, status: 'idle', approval: null, chat: action.chat, steps: action.steps }
    case 'new_chat':
      return { ...state, status: 'idle', approval: null, chat: [], steps: [] }
    case 'ws_event':
      return applyEvent(state, action.event)
    default:
      return state
  }
}

function applyEvent(state, ev) {
  switch (ev.type) {
    case 'task_start':
      return {
        ...state,
        status: 'running',
        runMeta: { model: ev.model, workdir: ev.workdir, safety: ev.safety },
        steps: [{ id: uid(), type: 'task', text: ev.task, status: 'ok' }],
      }
    case 'think':
      return {
        ...state,
        chat: [...state.chat, { id: uid(), kind: 'think', text: ev.text }],
        steps: [...state.steps, { id: uid(), type: 'think', text: ev.text, status: 'ok' }],
      }
    case 'tool_call': {
      const id = uid()
      return {
        ...state,
        chat: [...state.chat, { id, kind: 'tool', tool: ev.tool, args: ev.args, status: 'running' }],
        steps: [...state.steps, { id, type: 'tool', tool: ev.tool, args: ev.args, status: 'running' }],
      }
    }
    case 'tool_result': {
      const patch = { status: ev.ok ? 'ok' : 'err', observation: ev.observation }
      return {
        ...state,
        chat: patchLast(state.chat, m => m.kind === 'tool' && m.status === 'running', patch),
        steps: updateLastRunningStep(state.steps, patch),
      }
    }
    case 'approval_request':
      return {
        ...state,
        approval: { id: ev.id, prompt: ev.prompt },
        chat: [...state.chat, { id: ev.id, kind: 'approval', prompt: ev.prompt, resolved: null }],
        steps: updateLastRunningStep(state.steps, { status: 'awaiting' }),
      }
    case 'approval_result':
      return {
        ...state,
        approval: null,
        chat: state.chat.map(m => (m.kind === 'approval' && m.resolved === null ? { ...m, resolved: ev.approved } : m)),
        steps: updateLastRunningStep(state.steps, { status: 'running' }),
      }
    case 'finish':
      return {
        ...state,
        chat: [...state.chat, { id: uid(), kind: 'finish', text: ev.summary }],
        steps: [...state.steps, { id: uid(), type: 'finish', text: ev.summary, status: 'ok' }],
      }
    case 'answer':
      return {
        ...state,
        chat: [...state.chat, { id: uid(), kind: 'agent', text: ev.text }],
        steps: [...state.steps, { id: uid(), type: 'answer', text: ev.text, status: 'ok' }],
      }
    case 'max_steps':
      return { ...state, chat: [...state.chat, { id: uid(), kind: 'error', text: 'Stopped: reached the step limit without finishing.' }] }
    case 'error':
      if ((ev.message || '').startsWith('Access denied')) return { ...state, authDenied: true }
      return { ...state, chat: [...state.chat, { id: uid(), kind: 'error', text: ev.message }] }
    case 'run_done':
      return { ...state, status: 'idle', approval: null }
    default:
      return state
  }
}

export function useSpideySocket() {
  const [state, dispatch] = useReducer(reducer, initialState)
  const wsRef = useRef(null)

  useEffect(() => {
    let ws
    let retry
    let closed = false
    const connect = () => {
      ws = new WebSocket(wsUrl('/ws'))
      wsRef.current = ws
      ws.onopen = () => dispatch({ type: 'connected' })
      ws.onmessage = e => dispatch({ type: 'ws_event', event: JSON.parse(e.data) })
      ws.onclose = () => {
        dispatch({ type: 'disconnected' })
        if (!closed) retry = setTimeout(connect, 1500)
      }
    }
    connect()
    return () => {
      closed = true
      clearTimeout(retry)
      ws?.close()
    }
  }, [])

  const startRun = useCallback((task, config) => {
    dispatch({ type: 'user_task', task })
    wsRef.current?.send(JSON.stringify({ type: 'start', task, config }))
  }, [])

  const answerApproval = useCallback((id, approved) => {
    wsRef.current?.send(JSON.stringify({ type: 'approval', id, approved }))
  }, [])

  const stopRun = useCallback(() => {
    wsRef.current?.send(JSON.stringify({ type: 'stop' }))
  }, [])

  const restore = useCallback((chat, steps) => {
    dispatch({ type: 'restore', chat, steps })
  }, [])

  const newChat = useCallback(() => {
    wsRef.current?.send(JSON.stringify({ type: 'new_chat' })) // clear server-side memory of this session
    dispatch({ type: 'new_chat' })
  }, [])

  return { state, startRun, answerApproval, stopRun, restore, newChat }
}
