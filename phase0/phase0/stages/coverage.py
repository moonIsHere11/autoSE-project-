"""Coverage: every line of every program and copybook is blank, comment, attributed, or listed with
a reason (principle 3).

Attribution rules for lines that carry tokens after `cobc -E`:
* IDENTIFICATION / ENVIRONMENT DIVISION text: program structure (SELECTs become file facts);
* DATA DIVISION: inside a data entry (level number to its period), an FD/SD entry, or a header line;
* PROCEDURE DIVISION: inside a paragraph or section span, or the division / section header.
Lines without tokens that are not blank or comments are COPY statements (expanded by cobc),
compiler directives, or text the preprocessor dropped (listed with that reason).
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from phase0.schema import Field_, InventoryEntry, ParseStatus, ProgramCoverage, UnattributedLine, Unit
from phase0.stages.inventory import TextFile
from phase0.stages.layout import entry_end_lines
from phase0.stages.parse import StrictProgram
from verifier.cobol.lexer import PERIOD, Token

COPY_LINE = re.compile(r"^\s*(COPY|REPLACE)\b|\bCOPY\s+[A-Z0-9'\"]", re.I)
DIRECTIVE = re.compile(r"^\s*(>>|\$|\*>\s*>>)", re.I)
HEADER_WORDS = frozenset({"DIVISION", "SECTION", "DECLARATIVES"})
Key = tuple[str, int]


@dataclass
class LineFacts:
    """(file, line) sets collected from every strict program."""

    tokens: dict[Key, str] = field(default_factory=dict)  # line -> region
    units: set[Key] = field(default_factory=set)
    data: set[Key] = field(default_factory=set)
    headers: set[Key] = field(default_factory=set)
    owners: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))  # file -> programs


def span_lines(file: str, start: int, end: int) -> set[Key]:
    return {(file, n) for n in range(start, max(start, end) + 1)}


def regions(tokens: list[Token]) -> list[str]:
    """Division of each token: ident | env | data | proc."""
    out: list[str] = []
    region = "ident"
    for i, t in enumerate(tokens):
        if i + 1 < len(tokens) and tokens[i + 1].is_word("DIVISION"):
            region = {"ENVIRONMENT": "env", "DATA": "data", "PROCEDURE": "proc"}.get(t.up, region)
        out.append(region)
    return out


def entry_spans(tokens: list[Token], start_words: frozenset[str]) -> list[tuple[str, int, int]]:
    """Spans (file, first line, period line) of entries starting with one of `start_words`."""
    out: list[tuple[str, int, int]] = []
    opened: Token | None = None
    for t in tokens:
        if opened is None and t.up in start_words:
            opened = t
        elif opened is not None and t.kind == PERIOD:
            out.append((opened.file, opened.line, t.line))
            opened = None
    return out


def collect(programs: list[StrictProgram], units: list[Unit], fields: list[Field_]) -> LineFacts:
    lf = LineFacts()
    for sp in programs:
        regs = regions(sp.tokens)
        for t, reg in zip(sp.tokens, regs, strict=True):
            lf.tokens.setdefault((t.file, t.line), reg)
            lf.owners[t.file].add(sp.program.program_id)
            if t.up in HEADER_WORDS or reg in ("ident", "env"):
                lf.headers.add((t.file, t.line))
        data_toks = [t for t, r in zip(sp.tokens, regs, strict=True) if r == "data"]
        for file, a, b in entry_spans(data_toks, frozenset({"FD", "SD", "RD", "CD"})):
            lf.headers |= span_lines(file, a, b)
        proc_toks = [t for t, r in zip(sp.tokens, regs, strict=True) if r == "proc"]
        for file, a, b in entry_spans(proc_toks, frozenset({"PROCEDURE"}))[:1]:
            lf.headers |= span_lines(file, a, b)
        for cond_file, a, b in condition_spans(sp):
            lf.data |= span_lines(cond_file, a, b)
    for u in units:
        if u.kind != "program":
            lf.units |= span_lines(u.span.file, u.span.start_line, u.span.end_line)
    for f in fields:
        if f.provenance is not None:
            lf.data |= span_lines(f.provenance.file, f.provenance.start_line, f.provenance.end_line)
    return lf


def condition_spans(sp: StrictProgram) -> list[tuple[str, int, int]]:
    """88/66 entries: from their level number to the period that ends them."""
    ends = entry_end_lines(sp.tokens)
    out: list[tuple[str, int, int]] = []
    for item in sp.program.all_items():
        for c in item.conditions:
            out.append((c.file, c.line, ends.get((c.file, c.line), c.line)))
    return out


def is_comment(text: str, fmt: str | None) -> bool:
    if fmt == "free":
        return text.lstrip().startswith("*>")
    if len(text) > 6 and text[6] in "*/dD":
        return True
    return text.lstrip().startswith("*>")


def is_blank(text: str, fmt: str | None) -> bool:
    if fmt == "free":
        return not text.strip()
    return not text[6:72].strip() and (len(text) <= 6 or text[6] in " \t")


def classify_line(lf: LineFacts, key: Key, text: str, fmt: str | None) -> tuple[str, str | None]:
    """'blank' | 'comment' | 'attributed' | 'unattributed' and the reason for the last."""
    if is_blank(text, fmt):
        return "blank", None
    if is_comment(text, fmt):
        return "comment", None
    region = lf.tokens.get(key)
    if region is None:
        if COPY_LINE.search(text):
            return "attributed", None
        if DIRECTIVE.search(text):
            return "unattributed", "compiler directive (consumed by cobc -E)"
        return "unattributed", "text dropped by cobc -E (no tokens)"
    if key in lf.units or key in lf.data or key in lf.headers:
        return "attributed", None
    if region == "data":
        return "unattributed", "data division text outside any parsed entry"
    if region == "proc":
        return "unattributed", "procedure text outside any paragraph (parse error or DECLARATIVES)"
    return "unattributed", f"{region} text"


def file_coverage(entry: InventoryEntry, f: TextFile, lf: LineFacts, program: str, status: ParseStatus,
                  unsupported: dict[str, list[int]], unresolved: list[str], errors: list[str],
                  extractors: dict[str, int]) -> ProgramCoverage:
    counts = {"blank": 0, "comment": 0, "attributed": 0}
    missing: list[UnattributedLine] = []
    for n, text in enumerate(f.text.splitlines(), start=1):
        kind, reason = classify_line(lf, (f.path, n), text, entry.format)
        if kind == "unattributed":
            missing.append(UnattributedLine(file=f.path, line=n, reason=reason or "unknown"))
        else:
            counts[kind] += 1
    return ProgramCoverage(
        program=program,
        file=f.path,
        parse_status=status,
        lines_total=entry.lines,
        lines_attributed=counts["attributed"],
        lines_comment=counts["comment"],
        lines_blank=counts["blank"],
        unattributed=missing,
        unsupported=unsupported,
        unresolved_calls=unresolved,
        parse_errors=errors,
        facts_by_extractor=extractors,
    )
