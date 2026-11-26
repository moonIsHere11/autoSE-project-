"""Tool registry: schema + handler per tool, uniform dispatch (arg filtering, error wrapping, output clipping)."""
from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass
from typing import Any, Callable

S = {"type": "string"}
I = {"type": "integer"}  # noqa: E741
LIST_S = {"type": "array", "items": S}


def obj(required=(), **props) -> dict:
    """JSON-schema object shorthand: obj(required=['path'], path=S, content=S)."""
    return {"type": "object", "properties": props, "required": list(required)}


def clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n] + f"\n...[truncated {len(text) - n} chars; narrow your query]"


def load_adapter(spec: str, *args, **kwargs):
    """Instantiate 'package.module:Class'. This is how LLMs, verifiers and profiles are plugged in via config."""
    mod, _, attr = spec.partition(":")
    if not attr:
        raise ValueError(f"adapter spec must look like 'pkg.module:Class', got {spec!r}")
    return getattr(importlib.import_module(mod), attr)(*args, **kwargs)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable[..., Any]

    def schema(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": self.parameters}}


class ToolRegistry:
    def __init__(self, max_out: int = 5000):
        self.max_out = max_out
        self._tools: dict[str, Tool] = {}

    def add(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} already registered")
        self._tools[tool.name] = tool
        return tool

    def tool(self, name: str, description: str, parameters: dict | None = None):
        """Decorator: @registry.tool('read_file', 'Read a file', obj(['path'], path=S))"""
        def deco(fn):
            self.add(Tool(name, description, parameters or obj(), fn))
            return fn
        return deco

    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self, allow: set[str] | None = None) -> list[dict]:
        return [t.schema() for n, t in self._tools.items() if allow is None or n in allow]

    def call(self, name: str, args: dict | None) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"ERROR: unknown tool {name!r}. Available: {', '.join(self._tools)}"
        accepted = inspect.signature(tool.handler).parameters
        clean = {k: v for k, v in (args or {}).items() if k in accepted}  # small models add stray arguments
        try:
            return clip(str(tool.handler(**clean)), self.max_out)
        except TypeError as e:
            return f"ERROR: bad arguments for {name}: {e}"
        except Exception as e:  # tool failures go back to the model, never up the stack
            return f"ERROR: {type(e).__name__}: {e}"
