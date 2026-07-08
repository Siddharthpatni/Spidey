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
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from ..agent import Agent
from ..events import AgentEvent
from ..llm import build_backend
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
            backend = self._build_backend(config)
            workdir = config.get("workdir") or self.default_workdir
            agent = Agent(
                backend,
                workdir=workdir,
                safety=SafetyConfig(mode=config.get("safety", "ask")),
                max_steps=int(config.get("max_steps") or 25),
                verbose=False,
                approve=self.approve,
                on_event=self.on_event,
            )
            agent.run(task)
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


def create_app(default_workdir: str = ".") -> FastAPI:
    app = FastAPI(title="Spidey")
    default_workdir = str(Path(default_workdir).resolve())

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
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


def serve(host: str = "127.0.0.1", port: int = 8000, workdir: str = ".") -> int:
    import uvicorn

    app = create_app(default_workdir=workdir)
    print(f"● Spidey web UI → http://{host}:{port}   (agent workdir: {Path(workdir).resolve()})")
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0
