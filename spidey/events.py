"""Structured events emitted by the agent loop.

The agent's console output is just one view of a run. Frontends (the web UI, a
test harness, a logger) subscribe by passing ``on_event`` to :class:`~spidey.agent.Agent`;
they receive one :class:`AgentEvent` per meaningful moment in the loop and can render
it however they like. Events are plain data — safe to serialize straight to JSON.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

# Event types, in the order they typically occur in a run:
#   task_start        the run began                {task, workdir, model, safety}
#   think             free-text reasoning          {text}
#   tool_call         model chose a tool           {tool, args}
#   tool_result       the tool's observation       {tool, observation, ok}
#   approval_request  safety layer wants a human   {prompt}
#   approval_result   the human's verdict          {approved}
#   finish            model called finish          {summary}
#   answer            plain-text final answer      {text}
#   max_steps         loop hit the step budget     {}
#   error             backend/loop failure         {message}


@dataclass
class AgentEvent:
    type: str
    step: int = 0
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "step": self.step, **self.data}


EventHandler = Optional[Callable[[AgentEvent], None]]
