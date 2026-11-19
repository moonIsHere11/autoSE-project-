"""Run O2 traces and O3 inventories for D1/D2 and fold them into the E2 and E4 metrics."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from phase0.evaluation.datasets import Built
from phase0.evaluation.e2_e4_control import (
    ControlKb,
    ControlTally,
    camel,
    check_run,
    java_methods,
    manifest_units,
    ratio,
)
from phase0.evaluation.o2 import trace_program
from phase0.toolbox import Toolbox


@dataclass
class Inventory:
    kb: int = 0
    oracle: int = 0
    common: int = 0
    kb_only: list[str] = field(default_factory=list)
    oracle_only: list[str] = field(default_factory=list)

    def add(self, key: str, kb: set[str], oracle: set[str]) -> None:
        self.kb += len(kb)
        self.oracle += len(oracle)
        self.common += len(kb & oracle)
        self.kb_only += [f"{key}:{n}" for n in sorted(kb - oracle)]
        self.oracle_only += [f"{key}:{n}" for n in sorted(oracle - kb)]

    def scores(self) -> dict[str, Any]:
        return {"kb": self.kb, "oracle": self.oracle, "common": self.common,
                "precision": ratio(self.common, self.kb), "recall": ratio(self.common, self.oracle),
                "kb_only": self.kb_only, "oracle_only": self.oracle_only}


@dataclass
class ControlEval:
    tally: ControlTally = field(default_factory=ControlTally)
    static: set[tuple[str, str, str, str]] = field(default_factory=set)
    exercised: set[tuple[str, str, str, str]] = field(default_factory=set)
    entered: set[str] = field(default_factory=set)
    entered_paragraphs: set[str] = field(default_factory=set)
    missing: list[str] = field(default_factory=list)
    paragraphs: int = 0
    programs: int = 0
    cases: int = 0
    java: Inventory = field(default_factory=Inventory)
    manifest: Inventory = field(default_factory=Inventory)
    errors: list[dict[str, Any]] = field(default_factory=list)


def control_kb(b: Built) -> ControlKb:
    return ControlKb.load(b.kb("source/units.json"), b.kb("source/call_graph.json")["edges"])


def evaluate_program(ce: ControlEval, b: Built, toolbox: Toolbox, out: Path) -> ControlKb:
    key = f"{b.program.dataset}/{b.program.name}"
    kb = control_kb(b)
    repro = f"phase0/bin/phase0 eval --workspace {out} --only {b.program.name}"
    paras = {u for u, x in kb.units.items() if x["kind"] == "paragraph"}
    ce.paragraphs += len(paras)
    if b.program.java_dir is not None:
        ce.java.add(key, {camel(p) for p in paras}, java_methods(b.program.java_dir) - {"main"})
    if b.program.manifest is not None:
        ce.manifest.add(key, paras, manifest_units(b.program.manifest))
    traces = trace_program(toolbox, b.ws / "source", b.program.entry, b.program.cases)
    if traces.error is not None:
        ce.errors.append({"metric": "E4", "program": key, "kind": "trace failed", "detail": traces.error, "repro": repro})
        return kb
    ce.programs += 1
    ce.cases += traces.cases
    local = ControlTally()
    for run in traces.runs:
        check_run(kb, run, local, key, repro)
    fold(ce, local, key, kb)
    return kb


def fold(ce: ControlEval, local: ControlTally, key: str, kb: ControlKb) -> None:
    t = ce.tally
    t.transitions += local.transitions
    t.violations += local.violations
    t.start_checked += local.start_checked
    t.start_matched += local.start_matched
    t.statements += local.statements
    t.statements_in_span += local.statements_in_span
    names = {u for u, x in kb.units.items() if x["kind"] in ("paragraph", "section")}
    ce.entered |= {f"{key}:{n}" for n in local.entered}
    ce.entered_paragraphs |= {f"{key}:{n}" for n in local.entered if kb.units.get(n, {}).get("kind") == "paragraph"}
    ce.missing += [f"{key}:{n}" for n in sorted(local.entered - names)]
    ce.static |= {(key, s, d, k) for (s, d, k) in kb.edges}
    ce.exercised |= {(key, s, d, k) for (s, d, k) in local.exercised}


def e2_metrics(ce: ControlEval) -> dict[str, Any]:
    t = ce.tally
    return {
        "traced_programs": ce.programs,
        "trace_cases": ce.cases,
        "traced_units": len(ce.entered),
        "traced_units_missing_from_kb": ce.missing,
        "traced_unit_recall": ratio(len(ce.entered) - len(ce.missing), len(ce.entered)),
        "paragraphs_executed_share": ratio(len(ce.entered_paragraphs), ce.paragraphs),
        "span_start_exact": ratio(t.start_matched, t.start_checked),
        "span_start_checked": t.start_checked,
        "statements_inside_a_span": ratio(t.statements_in_span, t.statements),
        "java_methods": ce.java.scores(),
        "manifest_units": ce.manifest.scores(),
    }


def e4_metrics(ce: ControlEval) -> dict[str, Any]:
    violations = [v for v in ce.tally.violations if v["metric"] == "E4"]
    return {
        "transitions_checked": ce.tally.transitions,
        "soundness_violations": len(violations),
        "static_edges": len(ce.static),
        "static_edges_exercised": len(ce.exercised & ce.static),
        "static_edges_exercised_share": ratio(len(ce.exercised & ce.static), len(ce.static)),
    }
