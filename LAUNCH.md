# Launch kit 🚀

Everything you need to publish Spidey and get eyes on it. This file is for *you* — delete it before you make the repo public, or move it to a `.github/` note. It's not part of the product.

---

## ✅ Before you go public (10-minute checklist)

1. **Fill in the placeholders:** `Your Name` in `LICENSE` + `pyproject.toml`.
2. **Record THE demo GIF.** This is the single biggest driver of stars and LinkedIn reach:
   - Run `spidey serve`, open the browser, start a screen recording (QuickTime/Kap), hit **▶ Run demo**.
   - Capture: the splash ("With great power…"), the reasoning web growing node by node, the amber **Approve/Deny** safety card, the green finish card. ~25 seconds.
   - Export as GIF/MP4 and drop it at the `<!-- 🎬 -->` marker in README.md. (LinkedIn: upload the MP4 natively — native video massively outperforms links.)
3. **Run the fine-tune once for real** on a free Colab/Kaggle GPU (stage 1 + stage 2) and **paste your real eval numbers** into the README table (replace the illustrative rows). Real before/after numbers are what make the post credible.
4. **Add repo topics** (below) so it's discoverable, and **pin the repo** on your GitHub profile.

## 📌 Suggested GitHub repo metadata

**Description (the one-liner under the repo name):**
> Self-hostable AI agent with a live reasoning graph in your browser. Bring your own model (Claude/Gemini/GPT) or run it free & offline on Ollama — plus an SFT→DPO pipeline to train its own brain.

**Topics / tags:**
`ai-agent` · `llm` · `react` · `fastapi` · `websockets` · `ollama` · `dpo` · `qlora` · `fine-tuning` · `tool-calling` · `local-llm` · `autonomous-agents` · `anthropic` · `gemini` · `openai`

---

## 💬 LinkedIn post (first-person, honest — edit to taste)

> I wanted to see *how* an AI agent thinks — not read its logs afterwards. So I built one that draws its reasoning live in the browser.
>
> Meet **Spidey** 🕷️ — a self-hostable AI agent. You give it a task; it reads files, searches code, writes changes, and runs commands — and every thought and tool call appears as a node in a live graph while it works. When it wants to run something risky, the safety layer pauses the run and asks *you* to approve or deny, right in the UI.
>
> Three design decisions I'm proud of:
>
> 1. **Bring your own model.** It runs free and fully offline on open-weight models via Ollama — or you paste your own Claude / Gemini / GPT key in the browser and it uses that. Keys never touch the server's disk.
> 2. **Train the brain, don't hope.** Small local models are unreliable at tool-calling, so I built a two-stage pipeline: QLoRA SFT teaches the *format*, then DPO (Direct Preference Optimization — the same preference-alignment math used to align frontier models) teaches the *decision*, trained on the exact failure modes small models exhibit: narrating instead of acting, wrong tools, malformed arguments. It fine-tunes on a **free** Colab GPU, and an eval harness measures the before/after instead of vibes.
> 3. **Safety outside the model.** Command screening and path confinement live in code the model can't touch — a prompt-injected model can't talk its way past them.
>
> Stack: Python/FastAPI + WebSockets on the back, React + React Flow + Tailwind on the front, Unsloth/TRL for training.
>
> It's fully open source (MIT), with a zero-setup demo — clone it and watch it work in 30 seconds.
>
> Repo 👉 https://github.com/Siddharthpatni/Spidey
>
> Would genuinely love feedback from anyone working on agents, local LLMs, or preference training.
>
> #AI #LLM #OpenSource #MachineLearning #AIAgents #React #Python #Ollama

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
