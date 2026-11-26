"""The architecture plan: what the human reviewer reads (via architecture.md) and what part 2 (migration order)
and the translators consume (architecture.json). An uploaded architecture must validate against this schema."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .graph import Evidence

SCHEMA_VERSION = "1.0"


@dataclass
class Assignment:
    program: str
    confidence: float
    evidence: list[Evidence] = field(default_factory=list)
    decided_by: str = "draft"          # draft | agent
    low_kb_confidence: bool = False


@dataclass
class Module:
    id: str
    name: str
    purpose: str
    kind: str                          # domain | utility | isolated
    programs: list[Assignment] = field(default_factory=list)
    local_types: list[str] = field(default_factory=list)
    owned_stores: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)


@dataclass
class SharedType:
    copybook: str
    type_name: str
    used_by: list[str]                 # module ids


@dataclass
class SharedCode:
    copybook: str
    module: str                        # where it is implemented once
    used_by: list[str]                 # program ids


@dataclass
class Store:
    id: str
    kind: str                          # dataset | table | private
    owner: str                         # module id
    readers: list[str]
    writers: list[str]
    interface: str
    shared_write: bool


@dataclass
class Job:
    id: str
    steps: list[dict]                  # step, order, program, module, reads, writes


@dataclass
class Edit:
    action: str
    args: dict
    reason: str
    evidence: list[str]


@dataclass
class OpenQuestion:
    kind: str     # uncertain_program | low_kb_confidence | isolated | shared_write | missing_kb_fact | review_incomplete
    subject: str
    detail: str


@dataclass
class ArchitecturePlan:
    schema_version: str = SCHEMA_VERSION
    modules: list[Module] = field(default_factory=list)
    shared_types: list[SharedType] = field(default_factory=list)
    shared_code: list[SharedCode] = field(default_factory=list)
    stores: list[Store] = field(default_factory=list)
    jobs: list[Job] = field(default_factory=list)
    layout: dict = field(default_factory=dict)
    edits: list[Edit] = field(default_factory=list)
    open_questions: list[OpenQuestion] = field(default_factory=list)
    inputs: dict = field(default_factory=dict)

    def module_of(self, program: str) -> Module:
        for m in self.modules:
            if any(a.program == program for a in m.programs):
                return m
        raise KeyError(f"program {program!r} is in no module")

    def module(self, module_id: str) -> Module:
        for m in self.modules:
            if m.id == module_id:
                return m
        raise KeyError(f"no module {module_id!r}; modules: {[m.id for m in self.modules]}")

    def program_ids(self) -> list[str]:
        return [a.program for m in self.modules for a in m.programs]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> ArchitecturePlan:
        def assignment(a: dict) -> Assignment:
            return Assignment(**{**a, "evidence": [Evidence(**e) for e in a.get("evidence", [])]})

        return cls(
            schema_version=d.get("schema_version", SCHEMA_VERSION),
            modules=[Module(**{**m, "programs": [assignment(a) for a in m.get("programs", [])]})
                     for m in d.get("modules", [])],
            shared_types=[SharedType(**x) for x in d.get("shared_types", [])],
            shared_code=[SharedCode(**x) for x in d.get("shared_code", [])],
            stores=[Store(**x) for x in d.get("stores", [])],
            jobs=[Job(**x) for x in d.get("jobs", [])],
            layout=dict(d.get("layout", {})),
            edits=[Edit(**x) for x in d.get("edits", [])],
            open_questions=[OpenQuestion(**x) for x in d.get("open_questions", [])],
            inputs=dict(d.get("inputs", {})),
        )
