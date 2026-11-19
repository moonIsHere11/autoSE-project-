"""E7: Phase 1's tolerant analyser scored on E2-E5 with the same oracle runs as Phase 0."""

from __future__ import annotations

from typing import Any

from phase0.evaluation import baseline
from phase0.evaluation.datasets import Built
from phase0.evaluation.e2_e4_run import ControlEval, e2_metrics, e4_metrics, evaluate_facts
from phase0.evaluation.e3_data import Tally
from phase0.evaluation.e5_run import check_program
from phase0.evaluation.e5_run import metrics as e5_metrics
from phase0.evaluation.o1 import O1Outcome, shown_type
from phase0.evaluation.o4 import E5Tally
from phase0.toolbox import Toolbox

LAYOUT = ("offset(probe)", "byte_length(probe)")


def score_types(t: Tally, key: str, fields: list[dict[str, Any]], o1: O1Outcome) -> None:
    """Probe-observed sign/digits/scale and layout against Phase 1's fields (matched by field id)."""
    probe = o1.probe.get(key)
    if probe is None or probe.error is not None:
        return
    by_id = {f["field_id"]: f for f in fields}
    for fid, (offset, length) in sorted(probe.offsets.items()):
        f = by_id.get(fid, {})
        t.check("offset(probe)", key, fid, f.get("offset"), offset, "GnuCOBOL probe", "")
        t.check("byte_length(probe)", key, fid, f.get("byte_length"), length, "GnuCOBOL probe", "")
    for fid, text in sorted(probe.shown.items()):
        signed, digits, scale = shown_type(text)
        st = by_id.get(fid, {}).get("semantic_type") or {}
        t.check("signed(probe)", key, fid, st.get("signed"), signed, "GnuCOBOL probe", "")
        if "P" not in (by_id.get(fid, {}).get("pic") or "").upper():
            t.check("digits(probe)", key, fid, st.get("digits"), digits, "GnuCOBOL probe", "")
        t.check("scale(probe)", key, fid, st.get("scale"), scale, "GnuCOBOL probe", "")


def run_baseline(built: list[Built], toolbox: Toolbox, control: ControlEval, o1: O1Outcome,
                 out: Any) -> dict[str, Any]:
    ce = ControlEval()
    types = Tally()
    flow = E5Tally()
    failures: list[dict[str, Any]] = []
    for b in built:
        key = f"{b.program.dataset}/{b.program.name}"
        index = baseline.analyse(b)
        us = baseline.units(index)
        evaluate_facts(ce, b, baseline.control_kb(us), toolbox, out, key, control.traces.get(key))
        score_types(types, key, baseline.fields(index), o1)
        check_program(b, toolbox, baseline.unit_facts(us), "phase1", flow)
    failures += [dict(v, source="phase1") for v in ce.tally.violations]
    failures += [dict(f, source="phase1") for f in types.failures if f["attribute"] not in LAYOUT]
    failures += flow.write_violations + flow.read_violations
    return {"E2": e2_metrics(ce), "E3": types.rates(), "E4": e4_metrics(ce), "E5": e5_metrics(flow),
            "failures": failures}
