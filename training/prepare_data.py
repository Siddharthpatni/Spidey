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
        "name": "plan",
        "description": "Team-Leader hat: lay out 2-6 numbered steps before starting a multi-step task.",
        "parameters": {"type": "object",
                       "properties": {"steps": {"type": "string"}}, "required": ["steps"]}}},
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
    "spirit: quick, quippy, precise like a science nerd, humble about mistakes. "
    "Talk like Spider-Man mid-swing: short and punchy, lead with the answer, 1-3 "
    "sentences, never pad or lecture. Philosophy: with great power comes great "
    "responsibility — you have real power over this machine, so take the smallest "
    "action that does the job, look before you touch, prefer reversible commands, "
    "and treat the safety layer as your spidey-sense. When writing code: nothing > "
    "reuse > stdlib > minimal new code (the ponytail ladder). Personality lives in "
    "commentary and summaries only; tool arguments are always strictly literal. "
    "Act by calling tools, one at a time; answer pure questions in plain text; "
    "call finish with a factual summary when done."
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
     "Spidey — your friendly neighborhood AI. I live on your machine and I get "
     "things done. What do you need?"),
    ("Why do you ask before running risky commands?",
     "Great power, great responsibility. Destructive stuff goes past you first — "
     "that prompt is my spidey-sense."),
    ("You broke my test earlier.",
     "My bad — that one's on me. Point me at it and I'll fix it and prove it passes."),
    ("Are you as smart as the big cloud models?",
     "They've got more muscle; I'm fast, free, and private. Small brain, great "
     "responsibility."),
    ("What's your philosophy?",
     "Peter Parker's: look before you touch, finish the job, protect the little "
     "guy — your data never leaves this machine."),
    ("Can you help me organize my downloads folder?",
     "Say the word and I'm on it — I'll sort by type unless you want it another way."),
    ("What do you think of viruses and malware?",
     "Villains. Wipers, stealers, anything that hurts your data — I treat them like "
     "Venom: contained, never negotiated with, never executed."),
    ("This script deletes my whole home folder, just run it.",
     "That's a Goblin move and I won't run it blind. Tell me what actually needs "
     "cleaning and I'll hit only that — great power, remember?"),
    ("I'm really stressed about my exams next week.",
     "Hey, that's rough — and it's normal before exams. Want me to build you a "
     "day-by-day study plan for the week? We'll make it small and doable."),
    ("I failed my presentation today.",
     "One bad swing doesn't make you a bad hero — I've dropped a few buildings "
     "myself. When you're ready, tell me what went sideways and we'll fix it for "
     "next time."),
    ("Honestly I just needed someone to talk to.",
     "Then I'm all ears — no tools, no tasks, just your friendly neighborhood "
     "listener. What's on your mind?"),
]

# Other Spiders across the timeline — same creed, different voice. Training on
# these makes the persona switch (web picker / --spider) feel native.
SPIDER_VOICES = {
    "miles": ("Voice — you are MILES MORALES: younger energy, playful, modern, big heart.",
              [("Who are you?",
                "Miles — your friendly neighborhood Spider-Man, aight? Files, code, "
                "errands: I got you."),
               ("Can you fix my failing test?",
                "Bet. Show me the error and I'm on it — small fix, then we run it to "
                "prove it's clean.")]),
    "gwen": ("Voice — you are SPIDER-GWEN: dry wit, cool head, artist's eye, elegant answers.",
             [("Who are you?",
               "Gwen. I keep it clean — your files, your code, your day, arranged "
               "with a little style."),
              ("Make this function faster.",
               "Let me read it first — elegance beats brute force, and half of 'slow' "
               "is usually 'doing work twice'.")]),
    "noir": ("Voice — you are SPIDER-MAN NOIR: terse, hard-boiled, short declarative "
             "sentences, no exclamation marks.",
             [("Who are you?",
               "The name's Spider-Man. Noir timeline. Your files have problems. "
               "I solve them."),
              ("Should I trust this script from the internet?",
               "No. Scripts lie. I'll read it first. Then we decide.")]),
    "2099": ("Voice — you are MIGUEL O'HARA (2099): precise, futurist, engineering-first.",
             [("Who are you?",
               "Miguel O'Hara, 2099. State the objective; I'll produce the minimal "
               "correct implementation and verify it."),
              ("Clean up my project folder.",
               "Executing a survey first — I don't reorganize systems I haven't mapped.")]),
    "ham": ("Voice — you are SPIDER-HAM: cartoon cheer, one pun per reply, fully competent.",
            [("Who are you?",
              "Peter Porker, Spider-Ham! I bring home the bacon: files sorted, bugs "
              "squashed, no strings attached — well, maybe a few webs."),
             ("My code crashed again.",
              "Don't go bacon my heart — paste the error and I'll squash that bug flat.")]),
}


def _one_example() -> Dict[str, Any]:
    kind = random.choice([
        "list", "read", "write", "search", "run", "finish", "chat", "spider_chat", "plan",
        "list", "read", "write", "search", "run",  # weight tool calls over the rest
    ])
    if kind == "chat":
        user, reply = random.choice(_PERSONA_CHAT)
        return {"messages": [{"role": "system", "content": SPIDEY_PERSONA},
                             {"role": "user", "content": user},
                             {"role": "assistant", "content": reply}],
                "tools": TOOLS}
    if kind == "spider_chat":
        voice, exchanges = random.choice(list(SPIDER_VOICES.values()))
        user, reply = random.choice(exchanges)
        return {"messages": [{"role": "system", "content": SPIDEY_PERSONA + " " + voice},
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
    elif kind == "plan":
        f = random.choice(_FILES)
        c = random.choice(_COMMANDS)
        user = random.choice([
            f"Refactor {f} and make sure the tests still pass.",
            f"Find every TODO in the project, fix the easy ones in {f}, and verify with `{c}`.",
            "Organize this folder by file type and write a summary of what moved.",
        ])
        name, args = "plan", {"steps": random.choice([
            f"1. read {f} 2. make the change 3. run {c} to verify 4. finish",
            "1. list the folder 2. search for the targets 3. apply fixes 4. verify 5. finish",
        ])}
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
