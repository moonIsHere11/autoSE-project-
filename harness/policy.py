"""Privileges: which tools an agent is offered and whether one specific call may run.

The registry says what a tool is; the policy says what one agent may do with it. Kept apart so the same
registry can serve a read-only explorer and a writing builder.

    offered(tool)               static: does the model see this tool at all?
    check(tool, args, counts)   per call: allow | deny(reason) | ask (an approval callback decides)
"""
from __future__ import annotations

import copy as _copy
from dataclasses import dataclass, field, fields, replace
from typing import Callable, Literal

from .registry import Tool


@dataclass(frozen=True)
class PolicyDecision:
    action: Literal["allow", "deny", "ask"]
    reason: str = ""


@dataclass
class ToolPolicy:
    allow: set[str] | None = None          # None (and allow_tags None) = every tool is offered
    allow_tags: set[str] | None = None
    deny: set[str] = field(default_factory=set)       # deny and deny_tags always win
    deny_tags: set[str] = field(default_factory=set)
    ask: set[str] = field(default_factory=set)        # calls need the approval callback's yes
    limits: dict[str, int] = field(default_factory=dict)   # max calls per run, per tool name
    guards: dict[str, Callable[[dict], str | None]] = field(default_factory=dict)  # args -> refusal or None

    def offered(self, tool: Tool) -> bool:
        if tool.name in self.deny or tool.tags & self.deny_tags:
            return False
        if self.allow is None and self.allow_tags is None:
            return True
        return tool.name in (self.allow or set()) or bool(tool.tags & (self.allow_tags or set()))

    def check(self, tool: Tool, args: dict, counts: dict[str, int]) -> PolicyDecision:
        if not self.offered(tool):
            return PolicyDecision("deny", f"tool {tool.name} is not available to this agent")
        limit = self.limits.get(tool.name)
        if limit is not None and counts.get(tool.name, 0) >= limit:
            return PolicyDecision("deny", f"call limit {limit} reached for {tool.name}")
        guard = self.guards.get(tool.name)
        if guard is not None:
            refusal = guard(args)
            if refusal:
                return PolicyDecision("deny", refusal)
        if tool.name in self.ask:
            return PolicyDecision("ask", f"{tool.name} needs approval")
        return PolicyDecision("allow")

    def copy(self, **changes) -> ToolPolicy:
        """Independent copy (sets and dicts duplicated; guard callables shared), with `changes` applied."""
        base = replace(self, **{f.name: _copy.copy(getattr(self, f.name)) for f in fields(self)})
        return replace(base, **changes)
