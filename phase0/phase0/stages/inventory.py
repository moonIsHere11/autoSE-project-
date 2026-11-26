"""Stage A: classify every file under source/ by content (never by extension) and scan references.

Pattern scans only: COPY / SQL INCLUDE dependencies, CALL / CICS LINK|XCTL targets, JCL steps and DDs.
These are hints for the strict front end and for the batch-flow view; the strict parse (stage B)
supersedes them for programs it accepts.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from phase0.schema import FileKind, InventoryEntry
from verifier.cobol.preprocess import detect_format

LEVEL_LINE = re.compile(r"^\s*(0?[1-9]|[1-4][0-9]|66|77|88)\s+[A-Z0-9][A-Z0-9-]*\b", re.I)
OTHER_FORMAT = {"fixed": "free", "free": "fixed"}
PROGRAM_ID = re.compile(r"\bPROGRAM-ID\b", re.I)
PROCEDURE = re.compile(r"\bPROCEDURE\s+DIVISION\b", re.I)
COPY_STMT = re.compile(r"\bCOPY\s+(?:'([^']+)'|\"([^\"]+)\"|([A-Z0-9][A-Z0-9-]*))", re.I)
SQL_INCLUDE = re.compile(r"\bEXEC\s+SQL\s+INCLUDE\s+([A-Z0-9][A-Z0-9-]*)", re.I)
CALL_LIT = re.compile(r"\bCALL\s+(?:'([^']+)'|\"([^\"]+)\")", re.I)
CALL_DYN = re.compile(r"\bCALL\s+([A-Z][A-Z0-9-]*)", re.I)
CICS_PGM = re.compile(r"\b(?:LINK|XCTL)\s+PROGRAM\s*\(\s*(?:'([^']+)'|\"([^\"]+)\"|([A-Z][A-Z0-9-]*))", re.I)
PROGRAM_NAME = re.compile(r"\bPROGRAM-ID\s*\.?\s*(?:'([^']+)'|\"([^\"]+)\"|([A-Z0-9][A-Z0-9-]*))", re.I)
BMS = re.compile(r"\bDFHMSD\b|\bDFHMDF\b|\bDFHMDI\b")
JCL_CARD = re.compile(r"^//([A-Z0-9#@$]*)\s+(JOB|EXEC|DD|PROC|PEND|SET|INCLUDE|JCLLIB)\b(.*)$", re.I)
COBOL_VERBS = re.compile(r"^\s*(MOVE|PERFORM|COMPUTE|DISPLAY|IF|EVALUATE|ADD|SUBTRACT|EXEC|ELSE|END-IF|CALL|SET|GO)\b", re.I)
PARAGRAPH_HEADER = re.compile(r"^\s{0,4}[A-Z0-9][A-Z0-9-]*\.\s*$", re.I)
SQL_DECLARE = re.compile(r"\bEXEC\s+SQL\s+DECLARE\b", re.I)


@dataclass
class TextFile:
    path: str
    text: str
    raw: bytes


def read_tree(source: Path) -> list[TextFile]:
    out: list[TextFile] = []
    for p in sorted(source.rglob("*")):
        if p.is_file():
            raw = p.read_bytes()
            out.append(TextFile(p.relative_to(source).as_posix(), raw.decode("latin-1"), raw))
    return out


def code_lines(text: str, fmt: str) -> list[str]:
    """Statement area of each non-comment line (fixed: columns 8-72; free: before `*>`)."""
    out: list[str] = []
    for line in text.splitlines():
        if fmt == "fixed":
            if len(line) > 6 and line[6] in "*/":
                continue
            body = line[7:72]
        else:
            body = line.split("*>", 1)[0]
        out.append(body)
    return out


def _first(m: re.Match[str]) -> str:
    for g in m.groups():
        if g:
            return g
    return ""


def is_binary(raw: bytes) -> bool:
    return b"\0" in raw[:4096]


def classify(text: str, raw: bytes) -> tuple[FileKind, str | None]:
    if is_binary(raw):
        return "other", "binary"
    lines = text.splitlines()
    if not lines:
        return "other", "empty"
    jcl = sum(1 for ln in lines if JCL_CARD.match(ln))
    if jcl and jcl * 4 >= sum(1 for ln in lines if ln.startswith("//")):
        if any(re.match(r"^//\S*\s+PROC\b", ln, re.I) for ln in lines) and not any(
            re.match(r"^//\S*\s+JOB\b", ln, re.I) for ln in lines
        ):
            return "jcl", "proc"
        return "jcl", "job"
    if BMS.search(text):
        return "other", "bms"
    detected = detect_format(text)
    code_rows = [ln for ln in code_lines(text, detected) if ln.strip()]
    code = "\n".join(code_rows)
    if PROGRAM_ID.search(code) and PROCEDURE.search(code):
        return "program", None
    # the format heuristic can misread free-format text with deep indentation (TEAM_NOTES item 7):
    # a program is still a program, and goes to the tolerant fallback if cobc then rejects it
    other = "\n".join(code_lines(text, OTHER_FORMAT[detected]))
    if PROGRAM_ID.search(other) and PROCEDURE.search(other):
        return "program", "format-ambiguous"
    if SQL_DECLARE.search(code):
        return "copybook", "sql"
    if not code_rows:
        return "other", None
    levels = sum(1 for ln in code_rows if LEVEL_LINE.match(ln))
    if levels * 2 >= len(code_rows):
        return "copybook", "data"
    statements = sum(1 for ln in code_rows if COBOL_VERBS.match(ln) or PARAGRAPH_HEADER.match(ln))
    if statements * 3 >= len(code_rows) and any(PARAGRAPH_HEADER.match(ln) for ln in code_rows):
        return "copybook", "procedure"
    if levels and levels * 4 >= len(code_rows):
        return "copybook", "data"
    return "other", None


def copy_refs(code: str) -> list[str]:
    names = [_first(m).upper() for m in COPY_STMT.finditer(code)]
    names += [m.group(1).upper() for m in SQL_INCLUDE.finditer(code)]
    return sorted(set(names))


def call_refs(code: str) -> list[str]:
    """Static targets by name; dynamic CALL through a data item as `?ITEM` (resolved in stage E)."""
    out = {_first(m).upper() for m in CALL_LIT.finditer(code)}
    out |= {_first(m).upper() for m in CICS_PGM.finditer(code) if m.group(3) is None}
    for m in CICS_PGM.finditer(code):
        if m.group(3):
            out.add("?" + m.group(3).upper())
    for m in CALL_DYN.finditer(code):
        out.add("?" + m.group(1).upper())
    return sorted(out)


def program_names(code: str) -> list[str]:
    return [_first(m).upper() for m in PROGRAM_NAME.finditer(code)]


def jcl_cards(text: str) -> list[dict[str, str]]:
    """One row per EXEC / DD card: job, step, kind, program or proc, dd, dsn, disp."""
    rows: list[dict[str, str]] = []
    job = ""
    step = ""
    cards = _join_continuations(text.splitlines())
    for lineno, card in cards:
        m = JCL_CARD.match(card)
        if not m:
            continue
        name, op, rest = m.group(1).upper(), m.group(2).upper(), m.group(3)
        if op == "JOB":
            job = name
        elif op == "EXEC":
            step = name
            pgm = re.search(r"\bPGM=([A-Z0-9#@$]+)", rest, re.I)
            proc = re.search(r"^\s*(?:PROC=)?([A-Z0-9#@$]+)\s*(?:,|$)", rest, re.I)
            row = {"job": job, "step": step, "kind": "exec", "line": str(lineno)}
            if pgm:
                row["program"] = pgm.group(1).upper()
            elif proc:
                row["proc"] = proc.group(1).upper()
            rows.append(row)
        elif op == "DD":
            dsn = re.search(r"\bDSN(?:AME)?=([^,\s]+)", rest, re.I)
            disp = re.search(r"\bDISP=(\([^)]*\)|[A-Z]+)", rest, re.I)
            row = {"job": job, "step": step, "kind": "dd", "dd": name, "line": str(lineno)}
            if dsn:
                row["dsn"] = dsn.group(1).upper()
            if disp:
                row["disp"] = disp.group(1).upper().strip("()")
            rows.append(row)
    return rows


def _join_continuations(lines: list[str]) -> list[tuple[int, str]]:
    """JCL operands continue on `//` cards with a blank name field after a trailing comma."""
    out: list[tuple[int, str]] = []
    for i, ln in enumerate(lines, start=1):
        text = ln[:72].rstrip()
        if text.startswith("//*") or not text.startswith("//"):
            continue
        if out and out[-1][1].endswith(",") and re.match(r"^//\s+\S", text) and not JCL_CARD.match(text):
            out[-1] = (out[-1][0], out[-1][1] + text[2:].strip())
            continue
        out.append((i, text))
    return out


def inventory_entry(f: TextFile) -> InventoryEntry:
    kind, subkind = classify(f.text, f.raw)
    entry = InventoryEntry(
        path=f.path,
        kind=kind,
        subkind=subkind,
        lines=len(f.text.splitlines()),
        sha256=hashlib.sha256(f.raw).hexdigest(),
    )
    if kind in ("program", "copybook"):
        fmt = detect_format(f.text)
        code = "\n".join(code_lines(f.text, fmt))
        entry.format = fmt
        entry.copybooks = copy_refs(code)
        entry.calls = call_refs(code)
        entry.programs = program_names(code)
    if kind == "jcl":
        entry.jcl_steps = jcl_cards(f.text)
    return entry


def build_inventory(files: list[TextFile]) -> list[InventoryEntry]:
    return [inventory_entry(f) for f in files]
