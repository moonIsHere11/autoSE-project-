"""Pydantic models of every file under kb/ (agreement 4.1, contract 1.1).

Version 1.1 is additive over 1.0: every new field is optional with a default, so a 1.0 consumer that
ignores unknown keys reads 1.1 files unchanged.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.1"

Extractor = Literal["strict", "tolerant", "cobc", "pattern", "catalog", "config"]
ParseStatus = Literal["strict", "tolerant", "failed", "not-parsed"]
FileKind = Literal["program", "copybook", "jcl", "other"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)


class Provenance(Model):
    file: str
    start_line: int
    end_line: int
    extractor: Extractor
    confidence: float = Field(ge=0.0, le=1.0)


# ---- target side -------------------------------------------------------------------------------
class Toolchain(Model):
    language: str
    version: str
    file_ext: str
    build_cmd: list[str]
    test_cmd: list[str]
    lint_cmd: list[str] | None
    runtime_dir: str


class Rule(Model):
    rule_id: str
    cobol_construct: str
    required_pattern: str
    example_cobol: str
    example_target: str
    gap_ids: list[str] = Field(default_factory=list)
    source: str | None = None


class Gap(Model):
    gap_id: str
    topic: str
    cobol_behavior: str
    target_default: str
    required_handling: str
    rule_ids: list[str]
    source: str | None = None


# ---- source side -------------------------------------------------------------------------------
class SourceSpan(Model):
    file: str
    start_line: int
    end_line: int


class Hazard(Model):
    gap_id: str
    line: int
    detail: str
    fields: list[str] = Field(default_factory=list)
    severity: Literal["high", "medium", "low"] = "medium"


class Unit(Model):
    unit_id: str
    kind: Literal["program", "section", "paragraph"]
    span: SourceSpan
    reads: list[str]
    writes: list[str]
    performs: list[str]
    calls: list[str]
    falls_through_to: str | None
    summary: str | None
    # 1.1 additions
    program: str | None = None
    section: str | None = None
    unsupported: list[str] = Field(default_factory=list)
    provenance: Provenance | None = None
    perform_thru: list[tuple[str, str]] = Field(default_factory=list)
    goes_to: list[str] = Field(default_factory=list)
    exits: list[str] = Field(default_factory=list)
    hazards: list[Hazard] = Field(default_factory=list)


class SemanticType(Model):
    kind: Literal["decimal", "alphanumeric", "group"]
    digits: int | None
    scale: int | None
    signed: bool | None
    length: int | None


class ConditionName(Model):
    name: str
    values: list[str]


class Field_(Model):
    """`Field` in the contract (renamed in Python only, to avoid shadowing pydantic.Field)."""

    field_id: str
    level: int
    parent: str | None
    pic: str | None
    usage: str
    semantic_type: SemanticType
    occurs: int | None
    initial_value: str | None
    # 1.1 additions
    program: str | None = None
    name: str | None = None
    category: str | None = None
    offset: int | None = None
    byte_length: int | None = None
    redefines: str | None = None
    occurs_depending_on: str | None = None
    condition_names: list[ConditionName] = Field(default_factory=list)
    section: Literal["working-storage", "local-storage", "linkage", "file"] | None = None
    provenance: Provenance | None = None


class Edge(Model):
    src: str
    dst: str
    kind: Literal["perform", "perform-thru", "goto", "fallthrough", "call", "exit"]
    line: int
    file: str
    resolution: Literal["static", "resolved-by-constant", "unresolved"]
    detail: str | None = None


class CallGraph(Model):
    schema_version: str = SCHEMA_VERSION
    edges: list[Edge]


class FieldFlow(Model):
    field_id: str
    writers: list[str]
    readers: list[str]


class FileCrud(Model):
    program: str
    file: str
    organization: str
    assign: str | None
    units: dict[str, list[Literal["C", "R", "U", "D"]]]


class DataFlow(Model):
    schema_version: str = SCHEMA_VERSION
    fields: list[FieldFlow]
    files: list[FileCrud]


class InventoryEntry(Model):
    path: str
    kind: FileKind
    subkind: str | None = None
    format: Literal["fixed", "free"] | None = None
    lines: int
    sha256: str
    copybooks: list[str] = Field(default_factory=list)
    calls: list[str] = Field(default_factory=list)
    programs: list[str] = Field(default_factory=list)
    jcl_steps: list[dict[str, str]] = Field(default_factory=list)
    parse_status: ParseStatus = "not-parsed"
    parse_reason: str | None = None


class Inventory(Model):
    schema_version: str = SCHEMA_VERSION
    files: list[InventoryEntry]


class UnattributedLine(Model):
    file: str
    line: int
    reason: str


class ProgramCoverage(Model):
    program: str
    file: str
    parse_status: ParseStatus
    lines_total: int
    lines_attributed: int
    lines_comment: int
    lines_blank: int
    unattributed: list[UnattributedLine]
    unsupported: dict[str, list[int]]
    unresolved_calls: list[str]
    parse_errors: list[str]
    facts_by_extractor: dict[str, int]


class Coverage(Model):
    schema_version: str = SCHEMA_VERSION
    programs: list[ProgramCoverage]
    rejected_files: list[dict[str, str]]


class ExtractorInfo(Model):
    name: str
    version: str


class CoverageSummary(Model):
    files: int
    programs: int
    parsed_strict: int
    parsed_tolerant: int
    failed: int
    lines_total: int
    lines_unattributed: int


class KbManifest(Model):
    schema_version: str
    kb_version: str
    source_hash: str
    target: Toolchain
    extractors: list[ExtractorInfo] = Field(default_factory=list)
    coverage_summary: CoverageSummary | None = None
