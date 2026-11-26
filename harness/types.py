"""Contracts between the harness core and everything pluggable (LLM, verifier, domain profile, tool packs).
The core imports nothing domain-specific; adapters import these types, never the other way round."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass
class Task:
    """One unit of work for the agent (e.g. one COBOL program)."""
    id: str
    title: str = ""
    scope: list[str] = field(default_factory=list)   # ids handed to the verifier; defaults to [id]
    data: dict[str, Any] = field(default_factory=dict)  # profile-specific payload (file, loc, ...)

    def __post_init__(self):
        self.scope = self.scope or [self.id]


@dataclass
class Candidate:
    """An immutable snapshot the verifier is asked to judge."""
    workspace: Path
    submission_id: str
    task_id: str
    scope: list[str]
    regression: list[str]
    attempt: int
    required_tier: str


@dataclass
class Verdict:
    """Verifier answer, already in the agreement's report vocabulary."""
    status: str                      # green | red | error
    summary: str = ""
    findings: list[dict] = field(default_factory=list)
    units: list[dict] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @property
    def green(self) -> bool:
        return self.status == "green"


class LLM(Protocol):
    model: str

    def chat(self, messages: list[dict], tools: list[dict] | None) -> tuple[dict, dict]:
        """-> (assistant message with optional tool_calls, usage dict). Raise harness.llm.LLMError on failure."""


class Verifier(Protocol):
    def verify(self, candidate: Candidate) -> Verdict: ...


@dataclass
class ToolEnv:
    """What a tool pack may use when it registers its tools for one task."""
    workspace: Any                   # harness.workspace.Workspace
    config: dict
    task: Task
    accepted: list[str]
    state: dict                      # per-task mutable state (attempts, green, ...)


class ToolPack(Protocol):
    def register(self, registry: Any, env: ToolEnv) -> None: ...


class Profile(Protocol):
    """A domain bundle: which tasks exist, how to prompt for them, which tools help."""

    def tasks(self, workspace: Any, only: list[str] | None = None) -> list[Task]: ...
    def system_prompt(self, task: Task, notes: str) -> str: ...
    def first_message(self, task: Task, accepted: list[str], config: dict) -> str: ...
    def toolpacks(self) -> list[ToolPack]: ...
