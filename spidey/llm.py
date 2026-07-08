"""LLM backends for Spidey.

The agent speaks a single canonical message format (OpenAI-style dicts) and each
backend adapts it to the wire format of a concrete provider. A backend's ``chat``
returns a normalized :class:`AssistantReply` so the agent never has to know which
provider produced it.

Backends:
  * :class:`OllamaBackend`     — local, free, private. Talks to ``/api/chat``.
  * :class:`OpenAIBackend`     — any OpenAI-compatible endpoint (llama.cpp server,
                                 vLLM, LM Studio, a hosted provider, or your own
                                 fine-tuned GGUF served via ``llama-server``).
                                 Also covers OpenAI and Gemini via PROVIDER_PRESETS.
  * :class:`AnthropicBackend`  — Claude, via the native Messages API.
  * :class:`StubBackend`       — a deterministic, scripted "model" for offline demos
                                 and unit tests. No network, no GPU.

Bring your own key: hosted providers read their key from the standard env var
(``ANTHROPIC_API_KEY``, ``GEMINI_API_KEY``, ``OPENAI_API_KEY``) unless one is
passed explicitly. ``requests`` is imported lazily inside the network backends so
the Stub path and the offline demo run with only the Python standard library.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AssistantReply:
    """Normalized model output.

    ``tool_calls`` is a list of ``{"id": str, "name": str, "arguments": dict}``.
    """

    content: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)


class LLMBackend(ABC):
    name: str = "backend"

    @abstractmethod
    def chat(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> AssistantReply:
        """Send the conversation + tool specs, return the model's next reply."""


# --------------------------------------------------------------------------- #
# Format helpers
# --------------------------------------------------------------------------- #
def _to_openai_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Wrap normalized tool specs in the OpenAI/Ollama ``function`` envelope."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


def _to_ollama_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert canonical (OpenAI-style) history to what Ollama's /api/chat expects."""
    out: List[Dict[str, Any]] = []
    for m in messages:
        role = m["role"]
        if role == "assistant" and m.get("tool_calls"):
            tcs = []
            for tc in m["tool_calls"]:
                fn = tc["function"]
                args = fn["arguments"]
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                tcs.append({"function": {"name": fn["name"], "arguments": args}})
            out.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": tcs})
        elif role == "tool":
            out.append({"role": "tool", "content": m.get("content", "")})
        else:
            out.append({"role": role, "content": m.get("content") or ""})
    return out


def _parse_tool_calls(raw_calls, arguments_are_json_strings: bool) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []
    for i, tc in enumerate(raw_calls or []):
        fn = tc.get("function", {})
        args = fn.get("arguments", {})
        if arguments_are_json_strings and isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"_raw": args}
        if isinstance(args, str):  # Ollama sometimes still returns a string
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"_raw": args}
        calls.append(
            {"id": tc.get("id") or f"call_{i}", "name": fn.get("name", ""), "arguments": args or {}}
        )
    return calls


# --------------------------------------------------------------------------- #
# Backends
# --------------------------------------------------------------------------- #
class OllamaBackend(LLMBackend):
    def __init__(self, model: str, base_url: str = "http://localhost:11434",
                 temperature: float = 0.1, timeout: int = 180):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.timeout = timeout
        self.name = f"ollama:{model}"

    def chat(self, messages, tools):
        import requests  # lazy

        payload = {
            "model": self.model,
            "messages": _to_ollama_messages(messages),
            "tools": _to_openai_tools(tools),
            "stream": False,
            "options": {"temperature": self.temperature},
        }
        resp = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
        resp.raise_for_status()
        msg = resp.json().get("message", {})
        return AssistantReply(
            content=msg.get("content", "") or "",
            tool_calls=_parse_tool_calls(msg.get("tool_calls"), arguments_are_json_strings=False),
        )


class OpenAIBackend(LLMBackend):
    def __init__(self, model: str, base_url: str = "http://localhost:8000/v1",
                 api_key: str | None = None, temperature: float = 0.1, timeout: int = 180):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.temperature = temperature
        self.timeout = timeout
        self.name = f"openai:{model}"

    def chat(self, messages, tools):
        import requests  # lazy

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": messages,  # already OpenAI-shaped
            "tools": _to_openai_tools(tools),
            "temperature": self.temperature,
            "stream": False,
        }
        resp = requests.post(f"{self.base_url}/chat/completions", json=payload,
                             headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        choice = resp.json()["choices"][0]["message"]
        return AssistantReply(
            content=choice.get("content") or "",
            tool_calls=_parse_tool_calls(choice.get("tool_calls"), arguments_are_json_strings=True),
        )


class AnthropicBackend(LLMBackend):
    """Claude via the native Messages API (https://api.anthropic.com/v1/messages).

    Converts the canonical OpenAI-style history to Anthropic's format: the system
    message becomes the top-level ``system`` param, assistant tool calls become
    ``tool_use`` content blocks, and tool observations go back as ``tool_result``
    blocks inside a user message. No sampling params are sent — the newest Claude
    models reject non-default ``temperature``/``top_p``.
    """

    def __init__(self, model: str = "claude-sonnet-5", api_key: str | None = None,
                 base_url: str = "https://api.anthropic.com", max_tokens: int = 16000,
                 timeout: int = 300):
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.name = f"anthropic:{model}"

    @staticmethod
    def _to_anthropic(messages: List[Dict[str, Any]]):
        """Split canonical history into (system, anthropic_messages)."""
        system = ""
        out: List[Dict[str, Any]] = []
        for m in messages:
            role = m["role"]
            if role == "system":
                system = m.get("content") or ""
            elif role == "assistant" and m.get("tool_calls"):
                blocks: List[Dict[str, Any]] = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for tc in m["tool_calls"]:
                    fn = tc["function"]
                    args = fn["arguments"]
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {}
                    blocks.append({"type": "tool_use", "id": tc["id"],
                                   "name": fn["name"], "input": args})
                out.append({"role": "assistant", "content": blocks})
            elif role == "tool":
                block = {"type": "tool_result", "tool_use_id": m.get("tool_call_id", ""),
                         "content": m.get("content", "")}
                # Results for parallel tool calls must share one user message.
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
            else:
                out.append({"role": role, "content": m.get("content") or ""})
        return system, out

    def chat(self, messages, tools):
        import requests  # lazy

        if not self.api_key:
            raise RuntimeError("No Anthropic API key. Set ANTHROPIC_API_KEY or pass --api-key.")
        system, anthropic_messages = self._to_anthropic(messages)
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": anthropic_messages,
            "tools": [
                {"name": t["name"], "description": t.get("description", ""),
                 "input_schema": t.get("parameters", {"type": "object", "properties": {}})}
                for t in tools
            ],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        resp = requests.post(f"{self.base_url}/v1/messages", json=payload,
                             headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        content, tool_calls = "", []
        for block in data.get("content", []):
            if block.get("type") == "text":
                content += block.get("text", "")
            elif block.get("type") == "tool_use":
                tool_calls.append({"id": block["id"], "name": block["name"],
                                   "arguments": block.get("input") or {}})
        return AssistantReply(content=content, tool_calls=tool_calls)


class StubBackend(LLMBackend):
    """Replays a fixed script of :class:`AssistantReply` objects. For demos/tests."""

    def __init__(self, script: List[AssistantReply]):
        self.script = list(script)
        self._i = 0
        self.name = "stub"

    def chat(self, messages, tools):
        if self._i >= len(self.script):
            return AssistantReply(
                tool_calls=[{"id": "call_end", "name": "finish",
                             "arguments": {"summary": "stub script finished"}}]
            )
        reply = self.script[self._i]
        self._i += 1
        return reply


# Convenience builders for writing stub scripts.
def tool_call(name: str, **arguments: Any) -> AssistantReply:
    return AssistantReply(tool_calls=[{"id": f"call_{name}", "name": name, "arguments": arguments}])


def say(content: str) -> AssistantReply:
    return AssistantReply(content=content)


# --------------------------------------------------------------------------- #
# Provider registry — one place that knows how to build every backend.
# --------------------------------------------------------------------------- #
# Gemini and OpenAI both expose OpenAI-compatible endpoints, so they reuse
# OpenAIBackend with a preset base URL; Claude gets the native backend above.
PROVIDER_PRESETS: Dict[str, Dict[str, str]] = {
    "ollama":    {"default_model": "qwen2.5-coder:7b", "key_env": "",
                  "base_url": "http://localhost:11434"},
    "anthropic": {"default_model": "claude-sonnet-5", "key_env": "ANTHROPIC_API_KEY",
                  "base_url": "https://api.anthropic.com"},
    "gemini":    {"default_model": "gemini-2.5-flash", "key_env": "GEMINI_API_KEY",
                  "base_url": "https://generativelanguage.googleapis.com/v1beta/openai"},
    "openai":    {"default_model": "gpt-5", "key_env": "OPENAI_API_KEY",
                  "base_url": "https://api.openai.com/v1"},
    "custom":    {"default_model": "", "key_env": "",
                  "base_url": "http://localhost:8000/v1"},
}


def build_backend(provider: str, model: Optional[str] = None,
                  api_key: Optional[str] = None, base_url: Optional[str] = None,
                  temperature: float = 0.1) -> LLMBackend:
    """Build a backend from a provider name. Used by both the CLI and the server."""
    preset = PROVIDER_PRESETS.get(provider)
    if preset is None:
        raise ValueError(f"Unknown provider '{provider}'. "
                         f"Choose from: {', '.join(PROVIDER_PRESETS)}")
    model = model or preset["default_model"]
    if not model:
        raise ValueError(f"Provider '{provider}' needs an explicit model name.")
    api_key = api_key or (os.environ.get(preset["key_env"]) if preset["key_env"] else None)
    base_url = base_url or preset["base_url"]

    if provider == "ollama":
        return OllamaBackend(model, base_url=base_url, temperature=temperature)
    if provider == "anthropic":
        return AnthropicBackend(model, api_key=api_key, base_url=base_url)
    if preset["key_env"] and not api_key:
        raise RuntimeError(f"No API key for {provider}. "
                           f"Set {preset['key_env']} or pass one explicitly.")
    return OpenAIBackend(model, base_url=base_url, api_key=api_key, temperature=temperature)
