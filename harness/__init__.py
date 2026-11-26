"""Vanilla agent harness: loop, tool registry, context management, workspace, runner.
Domain knowledge (COBOL, Java) and the verifier live behind adapters; see harness/README.md."""
from .context import ContextManager, Scratchpad
from .loop import AgentLoop
from .registry import Tool, ToolRegistry, load_adapter
from .runner import Runner
from .types import Candidate, Task, ToolEnv, Verdict
from .workspace import Workspace

__all__ = ["AgentLoop", "Candidate", "ContextManager", "Runner", "Scratchpad", "Task", "Tool", "ToolEnv",
           "ToolRegistry", "Verdict", "Workspace", "load_adapter"]
