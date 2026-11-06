"""Regression tests for verifier bugs found while building the seed corpus (corpus/INDEX.md)."""

from __future__ import annotations

from verifier.cobol.lexer import map_lines, tokenize
from verifier.cobol.parser import parse_source
from verifier.cobol.syntax import Program


def _parse(src: str) -> list[Program]:
    text = '#line 1 "T.cbl"\n' + "\n".join(" " + ln.strip() for ln in src.strip().splitlines())
    return parse_source(tokenize(map_lines(text, "T.cbl")), "T.cbl")


def test_user_names_starting_with_end_are_not_scope_terminators() -> None:
    # corpus/grades: `PERFORM X UNTIL END-OF-FILE` lost its condition and reported
    # "unexpected 'END-OF-FILE'" because every word starting with END- ended the statement.
    src = """
IDENTIFICATION DIVISION.
PROGRAM-ID. T3.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-EOF PIC X VALUE "N".
88 END-OF-FILE VALUE "Y".
01 END-COUNT PIC 9.
PROCEDURE DIVISION.
P1.
PERFORM P2 UNTIL END-OF-FILE
PERFORM UNTIL END-OF-FILE OR END-COUNT > 3
ADD 1 TO END-COUNT
END-PERFORM
IF END-OF-FILE AND END-COUNT = 1
DISPLAY "Y"
END-IF
EVALUATE TRUE
WHEN END-OF-FILE DISPLAY "E"
END-EVALUATE
STOP RUN.
P2.
MOVE "Y" TO WS-EOF.
"""
    [p] = _parse(src)
    assert not p.parse_errors, p.parse_errors
    st = p.paragraphs[0].statements
    assert [s.verb for s in st] == ["PERFORM", "PERFORM", "IF", "EVALUATE", "STOP"]
    assert st[0].text() == "PERFORM P2 UNTIL END-OF-FILE"
    assert [t.up for t in st[1].tokens][-5:] == ["END-OF-FILE", "OR", "END-COUNT", ">", "3"]
    assert st[1].terminated and st[1].branches[0].body[0].verb == "ADD"
    assert [t.up for t in st[2].tokens][1:] == ["END-OF-FILE", "AND", "END-COUNT", "=", "1"]
    assert st[2].terminated
    assert st[3].branches[0].tokens[-1].up == "END-OF-FILE" and st[3].terminated
