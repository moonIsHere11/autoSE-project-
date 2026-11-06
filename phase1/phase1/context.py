"""Context management: keep the prompt small without losing what matters.
 1. every tool result is clipped at the source (tools.clip);
 2. old tool results / bulky tool-call arguments are elided once the history exceeds a budget;
 3. the agent's `notes` scratchpad is re-injected into the system prompt on every turn."""


def size(msgs):
    n = 0
    for m in msgs:
        n += len(m.get("content") or "")
        for c in m.get("tool_calls") or []:
            n += len(c["function"]["arguments"])
    return n


def compact(msgs, budget=36000, keep_last=8):
    """In place. Never removes messages (keeps tool_call/tool pairing valid), only shrinks them."""
    if size(msgs) <= budget:
        return 0
    names = {c["id"]: c["function"]["name"] for m in msgs for c in (m.get("tool_calls") or [])}
    cut = max(2, len(msgs) - keep_last)
    saved = 0
    for m in msgs[2:cut]:
        before = len(m.get("content") or "") + sum(len(c["function"]["arguments"]) for c in m.get("tool_calls") or [])
        if m["role"] == "tool" and len(m["content"]) > 200:
            m["content"] = f"[elided {len(m['content'])} chars of {names.get(m.get('tool_call_id'), 'tool')} output; re-run if needed]"
        elif m["role"] == "assistant":
            if len(m.get("content") or "") > 300:
                m["content"] = m["content"][:300] + "…"
            for c in m.get("tool_calls") or []:
                if len(c["function"]["arguments"]) > 300:
                    c["function"]["arguments"] = '{"elided":true}'
        after = len(m.get("content") or "") + sum(len(c["function"]["arguments"]) for c in m.get("tool_calls") or [])
        saved += before - after
    return saved
