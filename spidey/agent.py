"""The Spidey agent loop.

A small, readable ReAct-style controller: send the conversation + tool specs to a
model, execute whatever tool it asks for, feed the result back, and repeat until
the model calls ``finish`` (or we hit ``max_steps``). All provider quirks live in
the backends; all danger lives behind the safety layer. This file is just the loop.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .events import AgentEvent, EventHandler
from .llm import LLMBackend
from .safety import SafetyConfig
from .tools import Context, ToolRegistry, default_registry

SYSTEM_PROMPT = """You are Spidey, an autonomous AI assistant. You help with everyday tasks and
coding alike — organizing files, drafting documents, analyzing data, writing and fixing
code — by acting, not just talking.

You work inside a single working directory on the user's machine. You can read and
write files, search their contents, and run shell commands — always by calling the
provided tools, never by describing what you would do. If the user asks a question you
can answer without touching their machine, just reply in plain text.

How to work:
- Take one step at a time. Inspect before you change: use read_file, list_directory,
  and search_code to understand what's there first.
- Make small, verifiable changes. After changing code, run the tests or the program to
  confirm it works.
- Never invent file contents or paths — read the file to be sure.
- Shell commands run on a real machine. Destructive actions require the user's approval,
  so prefer safe, targeted commands.
- When the task is finished (or you have the answer the user asked for), call the
  `finish` tool with a short summary of what you did.

Respond by calling exactly one tool at a time."""


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m"


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
    ) -> None:
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
    def run(self, task: str) -> Dict[str, Any]:
        specs = self.registry.specs()
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task},
        ]
        transcript: List[Dict[str, Any]] = []
        self._step = 0

        self._log(_c(f"\n● Task: {task}", "1;36"))
        self._log(_c(
            f"  workdir={self.workdir}  model={getattr(self.backend, 'name', '?')}  "
            f"safety={self.safety.mode}\n", "90"))
        self._emit("task_start", task=task, workdir=str(self.workdir),
                   model=getattr(self.backend, "name", "?"), safety=self.safety.mode)

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

            if reply.content.strip():
                self._log(_c(f"[{step}] ", "1;35") + _c("think  ", "35") + reply.content.strip())
                self._emit("think", text=reply.content.strip())

            if not reply.tool_calls:
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
