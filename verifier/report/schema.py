"""Report data model (schema_version 1.0). See docs/INTERFACE.md section 4.

Principles encoded here:
* exactly one of six statuses per check;
* every PASS carries a `scope` (what, inputs/bound, oracle, tool + version, commands);
* every FAIL carries counterexamples that were confirmed by concrete execution;
* anything stubbed has `stub=True` and is rendered as STUB.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.0"


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    SKIPPED = "SKIPPED"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class ToolInfo(_Model):
    name: str
    version: str


class Scope(_Model):
    level: Literal["program", "unit"] = "unit"
    what: str = ""
    inputs: str | None = None
    bound: str | None = None
    domain: str | None = None
    oracle: str | None = None
    tools: list[ToolInfo] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)


class SourceRef(_Model):
    file: str
    line: int
    text: str = ""
    column: int | None = None


class Finding(_Model):
    check: str
    severity: Literal["ERROR", "WARNING", "INFO"]
    message: str
    file: str | None = None
    line: int | None = None
    column: int | None = None
    excerpt: str | None = None
    cobol_ref: str | None = None
    stub: bool = False


class Check(_Model):
    name: str
    status: Status
    reason: str | None = None
    findings: list[Finding] = Field(default_factory=list)
    stub: bool = False
    duration_s: float = 0.0


class FieldValue(_Model):
    field: str
    value: str
    pic: str | None = None
    location: str | None = None


class FieldDiff(_Model):
    location: str
    field: str | None = None
    pic: str | None = None
    expected: str
    actual: str


class Classification(_Model):
    label: str
    confidence: Literal["likely"] = "likely"
    explanation: str


class Counterexample(_Model):
    id: str
    source_tier: str
    signature: str
    case_id: str | None = None
    case_dir: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    input_fields: list[FieldValue] = Field(default_factory=list)
    expected: dict[str, Any] = Field(default_factory=dict)
    actual: dict[str, Any] = Field(default_factory=dict)
    diffs: list[FieldDiff] = Field(default_factory=list)
    shrunk: bool = False
    shrink_steps: int = 0
    classification: Classification | None = None
    cobol_statements: list[SourceRef] = Field(default_factory=list)
    field_mapping: dict[str, Any] | None = None
    target_location: SourceRef | None = None
    repro: str = ""
    confirmed_concretely: bool = False


class FailureSignature(_Model):
    signature: str
    kind: str
    location: str
    count: int
    severity: int
    example_case: str
    counterexample_id: str | None = None


class Coverage(_Model):
    paragraph: float
    statement: float
    uncovered: list[str] = Field(default_factory=list)
    covered_paragraphs: list[str] = Field(default_factory=list)
    minimised_case_count: int | None = None


class Exclusion(_Model):
    case_id: str
    reason: str


class TierResult(_Model):
    status: Status
    reason: str | None = None
    stub: bool = False
    method: str | None = None
    scope: Scope | None = None
    duration_s: float = 0.0
    checks: list[Check] = Field(default_factory=list)
    cases_run: int | None = None
    cases_failed: int | None = None
    cases_excluded: int | None = None
    exclusions: list[Exclusion] = Field(default_factory=list)
    coverage: Coverage | None = None
    unit_covered: bool | None = None
    pass_fraction: float | None = None
    failure_signatures: list[FailureSignature] = Field(default_factory=list)
    counterexamples: list[Counterexample] = Field(default_factory=list)
    bound: str | None = None
    vacuity: dict[str, Any] | None = None
    mutation_kill_rate: float | None = None
    sub: dict[str, TierResult] = Field(default_factory=dict)
    details: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _honesty(self) -> TierResult:
        needs_reason = {Status.ERROR, Status.TIMEOUT, Status.NOT_APPLICABLE, Status.SKIPPED}
        if self.status in needs_reason and not self.reason:
            raise ValueError(f"status {self.status.value} requires a reason")
        if self.status == Status.PASS and self.scope is None and not self.stub:
            raise ValueError("a PASS must record its scope")
        return self

    @staticmethod
    def skipped(reason: str) -> TierResult:
        return TierResult(status=Status.SKIPPED, reason=reason)

    @staticmethod
    def not_applicable(reason: str, method: str | None = None) -> TierResult:
        return TierResult(status=Status.NOT_APPLICABLE, reason=reason, method=method)

    @staticmethod
    def error(reason: str, method: str | None = None) -> TierResult:
        return TierResult(status=Status.ERROR, reason=reason, method=method)


class Acceptance(_Model):
    accepted: bool
    tiers_considered: list[str]
    reasons: list[str] = Field(default_factory=list)
    policy: dict[str, Any] = Field(default_factory=dict)


class UnitResult(_Model):
    id: str
    program: str
    paragraph: str
    target_symbol: str | None = None
    level: int = -1
    evidence: list[str] = Field(default_factory=list)
    accepted: bool = False
    acceptance: Acceptance | None = None
    score: float = 0.0
    tiers: dict[str, TierResult] = Field(default_factory=dict)
    integrity_clean: bool = True
    toolchain: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    repro: list[str] = Field(default_factory=list)


class ProgramResult(_Model):
    id: str
    cobol_file: str
    paragraphs: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    nondeterminism: list[str] = Field(default_factory=list)
    channels: dict[str, Any] = Field(default_factory=dict)
    target: dict[str, Any] = Field(default_factory=dict)
    tiers: dict[str, TierResult] = Field(default_factory=dict)


class RunInfo(_Model):
    cobol: str
    target: str
    lang: str
    mode: Literal["fast", "full"]
    tiers: list[int]
    seed: int
    iteration: int
    effective_seed: int
    previous_report: str | None = None
    manifest: str | None = None
    units_filter: list[str] | None = None
    argv: list[str] = Field(default_factory=list)


class Summary(_Model):
    units: int = 0
    accepted: int = 0
    level_histogram: dict[str, int] = Field(default_factory=dict)
    pct_units_at_least_level: dict[str, float] = Field(default_factory=dict)
    evidence_histogram: dict[str, int] = Field(default_factory=dict)
    tier_timings_s: dict[str, float] = Field(default_factory=dict)
    stubs: list[str] = Field(default_factory=list)
    programs: int = 0
    programs_out_of_scope: int = 0


class Report(_Model):
    schema_version: str = SCHEMA_VERSION
    verifier_version: str
    generated_at: str
    run: RunInfo
    toolchain: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    programs: list[ProgramResult] = Field(default_factory=list)
    units: list[UnitResult] = Field(default_factory=list)
    summary: Summary = Field(default_factory=Summary)
    errors: list[str] = Field(default_factory=list)

    def to_json(self) -> str:
        return self.model_dump_json(indent=2, exclude_none=True)

    @staticmethod
    def load(path: str) -> Report:
        with open(path, encoding="utf-8") as fh:
            return Report.model_validate_json(fh.read())
