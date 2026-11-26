"""Stage B: `cobc -E` (COPY expansion, line mapping) + the verifier's lexer and parser (ADR-0001).

A file the strict front end rejects (cobc -E error, lexer/parser exception) goes to the tolerant
fallback (ADR-0002). A program that parses with recoverable `parse_errors` stays strict; its errors
become coverage gaps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from phase0.schema import InventoryEntry
from phase0.toolbox import Toolbox
from verifier.cobol.ir import IrProgram, lower_program
from verifier.cobol.lexer import LexError, Token, tokenize
from verifier.cobol.parser import ParseError, parse_source, split_programs
from verifier.cobol.preprocess import Preprocessed, preprocess_all
from verifier.cobol.syntax import Program
from verifier.config import CobolConfig


@dataclass
class StrictProgram:
    source: str  # path under source/ of the compiled file
    program: Program
    ir: IrProgram
    tokens: list[Token]  # this program's tokens (original file/line on each)
    pre: Preprocessed


@dataclass
class Rejected:
    source: str
    reason: str


@dataclass
class ParseResult:
    strict: list[StrictProgram] = field(default_factory=list)
    rejected: list[Rejected] = field(default_factory=list)


def program_files(inventory: list[InventoryEntry]) -> list[str]:
    return [e.path for e in inventory if e.kind == "program"]


def copybook_dir_names(inventory: list[InventoryEntry]) -> list[str]:
    """Names of directories holding copybooks (by content), beyond the verifier's defaults."""
    names: set[str] = set()
    for e in inventory:
        parent = Path(e.path).parent
        if e.kind == "copybook" and parent.name:
            names.add(parent.name)
    return sorted(names)


def cobol_config(toolbox: Toolbox, inventory: list[InventoryEntry]) -> CobolConfig:
    """The verifier's CobolConfig with copybook directories appended AFTER its own: a program the
    verifier can preprocess resolves every COPY exactly as before (earlier -I wins); a program
    whose copybooks live elsewhere (CardDemo `cpy-bms/`) now preprocesses too."""
    cfg = toolbox.config.cobol
    extra = [d for d in copybook_dir_names(inventory) if d not in cfg.copy_dirs]
    return cfg.model_copy(update={"copy_dirs": [*cfg.copy_dirs, *extra]})


def parse_programs(toolbox: Toolbox, source: Path, inventory: list[InventoryEntry]) -> ParseResult:
    files = program_files(inventory)
    pre = preprocess_all(toolbox.runner, cobol_config(toolbox, inventory), source, files, toolbox.cache_dir)
    out = ParseResult()
    for rel in files:
        p = pre[rel]
        if not p.ok:
            out.rejected.append(Rejected(rel, "cobc -E: " + first_line(p.diagnostics)))
            continue
        parsed = parse_one(rel, p)
        if isinstance(parsed, Rejected):
            out.rejected.append(parsed)
        else:
            out.strict.extend(parsed)
    return out


def parse_one(rel: str, pre: Preprocessed) -> list[StrictProgram] | Rejected:
    try:
        toks = tokenize(pre.lines)
        programs = parse_source(toks, rel)
    except (LexError, ParseError) as exc:
        return Rejected(rel, f"parser: {exc}")
    chunks = split_programs(toks)
    out: list[StrictProgram] = []
    for prog, chunk in zip(programs, chunks, strict=True):
        out.append(StrictProgram(rel, prog, lower_program(prog), chunk, pre))
    return out


def first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:300]
    return "failed without diagnostics"
