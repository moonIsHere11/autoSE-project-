"""Pieces of `phase0 eval` that need no Docker: gold scoring, schema export, listing parsing."""

from __future__ import annotations

from phase0.evaluation.e6_gold import agreement, score
from phase0.evaluation.o1 import parse_listing, shown_type

from phase0.schemas import stale

GOLD_A = {"annotator": "A", "programs": {"P": {"paragraphs": {
    "MAIN": {"reads": ["X", "Y"], "writes": ["Z"], "performs": ["SUB"], "goes_to": [], "falls_through_to": "SUB"},
    "SUB": {"reads": [], "writes": [], "performs": [], "goes_to": [], "falls_through_to": None}}}}}
GOLD_B = {"annotator": "B", "programs": {"P": {"paragraphs": {
    "MAIN": {"reads": ["X"], "writes": ["Z"], "performs": ["SUB"], "goes_to": [], "falls_through_to": "SUB"}}}}}
UNITS = {"P": {"MAIN": {"reads": ["X", "Y", "W"], "writes": ["Z"], "performs": ["SUB"], "goes_to": [],
                        "falls_through_to": "SUB"}}}


def test_gold_scoring_counts_only_annotated_paragraphs() -> None:
    res, failures = score(UNITS, {"A": GOLD_A}, "phase0")
    reads = res["overall"]["reads"]
    assert (reads["tp"], reads["fp"], reads["fn"]) == (2, 1, 0)
    assert res["paragraphs"] == 1 and res["falls_through_to_accuracy"] == 1.0
    assert failures == []


def test_agreement_is_pairwise_f1() -> None:
    a = agreement({"A": GOLD_A, "B": GOLD_B})["A~B"]
    assert a["writes"] == 1.0 and a["reads"] == round(2 * 1 * 0.5 / 1.5, 4)


def test_exported_schemas_are_current() -> None:
    assert stale() == []


def test_listing_rows_and_display_types() -> None:
    text = """SIZE  TYPE           LVL  NAME                           PICTURE

      WORKING-STORAGE SECTION

00027 GROUP          01   TBL
00027 GROUP          05   ROW                            OCCURS 3
00002 NUMERIC        10   CELL                           9(2), OCCURS 4
00004 NUMERIC        01   PK                             S9(7) COMP-3, REDEFINES RAW
      CONDITIONAL    88   IS-OK
"""
    rows = parse_listing(text)
    assert [(r.name, r.size, r.occurs) for r in rows[:3]] == [("TBL", 27, None), ("ROW", 27, 3), ("CELL", 2, 4)]
    assert rows[3].redefines == "RAW" and rows[3].picture == "S9(7) COMP-3"
    assert rows[4].type == "CONDITIONAL"
    assert shown_type("-001.50") == (True, 5, 2) and shown_type("007") == (False, 3, 0)
