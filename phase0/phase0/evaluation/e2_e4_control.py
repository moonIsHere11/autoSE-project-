"""E2 (unit inventory, spans) and E4 (control-flow soundness) against O2 traces and O3 Java."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from verifier.cobol.trace import TraceEvent

CONTROL = {"perform", "perform-thru", "goto", "fallthrough"}


@dataclass
class ControlKb:
    """The KB facts E2/E4 use, read from kb/ JSON (bare names: one program per D1/D2 workspace)."""

    units: dict[str, dict[str, Any]]
    edges: set[tuple[str, str, str]]  # (src, dst, kind)
    perform_sites: dict[tuple[str, int], set[str]]  # (src unit, line) -> PERFORM targets

    @classmethod
    def load(cls, units: list[dict[str, Any]], edges: list[dict[str, Any]]) -> ControlKb:
        sites: dict[tuple[str, int], set[str]] = {}
        for e in edges:
            if e["kind"] in ("perform", "perform-thru"):
                sites.setdefault((e["src"], e["line"]), set()).add(e["dst"])
        return cls({u["unit_id"]: u for u in units},
                   {(e["src"], e["dst"], e["kind"]) for e in edges if e["kind"] in CONTROL}, sites)

    def paragraph_at(self, file: str, line: int) -> str | None:
        best: tuple[int, str] | None = None
        for uid, u in self.units.items():
            sp = u["span"]
            if u["kind"] == "paragraph" and same_file(sp["file"], file) and sp["start_line"] <= line <= sp["end_line"]:
                width = sp["end_line"] - sp["start_line"]
                if best is None or width < best[0]:
                    best = (width, uid)
        if best is None:
            return None
        return best[1]

    def first_paragraph(self, section: str) -> str | None:
        paras = [u for u in self.units.values() if u["kind"] == "paragraph" and u.get("section") == section]
        if not paras:
            return None
        return min(paras, key=lambda u: u["span"]["start_line"])["unit_id"]

    def explains(self, src: str, dst: str) -> tuple[str, str, str] | None:
        """A static edge src -> dst (a section counts through its first paragraph)."""
        for kind in ("perform", "perform-thru", "goto", "fallthrough"):
            if (src, dst, kind) in self.edges:
                return (src, dst, kind)
        dst_unit = self.units.get(dst)
        if dst_unit is not None and dst_unit["kind"] == "section":
            first = self.first_paragraph(dst)
            if first is not None:
                for kind in ("goto", "fallthrough"):
                    if (src, first, kind) in self.edges:
                        return (src, first, kind)
        return None


def same_file(a: str, b: str) -> bool:
    return a == b or Path(a).name.lower() == Path(b).name.lower()


@dataclass
class ControlTally:
    transitions: int = 0
    violations: list[dict[str, Any]] = field(default_factory=list)
    exercised: set[tuple[str, str, str]] = field(default_factory=set)
    entered: set[str] = field(default_factory=set)
    start_checked: int = 0
    start_matched: int = 0
    statements: int = 0
    statements_in_span: int = 0
    entered_keys: set[str] = field(default_factory=set)
    entered_paragraphs: set[str] = field(default_factory=set)
    exercised_by: dict[str, set[tuple[str, str, str]]] = field(default_factory=dict)


def check_run(kb: ControlKb, run: list[TraceEvent], tally: ControlTally, program: str, repro: str) -> None:
    performed: set[str] = set()
    prev: TraceEvent | None = None
    current: str | None = None
    for ev in run:
        if ev.kind == "statement":
            tally.statements += 1
            unit = kb.paragraph_at(ev.file, ev.line)
            if unit is not None:
                tally.statements_in_span += 1
            if ev.name.startswith("PERFORM") and unit is not None:
                performed |= kb.perform_sites.get((unit, ev.line), set())
        if ev.kind in ("paragraph", "section"):
            tally.entered.add(ev.name)
            check_span(kb, ev, tally, program, repro)
            check_entry(kb, ev, prev, current, performed, tally, program, repro)
            if ev.kind == "paragraph":
                current = ev.name
        if ev.kind != "entry" or prev is None:
            prev = ev


def check_span(kb: ControlKb, ev: TraceEvent, tally: ControlTally, program: str, repro: str) -> None:
    u = kb.units.get(ev.name)
    tally.start_checked += 1
    if u is not None and u["span"]["start_line"] == ev.line:
        tally.start_matched += 1
        return
    tally.violations.append({"metric": "E2", "kind": "span start", "program": program, "unit": ev.name,
                             "trace_line": ev.line, "kb": u and u["span"], "repro": repro})


def source_unit(kb: ControlKb, prev: TraceEvent | None, current: str | None) -> str | None:
    if prev is None:
        return None
    if prev.kind == "statement":
        return kb.paragraph_at(prev.file, prev.line) or current
    if prev.kind in ("paragraph", "section"):
        return prev.name
    return None


def check_entry(kb: ControlKb, ev: TraceEvent, prev: TraceEvent | None, current: str | None, performed: set[str],
                tally: ControlTally, program: str, repro: str) -> None:
    tally.transitions += 1
    if prev is None or prev.kind == "entry":
        return  # program start
    if prev.kind == "section" and ev.kind == "paragraph":
        u = kb.units.get(ev.name)
        if u is not None and u.get("section") == prev.name:
            return  # a section starts with its first paragraph
    src = source_unit(kb, prev, current)
    if src is not None:
        edge = kb.explains(src, ev.name)
        if edge is not None:
            tally.exercised.add(edge)
            return
    if ev.name in performed:
        return  # re-entry from the loop of an earlier PERFORM of this target
    tally.violations.append({"metric": "E4", "kind": "unexplained transition", "program": program,
                             "from_unit": src, "to": ev.name, "previous_event": f"{prev.kind} {prev.name} @{prev.line}",
                             "repro": repro})


# ---- O3: Java method inventory ------------------------------------------------------------------
METHOD = re.compile(r"^\s+(?:(?:public|protected|private|static|final|synchronized)\s+)*void\s+([a-z]\w*)\s*\(\s*\)",
                    re.M)


def camel(name: str) -> str:
    parts = [p for p in re.split(r"[-_]", name.lower()) if p]
    if not parts:
        return name
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])


def java_methods(java_dir: Path) -> set[str]:
    names: set[str] = set()
    for p in java_dir.rglob("*.java"):
        names |= set(METHOD.findall(p.read_text("utf-8", errors="replace")))
    return names


def manifest_units(manifest: Path) -> set[str]:
    data = json.loads(manifest.read_text("utf-8"))
    return {u["cobol_paragraph"].upper() for p in data["programs"] for u in p.get("units", [])}


def inventory_scores(kb_paragraphs: set[str], oracle: set[str]) -> dict[str, Any]:
    tp = len(kb_paragraphs & oracle)
    return {"kb": len(kb_paragraphs), "oracle": len(oracle), "common": tp,
            "precision": ratio(tp, len(kb_paragraphs)), "recall": ratio(tp, len(oracle)),
            "kb_only": sorted(kb_paragraphs - oracle), "oracle_only": sorted(oracle - kb_paragraphs)}


def ratio(a: int, b: int) -> float:
    if b == 0:
        return 1.0
    return round(a / b, 4)
