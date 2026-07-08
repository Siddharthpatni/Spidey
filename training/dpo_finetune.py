"""Stage 2: DPO — align Spidey's brain to *prefer* correct tool-call decisions.

Run this after finetune.py (stage 1, SFT). It loads your SFT checkpoint, trains on
(chosen, rejected) preference pairs from prepare_dpo_data.py, and exports a GGUF +
Ollama Modelfile exactly like stage 1 did. Also fits a free Colab T4 / Kaggle GPU.

    Stage 1 (SFT):  learn the tool-call format          → finetune.py
    Stage 2 (DPO):  learn to choose the right call      → this file

Quickstart (Colab / Kaggle GPU runtime):
    !pip install -U unsloth trl datasets
    !python finetune.py --epochs 1 --n-synthetic 3000        # stage 1
    !python dpo_finetune.py --adapter outputs --steps 100    # stage 2 (quick)
    !python dpo_finetune.py --adapter outputs --epochs 1 --n-pairs 2000   # real run

Then on your machine:
    ollama create spidey-brain -f ./spidey-brain-dpo/Modelfile
    spidey run "add type hints to models.py" --model spidey-brain

Notes:
  * `--adapter` points at stage 1's LoRA checkpoint dir (finetune.py's `output_dir`,
    default `outputs`). Omit it to run DPO straight on the base model — legal, but
    SFT-then-DPO is the standard recipe and works markedly better.
  * With a PEFT model and `ref_model=None`, TRL uses the adapter-disabled base as
    the frozen reference policy — no second model in memory. That's what makes
    this fit a free 16 GB GPU.
  * β (–-beta) is the KL leash: higher keeps the policy closer to the reference.
    0.1 is the standard starting point.
"""

from __future__ import annotations

import argparse

from prepare_data import TOOLS as SPIDEY_TOOLS
from prepare_dpo_data import build_dpo_dataset


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="DPO fine-tune + GGUF export for Spidey.")
    ap.add_argument("--model", default="unsloth/Qwen2.5-Coder-3B-Instruct",
                    help="Base model (must match stage 1 if --adapter is used).")
    ap.add_argument("--adapter", default=None,
                    help="Path to the stage-1 LoRA checkpoint (finetune.py's output_dir). "
                         "Omit to start from the plain base model.")
    ap.add_argument("--max-seq-len", type=int, default=2048)
    ap.add_argument("--steps", type=int, default=100,
                    help="Training steps for a quick run. Ignored if --epochs > 0.")
    ap.add_argument("--epochs", type=float, default=0.0)
    ap.add_argument("--n-pairs", type=int, default=1500,
                    help="How many synthetic preference pairs to generate.")
    ap.add_argument("--beta", type=float, default=0.1,
                    help="DPO β — strength of the KL constraint to the reference policy.")
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--lr", type=float, default=5e-6,
                    help="DPO wants a much smaller LR than SFT (5e-6 vs 2e-4).")
    ap.add_argument("--out", default="spidey-brain-dpo", help="Export directory.")
    ap.add_argument("--quant", default="q4_k_m")
    return ap.parse_args()


def main() -> None:
    args = parse_args()

    # Imported here so `--help` works without a GPU/unsloth install.
    from unsloth import FastLanguageModel, PatchDPOTrainer
    PatchDPOTrainer()  # must run before DPOTrainer is imported/used
    from trl import DPOConfig, DPOTrainer

    # 1) Load stage-1 checkpoint (or the base) in 4-bit.
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.adapter or args.model,
        max_seq_length=args.max_seq_len,
        load_in_4bit=True,
        dtype=None,
    )
    if args.adapter is None:
        model = FastLanguageModel.get_peft_model(
            model,
            r=args.lora_r,
            lora_alpha=args.lora_r,
            lora_dropout=0,
            bias="none",
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                            "gate_proj", "up_proj", "down_proj"],
            use_gradient_checkpointing="unsloth",
            random_state=3407,
        )

    # 2) Preference pairs, rendered with THIS model's chat template.
    dataset = build_dpo_dataset(tokenizer, n=args.n_pairs)
    print(f"\nPreference pairs: {len(dataset)}. Example:\n{'-' * 60}")
    print("CHOSEN:  ", dataset[0]["chosen"][:200])
    print("REJECTED:", dataset[0]["rejected"][:200])
    print("-" * 60)

    # 3) Train. ref_model=None + PEFT → the adapter-disabled base is the reference.
    cfg_kwargs = dict(
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        warmup_steps=5,
        learning_rate=args.lr,
        logging_steps=5,
        optim="adamw_8bit",
        weight_decay=0.01,
        lr_scheduler_type="linear",
        seed=3407,
        output_dir="outputs-dpo",
        report_to="none",
        beta=args.beta,
        max_length=args.max_seq_len,
        max_prompt_length=args.max_seq_len // 2,
    )
    if args.epochs > 0:
        cfg_kwargs["num_train_epochs"] = args.epochs
    else:
        cfg_kwargs["max_steps"] = args.steps

    trainer = DPOTrainer(
        model=model,
        ref_model=None,
        args=DPOConfig(**cfg_kwargs),
        train_dataset=dataset,
        tokenizer=tokenizer,
    )
    stats = trainer.train()
    print(f"\nDPO done. Final loss ~ {stats.training_loss:.4f}")

    # 4) Sanity check: prefers a clean call over prose?
    FastLanguageModel.for_inference(model)
    print("\n--- sanity generation ---")
    inputs = tokenizer.apply_chat_template(
        [{"role": "user", "content": "Where in the code do we define parse_config?"}],
        tools=SPIDEY_TOOLS, add_generation_prompt=True, return_tensors="pt",
    ).to(model.device)
    out = model.generate(input_ids=inputs, max_new_tokens=128, do_sample=False)
    print(tokenizer.decode(out[0][inputs.shape[1]:], skip_special_tokens=True))
    print("--- end sanity ---")

    # 5) Export: merge + quantize + Ollama Modelfile, same as stage 1.
    model.save_pretrained_gguf(args.out, tokenizer, quantization_method=args.quant)
    print(
        f"\n✅ Exported to ./{args.out}\n\n"
        f"Load it into Ollama and point Spidey at it:\n"
        f"   ollama create spidey-brain -f ./{args.out}/Modelfile\n"
        f'   spidey run "fix the failing test" --model spidey-brain\n\n'
        f"Quantify the gain (base vs SFT vs SFT+DPO):\n"
        f"   python eval/run_eval.py --models qwen2.5-coder:3b,spidey-sft,spidey-brain\n"
    )


if __name__ == "__main__":
    main()
