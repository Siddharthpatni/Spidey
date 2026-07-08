"""Spidey — an open, self-hostable coding agent that runs on free local models."""

__version__ = "0.1.0"

from .agent import Agent
from .tools import Tool, ToolRegistry, default_registry
from .llm import OllamaBackend, OpenAIBackend, StubBackend
from .safety import SafetyConfig

__all__ = [
    "Agent",
    "Tool",
    "ToolRegistry",
    "default_registry",
    "OllamaBackend",
    "OpenAIBackend",
    "StubBackend",
    "SafetyConfig",
    "__version__",
]
