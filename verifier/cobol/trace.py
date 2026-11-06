"""GnuCOBOL `-ftraceall` output (COB_TRACE_FORMAT="%F|%I|%L|%S", spike S1) and coverage."""

from __future__ import annotations

from dataclasses import dataclass

from verifier.cobol.syntax import Program


@dataclass(frozen=True)
class TraceEvent:
    file: str
    program: str
    line: int
    kind: str  # entry | paragraph | section | statement
    name: str


def parse_trace(text: str) -> list[TraceEvent]:
    events: list[TraceEvent] = []
    for raw in text.splitlines():
        parts = raw.split("|")
        if len(parts) < 4:
            continue
        file = parts[0].replace("Source:", "").strip()
        prog = parts[1].strip()
        try:
            line = int(parts[2].strip())
        except ValueError:
            continue
        rest = "|".join(parts[3:]).strip()
        if rest.startswith("Paragraph:"):
            events.append(TraceEvent(file, prog, line, "paragraph", rest.split(":", 1)[1].strip()))
        elif rest.startswith("Section:"):
            events.append(TraceEvent(file, prog, line, "section", rest.split(":", 1)[1].strip()))
        elif rest.startswith("Entry:"):
            events.append(TraceEvent(file, prog, line, "entry", rest.split(":", 1)[1].strip()))
        else:
            events.append(TraceEvent(file, prog, line, "statement", rest))
    return events


def _same_file(a: str, b: str) -> bool:
    return a == b or a.rsplit("/", 1)[-1].lower() == b.rsplit("/", 1)[-1].lower()


@dataclass
class CoverageInfo:
    paragraphs_total: list[str]
    paragraphs_hit: set[str]
    statements_total: set[tuple[str, int]]
    statements_hit: set[tuple[str, int]]

    @property
    def paragraph_ratio(self) -> float:
        return len(self.paragraphs_hit) / len(self.paragraphs_total) if self.paragraphs_total else 1.0

    @property
    def statement_ratio(self) -> float:
        if not self.statements_total:
            return 1.0
        return len(self.statements_hit & self.statements_total) / len(self.statements_total)


def statement_lines(prog: Program) -> set[tuple[str, int]]:
    return {(st.file, st.line) for st in prog.walk_statements()}


def case_coverage(prog: Program, events: list[TraceEvent]) -> tuple[set[str], set[tuple[str, int]]]:
    """Paragraphs and statement lines executed in one run."""
    total = statement_lines(prog)
    hit_lines: set[tuple[str, int]] = set()
    paras: set[str] = set()
    for ev in events:
        if ev.program.upper() != prog.program_id:
            continue
        if ev.kind == "paragraph":
            paras.add(ev.name.upper())
        elif ev.kind == "statement":
            for f, ln in total:
                if ln == ev.line and _same_file(f, ev.file):
                    hit_lines.add((f, ln))
                    break
    for p in prog.paragraphs:
        if p.name in paras:
            continue
        if any(f == p.file and p.line <= ln <= p.end_line for f, ln in hit_lines):
            paras.add(p.name)  # e.g. (MAIN): no Paragraph event, but its statements ran
    return paras, hit_lines


def combine(prog: Program, per_case: list[tuple[set[str], set[tuple[str, int]]]]) -> CoverageInfo:
    paras: set[str] = set()
    lines: set[tuple[str, int]] = set()
    for p, ls in per_case:
        paras |= p
        lines |= ls
    return CoverageInfo([p.name for p in prog.paragraphs], paras & {p.name for p in prog.paragraphs},
                        statement_lines(prog), lines)


def greedy_minimise(per_case: dict[str, tuple[set[str], set[tuple[str, int]]]]) -> list[str]:
    """Smallest-ish case subset with the same coverage (greedy set cover); reported only."""
    remaining = set().union(*(ls for _p, ls in per_case.values())) if per_case else set()
    chosen: list[str] = []
    while remaining:
        best = max(sorted(per_case), key=lambda c: len(per_case[c][1] & remaining))
        gain = per_case[best][1] & remaining
        if not gain:
            break
        chosen.append(best)
        remaining -= gain
    return chosen


def display_events(events: list[TraceEvent], prog: Program) -> list[TraceEvent]:
    return [e for e in events if e.kind == "statement" and e.name.split()[0] == "DISPLAY"
            and e.program.upper() == prog.program_id]
