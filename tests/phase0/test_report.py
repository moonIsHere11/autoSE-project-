"""`phase0 report` documents: generated from facts, deterministic, rationale never invented."""

from __future__ import annotations

from pathlib import Path

from phase0 import jsonio
from phase0.report import Facts, documents, records
from phase0.schema import CallGraph, DataFlow
from tests.phase0.helpers import facts

SRC = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 AMT           PIC S9(5)V99 COMP-3.
       01 CNT           PIC 9(2).
       PROCEDURE DIVISION.
       MAIN-PARA.
           ADD 1 TO CNT
      *    Keep the count small because the report has two columns.
           COMPUTE AMT = AMT * 2
           IF CNT > 5 GO TO DONE END-IF.
       DONE.
           MOVE 4 TO RETURN-CODE
           STOP RUN.
"""


def kb_facts(tmp: Path) -> Facts:
    f = facts(SRC)
    (tmp / "T.cbl").write_text(SRC, "latin-1")
    return Facts([u.model_dump(mode="json") for u in f.units], [x.model_dump(mode="json") for x in f.fields],
                 jsonio.to_data(CallGraph(edges=f.edges))["edges"],  # type: ignore[index]
                 jsonio.to_data(DataFlow(fields=[], files=[])), [], tmp)  # type: ignore[arg-type]


def test_records_come_from_fact_patterns(tmp_path: Path) -> None:
    titles = sorted(r.title for r in records(kb_facts(tmp_path)))
    assert titles == ["Control flow through GO TO and fall-through ranges", "Errors signalled through RETURN-CODE",
                      "Fixed-point decimal arithmetic", "Silent high-order truncation"]
    assert all(r.rationale == "unknown" or "because" in r.rationale for r in records(kb_facts(tmp_path)))


def test_documents_are_deterministic(tmp_path: Path) -> None:
    assert documents(kb_facts(tmp_path)) == documents(kb_facts(tmp_path))
    assert "flowchart TD" in documents(kb_facts(tmp_path))["views/T.control.md"]
