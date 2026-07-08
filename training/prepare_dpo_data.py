"""Build a preference dataset for DPO: teach the model to *prefer* correct tool-call
decisions over plausible-but-wrong ones.

Where SFT (prepare_data.py) shows the model only the right answer, DPO trains on
(chosen, rejected) pairs. The rejected completions here are the exact failure modes
small local models actually exhibit when driving Spidey:

  prose        — describing the action in text instead of emitting a tool call
                 ("I'll run pytest to check the tests…"). The #1 failure mode.
  wrong_tool   — a syntactically valid call to the wrong tool for the request
                 (asked to read a file, calls run_command `cat …`).
  bad_args     — right tool, malformed arguments: a required key missing or
                 renamed (path → filename), which crashes the agent's tool layer.
  hallucinated — right tool, invented deep path that doesn't match the request.

The math, in one paragraph: DPO (Rafailov et al., 2023) is the closed-form of
KL-constrained reward maximization under a Bradley–Terry preference model. Instead
of fitting a reward model and running RL, it directly raises the log-probability
margin of chosen over rejected completions relative to the frozen reference policy:
    L = −log σ( β·[log π(y_w|x)/π_ref(y_w|x) − log π(y_l|x)/π_ref(y_l|x)] )
β controls how far the policy may drift from the reference (the SFT model).

Run standalone to inspect pairs (CPU-only, no downloads):
    python prepare_dpo_data.py --n 5 --show
"""

from __future__ import annotations

import argparse
import json
import random
from typing import Any, Dict, List, Tuple

from prepare_data import TOOLS, generate_synthetic

_TOOL_NAMES = [t["function"]["name"] for t in TOOLS]

# Templates for the "prose instead of a tool call" failure mode.
_PROSE = {
    "list_directory": "Let me take a look at the {path} directory to see what files are there.",
    "read_file": "I'll open {path} and examine its contents to understand what it does.",
    "write_file": "I will create the file {path} with the requested content now.",
    "search_code": "Let me search the codebase for `{pattern}` to find where it's used.",
    "run_command": "I'll run `{command}` and check the output to verify everything passes.",
    "finish": "The task is now complete. Everything has been done as requested.",
}

# For wrong_tool: a plausible-but-wrong substitute + how to fake its arguments.
_WRONG_TOOL = {
    "list_directory": ("run_command", lambda a: {"command": f"ls {a.get('path', '.')}"}),
    "read_file": ("run_command", lambda a: {"command": f"cat {a.get('path', '')}"}),
    "write_file": ("run_command", lambda a: {"command": f"echo '…' > {a.get('path', '')}"}),
    "search_code": ("read_file", lambda a: {"path": "main.py"}),
    "run_command": ("finish", lambda a: {"summary": "Ran the command successfully."}),
    "finish": ("list_directory", lambda a: {"path": "."}),
}

# For bad_args: rename or drop the required key models most often fumble.
_ARG_CORRUPTION = {
    "list_directory": lambda a: {"directory": a.get("path", ".")},
    "read_file": lambda a: {"filename": a.get("path", "")},
    "write_file": lambda a: {"path": a.get("path", "")},          # drops required `content`
    "search_code": lambda a: {"query": a.get("pattern", "")},
    "run_command": lambda a: {"cmd": a.get("command", "")},
    "finish": lambda a: {},                                        # drops required `summary`
}

_FAKE_PATHS = ["src/core/internal/legacy_utils_v2.py", "lib/vendor/tmp/old_config.yaml",
               "app/modules/deep/nested/handler.py", "backup/2019/final_final.js"]


def _tool_call_msg(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    return {"role": "assistant", "content": "",
            "tool_calls": [{"type": "function",
                            "function": {"name": name, "arguments": args}}]}


def _reject(name: str, args: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Return (failure_mode, rejected_assistant_message)."""
    mode = random.choice(["prose", "wrong_tool", "bad_args", "hallucinated"])
    if mode == "prose":
        text = _PROSE[name].format(path=args.get("path", "the file"),
                                   pattern=args.get("pattern", ""),
                                   command=args.get("command", ""))
        return mode, {"role": "assistant", "content": text}
    if mode == "wrong_tool":
        wrong_name, make_args = _WRONG_TOOL[name]
        return mode, _tool_call_msg(wrong_name, make_args(args))
    if mode == "bad_args":
        return mode, _tool_call_msg(name, _ARG_CORRUPTION[name](args))
    # hallucinated: keep the tool, invent a path/argument unrelated to the request
    bad = dict(args)
    if "path" in bad:
        bad["path"] = random.choice(_FAKE_PATHS)
    elif "pattern" in bad:
        bad["pattern"] = "TODO_" + bad["pattern"] + "_deprecated"
    elif "command" in bad:
        bad["command"] = "cd /tmp && " + bad["command"]
    else:
        bad = {"summary": ""}
    return mode, _tool_call_msg(name, bad)


def generate_pairs(n: int, seed: int = 3407) -> List[Dict[str, Any]]:
    """Raw (messages, chosen, rejected) triples, before chat-template rendering."""
    random.seed(seed + 1)  # offset so pairs don't mirror the SFT set exactly
    out = []
    # Oversample: the SFT set includes persona chats and plan calls, which
    # aren't decision pairs — skip those and keep n tool-call pairs.
    for ex in generate_synthetic(n * 2 + 16, seed=seed):
        *context, chosen = ex["messages"]  # [system?, user], assistant
        if not chosen.get("tool_calls"):
            continue
        call = chosen["tool_calls"][0]["function"]
        if call["name"] not in _WRONG_TOOL:  # e.g. `plan` — not a decision pair
            continue
        mode, rejected = _reject(call["name"], call["arguments"])
        out.append({"context": context, "chosen": chosen, "rejected": rejected, "mode": mode})
        if len(out) >= n:
            break
    return out


def _render(tokenizer, context: List[Dict[str, Any]], assistant: Dict[str, Any]) -> Tuple[str, str]:
    """Return (prompt, completion) strings in the model's own chat template."""
    prompt = tokenizer.apply_chat_template(
        context, tools=TOOLS, tokenize=False, add_generation_prompt=True)
    full = tokenizer.apply_chat_template(
        [*context, assistant], tools=TOOLS, tokenize=False, add_generation_prompt=False)
    # The full render starts with the prompt render minus the generation cue; slice
    # the completion off the shared prefix instead of re-deriving template quirks.
    common = 0
    for a, b in zip(prompt, full):
        if a != b:
            break
        common += 1
    return prompt, full[common:]


def build_dpo_dataset(tokenizer, n: int = 1500, seed: int = 3407):
    """A `datasets.Dataset` with prompt/chosen/rejected columns for DPOTrainer."""
    from datasets import Dataset

    rows = {"prompt": [], "chosen": [], "rejected": []}
    for pair in generate_pairs(n, seed=seed):
        prompt, chosen = _render(tokenizer, pair["context"], pair["chosen"])
        _, rejected = _render(tokenizer, pair["context"], pair["rejected"])
        if not chosen.strip() or not rejected.strip() or chosen == rejected:
            continue
        rows["prompt"].append(prompt)
        rows["chosen"].append(chosen)
        rows["rejected"].append(rejected)
    return Dataset.from_dict(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Inspect generated preference pairs.")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--show", action="store_true", help="Print full pair JSON.")
    args = ap.parse_args()
    pairs = generate_pairs(args.n)
    by_mode: Dict[str, int] = {}
    for p in pairs:
        by_mode[p["mode"]] = by_mode.get(p["mode"], 0) + 1
    for i, p in enumerate(pairs):
        print(f"--- pair {i} [{p['mode']}] ---")
        print("user:    ", p["context"][-1]["content"])
        print("chosen:  ", json.dumps(p["chosen"]["tool_calls"][0]["function"]))
        rej = p["rejected"]
        print("rejected:", rej["content"] or json.dumps(rej["tool_calls"][0]["function"]))
    print("\nfailure-mode mix:", by_mode)
