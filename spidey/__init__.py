"""Spidey — an open, self-hostable coding agent that runs on free local models."""

__version__ = "1.0.0"

from .agent import Agent
from .tools import Tool, ToolRegistry, default_registry
from .llm import OllamaBackend, OpenAIBackend
from .safety import SafetyConfig

__all__ = [
    "Agent",
    "Tool",
    "ToolRegistry",
    "default_registry",
    "OllamaBackend",
    "OpenAIBackend",
    "SafetyConfig",
    "__version__",
]
