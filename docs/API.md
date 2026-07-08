# 🕷️ Spidey wire protocol

Everything a client needs to talk to `spidey serve`. The web UI and the Flutter app
are both plain consumers of this — you can build your own client in an afternoon.

## Authentication

If the server was started with `--token <t>` (or `$SPIDEY_TOKEN`), **every**
WebSocket connection must carry it as a query parameter:

```
ws://host:8000/ws?token=<t>
ws://host:8000/ws/voice?token=<t>
```

Wrong/missing token → the server sends one error event, then closes with code
**1008**:

```json
{"type": "error", "step": 0, "message": "Access denied: invalid or missing token. …"}
```

The web UI accepts the token once via the page URL (`http://host:8000/?token=<t>`),
stores it in `localStorage`, and strips it from the address bar.

## `/ws` — agent sessions

One connection = one interactive session; one run at a time per connection.

### Client → server

| Message | Shape | Meaning |
|---|---|---|
| start | `{"type":"start","task":str,"config":{…}}` | begin a run |
| approval | `{"type":"approval","id":str,"approved":bool}` | answer a pending safety prompt |
| stop | `{"type":"stop"}` | cancel the current run |

`config` (all optional except `provider` in practice):

```json
{
  "provider": "ollama | anthropic | gemini | openai | custom",
  "model":    "gemma4:12b",
  "api_key":  "…            — cloud providers only; never persisted server-side",
  "base_url": "…            — custom/OpenAI-compatible endpoints",
  "workdir":  "…            — agent sandbox; server default if empty",
  "safety":   "ask | enforce | off",
  "max_steps": 25
}
```

### Server → client

Events stream in the order they happen. `step` is the loop iteration.

| Event | Payload fields | Meaning |
|---|---|---|
| `task_start` | `task, workdir, model, safety` | run began |
| `think` | `text` | model commentary (drawn as a 🧠 node) |
| `tool_call` | `tool, args` | the model chose a tool |
| `tool_result` | `tool, observation, ok` | what the tool returned |
| `approval_request` | `id, prompt` | safety layer wants a human verdict |
| `approval_result` | `approved` | verdict echoed to all views |
| `finish` | `summary` | the agent called `finish` |
| `answer` | `text` | plain-text answer (no tool call) |
| `error` | `message` | backend/config problem, surfaced not fatal |
| `max_steps` | — | loop hit the step limit |
| `run_done` | — | always sent last, success or not |

## `/ws/voice` — offline voice

Client streams **binary** frames of raw PCM — 16 kHz, mono, 16-bit little-endian —
and receives JSON events. Availability first:

```
GET /api/voice/status →
{"available": bool, "vosk_installed": bool, "model_downloaded": bool,
 "model": "vosk-model-small-en-us-0.15", "hint": "…set-up command if missing…"}
```

On connect the server answers `{"type":"voice_ready","model":…}` or
`{"type":"voice_unavailable", …status fields…}` (then closes).

### Client → server

| Message | Meaning |
|---|---|
| binary frame | PCM audio chunk (any size; ~0.25 s chunks work well) |
| `{"type":"mode","mode":"wake"\|"direct"}` | `wake` = hands-free ("Hey Spidey"); `direct` = transcribe everything |

### Server → client

| Event | Meaning |
|---|---|
| `{"type":"wake"}` | wake word heard — UI chimes and shows "listening" |
| `{"type":"partial","text":…}` | live transcript while the user speaks |
| `{"type":"utterance","text":…}` | utterance complete — treat as the task |
| `{"type":"sleep"}` | back to waiting for the wake word |

Client-side conventions (what the web UI does with utterances): idle → start a
run; `stop/cancel/abort` while running → stop; `approve/yes` / `deny/no` while an
approval is pending → answer it.

## Design notes

- **Keys are ephemeral.** `api_key` rides inside each `start` and lives only in
  that run's backend object. The server never writes it anywhere.
- **Events over state.** The server pushes append-only events; clients derive
  their own views (chat, graph) — that's why two very different frontends share
  the protocol unchanged.
- **Voice never leaves home.** `/ws/voice` audio is consumed in-process by Vosk;
  there is no relay, no cloud STT, no recording to disk.
