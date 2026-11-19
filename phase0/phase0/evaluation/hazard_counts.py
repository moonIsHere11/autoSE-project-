"""Stage F check: hazard sites per gap id, Phase 0 vs Phase 1's scanner on the same workspaces,
next to the mid-report's CardDemo numbers (Phase 1's scanner at the time)."""

from __future__ import annotations

from collections import Counter
from typing import Any

from phase0.evaluation import baseline
from phase0.evaluation.datasets import Built

MID_REPORT_CARDDEMO = {"G-TRUNCATE": 180, "G-OVERFLOW": 168, "G-GROUPMOVE": 152, "G-NUMALPHA": 138, "G-GOTO": 86,
                       "G-SIGN": 63}


def paragraph_counts(units: list[dict[str, Any]]) -> Counter[str]:
    """Sites in paragraphs only: section units repeat their paragraphs' hazards."""
    c: Counter[str] = Counter()
    for u in units:
        if u["kind"] == "paragraph":
            c.update(h["gap_id"] for h in u.get("hazards", []))
    return c


def hazard_counts(built: list[Built]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for ds in sorted({b.program.dataset for b in built}):
        p0: Counter[str] = Counter()
        p1: Counter[str] = Counter()
        for b in built:
            if b.program.dataset != ds:
                continue
            p0 += paragraph_counts(b.kb("source/units.json"))
            p1 += paragraph_counts(baseline.analyse(b)["units"])
        row: dict[str, Any] = {"phase0": dict(sorted(p0.items())), "phase1_now": dict(sorted(p1.items()))}
        if ds == "D3":
            row["mid_report"] = MID_REPORT_CARDDEMO
        out[ds] = row
    return out
