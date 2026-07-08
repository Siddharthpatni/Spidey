"""Zero-setup demo: a scripted 'model' drives Spidey to build and test a small module.

This uses :class:`StubBackend`, so it needs no Ollama, no GPU, and no network — it
exists so anyone who clones the repo can watch the agent loop, the tools, and the
safety layer work in about ten seconds:

    python -m spidey demo
    # or
    python examples/demo_offline.py

The same script powers the web UI's "Demo" provider (`spidey serve`), where the
flagged cleanup command becomes an interactive Approve/Deny moment.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import List

from .agent import Agent
from .llm import AssistantReply, StubBackend, tool_call
from .safety import SafetyConfig

DEMO_TASK = (
    "Create a small calculator module with an add() function plus a test, "
    "then verify it works."
)

# `python` isn't on PATH everywhere (macOS ships only python3), so fall back.
_PY = "python3"
_TEST_CMD = (
    f"{_PY} -m pytest -q 2>/dev/null"
    f" || {_PY} -c \"import test_calc; test_calc.test_add(); print('tests passed')\""
)


def demo_script() -> List[AssistantReply]:
    """A deterministic script standing in for a real model's tool calls."""
    first = tool_call("list_directory", path=".")
    first.content = ("I'll look at the project first, then write the module, "
                     "add a test, and verify everything runs.")
    return [
        first,
        tool_call(
            "write_file",
            path="calc.py",
            content=(
                "def add(a, b):\n"
                "    return a + b\n\n"
                'if __name__ == "__main__":\n'
                "    print(add(2, 3))\n"
            ),
        ),
        tool_call(
            "write_file",
            path="test_calc.py",
            content=(
                "from calc import add\n\n"
                "def test_add():\n"
                "    assert add(2, 3) == 5\n"
                "    assert add(-1, 1) == 0\n"
            ),
        ),
        tool_call("run_command", command=_TEST_CMD),
        tool_call("run_command", command=f"{_PY} calc.py"),
        # Flagged by the safety layer (rm -rf) — harmless here, but it shows the
        # ask-a-human path: auto-approved in the terminal demo, an interactive
        # Approve/Deny prompt in the web UI.
        tool_call("run_command", command="rm -rf __pycache__ .pytest_cache"),
        tool_call(
            "finish",
            summary="Created calc.py with add(), added test_calc.py, verified both "
                    "(tests pass; running calc.py prints 5), and cleaned up caches.",
        ),
    ]


def run_demo() -> int:
    workdir = Path(tempfile.mkdtemp(prefix="spidey_demo_"))

    agent = Agent(
        StubBackend(demo_script()),
        workdir=workdir,
        safety=SafetyConfig(mode="ask"),
        max_steps=15,
        verbose=True,
        approve=lambda _prompt: True,  # the demo's commands are safe; auto-approve for a hands-off run
    )
    result = agent.run(DEMO_TASK)

    print("\nFinal answer:", result["answer"])
    print("Demo workdir:", workdir)
    return 0
