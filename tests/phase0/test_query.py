from __future__ import annotations

from pathlib import Path

import pytest
from phase0.cli import run_query
from phase0.query import KnowledgeBase, QueryError
from phase0.schema import SourceSpan, Unit
from phase0.target import load_gaps, load_rules

from phase0 import jsonio


def unit(uid: str, start: int, end: int, performs: list[str]) -> Unit:
    return Unit(unit_id=uid, kind="paragraph", span=SourceSpan(file="P.cbl", start_line=start, end_line=end),
                reads=["A"], writes=["B"], performs=performs, calls=[], falls_through_to=None, summary=None)


@pytest.fixture()
def kb(tmp_path: Path) -> KnowledgeBase:
    (tmp_path / "source").mkdir()
    (tmp_path / "source" / "P.cbl").write_text("L1\nL2\nL3\nL4\n", "latin-1")
    k = tmp_path / "kb"
    jsonio.write(k / "manifest.json", {})
    jsonio.write_model(k / "source" / "units.json", [unit("MAIN-PARA", 1, 2, ["CALC-FEE"]), unit("CALC-FEE", 3, 4, [])])
    jsonio.write_model(k / "target" / "semantic_gaps.json", load_gaps())
    jsonio.write_model(k / "target" / "mapping_rules.json", load_rules())
    jsonio.write(k / "source" / "call_graph.json", {"schema_version": "1.1", "edges": [
        {"src": "MAIN-PARA", "dst": "CALC-FEE", "kind": "perform", "line": 1, "file": "P.cbl", "resolution": "static"}]})
    return KnowledgeBase(k, tmp_path / "source")


def test_units_and_source_text(kb: KnowledgeBase) -> None:
    assert [u["unit_id"] for u in run_query(kb, "list_units", [])] == ["MAIN-PARA", "CALC-FEE"]  # type: ignore[union-attr,index]
    assert run_query(kb, "source_text", ["CALC-FEE"]) == "L3\nL4\n"
    assert run_query(kb, "callers", ["CALC-FEE"]) == ["MAIN-PARA"]
    assert run_query(kb, "callees", ["MAIN-PARA"]) == ["CALC-FEE"]


def test_unknown_ids_teach(kb: KnowledgeBase) -> None:
    with pytest.raises(QueryError, match=r"Did you mean: CALC-FEE.*Valid unit_ids: MAIN-PARA, CALC-FEE"):
        run_query(kb, "get_unit", ["CALC-FE"])
    with pytest.raises(QueryError, match="Valid methods"):
        run_query(kb, "nope", [])


def test_rules_and_gaps_matching(kb: KnowledgeBase) -> None:
    ids = [g["gap_id"] for g in run_query(kb, "gaps_for", ["G-TRUNCATE,rounding"])]  # type: ignore[union-attr,index]
    assert ids[0] == "G-TRUNCATE" and "G-ROUNDING" in ids
    rules = [r["rule_id"] for r in run_query(kb, "rules_for", ["EVALUATE", "G-DIVZERO"])]  # type: ignore[union-attr,index]
    assert rules[0] == "R-EVALUATE" and "R-ARITH" in rules
    assert len(run_query(kb, "gaps_for", [])) == len(load_gaps())  # type: ignore[arg-type]
    with pytest.raises(QueryError, match="Valid gaps"):
        run_query(kb, "gaps_for", ["quantum"])
