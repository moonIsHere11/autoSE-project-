"""Stages B-F over the whole source tree: strict programs, tolerant fallback, coverage."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from phase0.schema import (
    CallGraph,
    Coverage,
    CoverageSummary,
    DataFlow,
    Edge,
    Field_,
    FieldFlow,
    FileCrud,
    InventoryEntry,
    ParseStatus,
    ProgramCoverage,
    Unit,
)
from phase0.stages.coverage import LineFacts, collect, file_coverage, span_lines
from phase0.stages.facts import ProgramBuilder
from phase0.stages.inventory import TextFile
from phase0.stages.parse import ParseResult, StrictProgram, parse_programs
from phase0.stages.tolerant import TolerantProgram, analyse_file
from phase0.toolbox import Toolbox

# failure modes of Phase 1's regex analyser on unusual input; anything else is a bug and propagates
TOLERANT_ERRORS = (ValueError, KeyError, IndexError, AttributeError, TypeError, UnicodeDecodeError)


@dataclass
class SourceKb:
    units: list[Unit] = field(default_factory=list)
    fields: list[Field_] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    files: list[FileCrud] = field(default_factory=list)
    coverage: list[ProgramCoverage] = field(default_factory=list)
    rejected: list[dict[str, str]] = field(default_factory=list)
    parse: ParseResult = field(default_factory=ParseResult)
    tolerant: list[TolerantProgram] = field(default_factory=list)


def build_source_kb(toolbox: Toolbox, source: Path, inventory: list[InventoryEntry],
                    files: list[TextFile]) -> SourceKb:
    kb = SourceKb()
    kb.parse = parse_programs(toolbox, source, inventory)
    multi = len(kb.parse.strict) + len(kb.parse.rejected) > 1
    for sp in kb.parse.strict:
        facts = ProgramBuilder(sp, multi).build()
        kb.units += facts.units
        kb.fields += facts.fields
        kb.edges += facts.edges
        kb.files += facts.files
    by_path = {e.path: e for e in inventory}
    for rej in kb.parse.rejected:
        kb.rejected.append({"file": rej.source, "reason": rej.reason})
        entry = by_path[rej.source]
        try:
            progs = analyse_file(source, rej.source, multi)
        except TOLERANT_ERRORS as exc:
            entry.parse_status = "failed"
            entry.parse_reason = f"{rej.reason}; tolerant analyser: {type(exc).__name__}: {exc}"
            continue
        entry.parse_status = "tolerant"
        entry.parse_reason = rej.reason
        kb.tolerant += progs
        for tp in progs:
            kb.units += tp.units
            kb.fields += tp.fields
            kb.edges += tolerant_edges(tp)
    for sp in kb.parse.strict:
        by_path[sp.source].parse_status = "strict"
        by_path[sp.source].programs = sorted(set(by_path[sp.source].programs) | {sp.program.program_id})
    kb.coverage = coverage(kb, inventory, files)
    kb.units.sort(key=lambda u: (u.program or "", u.span.file, u.span.start_line, u.kind != "program", u.unit_id))
    kb.edges.sort(key=lambda e: (e.src, e.line, e.kind, e.dst))
    return kb


def tolerant_edges(tp: TolerantProgram) -> list[Edge]:
    out: list[Edge] = []
    for u in tp.units:
        f, line = u.span.file, u.span.start_line
        for p in u.performs:
            out.append(Edge(src=u.unit_id, dst=p, kind="perform", line=line, file=f, resolution="static",
                            detail="tolerant"))
        for g in u.goes_to:
            out.append(Edge(src=u.unit_id, dst=g, kind="goto", line=line, file=f, resolution="static", detail="tolerant"))
        if u.falls_through_to is not None:
            out.append(Edge(src=u.unit_id, dst=u.falls_through_to, kind="fallthrough", line=u.span.end_line, file=f,
                            resolution="static", detail="tolerant"))
        for c in u.calls:
            res: Literal["static", "unresolved"] = "static"
            if c.startswith("?"):
                res = "unresolved"
            out.append(Edge(src=u.unit_id, dst=c, kind="call", line=line, file=f, resolution=res,
                            detail="tolerant"))
    return out


def unsupported_lines(sp: StrictProgram) -> dict[str, list[int]]:
    out: dict[str, set[int]] = defaultdict(set)
    for feature, lines in sp.program.features.items():
        out[feature] |= set(lines)
    for s in sp.ir.unsupported():
        out[s.construct].add(s.loc.line)
    for reason in sp.ir.issues:
        out[reason].add(0)
    return {k: sorted(v) for k, v in sorted(out.items())}


def coverage(kb: SourceKb, inventory: list[InventoryEntry], files: list[TextFile]) -> list[ProgramCoverage]:
    lf = collect(kb.parse.strict, kb.units, kb.fields)
    add_tolerant(lf, kb.tolerant)
    text = {f.path: f for f in files}
    by_file: dict[str, list[StrictProgram]] = defaultdict(list)
    for sp in kb.parse.strict:
        by_file[sp.source].append(sp)
    tol_by_file: dict[str, list[TolerantProgram]] = defaultdict(list)
    for tp in kb.tolerant:
        tol_by_file[tp.source].append(tp)
    out: list[ProgramCoverage] = []
    for entry in inventory:
        if entry.kind not in ("program", "copybook"):
            continue
        out.append(entry_coverage(kb, entry, text[entry.path], lf, by_file[entry.path], tol_by_file[entry.path]))
    return out


def entry_coverage(kb: SourceKb, entry: InventoryEntry, f: TextFile, lf: LineFacts,
                   strict: list[StrictProgram], tolerant: list[TolerantProgram]) -> ProgramCoverage:
    extractors = extractor_counts(kb, entry.path)
    if entry.kind == "copybook":
        owners = ",".join(sorted(lf.owners.get(entry.path, set())))
        status: ParseStatus = "not-parsed"
        if owners:
            status = "strict"
        return file_coverage(entry, f, lf, owners or "(unused copybook)", status, {}, [], [], extractors)
    unsupported: dict[str, list[int]] = {}
    unresolved: list[str] = []
    errors: list[str] = []
    for sp in strict:
        unsupported.update(unsupported_lines(sp))
        errors += sp.program.parse_errors
    ids = {sp.program.program_id for sp in strict} | {tp.program for tp in tolerant}
    for e in kb.edges:
        if e.kind == "call" and e.resolution == "unresolved" and owner_program(kb, e.src) in ids:
            unresolved.append(e.dst)
    if entry.parse_reason and entry.parse_status != "strict":
        errors.append(entry.parse_reason)
    return file_coverage(entry, f, lf, ",".join(sorted(ids)) or entry.path, entry.parse_status, unsupported,
                         sorted(set(unresolved)), errors, extractors)


def owner_program(kb: SourceKb, unit_id: str) -> str | None:
    for u in kb.units:
        if u.unit_id == unit_id:
            return u.program
    return None


def extractor_counts(kb: SourceKb, path: str) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for u in kb.units:
        if u.provenance is not None and u.span.file == path:
            out[u.provenance.extractor] += 1
    for fl in kb.fields:
        if fl.provenance is not None and fl.provenance.file == path:
            out[fl.provenance.extractor] += 1
    return dict(sorted(out.items()))


def add_tolerant(lf: LineFacts, tolerant: list[TolerantProgram]) -> None:
    for tp in tolerant:
        for key in tp.covered:
            lf.tokens.setdefault(key, "tolerant")
            lf.owners[key[0]].add(tp.program)
        for u in tp.units:
            lf.units |= span_lines(u.span.file, u.span.start_line, u.span.end_line)
        for fl in tp.fields:
            if fl.provenance is not None:
                lf.data |= span_lines(fl.provenance.file, fl.provenance.start_line, fl.provenance.end_line)


def call_graph(kb: SourceKb) -> CallGraph:
    return CallGraph(edges=kb.edges)


def data_flow(kb: SourceKb) -> DataFlow:
    writers: dict[str, set[str]] = defaultdict(set)
    readers: dict[str, set[str]] = defaultdict(set)
    for u in kb.units:
        if u.kind != "paragraph":
            continue
        for w in u.writes:
            writers[w].add(u.unit_id)
        for r in u.reads:
            readers[r].add(u.unit_id)
    flows = [FieldFlow(field_id=f.field_id, writers=sorted(writers[f.field_id]), readers=sorted(readers[f.field_id]))
             for f in kb.fields]
    return DataFlow(fields=flows, files=kb.files)


def coverage_doc(kb: SourceKb) -> Coverage:
    return Coverage(programs=kb.coverage, rejected_files=kb.rejected)


def summary(kb: SourceKb, inventory: list[InventoryEntry]) -> CoverageSummary:
    programs = [e for e in inventory if e.kind == "program"]
    return CoverageSummary(
        files=len(inventory),
        programs=len(kb.parse.strict) + len(kb.tolerant),
        parsed_strict=sum(1 for e in programs if e.parse_status == "strict"),
        parsed_tolerant=sum(1 for e in programs if e.parse_status == "tolerant"),
        failed=sum(1 for e in programs if e.parse_status == "failed"),
        lines_total=sum(c.lines_total for c in kb.coverage),
        lines_unattributed=sum(len(c.unattributed) for c in kb.coverage),
    )

