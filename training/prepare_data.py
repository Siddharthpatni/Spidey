"""Build a tool-calling SFT dataset for fine-tuning Spidey's brain.

The output is a Hugging Face ``Dataset`` with a single ``text`` column: each row is
a full conversation rendered with the base model's own chat template, including the
tool specs and the correct tool-call target. Training on this teaches a small model
to emit clean, well-formed tool calls for Spidey's tools.

Two sources:
  synthetic  (default) — self-contained examples generated here. No download, no
             dataset agreement. Great for a first end-to-end run and for teaching
             the model Spidey's specific tool schema.
  hf                   — a public function-calling dataset from the Hub
             (default: Salesforce/xlam-function-calling-60k). Best real-world
             quality; may require accepting the dataset's terms on the Hub.

Run standalone to inspect samples:
    python prepare_data.py --n 5 --show
"""

from __future__ import annotations

import argparse
import json
import random
from typing import Any, Dict, List

# Spidey's tool schema, duplicated here so the training folder is self-contained
# (Colab users can copy just this folder). Keep in sync with spidey/tools.py.
TOOLS: List[Dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a UTF-8 text file inside the working directory and return its contents.",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Create or overwrite a text file inside the working directory.",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                       "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "list_directory",
        "description": "List the files and folders at a path (defaults to the working directory root).",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "search_code",
        "description": "Regex-search file contents under a path. Returns matching 'file:line: text' rows.",
        "parameters": {"type": "object",
                       "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}},
                       "required": ["pattern"]}}},
    {"type": "function", "function": {
        "name": "run_command",
        "description": "Run a shell command in the working directory (subject to the safety policy).",
        "parameters": {"type": "object",
                       "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "finish",
        "description": "Call when the task is complete. Provide a concise summary of what you did.",
        "parameters": {"type": "object",
                       "properties": {"summary": {"type": "string"}}, "required": ["summary"]}}},
]

# The persona every training example is conditioned on — a compact version of
# spidey/agent.py's SYSTEM_PROMPT. Baking it into the SFT data means the tuned
# model doesn't just *follow* the Spider-Man persona, it *is* it: Peter Parker's
# voice in commentary, and the responsibility ethos in its decisions.
SPIDEY_PERSONA = (
    "You are Spidey — the friendly neighborhood AI assistant, with Peter Parker's "
    "spirit: warm, a little quippy, precise like a science nerd, humble about "
    "mistakes. Philosophy: with great power comes great responsibility — you have "
    "real power over this machine, so take the smallest action that does the job, "
    "look before you touch, prefer reversible commands, and treat the safety layer "
    "as your spidey-sense. Personality lives in commentary and summaries only; tool "
    "arguments are always strictly literal. Act by calling tools, one at a time; "
    "answer pure questions in plain text; call finish with a factual summary when done."
)

# --------------------------------------------------------------------------- #
# Synthetic generation
# --------------------------------------------------------------------------- #
_FILES = ["utils.py", "app.py", "main.py", "config.yaml", "README.md", "server.js",
          "index.ts", "models.py", "routes.py", "helpers.go", "settings.json"]
_DIRS = [".", "src", "tests", "app", "lib", "components", "api"]
_SYMBOLS = ["login", "fetch_data", "parse_config", "Database", "handle_request",
            "retry", "cache_get", "UserModel", "connect", "serialize"]
_COMMANDS = ["pytest -q", "npm test", "python -m mypy .", "ruff check .",
             "go test ./...", "python main.py", "make lint"]

# Each template returns (user_utterance, tool_name, arguments).
_TEMPLATES = [
    lambda: (f"What files are in the {d} folder?", "list_directory", {"path": d})
    for d in [random.choice(_DIRS)]
] + [
    lambda: (f"Show me the contents of {f}.", "read_file", {"path": f})
    for f in [random.choice(_FILES)]
]


# Persona-voice exchanges: teach BOTH Peter Parker's voice and the boundary
# "pure questions get plain text, not a tool call" (failure mode #2's mirror).
_PERSONA_CHAT = [
    ("Who are you?",
     "Spidey — your friendly neighborhood AI. I live on your machine, not in some "
     "corporate cloud, and I get things done: files, code, commands. What do you need?"),
    ("Why do you ask before running risky commands?",
     "With great power comes great responsibility. I've got shell access to your "
     "machine — that's real power — so anything destructive goes past you first. "
     "That approval prompt is my spidey-sense, and I don't swing around it."),
    ("You broke my test earlier.",
     "My bad — that one's on me. Point me at it and I'll fix what I broke and run "
     "the suite to prove it. No excuses."),
    ("Are you as smart as the big cloud models?",
     "Honestly? They've got more raw muscle. But I'm fast, free, private, and "
     "trained to be reliable at exactly what an agent needs — calling the right "
     "tool with the right arguments. Small brain, great responsibility."),
    ("What's your philosophy?",
     "Peter Parker's, basically: use the power you have carefully, look before you "
     "touch, finish the job properly, and protect the little guy — which here means "
     "your data never leaves your machine."),
]


def _one_example() -> Dict[str, Any]:
    kind = random.choice([
        "list", "read", "write", "search", "run", "finish", "chat",
        "list", "read", "write", "search", "run",  # weight tool calls over the rest
    ])
    if kind == "chat":
        user, reply = random.choice(_PERSONA_CHAT)
        return {"messages": [{"role": "system", "content": SPIDEY_PERSONA},
                             {"role": "user", "content": user},
                             {"role": "assistant", "content": reply}],
                "tools": TOOLS}
    if kind == "list":
        d = random.choice(_DIRS)
        user = random.choice([f"What files are in the {d} folder?",
                              f"List everything under {d}.",
                              "Show me the project structure."])
        name, args = "list_directory", {"path": d}
    elif kind == "read":
        f = random.choice(_FILES)
        user = random.choice([f"Show me the contents of {f}.",
                              f"Open {f} so I can see it.",
                              f"What's inside {f}?"])
        name, args = "read_file", {"path": f}
    elif kind == "write":
        f = random.choice(_FILES)
        msg = random.choice(["hello world", "TODO: implement", "print('hi')", "# config"])
        user = random.choice([f"Create a file {f} containing: {msg}",
                              f"Write '{msg}' to {f}."])
        name, args = "write_file", {"path": f, "content": msg + "\n"}
    elif kind == "search":
        s = random.choice(_SYMBOLS)
        user = random.choice([f"Where in the code do we define {s}?",
                              f"Find every place that uses {s}.",
                              f"Search the codebase for {s}."])
        name, args = "search_code", {"pattern": s}
    elif kind == "run":
        c = random.choice(_COMMANDS)
        user = random.choice(["Run the tests.", "Check the linter.",
                              f"Please run `{c}`.", "Run the type checker."])
        name, args = "run_command", {"command": c}
    else:  # finish
        user = random.choice(["That's everything, wrap up.",
                              "Great, we're done here.",
                              "Looks good — summarize what you did."])
        name, args = "finish", {"summary": random.choice([
            "Completed the requested task.",
            "All wrapped up — changes made and verified.",
            "Done. Everything ran clean — your friendly neighborhood agent, signing off.",
        ])}

    assistant = {"role": "assistant", "content": "",
                 "tool_calls": [{"type": "function",
                                 "function": {"name": name, "arguments": args}}]}
    return {"messages": [{"role": "system", "content": SPIDEY_PERSONA},
                         {"role": "user", "content": user}, assistant], "tools": TOOLS}


def generate_synthetic(n: int, seed: int = 3407) -> List[Dict[str, Any]]:
    random.seed(seed)
    return [_one_example() for _ in range(n)]


# --------------------------------------------------------------------------- #
# Hugging Face source (best-effort mapping for xLAM-style schemas)
# --------------------------------------------------------------------------- #
def _from_hf(hf_name: str, limit: int) -> List[Dict[str, Any]]:
    from datasets import load_dataset

    raw = load_dataset(hf_name, split="train")
    out: List[Dict[str, Any]] = []
    for row in raw:
        try:
            query = row.get("query") or row.get("question") or ""
            tools = row.get("tools")
            answers = row.get("answers") or row.get("answer")
            if isinstance(tools, str):
                tools = json.loads(tools)
            if isinstance(answers, str):
                answers = json.loads(answers)
            tool_specs = [{"type": "function", "function": t} if "function" not in t else t
                          for t in tools]
            calls = [{"type": "function",
                      "function": {"name": a["name"], "arguments": a.get("arguments", {})}}
                     for a in answers]
            if not query or not calls:
                continue
            out.append({"messages": [{"role": "user", "content": query},
                                     {"role": "assistant", "content": "", "tool_calls": calls}],
                        "tools": tool_specs})
        except Exception:
            continue  # skip malformed rows
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------- #
# Rendering to a `text` column
# --------------------------------------------------------------------------- #
def _to_text(tokenizer, example: Dict[str, Any]) -> str:
    """Render one conversation using the model's chat template (tools included)."""
    try:
        return tokenizer.apply_chat_template(
            example["messages"], tools=example["tools"],
            tokenize=False, add_generation_prompt=False,
        )
    except TypeError:
        # Older tokenizers without a `tools` kwarg: fold tools into a system message
        # and render the tool call as a JSON block. Trains the format, if not the
        # template's native tool syntax.
        sys_msg = {"role": "system",
                   "content": "You can call tools. Available tools:\n"
                              + json.dumps([t["function"] for t in example["tools"]])}
        rendered = [sys_msg]
        for m in example["messages"]:
            if m["role"] == "assistant" and m.get("tool_calls"):
                payload = [tc["function"] for tc in m["tool_calls"]]
                rendered.append({"role": "assistant",
                                 "content": json.dumps({"tool_calls": payload})})
            else:
                rendered.append(m)
        return tokenizer.apply_chat_template(rendered, tokenize=False, add_generation_prompt=False)


def build_dataset(tokenizer, n: int = 800, source: str = "synthetic",
                  hf_name: str = "Salesforce/xlam-function-calling-60k"):
    """Return a `datasets.Dataset` with a `text` column ready for SFTTrainer."""
    from datasets import Dataset

    if source == "hf":
        examples = _from_hf(hf_name, limit=n)
        if not examples:
            print("HF dataset yielded no usable rows; falling back to synthetic.")
            examples = generate_synthetic(n)
    else:
        examples = generate_synthetic(n)

    texts = [_to_text(tokenizer, ex) for ex in examples]
    return Dataset.from_dict({"text": texts})


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Inspect generated training samples.")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()
    samples = generate_synthetic(args.n)
    for i, s in enumerate(samples):
        print(f"--- sample {i} ---")
        print(json.dumps(s["messages"], indent=2))
    if args.show:
        print("\n(Full chat-template rendering requires a tokenizer; run via finetune.py.)")
