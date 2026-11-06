"""Localise a failure: COBOL statements that (likely) wrote the differing field in the failing case."""

from __future__ import annotations

from pathlib import Path

from verifier.cobol.analysis import item_aliases, written_names
from verifier.cobol.syntax import Program, Statement
from verifier.cobol.trace import TraceEvent
from verifier.langpacks.base import ResolvedProgram
from verifier.report.schema import SourceRef


def _source_line(root: Path, file: str, line: int) -> str:
    p = root / file
    try:
        lines = p.read_text("latin-1").splitlines()
    except OSError:
        return ""
    return lines[line - 1].strip() if 0 < line <= len(lines) else ""


def writers(prog: Program, field: str) -> list[Statement]:
    aliases = item_aliases(prog, field)
    out = []
    for st in prog.walk_statements():
        names = set(written_names(prog, st))
        if names & aliases:
            out.append(st)
    return out


def localise(prog: Program, field: str, events: list[TraceEvent], cobol_root: Path,
             upto_line_event: int | None = None, limit: int = 3) -> tuple[list[SourceRef], bool]:
    """Executed writers of `field`, most recent (in trace order) first; plus whether any writer has
    an ON SIZE ERROR phrase."""
    ws = writers(prog, field)
    by_line = {(st.file.rsplit("/", 1)[-1].lower(), st.line): st for st in ws}
    seen: list[Statement] = []
    evs = events if upto_line_event is None else events[:upto_line_event]
    for ev in reversed(evs):
        if ev.kind != "statement":
            continue
        st = by_line.get((ev.file.rsplit("/", 1)[-1].lower(), ev.line))
        if st is not None and st not in seen:
            seen.append(st)
        if len(seen) >= limit:
            break
    if not seen:
        seen = ws[:limit]  # not executed in this case's trace (or no trace): static writers
    size_err = any(b.kind in ("size_error", "not_size_error") for st in seen for b in st.branches)
    refs = [SourceRef(file=st.file, line=st.line, text=_source_line(cobol_root, st.file, st.line) or st.text())
            for st in seen]
    return refs, size_err


def target_location(rp: ResolvedProgram | None, field: str, paragraph: str | None) -> SourceRef | None:
    if rp is None:
        return None
    m = rp.fields.get(field)
    if m and m.get("location"):
        f, ln = m["location"]
        return SourceRef(file=f, line=ln, text=f"field {m['target']} ({m.get('target_type')})")
    if paragraph:
        ms = rp.unit_locations.get(paragraph)
        if ms is not None:
            return SourceRef(file=ms.file, line=ms.line, text=f"method {ms.name}")
    return None


def paragraph_of(prog: Program, file: str, line: int) -> str | None:
    for p in prog.paragraphs:
        if p.file.rsplit("/", 1)[-1].lower() == file.rsplit("/", 1)[-1].lower() and p.line <= line <= p.end_line:
            return p.name
    return None
