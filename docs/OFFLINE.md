# 🕷️ Spidey, fully offline — the complete guide

Spidey's promise: **everything can run on your device**. This page is the one place
that spells out exactly what that means for each piece — the brain (LLM), the voice
(wake word / STT / TTS), the apps, and the training loop — plus what still needs
internet (spoiler: only the one-time downloads).

## TL;DR setup (macOS / Windows / Linux)

```bash
git clone https://github.com/Siddharthpatni/Spidey && cd Spidey
pip install -e ".[server,voice]"

# one-time downloads — internet needed HERE and only here
spidey setup              # brain:  Gemma 4 12B via Ollama (~7.6 GB)
spidey setup --voice      # ears:   Vosk speech model (~40 MB)

spidey serve              # → http://127.0.0.1:8000 — now unplug the router 🕸
```

Open the web UI, click the mic, and say **“Hey Spidey — list the files in my
downloads folder.”**

## The brain: which model, and is it *really* offline?

Spidey drives any of these through [Ollama](https://ollama.com), which stores the full
weights on your disk and serves them from `localhost`. Once pulled, **no request ever
leaves your machine** — airplane-mode works.

| Tag | Download | Effective params | Notes |
|---|---|---|---|
| **`gemma4:12b`** (default) | ~7.6 GB | 12 B | [Gemma 4](https://deepmind.google/models/gemma/gemma-4/) — Google's open-weight family (Apache 2.0, April 2026). Built for **agentic workflows**: native function-calling, 256 K context. The best offline agent brain right now. |
| `gemma4:e4b` | ~9.6 GB | 4.5 B | Gemma 4 "edge" — tuned for on-device use |
| `gemma4:e2b` | ~7.2 GB | 2.3 B | smallest Gemma 4; phones/thin laptops territory |
| `qwen2.5-coder:7b` | ~4.7 GB | 7 B | excellent coding-focused tool-caller |
| `llama3.1:8b` | ~4.9 GB | 8 B | strong general assistant |
| `qwen2.5-coder:1.5b` | ~1 GB | 1.5 B | experiments / very old hardware |

**Gemma vs Gemini, once and for all:** *Gemini* is Google's cloud API — never offline.
*Gemma* is Google's open-weight sibling you download and own — fully offline. Spidey
uses Gemma locally, and can optionally use Gemini via your API key if you choose the
cloud in Settings.

**RAM guide:** `gemma4:12b` wants ~10 GB free; `e4b`/`e2b` and the Qwen models fit
8 GB machines comfortably.

## The voice: "Hey Spidey", offline

Three parts, all on-device:

1. **Wake word + speech-to-text** — [Vosk](https://alphacephei.com/vosk/), a small
   open-source recognizer, runs *inside the Spidey server process*. The browser
   streams raw mic audio over a localhost WebSocket (`/ws/voice`); the server answers
   with wake / live-transcript / utterance events. `spidey/voice.py` is the whole engine.
2. **Text-to-speech** — the browser's `speechSynthesis` API, which uses your **OS's
   built-in local voices** (offline on macOS, Windows, most Linux). Zero downloads.
3. **Hands-free approvals** — when the safety layer flags a command, Spidey says so
   out loud; answer by voice: *"approve"* or *"deny"*. Saying *"stop"* cancels a run.

No cloud speech API exists anywhere in this loop. If voice isn't set up, the mic
button in the UI shows the two setup commands.

## The screens: web, desktop, mobile

- **Web UI** (`spidey serve`) — chat + live reasoning graph + voice. This is the
  full experience.
- **Flutter app** ([`app/`](../app/)) — iOS · Android · macOS · Windows · Linux.
  Same protocol, tap-to-talk voice using the OS speech engine. On a PC it points at
  `localhost` (fully offline); on a phone it points at your PC over Wi-Fi (nothing
  leaves your network). Per-platform build steps: [app/README.md](../app/README.md).

## The training loop: make the small brain smarter

The [training pipeline](../training/) (QLoRA **SFT** → **DPO**) tunes a small model
specifically on agent decisions — trains on a free Colab GPU, exports a GGUF that
Ollama serves offline like any other model. Gemma works as a base
(`--model unsloth/gemma-3-4b-it` today; check [Unsloth](https://unsloth.ai/docs) for
Gemma 4 tags as they land). You can even use Gemini or Claude as a one-time *teacher*
to label training pairs — the runtime stays 100 % offline; see
[training/README.md](../training/README.md).

## Performance: why local runs feel slow, and what to do

Three separate things get blamed as "the model is slow" — know which one you're hitting:

1. **Hidden thinking.** Reasoning models (Gemma 4, Qwen3…) generate a long private
   chain-of-thought before every answer — measured here: **1,273 hidden tokens for a
   one-line reply ≈ 107 s** on a base M4. Spidey turns thinking **off by default**
   (same reply: **1.4 s**). Prefer deliberation over speed? `SPIDEY_THINK=1 spidey serve`.
2. **Cold model load.** The first request after boot/idle streams the whole model
   (~8 GB for `gemma4:12b`) from disk into RAM — tens of seconds, worse when the
   machine is under memory pressure. Spidey passes `keep_alive: 30m` so the weights
   stay resident between steps and runs; only the *first* request pays this.
3. **Raw generation speed.** A 12B model on a 16 GB base M-series Mac ≈ 10–15 tok/s.
   That's physics (memory bandwidth). Pick the model for your hardware:

| Machine | Recommended | Feel |
|---|---|---|
| 8–16 GB laptop | `gemma4:e2b` or `qwen2.5-coder:7b` | snappy |
| 16 GB (this repo's default) | `gemma4:12b` | ~1–3 s per short step once warm |
| 32 GB+ / discrete GPU | `gemma4:26b` (MoE, 3.8 B active) | fast *and* smart |

### Want cloud speed? Two honest options

- **Bring-your-own-key** (Settings → Claude / Gemini / OpenAI): the *brain* moves to
  the cloud — instant, frontier-quality — while the agent, safety layer, files and
  voice stay on your machine. This is the "make it fast" switch; the privacy trade
  is explicit and yours.
- **Your own GPU box**: run Ollama (or vLLM/llama.cpp) on any machine you control —
  a gaming PC, a rented GPU server — and point Spidey's **Custom** provider at its
  URL. Fast *and* still self-hosted; pair it with `spidey serve --token …`.

### Using Spidey from another device on your network

```bash
spidey serve --host 0.0.0.0 --token $(openssl rand -hex 16)
# on the phone/laptop: http://<this-machine's-ip>:8000/?token=<that token>
```

Chat, runs, approvals and the reasoning web all work over the LAN. One browser rule
to know: microphones require a *secure context*, so the **mic button works on
localhost but not on plain `http://<ip>`** — put TLS in front (a one-liner with
[Caddy](https://caddyserver.com)) if you want voice from remote devices.

**Use it like an app, not a browser tab:** the UI is installable. On the phone, open
the URL once, then *Share → Add to Home Screen* (iOS) or *⋮ → Add to home screen*
(Android) — Spidey launches fullscreen with its own icon, like a native app. The UI
is fully responsive on phones (chat and the reasoning web become tabs). If the server
asks for a token, the app shows an unlock screen — paste the token once and it's
remembered. The true native app (Flutter, [app/](../app/)) covers
iOS/Android/desktop with the same protocol.

## What needs internet, exactly

| Action | Internet? |
|---|---|
| `pip install`, `spidey setup`, `spidey setup --voice` | once, yes |
| Chat, agent runs, voice, approvals — with Ollama | **no** |
| Claude / Gemini / OpenAI providers | yes (that's their point) |
| Fine-tuning on Colab | yes (it's a cloud GPU); running the result — **no** |

## Security note (same as everywhere else in this repo)

The agent has shell access — treat the server like SSH. On localhost the defaults
are fine; for LAN/phone access start it with an access token
(`spidey serve --host 0.0.0.0 --token <secret>`). Full threat model:
[SECURITY.md](SECURITY.md).
