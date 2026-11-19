"""Stages C-F on small programs: data layout, control flow, data flow, hazards."""

from __future__ import annotations

from tests.phase0.helpers import facts, unit

HEAD = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
"""

DATAFLOW = HEAD + """       01 REC.
          05 A          PIC 9(3).
          05 B          PIC X(2).
       01 OUT-REC       PIC X(5).
       01 D             PIC 9(8).
       01 D-PARTS REDEFINES D.
          05 YYYY       PIC 9(4).
          05 MMDD       PIC 9(4).
       01 TBL.
          05 CELL       PIC 9(2) OCCURS 3.
       01 I             PIC 9.
       01 X             PIC S9(3)V99.
       01 Y             PIC 9(2).
       PROCEDURE DIVISION.
       GROUP-MOVE.
           MOVE REC TO OUT-REC.
       ALIAS-WRITE.
           MOVE 20240115 TO D.
       ALIAS-READ.
           DISPLAY YYYY.
       SUBSCRIPT-WRITE.
           MOVE 7 TO CELL (I).
       NARROW.
           MOVE X TO Y
           COMPUTE Y = X * 2
           STOP RUN.
"""


def test_group_move_expands_to_elementary_items() -> None:
    u = unit(facts(DATAFLOW), "GROUP-MOVE")
    assert u.reads == ["REC.A", "REC.B"]
    assert u.writes == ["OUT-REC"]


def test_redefines_aliasing_both_directions() -> None:
    f = facts(DATAFLOW)
    assert unit(f, "ALIAS-WRITE").writes == ["D", "D-PARTS.MMDD", "D-PARTS.YYYY"]
    assert unit(f, "ALIAS-WRITE").reads == []
    assert unit(f, "ALIAS-READ").reads == ["D", "D-PARTS.YYYY"]


def test_subscripted_write_also_reads_the_table() -> None:
    u = unit(facts(DATAFLOW), "SUBSCRIPT-WRITE")
    assert u.writes == ["TBL.CELL"]
    assert u.reads == ["I", "TBL.CELL"]


def test_data_dictionary_layout() -> None:
    f = {x.field_id: x for x in facts(DATAFLOW).fields}
    assert (f["REC.B"].offset, f["REC.B"].byte_length) == (3, 2)
    assert f["D-PARTS"].redefines == "D"
    assert f["TBL.CELL"].occurs == 3 and f["TBL"].byte_length == 6
    x = f["X"].semantic_type
    assert (x.kind, x.digits, x.scale, x.signed) == ("decimal", 5, 2, True)
    assert f["OUT-REC"].semantic_type.length == 5 and f["REC"].semantic_type.kind == "group"


def test_hazards_use_phase1_gap_ids() -> None:
    gaps = sorted({h.gap_id for h in unit(facts(DATAFLOW), "NARROW").hazards})
    assert gaps == ["G-OVERFLOW", "G-SIGN", "G-TRUNCATE"]


CONTROL = HEAD + """       01 WS-PGM        PIC X(8) VALUE 'SUBA'.
       01 WS-OTHER      PIC X(8).
       01 N             PIC 9.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM P1 THRU P3
           PERFORM SEC-B
           MOVE 'SUBB' TO WS-PGM
           CALL WS-PGM
           CALL 'LIT'
           CALL WS-OTHER
           IF N > 1 GO TO P3 END-IF.
       P1.
           ADD 1 TO N.
       P2.
           GO TO P3.
       P3.
           EXIT.
       SEC-B SECTION.
       B1.
           DISPLAY N.
       B2.
           STOP RUN.
"""


def test_control_flow_edges() -> None:
    f = facts(CONTROL)
    main = unit(f, "MAIN-PARA")
    assert main.performs == ["P1", "P2", "P3", "SEC-B"]
    assert main.perform_thru == [("P1", "P3")]
    assert main.goes_to == ["P3"] and main.falls_through_to == "P1"
    assert main.calls == ["?WS-OTHER", "LIT", "SUBA", "SUBB"]
    assert unit(f, "P2").falls_through_to is None
    assert unit(f, "P3").falls_through_to == "B1"
    assert unit(f, "B2").exits == ["STOP RUN"] and unit(f, "B2").falls_through_to is None
    sec = unit(f, "SEC-B")
    assert sec.kind == "section" and (sec.span.start_line, sec.span.end_line) == (23, 27)
    kinds = {(e.src, e.dst, e.kind, e.resolution) for e in f.edges}
    assert ("MAIN-PARA", "SUBA", "call", "resolved-by-constant") in kinds
    assert ("MAIN-PARA", "?WS-OTHER", "call", "unresolved") in kinds
    assert ("P1", "P2", "fallthrough", "static") in kinds
    assert ("MAIN-PARA", "P2", "perform-thru", "static") in kinds


def test_paragraph_spans_end_before_section_headers() -> None:
    f = facts(CONTROL)
    assert (unit(f, "P3").span.start_line, unit(f, "P3").span.end_line) == (21, 22)


BRANCHES = HEAD + """       01 K             PIC 9.
       01 LONG-X        PIC X(25).
       01 SHORT-X       PIC X(9).
       01 LEN           PIC 99.
       PROCEDURE DIVISION.
       BOTH-LEAVE.
           IF K = 1
               GO TO DONE
           ELSE
               GO TO OTHER-P
           END-IF.
       OTHER-P.
           EVALUATE K
               WHEN 1 GO TO DONE
               WHEN OTHER STOP RUN
           END-EVALUATE.
       ONE-LEAVES.
           IF K = 1 GO TO DONE END-IF.
       REFMOD.
           MOVE LONG-X (1:LEN) TO SHORT-X
           MOVE LONG-X (1:5) TO SHORT-X
           MOVE LONG-X TO SHORT-X.
       DONE.
           STOP RUN.
"""


def test_branches_that_all_leave_stop_fall_through() -> None:
    f = facts(BRANCHES)
    assert unit(f, "BOTH-LEAVE").falls_through_to is None
    assert unit(f, "OTHER-P").falls_through_to is None
    assert unit(f, "ONE-LEAVES").falls_through_to == "REFMOD"


def test_variable_reference_modification_is_not_a_certain_truncation() -> None:
    details = [h.detail for h in unit(facts(BRANCHES), "REFMOD").hazards if h.gap_id == "G-TRUNCATE"]
    assert details == ["MOVE LONG-X (X(25)) -> SHORT-X (X(9)): right-truncated"]
