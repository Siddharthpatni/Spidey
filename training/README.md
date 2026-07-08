# Training Spidey's brain (QLoRA SFT → DPO → GGUF → Ollama)

The agent in this repo runs on any local model. This folder makes it run *better* on a
**small** one, in two stages:

1. **Stage 1 — SFT** (`finetune.py`): teach the model to emit well-formed tool calls
   in Spidey's exact schema.
2. **Stage 2 — DPO** (`dpo_finetune.py`): teach it to *prefer the right decision* —
   the correct call over prose, wrong tools, malformed arguments, and hallucinated paths.

Big models already do this; the interesting engineering is getting a 1.5B–4B model to do
it dependably — that's what earns the before/after numbers in the [eval](../eval).

Everything here fits on a **free GPU**: Google Colab (T4) or Kaggle (T4/P100).

## The whole loop

```bash
# On a GPU runtime (Colab/Kaggle):
pip install -U unsloth trl datasets

# Stage 1 — quick taste run (~a few minutes on a T4):
python finetune.py --steps 60
# ...or a real run:
python finetune.py --epochs 1 --n-synthetic 3000

# Stage 2 — DPO on top of the SFT checkpoint:
python dpo_finetune.py --adapter outputs --steps 100
# ...or a real run:
python dpo_finetune.py --adapter outputs --epochs 1 --n-pairs 2000

# Each stage writes a folder (./spidey-brain, ./spidey-brain-dpo) with a
# GGUF + an Ollama Modelfile.
```

Then, on the machine where Ollama runs:

```bash
ollama create spidey-brain -f ./spidey-brain-dpo/Modelfile
spidey run "add a docstring to utils.py" --model spidey-brain
```

## What each file does

| File | Purpose |
|------|---------|
| `finetune.py` | Stage 1 (SFT): loads a small base model in 4-bit, attaches LoRA, trains, sanity-checks, and exports GGUF + Modelfile in one call. |
| `prepare_data.py` | Builds the SFT tool-calling dataset. `synthetic` (default, self-contained) or `hf` (a public function-calling dataset). |
| `dpo_finetune.py` | Stage 2 (DPO): loads the stage-1 checkpoint, trains on preference pairs, exports GGUF + Modelfile the same way. |
| `prepare_dpo_data.py` | Builds (chosen, rejected) preference pairs from realistic failure modes. Run `python prepare_dpo_data.py --n 5` to inspect. |
| `Modelfile.example` | Optional hand-written Ollama Modelfile if you want to customize the system prompt/stop tokens. |

## Stage 2: why DPO, and the math in three sentences

SFT shows the model only correct examples, so it learns the *format* but stays fuzzy on
the *decision boundary* — it still sometimes narrates ("I'll run pytest…") instead of
calling the tool. **Direct Preference Optimization** (Rafailov et al., 2023) fixes this
by training on contrasts: it is the closed-form solution of KL-constrained reward
maximization under a **Bradley–Terry** preference model, which lets you skip reward
modeling and RL entirely. The loss directly pushes up the log-probability margin of the
chosen completion over the rejected one, relative to a frozen reference policy (your SFT
model), with β controlling how far the policy may drift:

```
L(θ) = −E[ log σ( β·( log πθ(y_w|x)/π_ref(y_w|x) − log πθ(y_l|x)/π_ref(y_l|x) ) ) ]
```

The rejected completions in `prepare_dpo_data.py` are the four failure modes small
models actually exhibit as agents: prose-instead-of-call, wrong tool, malformed
arguments, hallucinated paths. Measure the effect with the 3-way eval:

```bash
python ../eval/run_eval.py --models qwen2.5-coder:3b,spidey-sft,spidey-brain
```

## Training for SPEED (the honest version)

Training never makes a given model generate faster — tokens/second is set by model
size and your memory bandwidth. What training *does* do is let a **much smaller,
much faster** model reach the reliability of a bigger one on Spidey's specific job
(tool-calling). That's the speed play:

```bash
# Distill Spidey onto a 3B: ~3-4x faster than a 12B on the same laptop
python finetune.py     --model unsloth/Qwen2.5-Coder-3B-Instruct --epochs 1 --n-synthetic 3000
python dpo_finetune.py --adapter outputs --epochs 1
ollama create spidey-brain -f ./spidey-brain-dpo/Modelfile
spidey run "…" --model spidey-brain     # small, fast, AND reliable
```

Then prove it with the eval (`../eval`): base-3B vs spidey-brain accuracy, and
enjoy the tokens/second. The runtime also keeps latency down independently of
training: reasoning-model "thinking" is disabled by default and the weights are
held in RAM between steps (see `spidey/llm.py`).

## Specialist adapters — and training ON your Mac (M-series)

One "everything" fine-tune dilutes; a **wardrobe of small LoRA adapters** specializes.
Each adapter is megabytes, trains on the same base, and Ollama loads it like any
model (`ADAPTER` line in a Modelfile). Natural wardrobe for this repo:

- `spidey-coder` — Python/JS/C++ tasks, tests, refactors (SFT source: this folder's
  synthetic set + a code-instruct dataset)
- `spidey-files` — file-management decisions
- `spidey-research` — summarize/compare/cite behaviors
- `spidey-friend` — persona + listening/advice exchanges

The runtime's role-router (specialist "hats") is adapter-ready: the same routing that
picks a hat today can pick an adapter tomorrow.

**Can a MacBook Air M4 (16 GB) train these?** Honestly:

| Base size | On-Mac LoRA ([mlx-lm](https://github.com/ml-explore/mlx-lm)) | Free Colab (this repo's scripts) |
|---|---|---|
| 1–4 B | ✅ works, hours-scale | ✅ fastest path |
| 7–8 B | ⚠ tight — 4-bit base + small batches, slow | ✅ recommended |
| 12 B+ | ❌ not with 16 GB unified memory | ✅ (T4/A100 handles it) |

On-Mac quickstart (Apple's MLX, no CUDA needed):

```bash
pip install mlx-lm
mlx_lm.lora --model mlx-community/gemma-3-4b-it-4bit \
            --train --data ./data --batch-size 1 --iters 600
mlx_lm.fuse  --model mlx-community/gemma-3-4b-it-4bit --adapter-path adapters
# export to GGUF → Modelfile → `ollama create spidey-coder`
```

(`prepare_data.py` writes the conversations; convert to MLX's JSONL chat format with
a few lines.) Rule of thumb: prototype adapters on the Mac at 1–4 B, do the real runs
on Colab where this repo's Unsloth scripts already work.

## Teaching it to *be* Spider-Man (persona training)

Every synthetic SFT example is conditioned on `SPIDEY_PERSONA` (in `prepare_data.py`) —
a compact version of the runtime system prompt: Peter Parker's voice (warm, quippy,
science-nerd precise, owns his mistakes) plus the philosophy that actually matters for
an agent: *with great power comes great responsibility* → smallest action that works,
look before you touch, reversible over destructive, safety layer = spidey-sense.

Two kinds of examples carry it:

- **~8% persona-chat exchanges** — identity/philosophy questions answered in plain text,
  in character. These do double duty: they teach the voice *and* the boundary "a pure
  question gets prose, not a tool call".
- **Tool-call examples with the persona system prompt** — so the character never leaks
  into arguments: paths, commands and code stay strictly literal while the *summaries*
  get the flavor.

The DPO stage stays persona-neutral on purpose: it trains *decisions* (which tool, which
arguments), and mixing style preferences into decision pairs muddies both signals.

## Data: synthetic vs. real

- **Synthetic (default).** Generated here, no downloads, no dataset agreements. It teaches
  the model *Spidey's exact tool schema*, which is the fastest path to a working end-to-end
  demo. It is deliberately narrow — treat it as a starting point.
- **Real (`--source hf`).** Uses a public function-calling dataset
  (default `Salesforce/xlam-function-calling-60k`) for broader, higher-quality tool-use.
  You may need to accept the dataset's terms on the Hub first. Mix in the synthetic set to
  keep Spidey's own schema well-represented.

For a portfolio result worth writing up: train on the real dataset, then report eval
accuracy (base vs. fine-tuned) from [`../eval`](../eval).

## Choosing a base model

Confirm the current tag at <https://unsloth.ai/docs> (they move fast). Solid small options:

- `unsloth/Qwen2.5-Coder-3B-Instruct` — coding-focused, good default (this repo's default).
- `unsloth/Qwen3-4B-Instruct` — a bit larger, strong general tool-use.
- `unsloth/Llama-3.2-3B-Instruct` — set the stop token to `<|eot_id|>` in the Modelfile.
- `unsloth/gemma-3-4b-it` — Google's open **Gemma** (the open-weight sibling of Gemini;
  see the [google-gemini](https://github.com/google-gemini) org and its
  [gemma-cookbook](https://github.com/google-gemini/gemma-cookbook)). Strong instruction
  following for its size; Gemma uses its own chat template and `<end_of_turn>` stop token —
  Unsloth's exported Modelfile handles both. Both stages take it via
  `--model unsloth/gemma-3-4b-it`. **Gemma 4** (Apr 2026) is the family to prefer once
  Unsloth publishes 4-bit tags for its E2B/E4B edge variants — check
  <https://unsloth.ai/docs>; the inference-side default (`ollama pull gemma4:12b`) already
  uses it.

### Borrowing a big brain: distillation from Gemini / Claude

The free tier of a frontier API is a legitimate **teacher** for stage-2 data: have Gemini or
Claude label which of two candidate tool-calls is correct (or generate the "chosen" side
outright), and DPO-train the small local model on those preferences. That's classic
distillation — the *user's* runtime stays 100% offline; only *you*, the trainer, ever touch
the API, once, to build the dataset. `prepare_dpo_data.py --source hf` is the drop-in place
to swap in teacher-labeled pairs.

## The one gotcha that bites everyone

If the model looks great during training but produces **gibberish or endless repetition in
Ollama**, it is almost always a **chat-template / EOS-token mismatch** — the model was served
with a different prompt format than it learned. Unsloth's exported Modelfile matches the
training template on purpose, so use it rather than hand-rolling one. (See `finetune.py`'s
header notes.)

## Approximate resource needs

A 1.5B–4B model in 4-bit QLoRA at 2048 tokens trains comfortably on a single 12–16 GB GPU.
If you hit CUDA OOM: drop `per_device_train_batch_size` to 1, lower `--max-seq-len`, or pick
a smaller base model.
