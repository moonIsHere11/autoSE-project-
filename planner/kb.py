"""What the planner needs from the knowledge base (the KB contract), as plain records.

The planner reads facts only through a KnowledgeSource. `FixtureKb` reads one JSON file (tests, hand-made
estates); `planner.kb_phase0.Phase0Kb` reads Phase 0's kb/ files. docs/phase2/KB_CONTRACT.md lists, for the KB
team, which of these facts exist today and which the plan depends on most.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Program:
    id: str
    file: str                       # relative to source_root()
    loc: int
    kind: str                       # batch | online | subprogram
    confidence: float               # 1.0 = facts from the strict parser; lower = tolerant/heuristic facts
    copybooks: tuple[str, ...] = ()
    calls: tuple[str, ...] = ()     # static CALL / LINK / XCTL targets
    identifiers: tuple[str, ...] = ()  # paragraph and data item names


@dataclass(frozen=True)
class Copybook:
    name: str
    kind: str                       # record (data layout) | code (shared procedure text)


@dataclass(frozen=True)
class StoreUse:
    program: str
    store: str                      # dataset name, table name, or PROGRAM:ASSIGN for an unresolved file
    store_kind: str                 # dataset | table | private
    mode: str                       # read | write


@dataclass(frozen=True)
class JobStep:
    job: str
    step: str
    order: int                      # 1-based position in the job
    program: str | None             # None when the KB cannot say which program the step runs
    reads: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()


class KnowledgeSource(Protocol):
    def programs(self) -> list[Program]: ...
    def copybooks(self) -> dict[str, Copybook]: ...
    def store_uses(self) -> list[StoreUse]: ...
    def job_steps(self) -> list[JobStep]: ...
    def units(self, program_id: str) -> list[dict]: ...
    def source_root(self) -> Path: ...
    def kb_version(self) -> str: ...


class FixtureKb:
    """A whole estate in one JSON file: {kb_version, source_root, programs, copybooks, store_uses, job_steps, units}."""

    def __init__(self, path: Path):
        self.path = Path(path)
        d = json.loads(self.path.read_text())
        self._version = d.get("kb_version", "fixture")
        self._root = (self.path.parent / d.get("source_root", ".")).resolve()
        self._programs = [Program(**{**p, "copybooks": tuple(p.get("copybooks", ())), "calls": tuple(p.get("calls", ())),
                                     "identifiers": tuple(p.get("identifiers", ()))}) for p in d["programs"]]
        self._copybooks = {c["name"]: Copybook(c["name"], c["kind"]) for c in d.get("copybooks", [])}
        self._uses = [StoreUse(**u) for u in d.get("store_uses", [])]
        self._steps = sorted((JobStep(**{**s, "reads": tuple(s.get("reads", ())), "writes": tuple(s.get("writes", ()))})
                              for s in d.get("job_steps", [])), key=lambda s: (s.job, s.order))
        self._units = d.get("units", {})

    def programs(self) -> list[Program]:
        return list(self._programs)

    def copybooks(self) -> dict[str, Copybook]:
        return dict(self._copybooks)

    def store_uses(self) -> list[StoreUse]:
        return list(self._uses)

    def job_steps(self) -> list[JobStep]:
        return list(self._steps)

    def units(self, program_id: str) -> list[dict]:
        return list(self._units.get(program_id, []))

    def source_root(self) -> Path:
        return self._root

    def kb_version(self) -> str:
        return self._version
