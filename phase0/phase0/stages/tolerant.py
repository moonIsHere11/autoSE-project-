"""ADR-0002 fallback: Phase 1's regex-level analyser for files the strict front end rejects
(typically CICS / SQL programs). Read-only use of phase1/; every fact is tagged
`extractor: "tolerant"` with lower confidence and counted separately in coverage.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from phase0.schema import Field_, Hazard, Provenance, SemanticType, SourceSpan, Unit
from verifier.cobol.datadiv import DataDivisionError, parse_pic

REPO = Path(__file__).resolve().parents[3]
CONFIDENCE = 0.6


def _phase1() -> Any:
    """Phase 1's analyser modules (phase1/ is not an installed package)."""
    path = str(REPO / "phase1")
    if path not in sys.path:
        sys.path.append(path)
    from phase1.cobol import analyzer, repo, source

    return analyzer, repo, source


@dataclass
class TolerantProgram:
    source: str
    program: str
    units: list[Unit] = field(default_factory=list)
    fields: list[Field_] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    covered: set[tuple[str, int]] = field(default_factory=set)
    structure: set[tuple[str, int]] = field(default_factory=set)


def analyse_file(source_root: Path, rel: str, multi: bool) -> list[TolerantProgram]:
    analyzer, repo, source = _phase1()
    resolver = source.CopyResolver(source_root)
    lines, header = source.load_file(source_root / rel, rel)
    out: list[TolerantProgram] = []
    for chunk in repo.split_programs(lines):
        used: list[str] = []
        expanded = resolver.expand(chunk, used=used)
        prog, units, fields = analyzer.analyse_program(expanded, header, used)
        pid = (prog["program_id"] or Path(rel).stem).upper()
        prefix = ""
        if multi:
            prefix = pid + "."
        tp = TolerantProgram(rel, pid)
        tp.fields = [tolerant_field(f, pid, prefix) for f in fields if f["name"] != "FILLER"]
        tp.units = [tolerant_unit(u, pid, prefix) for u in units]
        tp.calls = sorted({c for u in tp.units for c in u.calls})
        for ln in expanded:
            tp.covered.add((ln.file, ln.no))
        tp.structure = structure_lines(expanded)
        for f in fields:
            if f["name"] == "FILLER":
                sp = f["span"]
                tp.structure |= {(sp["file"], n) for n in range(sp["start_line"], sp["end_line"] + 1)}
        out.append(tp)
    return out


DIVISION = re.compile(r"^\s*(IDENTIFICATION|ID|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION\b", re.I)
HEADER = re.compile(r"\b(DIVISION|SECTION)\s*\.", re.I)
ENTRY_START = re.compile(r"^\s*(FD|SD|88|66)\s", re.I)


def structure_lines(lines: list[Any]) -> set[tuple[str, int]]:
    """Lines the tolerant analyser reads but records no fact for: identification and environment
    text, division/section headers, FD/SD entries and 88/66 entries (to their period)."""
    out: set[tuple[str, int]] = set()
    division = "IDENTIFICATION"
    open_entry = False
    for ln in lines:
        m = DIVISION.match(ln.text)
        if m:
            division = m.group(1).upper()
        if division in ("IDENTIFICATION", "ID", "ENVIRONMENT") or HEADER.search(ln.text):
            out.add((ln.file, ln.no))
        if division == "DATA" and (open_entry or ENTRY_START.match(ln.text)):
            out.add((ln.file, ln.no))
            open_entry = not ln.text.rstrip().endswith(".")
    return out


def provenance(span: dict[str, Any]) -> Provenance:
    return Provenance(file=span["file"], start_line=span["start_line"], end_line=span["end_line"],
                      extractor="tolerant", confidence=CONFIDENCE)


def tolerant_unit(u: dict[str, Any], pid: str, prefix: str) -> Unit:
    span = u["span"]
    falls: str | None = None
    if u["falls_through_to"]:
        falls = prefix + u["falls_through_to"]
    section: str | None = None
    if u["section"]:
        section = prefix + u["section"]
    calls = [target for target, _dynamic in u["calls"]]
    hazards = [Hazard(gap_id=h["gap_id"], line=h["line"] or span["start_line"], detail=h["message"],
                      fields=list(h["fields"]), severity=h["severity"]) for h in u["hazards"]]
    return Unit(
        unit_id=prefix + u["unit_id"],
        kind=u["kind"],
        span=SourceSpan(file=span["file"], start_line=span["start_line"], end_line=span["end_line"]),
        reads=[prefix + r for r in u["reads"]],
        writes=[prefix + w for w in u["writes"]],
        performs=[prefix + p for p in u["performs"]],
        calls=calls,
        falls_through_to=falls,
        summary=None,
        program=pid,
        section=section,
        unsupported=sorted(u["unsupported"]),
        provenance=provenance(span),
        goes_to=sorted({prefix + g for g in u["gotos"]}),
        hazards=hazards,
    )


def pic_type(pic: str | None) -> SemanticType:
    if not pic:
        return SemanticType(kind="group", digits=None, scale=None, signed=None, length=None)
    try:
        info = parse_pic(pic)
    except DataDivisionError:
        return SemanticType(kind="alphanumeric", digits=None, scale=None, signed=None, length=None)
    if info.category == "numeric":
        return SemanticType(kind="decimal", digits=info.digits, scale=info.scale, signed=info.signed, length=None)
    return SemanticType(kind="alphanumeric", digits=None, scale=None, signed=None, length=info.length)


def tolerant_field(f: dict[str, Any], pid: str, prefix: str) -> Field_:
    """Phase 1's field record: no layout facts (offset/byte length stay unknown); the semantic type
    comes from the same PICTURE parser the strict path uses."""
    st = pic_type(f["pic"])
    parent: str | None = None
    if f["parent"]:
        parent = prefix + f["parent"]
    return Field_(
        field_id=prefix + f["field_id"],
        level=f["level"],
        parent=parent,
        pic=f["pic"],
        usage=f["usage"],
        semantic_type=st,
        occurs=f["occurs"],
        initial_value=f["initial_value"],
        program=pid,
        name=f["name"],
        redefines=f["redefines"],
        provenance=provenance(f["span"]),
    )
