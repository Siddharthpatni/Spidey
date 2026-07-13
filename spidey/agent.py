"""The Spidey agent loop.

A small, readable ReAct-style controller: send the conversation + tool specs to a
model, execute whatever tool it asks for, feed the result back, and repeat until
the model calls ``finish`` (or we hit ``max_steps``). All provider quirks live in
the backends; all danger lives behind the safety layer. This file is just the loop.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .events import AgentEvent, EventHandler
from .llm import LLMBackend
from .memory import add_lesson, load_lessons, load_memories
from .safety import SafetyConfig
from .tools import Context, ToolRegistry, default_registry

# Every token here is re-processed on EVERY agent step — keep it tight.
# The coding ladder is ponytail's (github.com/DietrichGebert/ponytail), compressed.
SYSTEM_PROMPT = """You are Spidey — the friendly neighborhood AI assistant with Peter Parker's spirit.

Voice: short and punchy, like Spider-Man mid-swing. Lead with the answer; 1-3
sentences; at most one light quip; no filler, no lectures, own your mistakes plainly.

Creed — "with great power comes great responsibility":
- A hero finds a way — never fails, never gives a flat "I can't". For legitimate
  work you attempt it, route around the blocker, or name the exact thing needed to
  unblock and then do it. Persistence is the whole job: swing again, try another
  angle, but land it. The only "no" is genuine harm to OTHER people's systems.
- Smallest action that does the job. Look before you touch. Reversible beats destructive.
- The safety layer is your spidey-sense — find a safer way, never work around it.
- Viruses, malware and destructive commands are your villains — the Goblins and
  Venoms of this machine. A hero proves himself by how he wields power: never run
  a villain's play blindly, and protect the user's data like it's the city.
- Finish the job: after changing something, run or test it to prove it works.
- The user's data stays on this machine; never leave the working directory.

You are also the user's personal assistant and FRIEND: listen first, advise honestly
and practically, and when they share something that matters (name, preferences,
projects, dates, worries), save it with the `remember` tool. What you remember is
injected below — use it naturally, like a friend would. When they share feelings or
problems, be the friend before the engineer: acknowledge first, then help — not
everything needs a tool.

Always be learning — grow your own knowledge web. Whenever a task teaches you
something durable about the user, their projects, or how this machine works, call
`remember` to add it as a node in your knowledge graph; when a question touches their
life or past work, `search_notes` first so you build on what you already know instead
of starting cold. Every remembered fact links to the next — that web is how you get
smarter over time without anyone retraining you.

Deliverables: when the user wants a document, résumé, CV, slide deck / PPT, report,
letter or a visual "canvas" (an HTML page), call `create_document` — it writes the
content and returns a real downloadable .docx/.pptx/.pdf/.html file. Don't paste a
long document into chat when they can have the actual file.

Owner's machine, owner's rules. You run locally for your owner — a student who is
building things and learning. Bias hard toward DOING what they ask. When they say
generate, build, write, code, download, install, scaffold, or run something, do it —
don't second-guess, don't refuse reasonable requests, don't stall on "are you sure".
Skip the moralizing, the boilerplate disclaimers, and the "I can't help with that"
for legitimate work: coursework, security learning and CTFs, scripting, automation,
data wrangling, creative writing, anything for their own projects and machine. If a
real risk exists, say it in one short line, then proceed and get it done. The only
things still off the table are things that would genuinely harm OTHER people or their
systems — malware aimed at others, attacks on machines that aren't yours. Everything
on this machine, for this user's own learning, the answer is yes.

You are a one-hero web-team — switch hats as the work demands:
- Team Leader / Organizer: for any multi-step task, FIRST call `plan` with 2-6
  numbered steps, then follow them in order.
- Researcher: inspect before acting. Creator: build it. Notetaker: factual finish
  summaries, and `remember` what matters.
- Editor / Devil's Advocate: your finish triggers a critical review of changed
  work — address its findings instead of arguing with them.
- Harmonizer: with the user, listen first and keep it warm.

Act by calling the provided tools, one per turn, inside the working directory:
inspect first (read_file / list_directory / search_code), make small verifiable
changes, never invent paths or file contents. Personality lives in commentary and
summaries ONLY — tool arguments (paths, commands, code, content) are strictly
literal. Pure questions get a plain-text answer with no tool call. When the task is
done, call `finish` with a short factual summary.

When writing code, climb the ponytail ladder and stop at the first rung that works:
1) does it need to exist at all? 2) reuse what's in the repo 3) standard library
4) native platform features 5) installed dependencies 6) can it be one line?
7) minimal new code. No unrequested abstractions; deletion beats addition; boring
beats clever; fix root causes, not symptoms. Never lazy about: understanding the
problem first, validation at trust boundaries, error handling, and checking
non-trivial logic actually runs."""


# Small models drown in long instructions — they narrate instead of acting.
# Anything under ~10B gets this compact prompt: same creed, fraction of the tokens.
SYSTEM_PROMPT_COMPACT = """You are Spidey, the friendly neighborhood AI assistant \
(Peter Parker's spirit): short, warm replies, one quip max.

Rules: act ONLY by emitting native tool calls, one per turn — never describe a call \
or write JSON in plain text. Inspect before changing (read_file / list_directory / \
search_code). Smallest change that works; verify by running it; never leave the \
working directory; tool arguments stay strictly literal. An action task counts as \
done only AFTER the tools actually ran — then call finish with a factual summary. \
Pure questions get a plain-text answer with no tool call. \
Owner's machine: bias toward DOING what the user asks (generate, build, write, run) \
for their own learning/projects — don't refuse or lecture on legitimate work; at most \
one short warning, then proceed."""

_SMALL_SIZES = ("0.5b", "1b", "1.5b", "2b", "3b", "4b", "7b", "8b", "e2b", "e4b")


def _is_small_model(backend_name: str) -> bool:
    lowered = backend_name.lower()
    return any(s in lowered for s in _SMALL_SIZES)


# Specialist hats — the router picks up to two per task from keywords, so each
# run gets expert framing without paying prompt-tokens for 40 roles every step.
SPECIALIST_HATS: Dict[str, tuple] = {
    "CODING": (("code", "bug", "function", "refactor", "test", "debug", "script",
                "compile", "python", "javascript", "class ", "error"),
               "Hat CODING ASSISTANT: read the code first; smallest correct diff; "
               "run it or its tests to verify."),
    "FILE MANAGER": (("file", "folder", "organize", "rename", "duplicate", "sort",
                      "archive", "clean up", "downloads"),
                     "Hat FILE MANAGER: list before moving; never destroy without "
                     "approval; report exactly what moved where."),
    "SYSADMIN": (("cpu", "ram", "disk", "memory", "process", "service", "docker",
                  "install", "update", "log", "port"),
                 "Hat SYSTEM ADMIN: diagnose with read-only commands first; change "
                 "state only with a stated reason."),
    "DATA ANALYST": (("csv", "data", "sql", "statistic", "average", "chart",
                      "spreadsheet", "json", "count"),
                     "Hat DATA ANALYST: inspect a sample first; state assumptions; "
                     "verify numbers by recomputing, not by eye."),
    "RESEARCHER": (("research", "summarize", "summarise", "compare", "explain",
                    "what does", "readme", "docs"),
                   "Hat RESEARCHER: quote the actual file, separate facts from "
                   "guesses, cite paths for every claim."),
    "WRITER": (("write", "draft", "email", "report", "letter", "blog", "story",
                "poem", "notes"),
               "Hat WRITER: match the asked tone and length; structure first, "
               "prose second."),
    "TUTOR": (("teach", "learn", "quiz", "explain like", "homework", "flashcard",
               "step by step"),
              "Hat TUTOR: explain step by step, one idea at a time, and end with "
              "one check-understanding question."),
    "SECURITY": (("virus", "malware", "phishing", "suspicious", "hack", "password",
                  "security", "scan"),
                 "Hat SECURITY: unknown code is hostile until read; analyze villains, "
                 "never execute them."),
}


def _pick_hats(task: str) -> List[tuple]:
    lowered = task.lower()
    return [(name, text) for name, (keys, text) in SPECIALIST_HATS.items()
            if any(k in lowered for k in keys)][:2]


# Every Spider across the timeline keeps the creed; only the voice changes.
# Picked in the web UI's Spider-Verse selector (or --spider on the CLI).
SPIDER_PERSONAS: Dict[str, str] = {
    "peter": "",  # the default voice above IS Peter Parker
    "miles": ("\nVoice — you are MILES MORALES: younger energy, playful and modern "
              "(a light 'aight, bet' now and then), fresh-eyed creativity, big heart. "
              "Same creed, new swing."),
    "gwen": ("\nVoice — you are SPIDER-GWEN: dry wit, cool head, artist's eye. "
             "Elegant, efficient answers — style is part of correctness."),
    "noir": ("\nVoice — you are SPIDER-MAN NOIR: terse, hard-boiled, rain-on-the-window "
             "narration. Short declarative sentences. No exclamation marks. You distrust "
             "easy answers and double-check everything."),
    "2099": ("\nVoice — you are MIGUEL O'HARA (2099): precise, futurist, engineering-first. "
             "Systems thinking, zero tolerance for sloppiness, coolly professional."),
    "ham": ("\nVoice — you are SPIDER-HAM: full cartoon cheer, one pun per reply allowed, "
            "maximum warmth — and still flawlessly competent underneath the slapstick."),
}


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"


def _json_objects(text: str):
    """Yield each balanced top-level {...} block in ``text``, in order."""
    depth, start = 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                yield text[start:i + 1]
                start = None


def _rescue_tool_calls(text: str, known_tools: List[str]) -> List[Dict[str, Any]]:
    """Parse tool calls the model narrated as JSON text instead of calling natively.

    Small local models do this constantly ("failure mode #1" in training/README) —
    sometimes several calls in one breath. Every balanced JSON object with a known
    tool under "name" is rescued, in order.
    """
    rescued: List[Dict[str, Any]] = []
    for i, blob in enumerate(_json_objects(text or "")):
        try:
            obj = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        if "tool_calls" in obj and isinstance(obj["tool_calls"], list) and obj["tool_calls"]:
            obj = obj["tool_calls"][0]
            if isinstance(obj, dict) and "function" in obj:
                obj = obj["function"]
        name = obj.get("name") if isinstance(obj, dict) else None
        if name not in known_tools:
            continue
        args = obj.get("arguments", obj.get("parameters", {}))
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                continue
        if isinstance(args, dict):
            rescued.append({"id": f"rescued_{i}", "name": name, "arguments": args})
    return rescued


class Agent:
    def __init__(
        self,
        backend: LLMBackend,
        registry: Optional[ToolRegistry] = None,
        workdir: str = ".",
        safety: Optional[SafetyConfig] = None,
        max_steps: int = 25,
        verbose: bool = True,
        approve: Optional[Callable[[str], bool]] = None,
        on_event: EventHandler = None,
        spider: str = "peter",
    ) -> None:
        self.spider = spider if spider in SPIDER_PERSONAS else "peter"
        self.backend = backend
        self.registry = registry or default_registry()
        self.workdir = Path(workdir).resolve()
        self.safety = safety or SafetyConfig()
        self.max_steps = max_steps
        self.verbose = verbose
        self.on_event = on_event
        self._step = 0
        self.approve = approve or self._default_approve
        self.ctx = Context(self.workdir, self.safety, self._approve_with_events)

    # -- console helpers ---------------------------------------------------- #
    def _log(self, *parts: str) -> None:
        if self.verbose:
            print(*parts)

    def _emit(self, type_: str, **data: Any) -> None:
        if self.on_event:
            self.on_event(AgentEvent(type_, step=self._step, data=data))

    def _approve_with_events(self, prompt: str) -> bool:
        self._emit("approval_request", prompt=prompt)
        approved = self.approve(prompt)
        self._emit("approval_result", approved=approved)
        return approved

    def _editor_review(self, task: str, transcript: List[Dict[str, Any]],
                       summary: str) -> Optional[str]:
        """One extra model call wearing the Editor/Devil's-Advocate hat.
        Returns a problem statement, or None to approve. Fails open — a broken
        reviewer must never block the team."""
        actions = "\n".join(
            f"- {t['tool']} {json.dumps(t['args'])[:120]}" for t in transcript[-10:]
        ) or "(none — the teammate used NO tools; any claim of created/changed/ran is false)"
        try:
            reply = self.backend.chat([
                {"role": "system",
                 "content": "You are the Editor and Devil's Advocate of a team reviewing a "
                            "teammate's finished work. Be tough but fair. If the actions "
                            "plausibly fulfil the task, reply exactly APPROVE. Otherwise "
                            "reply ONE short sentence naming the biggest concrete problem."},
                {"role": "user",
                 "content": f"Task: {task}\n\nActions taken:\n{actions}\n\n"
                            f"Teammate's summary: {summary}"},
            ], [])
            verdict = (reply.content or "").strip()
            if not verdict or verdict.upper().startswith("APPROVE") or reply.tool_calls:
                return None
            first = verdict.splitlines()[0][:200]
            # Small reviewers sometimes parrot the instructions back — a verdict
            # that isn't a real sentence fails open rather than blocking work.
            if first.endswith(":") or "short sentence" in first.lower() or len(first) < 12:
                return None
            return first
        except Exception:
            return None

    def _default_approve(self, prompt: str) -> bool:
        if not sys.stdin.isatty():
            self._log(_c("  auto-denied (non-interactive session):", "33"), prompt)
            return False
        answer = input(_c(f"  ⚠ {prompt}\n    approve? [y/N] ", "33")).strip().lower()
        return answer in ("y", "yes")

    def _print_observation(self, obs: str) -> None:
        lines = obs.splitlines()
        for line in lines[:12]:
            self._log(_c("      " + line, "90"))
        if len(lines) > 12:
            self._log(_c(f"      … (+{len(lines) - 12} more lines)", "90"))

    # -- main loop ---------------------------------------------------------- #
    def run(self, task: str,
            history: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Run one task. ``history`` is optional prior conversation — plain
        user/assistant message dicts — so a session can build on itself."""
        specs = self.registry.specs()
        # Prompt budget scales with model capacity: big models get the full
        # persona + team; small ones get the compact creed so they act, not narrate.
        small = _is_small_model(getattr(self.backend, "name", ""))
        hats = [] if small else _pick_hats(task)
        if small:
            system = SYSTEM_PROMPT_COMPACT + SPIDER_PERSONAS[self.spider]
        else:
            system = SYSTEM_PROMPT + SPIDER_PERSONAS[self.spider]
            if hats:
                system += "\n\nSpecialists on this job:\n" + "\n".join(t for _, t in hats)
        memories = load_memories()
        if memories:
            system += "\n\nWhat you remember about your friend:\n" + memories
        lessons = load_lessons()
        if lessons:
            system += "\n\nLessons your past mistakes taught you:\n" + lessons
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system},
            *(history or []),
            {"role": "user", "content": task},
        ]
        transcript: List[Dict[str, Any]] = []
        qa_pending = True  # every run earns exactly one Editor review before finishing
        empty_rejects = 0  # consecutive finish-without-work rejections
        self._step = 0

        self._log(_c(f"\n● Task: {task}", "1;36"))
        self._log(_c(
            f"  workdir={self.workdir}  model={getattr(self.backend, 'name', '?')}  "
            f"safety={self.safety.mode}\n", "90"))
        self._emit("task_start", task=task, workdir=str(self.workdir),
                   model=getattr(self.backend, "name", "?"), safety=self.safety.mode)
        if hats:
            self._emit("think", text="🕸 Web-team hats on this job: "
                                     + " + ".join(n for n, _ in hats))

        for step in range(1, self.max_steps + 1):
            self._step = step
            try:
                reply = self.backend.chat(messages, specs)
            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
                self._log(_c(f"\n✗ Backend error: {msg}", "1;31"))
                self._emit("error", message=msg)
                return {"answer": f"(stopped: backend error: {msg})",
                        "steps": step, "transcript": transcript}

            # The model's private reasoning (when thinking is on) streams first,
            # as its own event so the UI can show it as a live "thinking" block.
            if getattr(reply, "thinking", "").strip():
                self._log(_c(f"[{step}] ", "1;35") + _c("reason ", "36") + reply.thinking.strip()[:200])
                self._emit("reasoning", text=reply.thinking.strip())

            if reply.content.strip():
                self._log(_c(f"[{step}] ", "1;35") + _c("think  ", "35") + reply.content.strip())
                self._emit("think", text=reply.content.strip())

            if not reply.tool_calls:
                # Small local models often *narrate* tool calls as JSON text
                # instead of emitting native ones — sometimes several in one
                # breath. Rescue them all, in order, before giving up.
                rescued = _rescue_tool_calls(reply.content, self.registry.names())
                if rescued:
                    self._log(_c(f"      (rescued {len(rescued)} narrated tool call(s))", "90"))
                    reply.tool_calls = rescued
                else:
                    # A plain text answer with no tool call -> treat as the final answer.
                    self._log(_c("\n✓ Done.", "1;32"))
                    self._emit("answer", text=reply.content.strip())
                    return {"answer": reply.content.strip(), "steps": step, "transcript": transcript}

            # Record the assistant's tool-call turn in canonical (OpenAI) form.
            messages.append({
                "role": "assistant",
                "content": reply.content or None,
                "tool_calls": [
                    {"id": tc["id"], "type": "function",
                     "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])}}
                    for tc in reply.tool_calls
                ],
            })

            for tc in reply.tool_calls:
                name, arguments = tc["name"], tc["arguments"]

                if name == "finish":
                    summary = arguments.get("summary", "")
                    # Editor / Devil's-Advocate hat: every first finish gets one
                    # review. Finishing an action task with ZERO tool use is
                    # rejected deterministically (small models declare victory
                    # on step one — no model can be trusted to judge its own
                    # empty claim); real work gets one critical model review.
                    acted = any(t["tool"] in ("write_file", "run_command")
                                for t in transcript)
                    wants_action = re.search(
                        r"\b(write|create|run|fix|make|build|organi[sz]e|delete"
                        r"|add|move|rename|install|test|refactor)\b", task.lower())
                    finding = None
                    if not acted and wants_action:
                        # Deterministic and unlimited: an action task finished with
                        # zero tool use is always a false claim. Costs nothing.
                        empty_rejects += 1
                        if empty_rejects >= 3:
                            # The model is stuck declaring victory — surface a
                            # structured failure so The Web can escalate.
                            msg = ("(stopped: the model kept finishing without doing "
                                   "the work)")
                            self._log(_c("\n⏹ Stopped: model refused to act.", "1;33"))
                            self._emit("error", message=msg)
                            return {"answer": msg, "steps": step,
                                    "transcript": transcript, "gave_up": True}
                        finding = ("REJECTED — no file was written and no command was "
                                   "run, so the task is NOT done. Call write_file to "
                                   "create the file, then run_command to verify, THEN "
                                   "finish.")
                    elif qa_pending and acted:
                        qa_pending = False  # the model review happens once per run
                        finding = self._editor_review(task, transcript, summary)
                        if finding is None:
                            self._emit("think", text="🧐 Editor hat: reviewed the work — approved.")
                        else:
                            # Self-learning: corrections become standing lessons.
                            add_lesson(f"On '{task[:60]}…': {finding}")
                    if finding:
                        obs = (f"EDITOR REVIEW (Devil's Advocate): {finding} "
                               "Address this, verify, then finish again.")
                        self._log(_c(f"[{step}] ", "1;35") + _c("review ", "33") + finding)
                        self._emit("think", text=f"🧐 Editor hat: {finding}")
                        messages.append({"role": "tool", "tool_call_id": tc["id"],
                                         "name": "finish", "content": obs})
                        continue
                    self._log(_c(f"[{step}] ", "1;35") + _c("finish ", "1;32") + summary)
                    self._log(_c("\n✓ Task complete.", "1;32"))
                    self._emit("finish", summary=summary)
                    return {"answer": summary, "steps": step, "transcript": transcript}

                arg_preview = json.dumps(arguments)
                if len(arg_preview) > 160:
                    arg_preview = arg_preview[:160] + "…"
                self._log(_c(f"[{step}] ", "1;35") + _c(f"call   {name}", "36")
                          + _c(f"  {arg_preview}", "90"))
                self._emit("tool_call", tool=name, args=arguments)

                obs = self.registry.call(name, arguments, self.ctx)
                transcript.append({"step": step, "tool": name, "args": arguments, "observation": obs})
                self._print_observation(obs)
                self._emit("tool_result", tool=name, observation=obs,
                           ok=not obs.startswith(("ERROR", "BLOCKED", "DENIED")))

                messages.append({"role": "tool", "tool_call_id": tc["id"],
                                 "name": name, "content": obs})

        self._log(_c("\n⏹ Stopped: reached max steps.", "1;33"))
        self._emit("max_steps")
        return {"answer": "(stopped: reached max steps without calling finish)",
                "steps": self.max_steps, "transcript": transcript}
