"""E5: data-flow soundness of KB reads/writes against O4 (model-based)."""

from __future__ import annotations

from typing import Any

from phase0.evaluation.datasets import Built
from phase0.evaluation.o4 import E5Tally, Facts, check_paragraph, elementaries
from phase0.schema import InventoryEntry
from phase0.stages.layout import index_program
from phase0.stages.parse import parse_programs
from phase0.toolbox import Toolbox

UnitFacts = dict[str, dict[str, Any]]


def reachable(start: str, units: UnitFacts) -> set[str]:
    """Units run_paragraph may execute from `start`: PERFORM targets, GO TO targets, and the
    fall-through chain of anything entered by GO TO (a PERFORM returns at the end of its target)."""
    seen = {start}
    todo = [(start, False)]
    while todo:
        uid, by_goto = todo.pop()
        u = units.get(uid)
        if u is None:
            continue
        nxt = [(p, False) for p in u.get("performs", [])] + [(g, True) for g in u.get("goes_to", [])]
        if by_goto and u.get("falls_through_to"):
            nxt.append((u["falls_through_to"], True))
        for n, flag in nxt:
            if n not in seen:
                seen.add(n)
                todo.append((n, flag))
    return seen


def closed_facts(start: str, units: UnitFacts, return_code: str) -> Facts:
    reads: set[str] = set()
    writes: set[str] = set()
    for uid in reachable(start, units):
        u = units.get(uid, {})
        reads |= set(u.get("reads", []))
        writes |= set(u.get("writes", []))
    return Facts(reads, writes, return_code)


def strict_ir(b: Built, toolbox: Toolbox) -> Any:
    inventory = [InventoryEntry.model_validate(e) for e in b.kb("source/inventory.json")["files"]]
    tb = Toolbox(toolbox.config, toolbox.runner, b.ws / ".phase0-cache", toolbox.versions())
    parsed = parse_programs(tb, b.ws / "source", inventory)
    return parsed.strict[0].ir


def check_program(b: Built, toolbox: Toolbox, units: UnitFacts, label: str, tally: E5Tally) -> None:
    ir = strict_ir(b, toolbox)
    index = index_program(ir.program, "")
    items = elementaries(ir, index.id_of)
    key = f"{b.program.dataset}/{b.program.name}"
    for para in ir.paragraphs:
        if para.name not in units:
            continue
        check_paragraph(ir, para.name, items, closed_facts(para.name, units, "RETURN-CODE"), tally, key, label)


def kb_units(b: Built) -> UnitFacts:
    return {u["unit_id"]: u for u in b.kb("source/units.json")}


def metrics(t: E5Tally) -> dict[str, Any]:
    return {
        "label": "model-based (O4 shares the front end with Phase 0)",
        "paragraphs": t.paragraphs,
        "interpreter_runs": t.runs,
        "refused_runs": t.refused,
        "write_checks": t.write_checks,
        "write_violations": len(t.write_violations),
        "read_checks": t.read_checks,
        "read_violations": len(t.read_violations),
        "declared_writes": t.declared_writes,
        "declared_writes_observed": t.observed_writes,
        "declared_writes_observed_share": round(t.observed_writes / max(t.declared_writes, 1), 4),
    }
