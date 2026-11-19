"""Stage D: control-flow facts per paragraph, from the syntax tree (complete even where the IR
gives up): PERFORM (all forms, THRU ranges, sections), GO TO, fall-through, exits, CALL.

Fall-through rule: control falls from a paragraph into the next one in source order unless the
paragraph's last top-level statement always leaves (STOP RUN, GOBACK, EXIT PROGRAM, unconditional
GO TO). Branch-dependent exits keep the edge: the KB over-approximates, eval E4 measures it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from phase0.schema import Edge, EdgeKind, Hazard, Resolution
from verifier.cobol.analysis import parse_ident
from verifier.cobol.lexer import STR, WORD, Token
from verifier.cobol.syntax import Paragraph, Program, Statement

LOOP_WORDS = frozenset({"UNTIL", "VARYING", "TIMES", "WITH", "TEST", "FOREVER"})


@dataclass
class CallSite:
    target: str  # program name, or `?ITEM` when unresolved
    line: int
    file: str
    resolution: Resolution
    via: str  # CALL | CICS LINK | CICS XCTL


@dataclass
class ParagraphControl:
    name: str
    performs: list[tuple[str, str, int]] = field(default_factory=list)  # (first, last, line)
    gotos: list[tuple[str, int]] = field(default_factory=list)
    exits: list[tuple[str, int]] = field(default_factory=list)
    calls: list[CallSite] = field(default_factory=list)
    alters: list[int] = field(default_factory=list)
    falls_through_to: str | None = None


def perform_target(prog: Program, st: Statement) -> tuple[str, str] | None:
    """(first, last) procedure names of an out-of-line PERFORM, None for inline PERFORM."""
    toks = st.tokens[1:]
    if st.verb != "PERFORM" or st.branches or not toks or toks[0].kind not in (WORD, "NUM"):
        return None
    first = toks[0].up
    names = {p.name for p in prog.paragraphs} | set(prog.sections)
    if first in LOOP_WORDS or first not in names:
        return None
    last = first
    if len(toks) > 2 and toks[1].is_word("THRU", "THROUGH"):
        last = toks[2].up
    return first, last


def goto_targets(st: Statement) -> list[str]:
    out: list[str] = []
    for t in st.tokens[1:]:
        if t.is_word("TO"):
            continue
        if t.is_word("DEPENDING"):
            break
        if t.kind in (WORD, "NUM"):
            out.append(t.up)
    return out


def exit_kind(st: Statement) -> str | None:
    if st.verb == "STOP" and len(st.tokens) > 1 and st.tokens[1].is_word("RUN"):
        return "STOP RUN"
    if st.verb == "GOBACK":
        return "GOBACK"
    if st.verb == "EXIT" and len(st.tokens) > 1 and st.tokens[1].is_word("PROGRAM"):
        return "EXIT PROGRAM"
    return None


def always_leaves(st: Statement) -> bool:
    if exit_kind(st) is not None:
        return True
    return st.verb == "GO" and not any(t.is_word("DEPENDING") for t in st.tokens)


def string_literal_moves(prog: Program) -> dict[str, set[str]]:
    """Item name -> literals ever MOVEd into it; an entry maps to {'?'} if any non-literal store."""
    out: dict[str, set[str]] = {}
    for item in prog.all_items():
        if item.value is not None and item.value.kind == "str":
            out.setdefault(item.name.upper(), set()).add(item.value.text.strip().upper())
    for st in prog.walk_statements():
        if st.verb != "MOVE" or len(st.tokens) < 4:
            continue
        ups = [t.up for t in st.tokens]
        if "TO" not in ups:
            continue
        k = ups.index("TO")
        src: Token = st.tokens[1]
        literal = "?"
        if k == 2 and src.kind == STR:
            literal = src.value.strip().upper()
        j = k + 1
        while j < len(st.tokens):
            ident = parse_ident(st.tokens, j)
            if ident is None:
                j += 1
                continue
            out.setdefault(ident.name, set()).add(literal)
            j = ident.end
    return out


def call_sites(prog: Program, st: Statement, literals: dict[str, set[str]]) -> list[CallSite]:
    toks = st.tokens
    if st.verb == "CALL" and len(toks) > 1:
        return resolve_target(toks[1], st, "CALL", literals)
    if st.verb == "EXEC" and len(toks) > 2 and toks[1].is_word("CICS"):
        ups = [t.up for t in toks]
        for kw in ("LINK", "XCTL"):
            if kw in ups and "PROGRAM" in ups:
                k = ups.index("PROGRAM")
                if k + 2 < len(toks) and toks[k + 1].text == "(":
                    return resolve_target(toks[k + 2], st, "CICS " + kw, literals)
    return []


def resolve_target(tok: Token, st: Statement, via: str, literals: dict[str, set[str]]) -> list[CallSite]:
    if tok.kind == STR:
        return [CallSite(tok.value.strip().upper(), st.line, st.file, "static", via)]
    values = literals.get(tok.up, set())
    if values and "?" not in values:
        return [CallSite(v, st.line, st.file, "resolved-by-constant", via) for v in sorted(values)]
    return [CallSite("?" + tok.up, st.line, st.file, "unresolved", via)]


def paragraph_control(prog: Program, para: Paragraph, nxt: str | None,
                      literals: dict[str, set[str]]) -> ParagraphControl:
    pc = ParagraphControl(para.name)
    for st in para.walk():
        target = perform_target(prog, st)
        if target is not None:
            pc.performs.append((target[0], target[1], st.line))
        if st.verb == "GO":
            pc.gotos += [(t, st.line) for t in goto_targets(st)]
        kind = exit_kind(st)
        if kind is not None:
            pc.exits.append((kind, st.line))
        if st.verb == "ALTER":
            pc.alters.append(st.line)
        pc.calls += call_sites(prog, st, literals)
    if para.statements and always_leaves(para.statements[-1]):
        return pc
    pc.falls_through_to = nxt
    return pc


def program_control(prog: Program) -> list[ParagraphControl]:
    literals = string_literal_moves(prog)
    names = [p.name for p in prog.paragraphs]
    out: list[ParagraphControl] = []
    for i, para in enumerate(prog.paragraphs):
        nxt: str | None = None
        if i + 1 < len(names):
            nxt = names[i + 1]
        out.append(paragraph_control(prog, para, nxt, literals))
    return out


def expand_range(prog: Program, first: str, last: str) -> list[str]:
    """Paragraphs covered by PERFORM first [THRU last]; a section stands for its paragraphs."""
    names = [p.name for p in prog.paragraphs]
    lo, hi = first, last
    if first in prog.sections:
        own = [p.name for p in prog.paragraphs if p.section == first]
        if not own:
            return []
        lo = own[0]
    if last in prog.sections:
        own = [p.name for p in prog.paragraphs if p.section == last]
        if not own:
            return []
        hi = own[-1]
    if lo not in names or hi not in names or names.index(hi) < names.index(lo):
        return []
    return names[names.index(lo) : names.index(hi) + 1]


def overlapping_ranges(prog: Program, controls: list[ParagraphControl]) -> list[tuple[str, int, str]]:
    """THRU ranges that partially overlap another range (neither nested nor disjoint)."""
    ranges: list[tuple[str, int, list[str]]] = []
    for pc in controls:
        for first, last, line in pc.performs:
            if first != last:
                ranges.append((pc.name, line, expand_range(prog, first, last)))
    out: list[tuple[str, int, str]] = []
    for owner, line, r in ranges:
        for _o2, _l2, r2 in ranges:
            common = set(r) & set(r2)
            if common and not (set(r) <= set(r2) or set(r2) <= set(r)):
                out.append((owner, line, f"PERFORM {r[0]} THRU {r[-1]} overlaps {r2[0]} THRU {r2[-1]}"))
                break
    return out


def control_hazards(pc: ParagraphControl, overlaps: list[tuple[str, int, str]]) -> list[Hazard]:
    out: list[Hazard] = []
    for line in pc.alters:
        out.append(Hazard(gap_id="G-GOTO", line=line, detail="ALTER changes a GO TO target at run time",
                          severity="high"))
    for owner, line, detail in overlaps:
        if owner == pc.name:
            out.append(Hazard(gap_id="G-FALLTHROUGH", line=line, detail=detail, severity="high"))
    return out


def edges_for(prog: Program, pc: ParagraphControl, src_id: str, qualify: dict[str, str],
              para: Paragraph) -> list[Edge]:
    out: list[Edge] = []
    for first, last, line in pc.performs:
        kind: EdgeKind = "perform"
        if first != last:
            kind = "perform-thru"
        for name in perform_units(prog, first, last):
            out.append(Edge(src=src_id, dst=qualify.get(name, name), kind=kind, line=line, file=para.file,
                            resolution="static"))
    for target, line in pc.gotos:
        out.append(Edge(src=src_id, dst=qualify.get(target, target), kind="goto", line=line, file=para.file,
                        resolution="static"))
    if pc.falls_through_to is not None:
        out.append(Edge(src=src_id, dst=qualify[pc.falls_through_to], kind="fallthrough", line=para.end_line,
                        file=para.file, resolution="static"))
    for exit_name, line in pc.exits:
        out.append(Edge(src=src_id, dst=exit_name, kind="exit", line=line, file=para.file, resolution="static"))
    for c in pc.calls:
        out.append(Edge(src=src_id, dst=c.target, kind="call", line=c.line, file=c.file, resolution=c.resolution,
                        detail=c.via))
    return out


def perform_units(prog: Program, first: str, last: str) -> list[str]:
    """Unit names a PERFORM reaches: the section itself, or every paragraph of a THRU range."""
    if first == last:
        return [first]
    return expand_range(prog, first, last)
