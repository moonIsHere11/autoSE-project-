"""The standard agent loop every agent in the harness uses (builders, planners, explorers, reviewers).

An Agent = an LLM + a ToolRegistry (what tools exist, maintained elsewhere) + an AgentSpec (everything that
makes this agent this agent: prompt sections, privileges, budgets, recovery limits, result schema).
Everything is changeable through methods, and hooks cover what methods do not:

    before_model(messages, state)            after_model(message, state)
    before_tool(name, args, state) -> None | dict (new args) | str (veto: becomes the tool result)
    after_tool(name, args, output, state) -> None | str (replacement output)
    on_text_reply(text, state)               on_stop(result)

One turn: render prompt -> compact history -> offer the tools the policy allows -> model call -> for each tool
call: policy check (again: a tool that was not offered is never run) -> hooks -> dispatch -> stop checks.
"""
from __future__ import annotations

import copy as _copy
import json
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from .context import ContextManager
from .events import EventLog
from .llm import LLMError
from .policy import ToolPolicy
from .prompt import PromptBuilder
from .registry import Tool, ToolRegistry, clip
from .schema_check import validate

NUDGE = "You must act through tool calls. Do not reply with plain text; call a tool to make progress."
MALFORMED = ("Your last tool call was malformed JSON and was rejected. "
             "Call the tool again with valid JSON arguments (use {} when there are none).")
HOOKS = ("before_model", "after_model", "before_tool", "after_tool", "on_text_reply", "on_stop")


@dataclass
class AgentSpec:
    name: str
    prompt: PromptBuilder
    policy: ToolPolicy = field(default_factory=ToolPolicy)
    max_steps: int = 40
    max_tokens: int | None = None
    context_budget: int = 36000
    keep_last: int | None = None
    max_malformed: int = 6
    max_nudges: int = 3
    nudge: str = NUDGE
    result_schema: dict | None = None
    finish_tool: str = "finish"

    def copy(self, **changes) -> AgentSpec:
        base = replace(self, prompt=self.prompt.copy(), policy=self.policy.copy(),
                       result_schema=_copy.deepcopy(self.result_schema))
        return replace(base, **changes)


@dataclass
class AgentResult:
    stop_reason: str
    output: dict | None
    steps: int
    usage: dict[str, int]
    messages: list[dict]
    state: dict


class Agent:
    def __init__(self, llm, registry: ToolRegistry, spec: AgentSpec, *, events: EventLog | None = None,
                 log: Callable = lambda *a: None, approve: Callable[[str, dict], bool] | None = None):
        self.llm, self.registry, self.spec = llm, registry, spec
        self.events, self.log, self.approve = events, log, approve
        self.context = ContextManager(spec.context_budget, spec.keep_last)
        self._stops: list[tuple[str, Callable[[dict], bool]]] = []
        self._hooks: dict[str, list[Callable]] = {h: [] for h in HOOKS}
        self._usage = {"tokens_in": 0, "tokens_out": 0}  # live during run(); sub-agents add to it

    # ---- configuration ----
    def set_system_prompt(self, text: str) -> None:
        self.spec.prompt = PromptBuilder()
        self.spec.prompt.set("system", text)

    def add_prompt_section(self, name: str, content, *, before: str | None = None, after: str | None = None) -> None:
        self.spec.prompt.set(name, content, before=before, after=after)

    def remove_prompt_section(self, name: str) -> None:
        self.spec.prompt.remove(name)

    def set_policy(self, policy: ToolPolicy) -> None:
        self.spec.policy = policy

    def allow_tools(self, *names: str) -> None:
        self.spec.policy.deny -= set(names)
        if self.spec.policy.allow is not None:
            self.spec.policy.allow |= set(names)

    def deny_tools(self, *names: str) -> None:
        self.spec.policy.deny |= set(names)

    def set_budget(self, max_steps: int | None = None, max_tokens: int | None = None) -> None:
        if max_steps is not None:
            self.spec.max_steps = max_steps
        if max_tokens is not None:
            self.spec.max_tokens = max_tokens

    def set_context(self, manager: ContextManager) -> None:
        self.context = manager

    def add_stop_condition(self, name: str, fn: Callable[[dict], bool]) -> None:
        self._stops.append((name, fn))

    def on(self, event: str, hook: Callable) -> None:
        if event not in self._hooks:
            raise ValueError(f"unknown hook {event!r}; one of {HOOKS}")
        self._hooks[event].append(hook)

    def expect_result(self, schema: dict) -> None:
        self.spec.result_schema = schema

    # ---- tools ----
    def _finish_tool(self) -> Tool | None:
        if self.spec.result_schema is None:
            return None
        return Tool(self.spec.finish_tool, "Call once you are done, with your final result. The task ends here.",
                    self.spec.result_schema, lambda **kw: "accepted", frozenset({"finish"}))

    def _offered(self) -> list[Tool]:
        out = [t for t in self.registry.tools() if self.spec.policy.offered(t) and t.name != self.spec.finish_tool]
        finish = self._finish_tool()
        return out + ([finish] if finish else [])

    def offered_tools(self) -> list[str]:
        return [t.name for t in self._offered()]

    def _dispatch(self, name: str, args: dict, counts: dict[str, int], state: dict) -> str:
        tool = self.registry.get(name)
        if tool is None or name == self.spec.finish_tool:
            return f"ERROR: unknown tool {name!r}. Available: {', '.join(self.offered_tools())}"
        decision = self.spec.policy.check(tool, args, counts)
        if decision.action == "ask":
            ok = self.approve is not None and self.approve(name, args)
            decision = replace(decision, action="allow" if ok else "deny",
                               reason="" if ok else f"{name} was not approved")
        self._emit("tool_called", tool=name, decision=decision.action)
        if decision.action == "deny":
            return f"ERROR: {decision.reason}"
        for hook in self._hooks["before_tool"]:
            r = hook(name, args, state)
            if isinstance(r, str):
                return r
            if isinstance(r, dict):
                args = r
        counts[name] = counts.get(name, 0) + 1
        out = self.registry.call(name, args)
        for hook in self._hooks["after_tool"]:
            r = hook(name, args, out, state)
            if isinstance(r, str):
                out = r
        return out

    # ---- the loop ----
    def _emit(self, kind: str, **data: Any) -> None:
        if self.events is not None:
            self.events.emit(kind, unit_id=self.spec.name, **data)

    def _stop(self, reason: str, output, steps: int, msgs: list[dict], state: dict) -> AgentResult:
        result = AgentResult(reason, output, steps, dict(self._usage), msgs, state)
        self._emit("agent_stopped", reason=reason, steps=steps)
        self.log(f"  [{self.spec.name}] stopped: {reason} after {steps} step(s)")
        for hook in self._hooks["on_stop"]:
            hook(result)
        return result

    def run(self, message: str, state: dict | None = None) -> AgentResult:
        state = {} if state is None else state
        spec = self.spec
        msgs = [{"role": "system", "content": ""}, {"role": "user", "content": message}]  # rendered per turn
        self._usage = {"tokens_in": 0, "tokens_out": 0}
        counts: dict[str, int] = {}
        steps = nudges = malformed = 0
        while True:
            if steps >= spec.max_steps:
                return self._stop("max_steps", None, steps, msgs, state)
            if spec.max_tokens is not None and self._usage["tokens_in"] + self._usage["tokens_out"] >= spec.max_tokens:
                return self._stop("max_tokens", None, steps, msgs, state)
            steps += 1
            msgs[0]["content"] = spec.prompt.render()
            saved = self.context.prepare(msgs)
            if saved:
                self._emit("context_compacted", chars_saved=saved)
            for hook in self._hooks["before_model"]:
                hook(msgs, state)
            try:
                msg, usage = self.llm.chat(msgs, [t.schema() for t in self._offered()])
            except LLMError as e:
                if e.recoverable and malformed < spec.max_malformed:
                    malformed += 1
                    msgs.append({"role": "user", "content": MALFORMED})
                    continue
                return self._stop(f"llm_error: {e}", None, steps, msgs, state)
            self._usage["tokens_in"] += usage.get("prompt_tokens") or 0
            self._usage["tokens_out"] += usage.get("completion_tokens") or 0
            self._emit("llm_usage", model=getattr(self.llm, "model", "?"),
                       tokens_in=usage.get("prompt_tokens"), tokens_out=usage.get("completion_tokens"))
            for hook in self._hooks["after_model"]:
                hook(msg, state)
            calls = msg.get("tool_calls") or []
            entry: dict = {"role": "assistant", "content": msg.get("content") or ""}
            if calls:
                entry["tool_calls"] = calls
            msgs.append(entry)
            if not calls:
                for hook in self._hooks["on_text_reply"]:
                    hook(entry["content"], state)
                if nudges >= spec.max_nudges:
                    return self._stop("gave_up", None, steps, msgs, state)
                nudges += 1
                msgs.append({"role": "user", "content": spec.nudge})
                continue
            output = None
            for c in calls:
                name = c["function"]["name"]
                try:
                    args = json.loads(c["function"]["arguments"] or "{}")
                    bad_json = not isinstance(args, dict)
                except json.JSONDecodeError:
                    args, bad_json = {}, True
                if bad_json:
                    out = "ERROR: arguments were not a valid JSON object; call the tool again."
                elif name == spec.finish_tool and spec.result_schema is not None:
                    errors = validate(args, spec.result_schema)
                    out = "ERROR: invalid result: " + "; ".join(errors) if errors else "accepted"
                    if not errors:
                        output = args
                else:
                    out = clip(self._dispatch(name, args, counts, state), self.registry.max_out)
                self.log(f"  [{spec.name}] {name} -> {out[:80]!r}")
                msgs.append({"role": "tool", "tool_call_id": c["id"], "content": out})
            if output is not None:
                return self._stop("finished", output, steps, msgs, state)
            for stop_name, fn in self._stops:
                if fn(state):
                    return self._stop(stop_name, None, steps, msgs, state)
