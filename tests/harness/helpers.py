"""Shared test doubles: a scripted LLM and a tool-call message builder (no network)."""
import json


def call(name, args, i=0):
    """An assistant message carrying one tool call."""
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def text(content):
    return {"role": "assistant", "content": content}


class ScriptedLLM:
    """Replays `steps` in order. A step is a message, an Exception to raise, or a callable(msgs) -> message.
    Records the last message and the tool names offered on every call."""
    model = "scripted"

    def __init__(self, steps, usage=None):
        self.steps, self.i, self.seen, self.offered = list(steps), 0, [], []
        self.usage = usage or {}

    def chat(self, msgs, tools):
        self.seen.append(msgs[-1])
        self.offered.append([t["function"]["name"] for t in tools or []])
        if self.i >= len(self.steps):
            raise AssertionError(f"ScriptedLLM ran out of steps after {self.i} calls")
        step = self.steps[self.i]
        self.i += 1
        if isinstance(step, Exception):
            raise step
        return (step(msgs) if callable(step) else step), dict(self.usage)
