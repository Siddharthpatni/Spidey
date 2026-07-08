"""Command-line interface for Spidey.

    spidey setup           # download an open-weight model for fully offline use
    spidey run "add type hints to utils.py and run mypy" --model qwen2.5-coder:7b
    spidey run "fix the failing test" --backend anthropic     # bring your own key
    spidey run --file task.md --workdir ./myproject --safety enforce
    spidey serve           # web UI: chat + live agent graph
    spidey version
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from .agent import Agent
from .llm import PROVIDER_PRESETS, build_backend
from .safety import SafetyConfig


def _add_run_parser(sub: argparse._SubParsersAction) -> None:
    r = sub.add_parser("run", help="Run a task with a real model.")
    r.add_argument("task", nargs="?", help="Task description (or use --file).")
    r.add_argument("--file", help="Read the task from a file instead of the argument.")
    r.add_argument("--model", default=None,
                   help="Model name; defaults to the provider's preset "
                        "(ollama: gemma4:12b, anthropic: claude-sonnet-5, ...).")
    r.add_argument("--backend", choices=list(PROVIDER_PRESETS),
                   default="ollama",
                   help="ollama (local, free) | anthropic | gemini | openai | custom "
                        "(any OpenAI-compatible URL).")
    r.add_argument("--base-url", default=None, help="Override the backend URL.")
    r.add_argument("--api-key", default=None,
                   help="API key. Falls back to ANTHROPIC_API_KEY / GEMINI_API_KEY / "
                        "OPENAI_API_KEY for the matching provider.")
    r.add_argument("--workdir", default=".", help="Directory the agent operates in. Default: .")
    r.add_argument("--max-steps", type=int, default=25)
    r.add_argument("--safety", choices=["ask", "enforce", "off"], default="ask",
                   help="ask=prompt on dangerous commands, enforce=block them, off=no checks.")
    r.add_argument("--spider", default="peter",
                   choices=["peter", "miles", "gwen", "noir", "2099", "ham"],
                   help="Which Spider answers: peter (default) | miles | gwen | noir | 2099 | ham.")
    r.add_argument("--temp", type=float, default=0.1)
    r.add_argument("--yes", action="store_true",
                   help="Auto-approve command prompts. Convenient but removes the human check.")
    r.add_argument("--quiet", action="store_true", help="Only print the final answer.")


def _cmd_up(args) -> int:
    """One command, whole assistant: ensure Ollama is running and a brain is
    present, then start the server and open the browser. Jarvis, but Spidey."""
    import shutil
    import subprocess
    import threading
    import time
    import webbrowser

    import requests

    from .server.app import serve

    ollama_url = "http://localhost:11434"

    def ollama_alive() -> bool:
        try:
            return requests.get(f"{ollama_url}/api/version", timeout=2).ok
        except requests.RequestException:
            return False

    if not ollama_alive():
        if shutil.which("ollama") is None:
            print("Ollama isn't installed — it's the free runtime for Spidey's offline brain.")
            print("Get it at https://ollama.com/download, then re-run:  spidey up")
            return 1
        print("● Waking up Ollama…")
        subprocess.Popen(["ollama", "serve"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(20):
            if ollama_alive():
                break
            time.sleep(0.5)
        else:
            print("✗ Ollama didn't start — try `ollama serve` in another terminal.")
            return 1

    try:
        tags = [m["name"] for m in
                requests.get(f"{ollama_url}/api/tags", timeout=5).json().get("models", [])]
    except requests.RequestException:
        tags = []
    if not any(t.startswith(args.model.split(":")[0]) for t in tags):
        print(f"● No brain yet — downloading {args.model} (one time)…")
        if subprocess.run(["ollama", "pull", args.model]).returncode != 0:
            return 1

    from .voice import voice_status
    if not voice_status()["available"]:
        print('  (tip: offline voice is one command away — `spidey setup --voice`)')

    scheme = "https" if args.https else "http"
    url = f"{scheme}://127.0.0.1:{args.port}/" + (f"?token={args.token}" if args.token else "")
    if not args.no_open:
        threading.Timer(1.5, webbrowser.open, [url]).start()
    return serve(host=args.host, port=args.port, workdir=args.workdir,
                 token=args.token, https=args.https)


def _cmd_setup_voice() -> int:
    """Download the offline speech model so 'Hey Spidey' works without internet."""
    from . import voice

    if not voice.vosk_installed():
        print("Voice needs the vosk recognizer (runs 100% on your machine). Install it with:")
        print('    pip install -e ".[voice]"')
        print("then re-run:  spidey setup --voice")
        return 1
    voice.download_model()
    print("\n✓ Offline voice is ready. Run `spidey serve`, click the mic, and say:")
    print('    "Hey Spidey, …"')
    return 0


def _cmd_setup(model: str) -> int:
    """Pull the full model weights to this machine — after that, no internet needed."""
    import shutil
    import subprocess

    if shutil.which("ollama") is None:
        print("Ollama isn't installed yet — it's the free runtime Spidey uses for local models.")
        print("Grab it from https://ollama.com/download, then re-run:  spidey setup")
        return 1
    print(f"● Downloading {model} (stored locally — everything runs offline afterwards)…")
    proc = subprocess.run(["ollama", "pull", model])
    if proc.returncode != 0:
        print("Download failed — check the model tag at https://ollama.com/library")
        return proc.returncode
    print(f"\n✓ {model} is on your machine. Try it:")
    print(f'    spidey run "summarize README.md" --model {model}')
    print("    spidey serve      # web UI: chat + live reasoning web")
    print("\nWant a smarter brain? Fine-tune your own — see training/README.md")
    return 0


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="spidey",
        description="Spidey — an open, self-hostable coding agent that runs on free local models.",
    )
    sub = parser.add_subparsers(dest="cmd")
    _add_run_parser(sub)
    u = sub.add_parser("up", help="Start EVERYTHING: Ollama + brain check + web UI + browser.")
    u.add_argument("--model", default="gemma4:12b", help="Brain to ensure is downloaded.")
    u.add_argument("--host", default="127.0.0.1")
    u.add_argument("--port", type=int, default=8000)
    u.add_argument("--workdir", default=".")
    u.add_argument("--token", default=None, help="Access token (needed beyond localhost).")
    u.add_argument("--https", action="store_true", help="Self-signed HTTPS (mic from phones).")
    u.add_argument("--no-open", action="store_true", help="Don't auto-open the browser.")
    s = sub.add_parser("serve", help="Start the web UI (chat + live agent graph).")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--workdir", default=".", help="Default working directory for agent runs.")
    s.add_argument("--token", default=None,
                   help="Require this access token on every connection (also $SPIDEY_TOKEN). "
                        "Mandatory before exposing Spidey beyond localhost.")
    s.add_argument("--https", action="store_true",
                   help="Serve over HTTPS with an auto-generated self-signed certificate. "
                        "Needed for the mic/voice to work from phones and other devices.")
    p = sub.add_parser("setup", help="Download an open-weight model so Spidey runs fully offline.")
    p.add_argument("--model", default="gemma4:12b",
                   help="Ollama model tag to download. Default: gemma4:12b (~7.6 GB).")
    p.add_argument("--voice", action="store_true",
                   help="Also/only download the offline speech model (~40 MB) for "
                        "'Hey Spidey' voice control.")
    sub.add_parser("version", help="Print the version and exit.")

    args = parser.parse_args(argv)

    if args.cmd is None:
        parser.print_help()
        return 0

    if args.cmd == "version":
        from . import __version__
        print(f"spidey {__version__}")
        return 0

    if args.cmd == "up":
        return _cmd_up(args)

    if args.cmd == "setup":
        if args.voice:
            return _cmd_setup_voice()
        return _cmd_setup(args.model)

    if args.cmd == "serve":
        try:
            from .server.app import serve
        except ImportError:
            raise SystemExit(
                "The web UI needs the server extras. Install with:\n"
                '    pip install -e ".[server]"'
            )
        return serve(host=args.host, port=args.port, workdir=args.workdir,
                     token=args.token, https=args.https)

    if args.cmd == "run":
        task = args.task
        if args.file:
            task = Path(args.file).read_text()
        if not task:
            raise SystemExit("Provide a task string or --file.")
        try:
            backend = build_backend(args.backend, model=args.model,
                                    api_key=args.api_key, base_url=args.base_url,
                                    temperature=args.temp)
        except (ValueError, RuntimeError) as e:
            raise SystemExit(str(e))
        approve = (lambda _p: True) if args.yes else None
        agent = Agent(
            backend,
            workdir=args.workdir,
            safety=SafetyConfig(mode=args.safety),
            max_steps=args.max_steps,
            verbose=not args.quiet,
            approve=approve,
            spider=args.spider,
        )
        result = agent.run(task)
        if args.quiet:
            print(result["answer"])
        return 0

    parser.print_help()
    return 0
