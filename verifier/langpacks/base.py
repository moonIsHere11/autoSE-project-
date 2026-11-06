"""Language-pack interface (spec section 5). Any method may return `NotApplicable`."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from verifier.cobol.syntax import Program
from verifier.config import VerifierConfig
from verifier.manifest import Manifest, ProgramMap
from verifier.report.schema import Finding
from verifier.sandbox.docker_runner import DockerRunner


@dataclass(frozen=True)
class NotApplicable:
    reason: str


# ---------------------------------------------------------------------------------------------
# symbol index (filled by tree-sitter in each pack)
# ---------------------------------------------------------------------------------------------
@dataclass
class FieldSym:
    name: str
    type_text: str
    file: str
    line: int
    init_text: str | None = None


@dataclass
class MethodSym:
    name: str
    file: str
    line: int
    end_line: int
    params: list[str] = field(default_factory=list)
    is_static: bool = False


@dataclass
class TypeSym:
    """A class (Java/Python), or a package/struct (Go)."""

    name: str
    qualified: str
    file: str
    line: int
    methods: list[MethodSym] = field(default_factory=list)
    fields: list[FieldSym] = field(default_factory=list)
    has_main: bool = False


@dataclass
class Literal_:
    kind: str  # int | float | str
    text: str
    value: str  # normalised
    file: str
    line: int


@dataclass
class CallSite:
    callee: str  # e.g. "System.currentTimeMillis", "Runtime.getRuntime().exec", "open"
    file: str
    line: int
    args_text: list[str] = field(default_factory=list)
    string_args: list[str] = field(default_factory=list)


@dataclass
class CatchSite:
    types: list[str]
    file: str
    line: int
    swallows: bool


@dataclass
class SymbolIndex:
    files: dict[str, bytes] = field(default_factory=dict)
    types: list[TypeSym] = field(default_factory=list)
    literals: list[Literal_] = field(default_factory=list)
    calls: list[CallSite] = field(default_factory=list)
    imports: list[tuple[str, str, int]] = field(default_factory=list)  # (module, file, line)
    catches: list[CatchSite] = field(default_factory=list)
    news: list[CallSite] = field(default_factory=list)  # constructor calls (Java)
    float_uses: list[tuple[str, str, int]] = field(default_factory=list)  # (type text, file, line)
    parse_errors: list[str] = field(default_factory=list)

    def find_type(self, name: str) -> list[TypeSym]:
        from verifier.manifest import loose

        key = loose(name.split(".")[-1])
        return [t for t in self.types if loose(t.name) == key or t.qualified == name]

    def line_text(self, file: str, line: int) -> str:
        data = self.files.get(file)
        if data is None:
            return ""
        lines = data.decode("utf-8", errors="replace").splitlines()
        return lines[line - 1] if 0 < line <= len(lines) else ""


# ---------------------------------------------------------------------------------------------
# build / resolution results
# ---------------------------------------------------------------------------------------------
@dataclass
class BuildResult:
    ok: bool
    command: str
    output: str
    duration_s: float
    diagnostics: list[Finding] = field(default_factory=list)
    timed_out: bool = False
    tool_version: str = ""


@dataclass
class ResolvedProgram:
    program_id: str
    cobol_file: str
    type_sym: TypeSym | None
    run_command: str | None
    files: dict[str, str]  # SELECT name -> path in working dir
    units: dict[str, str | None]  # paragraph -> target symbol
    unit_locations: dict[str, MethodSym | None]
    fields: dict[str, dict[str, Any]]  # cobol field -> {"target":..., "declared":..., "target_type":...}
    source: str  # manifest | convention | mixed
    notes: list[str] = field(default_factory=list)


@dataclass
class PackContext:
    config: VerifierConfig
    runner: DockerRunner
    target_root: Path  # workspace copy of the target repo
    manifest: Manifest | None
    runtime_dir: Path | None  # host dir mounted at /opt/cobolrt


class LangPack(ABC):
    name: str = ""
    file_suffixes: tuple[str, ...] = ()

    # ---- T0a / T1 ------------------------------------------------------------------------
    @abstractmethod
    def build(self, ctx: PackContext) -> BuildResult: ...

    @abstractmethod
    def index(self, root: Path) -> SymbolIndex: ...

    @abstractmethod
    def resolve_program(
        self, ctx: PackContext, index: SymbolIndex, prog: Program, entry: ProgramMap | None
    ) -> ResolvedProgram: ...

    @abstractmethod
    def run_command(self, ctx: PackContext, resolved: ResolvedProgram) -> list[str] | NotApplicable: ...

    # ---- T0b -----------------------------------------------------------------------------
    @abstractmethod
    def static_rules(self) -> dict[str, Any]:
        """Language-specific tables used by tiers/t0_static.py."""

    # ---- T2 / T3 (Java first; others return NotApplicable until implemented) --------------
    def emit_reference(self, ir_unit: Any) -> Any:
        return NotApplicable(f"{self.name}: reference emitter not implemented")

    def make_equivalence_harness(self, unit: Any, mapping: Any) -> Any:
        return NotApplicable(f"{self.name}: equivalence harness not implemented")

    def run_symbolic(self, harness: Any, bound: int) -> Any:
        return NotApplicable(f"{self.name}: no symbolic checker")

    def instrument_contracts(self, unit: Any, contracts: Any) -> Any:
        return NotApplicable(f"{self.name}: contract checking not implemented")

    def check_contracts(self, *args: Any) -> Any:
        return NotApplicable(f"{self.name}: contract checking not implemented")

    def parse_counterexample(self, raw: Any) -> Any:
        return NotApplicable(f"{self.name}: no counterexample parser")

    def replay_concrete(self, *args: Any) -> Any:
        return NotApplicable(f"{self.name}: no concrete replay")


def rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
