"""Fine-tune a small open model into "Spidey's brain", then export it for Ollama.

This is a single-GPU QLoRA run designed to fit a free Colab T4 or Kaggle GPU. It:
  1. loads a small base model in 4-bit (QLoRA),
  2. attaches LoRA adapters,
  3. trains on tool-calling data (synthetic by default; a public dataset optionally),
  4. runs a quick sanity generation,
  5. merges + quantizes + writes an Ollama Modelfile via Unsloth's one-call GGUF export.

Quickstart (Colab / Kaggle GPU runtime):
    !pip install -U unsloth trl datasets
    !python finetune.py --steps 60            # small taste run
    # For a real run, prefer epochs and more data:
    !python finetune.py --epochs 1 --n-synthetic 3000

Then on your own machine (where Ollama lives):
    ollama create spidey-brain -f ./spidey-brain/Modelfile
    spidey run "add a docstring to utils.py" --model spidey-brain

Notes:
  * Confirm the base model tag is live at https://unsloth.ai/docs (tags move fast).
    Good small choices in 2026: unsloth/Qwen2.5-Coder-3B-Instruct, unsloth/Qwen3-4B-Instruct,
    unsloth/Llama-3.2-3B-Instruct, unsloth/gemma-3-4b-it (Google's open Gemma 3 — see
    github.com/google-gemini/gemma-cookbook; its chat template/stop token differ, and the
    exported Modelfile handles that).
  * The #1 cause of "works in the notebook, gibberish in Ollama" is a chat-template
    mismatch. Unsloth's exporter writes a matching Modelfile for you — use it.
  * Tested against unsloth 2026.x + trl ~0.22. If SFTConfig rejects `max_seq_length`,
    rename that one arg to `max_length`.
"""

from __future__ import annotations

import argparse

from prepare_data import TOOLS as SPIDEY_TOOLS
from prepare_data import build_dataset


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="QLoRA fine-tune + GGUF export for Spidey.")
    ap.add_argument("--model", default="unsloth/Qwen2.5-Coder-3B-Instruct",
                    help="Base model (confirm the live tag at unsloth.ai/docs).")
    ap.add_argument("--max-seq-len", type=int, default=2048)
    ap.add_argument("--steps", type=int, default=60,
                    help="Training steps for a quick run. Ignored if --epochs > 0.")
    ap.add_argument("--epochs", type=float, default=0.0,
                    help="Train for this many epochs instead of --steps (use for real runs).")
    ap.add_argument("--n-synthetic", type=int, default=1500,
                    help="How many synthetic tool-calling examples to generate.")
    ap.add_argument("--source", choices=["synthetic", "hf"], default="synthetic")
    ap.add_argument("--dataset", default="Salesforce/xlam-function-calling-60k")
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--out", default="spidey-brain", help="Export directory.")
    ap.add_argument("--quant", default="q4_k_m",
                    help="GGUF quantization (q4_k_m, q8_0, f16).")
    return ap.parse_args()


def main() -> None:
    args = parse_args()

    # Imported here so `--help` works without a GPU/unsloth install.
    from unsloth import FastLanguageModel
    from trl import SFTConfig, SFTTrainer

    # 1) Load base model in 4-bit (the "Q" in QLoRA).
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.model,
        max_seq_length=args.max_seq_len,
        load_in_4bit=True,
        dtype=None,  # auto (bf16 where supported, else fp16)
    )

    # 2) Attach LoRA adapters (only these train; the base stays frozen).
    model = FastLanguageModel.get_peft_model(
        model,
        r=args.lora_r,
        lora_alpha=args.lora_r,     # alpha ≈ r is a solid default
        lora_dropout=0,             # Unsloth is optimized for 0
        bias="none",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth",  # big VRAM savings
        random_state=3407,
    )

    # 3) Build the tool-calling dataset (rendered with THIS model's chat template).
    dataset = build_dataset(tokenizer, n=args.n_synthetic,
                            source=args.source, hf_name=args.dataset)
    print(f"\nDataset: {len(dataset)} examples. First rendered sample:\n"
          f"{'-' * 60}\n{dataset[0]['text'][:700]}\n{'-' * 60}\n")

    # 4) Train.
    cfg_kwargs = dict(
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,     # effective batch size 8
        warmup_steps=5,
        learning_rate=args.lr,
        logging_steps=5,
        optim="adamw_8bit",
        weight_decay=0.01,
        lr_scheduler_type="linear",
        seed=3407,
        output_dir="outputs",
        report_to="none",
        dataset_text_field="text",
        max_seq_length=args.max_seq_len,   # rename to max_length if your trl complains
    )
    if args.epochs > 0:
        cfg_kwargs["num_train_epochs"] = args.epochs
    else:
        cfg_kwargs["max_steps"] = args.steps

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        args=SFTConfig(**cfg_kwargs),
    )
    stats = trainer.train()
    print(f"\nTraining done. Final loss ~ {stats.training_loss:.4f}")

    # 5) Sanity check: does it emit a sensible tool call?
    FastLanguageModel.for_inference(model)
    print("\n--- sanity generation ---")
    inputs = tokenizer.apply_chat_template(
        [{"role": "user", "content": "List the files in the current folder."}],
        tools=SPIDEY_TOOLS, add_generation_prompt=True, return_tensors="pt",
    ).to(model.device)
    out = model.generate(input_ids=inputs, max_new_tokens=128, do_sample=False)
    print(tokenizer.decode(out[0][inputs.shape[1]:], skip_special_tokens=True))
    print("--- end sanity ---")

    # 6) Export: merge + quantize + write an Ollama Modelfile (one call).
    model.save_pretrained_gguf(args.out, tokenizer, quantization_method=args.quant)
    print(
        f"\n✅ Exported to ./{args.out}\n\n"
        f"Load it into Ollama and point Spidey at it:\n"
        f"   ollama create spidey-brain -f ./{args.out}/Modelfile\n"
        f'   spidey run "add a docstring to utils.py" --model spidey-brain\n'
    )


if __name__ == "__main__":
    main()
