"""Gap/rule catalogue: closed under every gap id Phase 1 and Phase 2 emit, internally consistent."""

from __future__ import annotations

import re
from pathlib import Path

from phase0.target import load_gaps, load_rules

REPO = Path(__file__).resolve().parents[2]
GAP_ID = re.compile(r"\bG-[A-Z]+\b")
REFERENCING = ["phase1/phase1", "phase2/phase2_adapter", "integration"]


def referenced_gap_ids() -> set[str]:
    ids: set[str] = set()
    for d in REFERENCING:
        for p in (REPO / d).rglob("*.py"):
            for line in p.read_text("utf-8").splitlines():
                if '"G-' in line or "'G-" in line:
                    ids |= set(GAP_ID.findall(line))
    return ids


def test_every_referenced_gap_exists() -> None:
    have = {g.gap_id for g in load_gaps()}
    required = {"G-TRUNCATE", "G-OVERFLOW", "G-ROUNDING", "G-SIGN", "G-STORAGE", "G-NUMALPHA", "G-PACKED",
                "G-GROUPMOVE", "G-GOTO", "G-FALLTHROUGH", "G-DIVZERO"}
    found = referenced_gap_ids()
    assert found >= {"G-TRUNCATE", "G-SIGN", "G-GOTO"}  # the scan itself works
    assert sorted((found | required) - have) == []


def test_cross_references_resolve() -> None:
    gaps = {g.gap_id: g for g in load_gaps()}
    rules = {r.rule_id: r for r in load_rules()}
    assert len(gaps) == len(load_gaps()) and len(rules) == len(load_rules())
    for g in gaps.values():
        assert set(g.rule_ids) <= set(rules), g.gap_id
        assert g.source, g.gap_id
    for r in rules.values():
        assert set(r.gap_ids) <= set(gaps), r.rule_id
        assert r.source, r.rule_id


def test_required_constructs_have_rules() -> None:
    constructs = " ".join(r.cobol_construct.upper() for r in load_rules())
    for c in ["MOVE", "DISPLAY", "ACCEPT", "COMPUTE", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "EVALUATE",
              "THRU", "TIMES", "UNTIL", "VARYING", "88", "READ", "WRITE", "IF"]:
        assert c in constructs, c


def test_cited_files_exist() -> None:
    for item in [*load_gaps(), *load_rules()]:
        assert item.source is not None
        for path in re.findall(r"(?:docs|corpus|tests)/[\w./-]+", item.source):
            target = REPO / path.rstrip(".,;")
            assert target.exists(), f"{item}: {path}"
