"""Context management, independent of any domain:
 1. tool output is clipped at the registry (ToolRegistry.max_out);
 2. once the history exceeds a character budget, old tool results and bulky tool-call arguments are elided
    (messages are shrunk, never removed, so every tool_call keeps its matching tool result);
 3. a Scratchpad of agent-written notes is re-pinned into the system prompt on every turn."""
from __future__ import annotations

from pathlib import Path


class Scratchpad:
    def __init__(self, path: Path, limit: int = 3000):
        self.path, self.limit = Path(path), limit

    def append(self, text: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a") as f:
            f.write(text.strip() + "\n")

    def read(self) -> str:
        return self.path.read_text()[-self.limit:] if self.path.exists() else ""


def size(msgs: list[dict]) -> int:
    n = 0
    for m in msgs:
        n += len(m.get("content") or "")
        for c in m.get("tool_calls") or []:
            n += len(c["function"]["arguments"])
    return n


def elide(msgs: list[dict], budget: int, keep_last: int) -> int:
    """In place; returns characters saved. msgs[0] is the system prompt, msgs[1] the task message."""
    if size(msgs) <= budget:
        return 0
    names = {c["id"]: c["function"]["name"] for m in msgs for c in (m.get("tool_calls") or [])}
    cut = max(2, len(msgs) - keep_last)
    before = size(msgs)
    for m in msgs[2:cut]:
        if m["role"] == "tool" and len(m["content"]) > 200:
            m["content"] = f"[elided {len(m['content'])} chars of {names.get(m.get('tool_call_id'), 'tool')} output; re-run if needed]"
        elif m["role"] == "assistant":
            if len(m.get("content") or "") > 300:
                m["content"] = m["content"][:300] + "…"
            for c in m.get("tool_calls") or []:
                if len(c["function"]["arguments"]) > 300:
                    c["function"]["arguments"] = '{"elided":true}'
    return before - size(msgs)


class ContextManager:
    def __init__(self, budget: int = 36000, keep_last: int | None = None):
        self.budget = budget
        self.keep_last = keep_last if keep_last is not None else (5 if budget < 20000 else 8)

    def prepare(self, msgs: list[dict]) -> int:
        return elide(msgs, self.budget, self.keep_last)
