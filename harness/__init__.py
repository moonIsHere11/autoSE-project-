"""Vanilla agent harness: loop, tool registry, privileges, prompts, context management, workspace, runner.
Domain knowledge (COBOL, Java) and the verifier live behind adapters; see harness/README.md."""
from .agent import Agent, AgentResult, AgentSpec
from .context import ContextManager, Scratchpad
from .loop import AgentLoop
from .policy import PolicyDecision, ToolPolicy
from .prompt import PromptBuilder
from .registry import Tool, ToolRegistry, load_adapter
from .runner import Runner
from .types import Candidate, Task, ToolEnv, Verdict
from .workspace import Workspace

__all__ = ["Agent", "AgentLoop", "AgentResult", "AgentSpec", "Candidate", "ContextManager", "PolicyDecision",
           "PromptBuilder", "Runner", "Scratchpad", "Task", "Tool", "ToolEnv", "ToolPolicy", "ToolRegistry",
           "Verdict", "Workspace", "load_adapter"]
