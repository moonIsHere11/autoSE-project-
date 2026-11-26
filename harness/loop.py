"""Compatibility shim: the original AgentLoop interface (used by Runner) implemented on harness.agent.Agent.
New code should build an Agent directly."""
from __future__ import annotations

from typing import Callable

from .agent import MALFORMED, NUDGE, Agent, AgentSpec
from .context import ContextManager
from .events import EventLog
from .policy import ToolPolicy
from .prompt import PromptBuilder
from .registry import ToolRegistry

__all__ = ["AgentLoop", "MALFORMED", "NUDGE"]


class AgentLoop:
    def __init__(self, llm, registry: ToolRegistry, context: ContextManager, events: EventLog, *,
                 allow: set[str] | None = None, label: str | None = None, log: Callable = print,
                 max_malformed: int = 6, max_nudges: int = 3, nudge: str = NUDGE):
        self.llm, self.registry, self.context, self.events = llm, registry, context, events
        self.allow, self.label, self.log = allow, label, log
        self.max_malformed, self.max_nudges, self.nudge = max_malformed, max_nudges, nudge

    def run(self, system_fn: Callable[[], str], user_msg: str, done: Callable[[], bool], max_steps: int = 40) -> str:
        """Returns why it stopped: 'done' | 'max_steps' | 'gave_up' | 'llm_error: ...'."""
        prompt = PromptBuilder()
        prompt.set("system", system_fn)  # re-evaluated every turn: keeps the scratchpad notes current
        spec = AgentSpec(self.label or "agent", prompt, ToolPolicy(allow=None if self.allow is None else set(self.allow)),
                         max_steps=max_steps, max_malformed=self.max_malformed, max_nudges=self.max_nudges,
                         nudge=self.nudge)
        agent = Agent(self.llm, self.registry, spec, events=self.events, log=self.log)
        agent.set_context(self.context)
        agent.add_stop_condition("done", lambda state: done())
        return agent.run(user_msg).stop_reason
