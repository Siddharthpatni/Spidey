# Launch kit 🚀

Everything you need to publish Spidey and get eyes on it. This file is for *you* — delete it before you make the repo public, or move it to a `.github/` note. It's not part of the product.

---

## ✅ Before you go public (10-minute checklist)

1. ~~Fill in the placeholders~~ — done (`Siddharth Patni` in `LICENSE` + `pyproject.toml`).
2. **Record THE demo GIF.** This is the single biggest driver of stars and LinkedIn reach:
   - Run `spidey serve`, open the browser, start a screen recording (QuickTime/Kap), and give it a real
     task — or click the mic and say **"Hey Spidey, organize this folder"** (voice makes a killer clip).
   - Capture: the splash ("With great power…"), the reasoning web growing node by node, the amber **Approve/Deny** safety card, the green finish card. ~25 seconds.
   - Export as GIF/MP4 and drop it at the `<!-- 🎬 -->` marker in README.md. (LinkedIn: upload the MP4 natively — native video massively outperforms links.)
3. **Run the fine-tune once for real** on a free Colab/Kaggle GPU (stage 1 + stage 2) and **paste your real eval numbers** into the README table (replace the illustrative rows). Real before/after numbers are what make the post credible.
4. **Add repo topics** (below) so it's discoverable, and **pin the repo** on your GitHub profile.

## 📌 Suggested GitHub repo metadata

**Description (the one-liner under the repo name):**
> Your friendly neighborhood AI — a fully offline voice assistant + agent. Say "Hey Spidey", watch it think in a live reasoning web, run it on Gemma 4 via Ollama (or your own Claude/Gemini/GPT key), and train its brain with SFT→DPO.

**Topics / tags:**
`ai-agent` · `voice-assistant` · `offline-first` · `llm` · `react` · `fastapi` · `websockets` · `ollama` · `gemma` · `vosk` · `dpo` · `qlora` · `fine-tuning` · `tool-calling` · `local-llm` · `autonomous-agents` · `flutter`

---

## 💬 LinkedIn post — v1 announcement (paste-ready)

> I just shipped v1.0 of a project I've been obsessed with: an AI assistant that runs **entirely on your own machine** — voice and all.
>
> Meet **Spidey** 🕷️ — your friendly neighborhood AI.
>
> Say **"Hey Spidey"** and just talk to it. The wake word, the speech-to-text, the model, the spoken reply — every single piece runs offline, on-device. Unplug the router and it still works. No cloud, no per-token bills, no audio or files ever leaving your machine.
>
> And you don't have to trust it blindly: while it works, **every thought and tool call is drawn live as a node in a reasoning web** in your browser. When it wants to run something risky, its "spidey-sense" pauses the run and asks you to approve or deny — by click, or just by saying "approve".
>
> What's under the hood:
>
> 🧠 **Gemma 4 by default** — Google's open-weight model with native function-calling, served locally by Ollama. Or paste your own Claude / Gemini / GPT key; it never touches the server's disk.
>
> 🎙 **Offline voice** — Vosk recognizes speech in-process on your machine; replies are spoken with your OS's own voices. There is no cloud speech API anywhere in the loop.
>
> 🏋️ **A trainable brain** — small local models are unreliable at tool-calling, so Spidey ships a two-stage pipeline: QLoRA SFT teaches the format, then DPO (the same preference-alignment math behind frontier models) teaches the decision — trained on the exact failure modes small models exhibit. Runs on a free Colab GPU, with an eval harness measuring before/after instead of vibes. It's even trained on the character: Peter Parker's voice, and his philosophy — with great power comes great responsibility — mapped to how an agent should behave.
>
> 🛡 **Safety outside the model.** Command screening, path confinement and token auth live in code the model can't talk its way past.
>
> 📱 One protocol, every screen: web UI plus a Flutter client for iOS / Android / macOS / Windows / Linux.
>
> Fully open source (MIT). Three commands to run it:
> git clone → spidey setup → spidey serve
>
> Repo 👉 https://github.com/Siddharthpatni/Spidey
>
> I'd genuinely love feedback from anyone building agents, running local LLMs, or doing preference training — and if you try the voice mode, tell me what it misheard 🙂
>
> #AI #LLM #OpenSource #OfflineAI #VoiceAssistant #AIAgents #Ollama #Gemma #MachineLearning #Python #React #Flutter

**Tips for the post:**
- Lead with the screen recording of the reasoning web — native media gets ~5× the reach of a bare link.
- Post Tue–Thu morning; reply to every comment in the first hour (it boosts distribution).
- The "here's what I learned" framing outperforms a feature dump. Pick ONE lesson (e.g. "DPO on synthetic failure modes fixed my agent's narrate-instead-of-act habit") for a follow-up post a week later — two posts > one.

## 📣 Other good places to share

- **r/LocalLLaMA** — the home crowd for local-model + agent tooling (read their self-promo rules first).
- **Hacker News** "Show HN" — title: `Show HN: Spidey – a self-hostable AI agent that draws its reasoning live in your browser`.
- **X/Twitter** — same video, tag `#LocalLLM`, mention Ollama/Unsloth/React Flow.
- **Ollama Discord** and **React Flow's showcase** — both actively feature community projects.
- Your portfolio site with the GIF + repo link.

## 🎯 For interviews / your portfolio (the 60-second version)

- **Problem:** agents are cloud-only black boxes; local models are unreliable at tool-calling; nobody can see why an agent did what it did.
- **What you built:** full-stack agent infrastructure — a ReAct loop with an external safety layer, a multi-provider backend abstraction (Claude/Gemini/GPT/Ollama behind one interface), a WebSocket event stream, and a React Flow UI that renders the agent's reasoning live with human-in-the-loop approvals.
- **The ML depth:** a two-stage post-training pipeline (QLoRA SFT → DPO) targeting the specific failure modes of small models as agents, with an eval harness quantifying the gain.
- **What it shows:** you can ship product (React/FastAPI), infra (streaming, concurrency, safety), *and* applied ML (preference optimization, quantized deployment, evaluation) end to end.
