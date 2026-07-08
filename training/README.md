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
