"""The vanilla agent loop: model -> tool calls -> tool results -> ... until `done()` or the step budget ends.
Handles malformed model output (recoverable LLM errors), text-only replies (nudges), context compaction."""
from __future__ import annotations

import json
from typing import Callable

from .context import ContextManager
from .events import EventLog
from .llm import LLMError
from .registry import ToolRegistry

NUDGE = ("You must act through tool calls. Do not reply with plain text; call a tool to make progress.")
MALFORMED = ("Your last tool call was malformed JSON and was rejected. "
             "Call the tool again with valid JSON arguments (use {} when there are none).")


class AgentLoop:
    def __init__(self, llm, registry: ToolRegistry, context: ContextManager, events: EventLog, *,
                 allow: set[str] | None = None, label: str | None = None, log: Callable = print,
                 max_malformed: int = 6, max_nudges: int = 3, nudge: str = NUDGE):
        self.llm, self.registry, self.context, self.events = llm, registry, context, events
        self.allow, self.label, self.log = allow, label, log
        self.max_malformed, self.max_nudges, self.nudge = max_malformed, max_nudges, nudge

    def run(self, system_fn: Callable[[], str], user_msg: str, done: Callable[[], bool], max_steps: int = 40) -> str:
        """Returns why it stopped: 'done' | 'max_steps' | 'gave_up' | 'llm_error: ...'."""
        msgs = [{"role": "system", "content": system_fn()}, {"role": "user", "content": user_msg}]
        tools = self.registry.schemas(self.allow)
        nudges = malformed = 0
        for _ in range(max_steps):
            msgs[0]["content"] = system_fn()  # re-pin the latest scratchpad notes
            saved = self.context.prepare(msgs)
            if saved:
                self.events.emit("context_compacted", unit_id=self.label, chars_saved=saved)
            try:
                msg, usage = self.llm.chat(msgs, tools)
            except LLMError as e:
                if e.recoverable and malformed < self.max_malformed:
                    malformed += 1
                    msgs.append({"role": "user", "content": MALFORMED})
                    self.log(f"  [{self.label}] malformed model output, retrying ({malformed})")
                    continue
                self.log(f"[harness] LLM error: {e}")
                return f"llm_error: {e}"
            self.events.emit("llm_usage", unit_id=self.label, model=self.llm.model,
                             tokens_in=usage.get("prompt_tokens"), tokens_out=usage.get("completion_tokens"))
            calls = msg.get("tool_calls") or []
            entry = {"role": "assistant", "content": msg.get("content") or ""}
            if calls:
                entry["tool_calls"] = calls
            msgs.append(entry)
            if not calls:
                self.log(f"  [{self.label}] text reply: {entry['content'][:120]!r}")
                if nudges >= self.max_nudges:
                    return "gave_up"
                nudges += 1
                msgs.append({"role": "user", "content": self.nudge})
                continue
            for c in calls:
                try:
                    args = json.loads(c["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                out = self.registry.call(c["function"]["name"], args)
                self.log(f"  [{self.label}] {c['function']['name']}({', '.join(f'{k}={str(v)[:30]}' for k, v in args.items())})"
                         f" -> {out[:80]!r}")
                msgs.append({"role": "tool", "tool_call_id": c["id"], "content": out})
            if done():
                return "done"
        return "max_steps"
