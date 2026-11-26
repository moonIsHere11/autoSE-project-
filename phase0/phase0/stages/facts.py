"""Assemble stages C-F for one strictly parsed program into contract records."""

from __future__ import annotations

import itertools
from collections.abc import Iterable
from dataclasses import dataclass, field

from phase0.schema import Edge, Field_, FileCrud, Hazard, Provenance, SourceSpan, Unit
from phase0.stages.control import (
    ParagraphControl,
    control_hazards,
    edges_for,
    overlapping_ranges,
    perform_units,
    program_control,
)
from phase0.stages.dataflow import Effects, FlowAnalyser, syntax_index
from phase0.stages.hazards import paragraph_hazards, unit_level_hazards
from phase0.stages.layout import FieldIndex, data_dictionary, field_record, index_program
from phase0.stages.parse import StrictProgram
from phase0.stages.storage import Storage
from verifier.cobol import ir as I
from verifier.cobol.lexer import PERIOD, WORD
from verifier.cobol.syntax import Paragraph, Program, Statement

OUT_OF_SCOPE_VERBS = {"SORT": "SORT/MERGE", "MERGE": "SORT/MERGE", "RELEASE": "SORT/MERGE", "RETURN": "SORT/MERGE"}
FILE_VERBS = frozenset({"OPEN", "CLOSE", "READ", "WRITE", "REWRITE", "DELETE", "START"})
OPEN_MODES = {"INPUT": "R", "OUTPUT": "C", "EXTEND": "U", "I-O": "U"}


@dataclass
class ProgramFacts:
    program: str
    units: list[Unit] = field(default_factory=list)
    fields: list[Field_] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    files: list[FileCrud] = field(default_factory=list)
    fallback_lines: set[int] = field(default_factory=set)


def qualifier(program: str, multi: bool) -> str:
    if multi:
        return program + "."
    return ""


def ids_of(effects: set[int], fx: Effects, index: FieldIndex) -> list[str]:
    out: set[str] = set()
    for key in effects:
        fid = index.id_of(fx.items[key])
        if fid is not None and "FILLER#" not in fid:
            out.add(fid)
    return sorted(out)


def unsupported_in(prog: Program, para: Paragraph, body: list[I.Stmt]) -> list[str]:
    found: set[str] = set()
    for s in body:
        for sub in s.walk():
            if isinstance(sub, I.Unsupported):
                found.add(sub.construct)
    for st in para.walk():
        found |= statement_scope(prog, st)
    return sorted(found)


def statement_scope(prog: Program, st: Statement) -> set[str]:
    out: set[str] = set()
    if st.verb == "EXEC" and len(st.tokens) > 1:
        out.add("EXEC " + st.tokens[1].up)
    if st.verb in OUT_OF_SCOPE_VERBS:
        out.add(OUT_OF_SCOPE_VERBS[st.verb])
    if st.verb == "ALTER":
        out.add("ALTER")
    if st.verb in FILE_VERBS:
        for name in file_operands(prog, st):
            sel = prog.select(name)
            if sel is not None and sel.organization not in ("SEQUENTIAL", "LINE SEQUENTIAL"):
                out.add(f"{sel.organization} file")
    return out


def record_owner(prog: Program) -> dict[str, str]:
    out: dict[str, str] = {}
    for fd in prog.fds:
        for r in fd.records:
            out[r.name.upper()] = fd.name.upper()
    return out


def file_operands(prog: Program, st: Statement) -> list[str]:
    """File names a file statement acts on (WRITE/REWRITE name a record: map it to its FD)."""
    owners = record_owner(prog)
    names = [t.up for t in st.tokens[1:] if t.kind == WORD]
    if st.verb in ("WRITE", "REWRITE"):
        return [owners[n] for n in names[:1] if n in owners]
    return [n for n in names if prog.select(n) is not None]


def crud_ops(prog: Program, st: Statement) -> list[tuple[str, str]]:
    if st.verb == "OPEN":
        out: list[tuple[str, str]] = []
        mode = "R"
        for t in st.tokens[1:]:
            if t.up in OPEN_MODES:
                mode = OPEN_MODES[t.up]
            elif prog.select(t.up) is not None:
                out.append((t.up, mode))
        return out
    letter = {"READ": "R", "START": "R", "WRITE": "C", "REWRITE": "U", "DELETE": "D"}.get(st.verb)
    if letter is None:
        return []
    return [(name, letter) for name in file_operands(prog, st)]


class ProgramBuilder:
    def __init__(self, sp: StrictProgram, multi: bool) -> None:
        self.sp = sp
        self.prog = sp.program
        self.prefix = qualifier(self.prog.program_id, multi)
        self.index = index_program(self.prog, self.prefix)
        self.index.add(sp.ir.return_code, self.prefix + "RETURN-CODE")
        self.flow = FlowAnalyser(self.prog, Storage.build(self.prog), sp.ir.return_code)
        self.controls = program_control(self.prog)
        self.qmap = {p.name: self.q(p.name) for p in self.prog.paragraphs}
        self.qmap.update({s: self.q(s) for s in self.prog.sections})
        self.facts = ProgramFacts(self.prog.program_id)
        self.effects: dict[str, Effects] = {}
        self.crud: dict[str, dict[str, set[str]]] = {}

    def q(self, name: str) -> str:
        return self.prefix + name

    def build(self) -> ProgramFacts:
        self.ends = paragraph_end_lines(self.sp)
        overlaps = overlapping_ranges(self.prog, self.controls)
        paragraph_units: list[Unit] = []
        for para, irp, pc in zip(self.prog.paragraphs, self.sp.ir.paragraphs, self.controls, strict=True):
            paragraph_units.append(self.paragraph_unit(para, irp, pc, overlaps))
        section_units = [self.section_unit(s, paragraph_units) for s in self.prog.sections]
        merged = {u.unit_id for u in section_units}
        kept = [u for u in paragraph_units if u.unit_id not in merged]
        self.facts.units = [self.program_unit(paragraph_units), *section_units, *kept]
        self.facts.fields = self.fields()
        self.facts.files = self.file_crud()
        return self.facts

    # ---- paragraphs --------------------------------------------------------------------------
    def paragraph_unit(self, para: Paragraph, irp: I.IrParagraph, pc: ParagraphControl,
                       overlaps: list[tuple[str, int, str]]) -> Unit:
        syntax = syntax_index(para.statements)
        fx = self.flow.block(irp.body, syntax)
        uid = self.q(para.name)
        end_line = self.ends.get((para.file, para.line), para.end_line)
        self.effects[uid] = fx
        self.facts.fallback_lines |= fx.fallback_lines
        self.facts.edges += edges_for(self.prog, pc, uid, self.qmap, para)
        for st in para.walk():
            for name, letter in crud_ops(self.prog, st):
                self.crud.setdefault(name, {}).setdefault(uid, set()).add(letter)
        touched = [fx.items[k] for k in fx.reads | fx.writes]
        gotos = [t for t, _line in pc.gotos]
        goto_line = para.line
        if pc.gotos:
            goto_line = pc.gotos[0][1]
        hazards = control_hazards(pc, overlaps) + paragraph_hazards(self.prog, irp.body, syntax)
        hazards += unit_level_hazards(gotos, goto_line, pc.falls_through_to, end_line, para.line, touched)
        performs: list[str] = []
        for first, last, _line in pc.performs:
            for name in perform_units(self.prog, first, last):
                if self.q(name) not in performs:
                    performs.append(self.q(name))
        confidence = 1.0
        if fx.fallback_lines:
            confidence = 0.8
        falls: str | None = None
        if pc.falls_through_to is not None:
            falls = self.q(pc.falls_through_to)
        section: str | None = None
        if para.section is not None:
            section = self.q(para.section)
        return Unit(
            unit_id=uid,
            kind="paragraph",
            span=SourceSpan(file=para.file, start_line=para.line, end_line=end_line),
            reads=ids_of(fx.reads, fx, self.index),
            writes=ids_of(fx.writes, fx, self.index),
            performs=performs,
            calls=sorted({c.target for c in pc.calls}),
            falls_through_to=falls,
            summary=None,
            program=self.prog.program_id,
            section=section,
            unsupported=unsupported_in(self.prog, para, irp.body),
            provenance=Provenance(file=para.file, start_line=para.line, end_line=end_line,
                                  extractor="strict", confidence=confidence),
            perform_thru=[(self.q(a), self.q(b)) for a, b, _line in pc.performs if a != b],
            goes_to=sorted({self.q(t) for t in gotos}),
            exits=sorted({k for k, _line in pc.exits}),
            hazards=sorted(hazards, key=lambda h: (h.line, h.gap_id, h.detail)),
        )

    # ---- sections and the program --------------------------------------------------------------
    def section_header_line(self, name: str) -> int:
        seen_proc = False
        toks = self.sp.tokens
        for i, t in enumerate(toks[:-1]):
            if t.is_word("PROCEDURE") and toks[i + 1].is_word("DIVISION"):
                seen_proc = True
            if seen_proc and t.up == name and toks[i + 1].is_word("SECTION"):
                return t.line
        return 0

    def section_unit(self, name: str, paragraphs: list[Unit]) -> Unit:
        sid = self.q(name)
        members = [u for u in paragraphs if u.section == sid]
        own_ids = {u.unit_id for u in members}
        start = self.section_header_line(name)
        file = self.prog.source_file
        end = start
        if members:
            file = members[0].span.file
            start = min(start or members[0].span.start_line, members[0].span.start_line)
            end = members[-1].span.end_line
        falls: str | None = None
        if members and members[-1].falls_through_to is not None:
            falls = self.section_of(members[-1].falls_through_to, paragraphs)
        return Unit(
            unit_id=sid,
            kind="section",
            span=SourceSpan(file=file, start_line=start, end_line=end),
            reads=union(u.reads for u in members),
            writes=union(u.writes for u in members),
            performs=[p for p in union(u.performs for u in members) if p not in own_ids and p != sid],
            calls=union(u.calls for u in members),
            falls_through_to=falls,
            summary=None,
            program=self.prog.program_id,
            unsupported=union(u.unsupported for u in members),
            provenance=Provenance(file=file, start_line=start, end_line=end, extractor="strict",
                                  confidence=min([u.provenance.confidence for u in members if u.provenance] or [1.0])),
            perform_thru=[t for u in members for t in u.perform_thru],
            goes_to=union(u.goes_to for u in members),
            exits=union(u.exits for u in members),
            hazards=dedupe_hazards(h for u in members for h in u.hazards),
        )

    def section_of(self, unit_id: str, paragraphs: list[Unit]) -> str:
        for u in paragraphs:
            if u.unit_id == unit_id and u.section is not None:
                return u.section
        return unit_id

    def program_unit(self, paragraphs: list[Unit]) -> Unit:
        lines = [t.line for t in self.sp.tokens if t.file == self.sp.source]
        start, end = self.prog.line, self.prog.line
        if lines:
            start, end = min(lines), max(lines)
        return Unit(
            unit_id=self.prog.program_id,
            kind="program",
            span=SourceSpan(file=self.sp.source, start_line=start, end_line=end),
            reads=union(u.reads for u in paragraphs),
            writes=union(u.writes for u in paragraphs),
            performs=[],
            calls=union(u.calls for u in paragraphs),
            falls_through_to=None,
            summary=None,
            program=self.prog.program_id,
            unsupported=union(u.unsupported for u in paragraphs),
            provenance=Provenance(file=self.sp.source, start_line=start, end_line=end, extractor="strict",
                                  confidence=1.0),
            exits=union(u.exits for u in paragraphs),
        )

    # ---- data ------------------------------------------------------------------------------------
    def fields(self) -> list[Field_]:
        out = data_dictionary(self.prog, self.index, self.sp.tokens)
        rc = self.sp.ir.return_code
        used = any(id(rc) in fx.reads | fx.writes for fx in self.effects.values())
        if used:
            rec = field_record(self.index, rc, self.prog, {})
            rec.section = None
            rec.provenance = None
            out.append(rec)
        return out

    def file_crud(self) -> list[FileCrud]:
        out: list[FileCrud] = []
        for sel in self.prog.selects:
            units = {u: sorted(ops) for u, ops in sorted(self.crud.get(sel.name.upper(), {}).items())}
            out.append(FileCrud.model_validate({"program": self.prog.program_id, "file": sel.name.upper(),
                                                "organization": sel.organization, "assign": sel.assign,
                                                "units": units}))
        return out


def paragraph_end_lines(sp: StrictProgram) -> dict[tuple[str, int], int]:
    """(file, header line) of each paragraph -> line of its last token.

    Computed from the token stream because `verifier.cobol.parser` leaves `Paragraph.end_line` at
    the header line when a SECTION header follows the paragraph (TEAM_NOTES item 5)."""
    toks = sp.tokens
    proc = 0
    for i in range(len(toks) - 1):
        if toks[i].is_word("PROCEDURE") and toks[i + 1].is_word("DIVISION"):
            proc = i
            break
    starts: list[int] = []
    names = {p.name for p in sp.program.paragraphs} | set(sp.program.sections)
    for i in range(proc, len(toks) - 1):
        t, nxt = toks[i], toks[i + 1]
        header = (nxt.kind == PERIOD or nxt.is_word("SECTION")) and (i == 0 or toks[i - 1].kind == PERIOD)
        if header and t.up in names:
            starts.append(i)
        if t.is_word("END") and nxt.is_word("PROGRAM"):
            starts.append(i)
            break
    if not starts or not toks[starts[-1]].is_word("END"):
        starts.append(len(toks))
    out: dict[tuple[str, int], int] = {}
    for a, b in itertools.pairwise(starts):
        if toks[a].up in sp.program.sections and toks[a + 1].is_word("SECTION"):
            continue
        out[(toks[a].file, toks[a].line)] = toks[b - 1].line
    return out


def union(lists: Iterable[list[str]]) -> list[str]:
    out: set[str] = set()
    for xs in lists:
        out |= set(xs)
    return sorted(out)


def dedupe_hazards(hazards: Iterable[Hazard]) -> list[Hazard]:
    out: list[Hazard] = []
    for h in hazards:
        if h not in out:
            out.append(h)
    return out
