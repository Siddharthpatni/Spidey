"""FastAPI server: the bridge between the browser and the agent loop.

One WebSocket connection = one interactive session. The browser sends a ``start``
message with a task + provider config; the agent runs in a worker thread and its
events stream back over the socket as JSON. When the safety layer flags a command,
the run pauses on a Future until the browser answers the approval prompt.

Protocol (client -> server):
    {"type": "start", "task": str, "config": {provider, model, api_key, base_url,
                                              workdir, safety, max_steps}}
    {"type": "approval", "id": str, "approved": bool}
    {"type": "stop"}

Server -> client: AgentEvent dicts (task_start, think, tool_call, tool_result,
finish, answer, error, max_steps), plus:
    {"type": "approval_request", "id": str, "prompt": str}
    {"type": "run_done"}   after every run, success or not

A second WebSocket, ``/ws/voice``, carries offline voice: the browser streams
raw microphone PCM (16 kHz mono s16le) as binary frames; the server answers with
wake / partial / utterance / sleep events from the on-device recognizer (see
``spidey.voice``). Nothing is sent to any cloud — recognition happens in-process.

API keys arrive with each start message and live only in that run's backend
object — the server never writes them to disk.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import secrets
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from ..agent import Agent
from ..events import AgentEvent
from ..llm import build_backend
from ..router import route_task
from ..safety import SafetyConfig
from ..voice import VoiceSession, voice_status

STATIC_DIR = Path(__file__).parent / "static"
APPROVAL_TIMEOUT = 300  # seconds a run will wait for a human verdict before denying


class RunCancelled(Exception):
    """Raised inside the agent thread when the browser asks to stop."""


class Session:
    """State for one WebSocket connection / one run at a time."""

    def __init__(self, ws: WebSocket, default_workdir: str) -> None:
        self.ws = ws
        self.default_workdir = default_workdir
        self.loop = asyncio.get_running_loop()
        self.queue: asyncio.Queue[Optional[Dict[str, Any]]] = asyncio.Queue()
        self.pending_approvals: Dict[str, concurrent.futures.Future] = {}
        self.cancelled = False
        self.running = False
        # Conversation memory for this socket: past (task, answer) turns, so
        # follow-ups build on each other like a real conversation.
        self.history: list[Dict[str, Any]] = []

    # -- called from the agent's worker thread ------------------------------ #
    def _push(self, payload: Dict[str, Any]) -> None:
        self.loop.call_soon_threadsafe(self.queue.put_nowait, payload)

    def on_event(self, event: AgentEvent) -> None:
        if self.cancelled:
            raise RunCancelled()
        # The server sends its own approval_request (with a correlation id).
        if event.type != "approval_request":
            self._push(event.to_dict())

    def approve(self, prompt: str) -> bool:
        if self.cancelled:
            return False
        approval_id = uuid.uuid4().hex[:8]
        fut: concurrent.futures.Future = concurrent.futures.Future()
        self.pending_approvals[approval_id] = fut
        self._push({"type": "approval_request", "id": approval_id, "prompt": prompt})
        try:
            return bool(fut.result(timeout=APPROVAL_TIMEOUT))
        except concurrent.futures.TimeoutError:
            return False
        finally:
            self.pending_approvals.pop(approval_id, None)

    def run_agent(self, task: str, config: Dict[str, Any]) -> None:
        try:
            # "The Web" auto mode: classify the task and dispatch it to the
            # Spider (model + personality) that solves it most efficiently.
            auto = (config.get("spider") == "auto"
                    and config.get("provider", "ollama") == "ollama")
            if auto:
                spider, model, reason = route_task(task)
                config = {**config, "spider": spider, "model": model}
                self._push({"type": "think", "step": 0, "text": f"🕸 The Web: {reason}"})

            def _run_with(cfg: Dict[str, Any]) -> Dict[str, Any]:
                agent = Agent(
                    self._build_backend(cfg),
                    workdir=cfg.get("workdir") or self.default_workdir,
                    safety=SafetyConfig(mode=cfg.get("safety", "off"),
                                        confine_to_workdir=bool(cfg.get("confine_to_workdir", False))),
                    max_steps=int(cfg.get("max_steps") or 25),
                    verbose=False,
                    approve=self.approve,
                    on_event=self.on_event,
                    spider=cfg.get("spider") or "peter",
                )
                return agent.run(task, history=self.history[-12:])

            result = _run_with(config)
            # Team escalation: if the dispatched specialist flounders, the
            # leader takes over — once.
            if auto and result.get("gave_up") and config.get("spider") != "peter":
                self._push({"type": "think", "step": 0,
                            "text": "🕸 The Web: that Spider got stuck — "
                                    "Peter Parker is taking over."})
                result = _run_with({**config, "spider": "peter", "model": "gemma4:12b"})
            answer = (result.get("answer") or "").strip()
            if answer and not answer.startswith("(stopped:"):
                self.history += [{"role": "user", "content": task},
                                 {"role": "assistant", "content": answer}]
                del self.history[:-24]
        except RunCancelled:
            self._push({"type": "error", "step": 0, "message": "Run stopped by user."})
        except Exception as e:  # config/backend errors -> surface, don't kill the socket
            self._push({"type": "error", "step": 0, "message": f"{type(e).__name__}: {e}"})
        finally:
            self._push({"type": "run_done"})
            self._push(None)  # wake the sender loop so it can re-check state

    @staticmethod
    def _build_backend(config: Dict[str, Any]):
        provider = config.get("provider", "ollama")
        return build_backend(
            provider,
            model=config.get("model") or None,
            api_key=config.get("api_key") or None,
            base_url=config.get("base_url") or None,
        )

    # -- teardown ------------------------------------------------------------ #
    def cancel(self) -> None:
        self.cancelled = True
        for fut in list(self.pending_approvals.values()):
            if not fut.done():
                fut.set_result(False)


def create_app(default_workdir: str = ".", token: Optional[str] = None) -> FastAPI:
    """Build the app. If ``token`` (or $SPIDEY_TOKEN) is set, both WebSockets
    require ``?token=<value>`` — set it whenever the server is reachable by
    anyone but you. Without a token, bind to 127.0.0.1 only."""
    app = FastAPI(
        title="Spidey",
        version="2.0.0",
        description="Self-hostable AI agent + capability platform: web automation, "
                    "file pipeline, analytics, fleet, job matching, research, code "
                    "assistant, email, driving data and a multi-agent team — over one "
                    "shared queue/scheduler/auth/metrics core. Ops view at /platform.",
    )
    from ..platform import mount_platform
    mount_platform(app)
    default_workdir = str(Path(default_workdir).resolve())
    auth_token = token if token is not None else (os.environ.get("SPIDEY_TOKEN") or None)

    async def _authorized(ws: WebSocket) -> bool:
        if not auth_token:
            return True
        supplied = ws.query_params.get("token", "")
        if secrets.compare_digest(supplied, auth_token):
            return True
        # Complete the handshake and say why before closing (1008 = policy
        # violation) so clients fail fast with a visible reason, not a hang.
        await ws.accept()
        await ws.send_json({"type": "error", "step": 0,
                            "message": "Access denied: invalid or missing token. "
                                       "Open the UI with ?token=<your token>."})
        await ws.close(code=1008, reason="invalid or missing token")
        return False

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        if not await _authorized(ws):
            return
        await ws.accept()
        session = Session(ws, default_workdir)

        async def sender() -> None:
            while True:
                payload = await session.queue.get()
                if payload is not None:
                    await ws.send_json(payload)

        send_task = asyncio.create_task(sender())
        run_task: Optional[asyncio.Task] = None
        try:
            while True:
                msg = await ws.receive_json()
                mtype = msg.get("type")
                if mtype == "start":
                    if session.running:
                        await ws.send_json({"type": "error", "step": 0,
                                            "message": "A run is already in progress."})
                        continue
                    session.running = True
                    session.cancelled = False

                    async def _run(task=msg.get("task", ""), config=msg.get("config") or {}):
                        try:
                            await asyncio.to_thread(session.run_agent, task, config)
                        finally:
                            session.running = False

                    run_task = asyncio.create_task(_run())
                elif mtype == "approval":
                    fut = session.pending_approvals.get(msg.get("id", ""))
                    if fut and not fut.done():
                        fut.set_result(bool(msg.get("approved")))
                elif mtype == "stop":
                    session.cancel()
                elif mtype == "new_chat":
                    session.history.clear()
        except WebSocketDisconnect:
            pass
        finally:
            session.cancel()
            send_task.cancel()
            if run_task:
                # Let the worker thread notice the cancel flag and finish.
                try:
                    await asyncio.wait_for(run_task, timeout=5)
                except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                    pass

    @app.get("/api/voice/status")
    async def api_voice_status() -> Dict[str, Any]:
        return voice_status()

    @app.websocket("/ws/voice")
    async def ws_voice(ws: WebSocket) -> None:
        if not await _authorized(ws):
            return
        await ws.accept()
        status = voice_status()
        if not status["available"]:
            await ws.send_json({"type": "voice_unavailable", **status})
            await ws.close()
            return

        # Building the recognizer loads the model on first use (~1 s) — keep it
        # off the event loop.
        session: VoiceSession = await asyncio.to_thread(VoiceSession, "wake")
        await ws.send_json({"type": "voice_ready", "model": status["model"]})
        try:
            while True:
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                if msg.get("bytes"):
                    events = await asyncio.to_thread(session.feed, msg["bytes"])
                    for ev in events:
                        await ws.send_json(ev)
                elif msg.get("text"):
                    ctrl = json.loads(msg["text"])
                    if ctrl.get("type") == "mode" and ctrl.get("mode") in ("wake", "direct"):
                        await asyncio.to_thread(session.set_mode, ctrl["mode"])
        except WebSocketDisconnect:
            pass

    if STATIC_DIR.is_dir() and (STATIC_DIR / "index.html").exists():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    else:
        @app.get("/")
        async def no_ui() -> Dict[str, str]:
            return {"spidey": "The web UI isn't built. Run `npm install && npm run build` "
                            "in web/, or reinstall the package."}

    return app


def _lan_ips() -> list[str]:
    """Every LAN address of this machine — multi-homed Macs have several."""
    import socket

    ips = set()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packets sent; just picks the route
        ips.add(s.getsockname()[0])
    except OSError:
        pass
    finally:
        s.close()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    return sorted(ips)


def _port_in_use(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _ensure_cert(lan_ips: list[str]) -> tuple[str, str]:
    """Self-signed TLS cert in ~/.spidey/certs — created once, regenerated when
    the machine's addresses change. HTTPS is what lets phone browsers open the mic."""
    import subprocess

    cert_dir = Path.home() / ".spidey" / "certs"
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert, key = cert_dir / "cert.pem", cert_dir / "key.pem"

    if cert.exists() and key.exists():
        txt = subprocess.run(["openssl", "x509", "-in", str(cert), "-noout", "-text"],
                             capture_output=True, text=True).stdout
        if all(f"IP Address:{ip}" in txt for ip in lan_ips):
            return str(cert), str(key)

    san = ",".join(["DNS:localhost", "IP:127.0.0.1", *(f"IP:{ip}" for ip in lan_ips)])
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256", "-days", "3650",
         "-nodes", "-keyout", str(key), "-out", str(cert),
         "-subj", "/CN=Spidey", "-addext", f"subjectAltName={san}"],
        check=True, capture_output=True,
    )
    return str(cert), str(key)


def serve(host: str = "127.0.0.1", port: int = 8000, workdir: str = ".",
          token: Optional[str] = None, https: bool = False) -> int:
    import uvicorn

    if _port_in_use(port):
        print(f"✗ Port {port} is already serving something (probably another Spidey).")
        print(f"  Stop it first (e.g. `pkill -f 'spidey serve'`) or pick another port: "
              f"--port {port + 1}")
        return 1

    token = token or os.environ.get("SPIDEY_TOKEN") or None
    app = create_app(default_workdir=workdir, token=token)
    lan = _lan_ips() if host not in ("127.0.0.1", "localhost") else []
    ssl_kwargs: Dict[str, Any] = {}
    if https:
        certfile, keyfile = _ensure_cert(lan)
        ssl_kwargs = {"ssl_certfile": certfile, "ssl_keyfile": keyfile}

    scheme = "https" if https else "http"
    q = f"/?token={token}" if token else "/"
    print(f"● Spidey is up   (agent workdir: {Path(workdir).resolve()})")
    print(f"  this machine → {scheme}://127.0.0.1:{port}{q}")
    for ip in lan:
        print(f"  same Wi-Fi   → {scheme}://{ip}:{port}{q}")
    if host not in ("127.0.0.1", "localhost"):
        if not token:
            print("  ⚠ auth: NONE and the server is reachable from the network. "
                  "Restart with --token (or $SPIDEY_TOKEN).")
        if https:
            print("  cert is self-signed: the browser warns once — proceed, and the "
                  "mic + voice work from any device.")
        else:
            print("  (voice note: phone browsers only open the mic over HTTPS — "
                  "restart with --https to talk to Spidey from other devices)")
    uvicorn.run(app, host=host, port=port, log_level="warning", **ssl_kwargs)
    return 0
