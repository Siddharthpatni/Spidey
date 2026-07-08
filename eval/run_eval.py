"""Measure tool-selection accuracy: does the model call the *right* tool, with the
*right* arguments, on the first move?

This is the number that makes the fine-tuning worth writing up. It runs each task in
`tasks.jsonl` through one or two Ollama models (Spidey's tool specs attached) and scores:
  * tool match      — did it pick the expected tool?
  * arg match       — do required argument substrings appear? (when a task specifies them)

Usage:
    # Compare any number of models (first one is the baseline for the Δ row):
    python eval/run_eval.py --models qwen2.5-coder:3b,spidey-sft,spidey-brain

    # Legacy two-model form:
    python eval/run_eval.py --base qwen2.5-coder:3b --tuned spidey-brain

    # Score a single model:
    python eval/run_eval.py --single llama3.1:8b

Requires Ollama running locally with the models pulled/created.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

# Import Spidey's real tool specs so the model sees exactly what it sees in production.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from spidey.llm import OllamaBackend  # noqa: E402
from spidey.tools import default_registry  # noqa: E402

TASKS_PATH = pathlib.Path(__file__).resolve().parent / "tasks.jsonl"


def load_tasks():
    with open(TASKS_PATH) as f:
        return [json.loads(line) for line in f if line.strip()]


def score_task(backend, task, specs):
    """Return (tool_ok, arg_ok, called_name)."""
    try:
        reply = backend.chat(
            [{"role": "user", "content": task["prompt"]}], specs
        )
    except Exception as e:
        return False, False, f"<error: {e}>"

    if not reply.tool_calls:
        return False, False, "<no tool call>"

    call = reply.tool_calls[0]
    tool_ok = call["name"] == task["expected_tool"]

    arg_ok = True
    for key, needle in (task.get("must_include") or {}).items():
        val = str(call["arguments"].get(key, ""))
        if needle.lower() not in val.lower():
            arg_ok = False
            break
    return tool_ok, arg_ok, call["name"]


def evaluate(model: str, base_url: str):
    backend = OllamaBackend(model, base_url=base_url, temperature=0.0)
    specs = default_registry().specs()
    tasks = load_tasks()

    tool_hits = arg_hits = 0
    rows = []
    for t in tasks:
        tool_ok, arg_ok, called = score_task(backend, t, specs)
        tool_hits += int(tool_ok)
        arg_hits += int(tool_ok and arg_ok)
        mark = "✓" if tool_ok else "✗"
        rows.append(f"  {mark}  want={t['expected_tool']:<15} got={called:<15} {t['prompt'][:44]}")

    n = len(tasks)
    print(f"\n== {model} ==")
    print("\n".join(rows))
    print(f"  tool-selection: {tool_hits}/{n} ({100*tool_hits/n:.0f}%)   "
          f"tool+args: {arg_hits}/{n} ({100*arg_hits/n:.0f}%)")
    return {"model": model, "n": n, "tool": tool_hits, "arg": arg_hits}


def main():
    ap = argparse.ArgumentParser(description="Tool-selection accuracy eval for Spidey.")
    ap.add_argument("--models",
                    help="Comma-separated model tags; the first is the baseline "
                         "(e.g. qwen2.5-coder:3b,spidey-sft,spidey-brain).")
    ap.add_argument("--base", help="Base model tag (e.g. qwen2.5-coder:3b).")
    ap.add_argument("--tuned", help="Fine-tuned model tag (e.g. spidey-brain).")
    ap.add_argument("--single", help="Score just this one model.")
    ap.add_argument("--base-url", default="http://localhost:11434")
    args = ap.parse_args()

    if args.models:
        models = [m.strip() for m in args.models.split(",") if m.strip()]
    elif args.single:
        models = [args.single]
    elif args.base and args.tuned:
        models = [args.base, args.tuned]
    else:
        raise SystemExit("Pass --models a,b,c  (or --base/--tuned, or --single MODEL).")

    results = []
    try:
        for m in models:
            results.append(evaluate(m, args.base_url))
    except Exception as e:
        raise SystemExit(
            f"\nCould not reach Ollama at {args.base_url} ({e}).\n"
            f"Start Ollama and make sure the models are available "
            f"(`ollama list`), then re-run."
        )

    if len(results) >= 2:
        base, n = results[0], results[0]["n"]
        width = max(22, max(len(r["model"]) for r in results) + 2)
        print("\n" + "=" * (width + 30))
        print(f"{'model':<{width}}{'tool sel.':>14}{'tool+args':>15}")
        print("-" * (width + 30))
        for r in results:
            print(f"{r['model']:<{width}}{r['tool']}/{n} ({100*r['tool']//n:>3}%){'':>3}"
                  f"{r['arg']}/{n} ({100*r['arg']//n:>3}%)")
        print("=" * (width + 30))
        for r in results[1:]:
            delta = (r["tool"] - base["tool"]) * 100 // n
            print(f"Δ tool-selection vs {base['model']}: {delta:+d} pp  ({r['model']})")
        print()


if __name__ == "__main__":
    main()
