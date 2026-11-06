from __future__ import annotations

from pathlib import Path

import pytest

from verifier.cobol.datadiv import parse_pic
from verifier.cobol.lexer import map_lines, tokenize
from verifier.cobol.parser import parse_source
from verifier.cobol.preprocess import detect_format, preprocess_all
from verifier.config import CobolConfig
from verifier.sandbox.docker_runner import DockerRunner


def _parse(src: str):  # type: ignore[no-untyped-def]
    text = '#line 1 "T.cbl"\n' + "\n".join(" " + ln.strip() for ln in src.strip().splitlines())
    return parse_source(tokenize(map_lines(text, "T.cbl")), "T.cbl")


@pytest.mark.parametrize(
    ("pic", "cat", "digits", "scale", "signed", "length"),
    [
        ("9(5)", "numeric", 5, 0, False, 5),
        ("S9(5)V99", "numeric", 7, 2, True, 7),
        ("V99", "numeric", 2, 2, False, 2),
        ("9(3)PP", "numeric", 3, -2, False, 3),
        ("PP9(2)", "numeric", 2, 4, False, 2),
        ("X(10)", "alphanumeric", 0, 0, False, 10),
        ("A(3)", "alphabetic", 0, 0, False, 3),
        ("ZZ,ZZ9.99", "numeric-edited", 7, 2, False, 9),
        ("-(4)9", "numeric-edited", 4, 0, True, 5),
    ],
)
def test_parse_pic(pic: str, cat: str, digits: int, scale: int, signed: bool, length: int) -> None:
    p = parse_pic(pic)
    assert (p.category, p.digits, p.scale, p.signed, p.length) == (cat, digits, scale, signed, length)


def test_detect_format() -> None:
    fixed = "       IDENTIFICATION DIVISION.\n      * comment\n       PROGRAM-ID. X.\n"
    free = "IDENTIFICATION DIVISION.\nPROGRAM-ID. X.\n*> c\n"
    assert detect_format(fixed) == "fixed"
    assert detect_format(free) == "free"


SAMPLE = """
IDENTIFICATION DIVISION.
PROGRAM-ID. SAMPLE.
ENVIRONMENT DIVISION.
INPUT-OUTPUT SECTION.
FILE-CONTROL.
SELECT IN-FILE ASSIGN TO "IN.DAT" ORGANIZATION IS LINE SEQUENTIAL FILE STATUS IS WS-FS.
SELECT OUT-FILE ASSIGN TO OUTF ORGANIZATION IS SEQUENTIAL.
DATA DIVISION.
FILE SECTION.
FD IN-FILE.
01 IN-REC.
05 IN-AMT PIC S9(5)V99.
05 IN-NAME PIC X(10).
FD OUT-FILE.
01 OUT-REC PIC X(20).
WORKING-STORAGE SECTION.
01 WS-FS PIC XX.
01 WS-EOF PIC X VALUE "N".
88 EOF-YES VALUE "Y".
01 WS-TOTAL PIC S9(7)V99 COMP-3 VALUE ZERO.
01 WS-TAB.
05 WS-E PIC 9(2) OCCURS 3 TIMES.
01 WS-R REDEFINES WS-TAB PIC X(6).
77 WS-I PIC 9(4) COMP.
PROCEDURE DIVISION.
MAIN-PARA.
OPEN INPUT IN-FILE OUTPUT OUT-FILE
PERFORM UNTIL EOF-YES
READ IN-FILE
AT END SET EOF-YES TO TRUE
NOT AT END
ADD IN-AMT TO WS-TOTAL ON SIZE ERROR DISPLAY "OVF" END-ADD
PERFORM CALC-PARA
END-READ
END-PERFORM
IF WS-TOTAL > 1000
DISPLAY "BIG" WS-TOTAL
ELSE
EVALUATE TRUE
WHEN WS-TOTAL < 0 DISPLAY "NEG"
WHEN OTHER CONTINUE
END-EVALUATE
END-IF
CLOSE IN-FILE OUT-FILE
STOP RUN.
CALC-PARA.
COMPUTE WS-I ROUNDED = WS-I + 1.
"""


def test_parse_structure_and_layout() -> None:
    [p] = _parse(SAMPLE)
    assert p.program_id == "SAMPLE"
    assert not p.parse_errors, p.parse_errors
    assert [s.name for s in p.selects] == ["IN-FILE", "OUT-FILE"]
    assert p.selects[0].organization == "LINE SEQUENTIAL" and p.selects[0].assign == "IN.DAT"
    assert p.selects[0].file_status == "WS-FS"
    assert p.selects[1].assign_kind == "name" and p.selects[1].organization == "SEQUENTIAL"
    assert p.fd("IN-FILE").record_size == 17  # type: ignore[union-attr]
    assert p.resolve("WS-TOTAL").size == 5  # type: ignore[union-attr]
    assert p.resolve("WS-TAB").size == 6  # type: ignore[union-attr]
    assert p.resolve("WS-E").unit_size == 2 and p.resolve("WS-E").occurs == 3  # type: ignore[union-attr]
    assert p.resolve("WS-I").size == 2  # type: ignore[union-attr]
    assert "EOF-YES" in p.condition_names()
    assert [para.name for para in p.paragraphs] == ["MAIN-PARA", "CALC-PARA"]
    verbs = [s.verb for s in p.paragraphs[0].walk()]
    assert verbs == ["OPEN", "PERFORM", "READ", "SET", "ADD", "DISPLAY", "PERFORM", "IF", "DISPLAY",
                     "EVALUATE", "DISPLAY", "CONTINUE", "CLOSE", "STOP"]
    read = next(s for s in p.paragraphs[0].walk() if s.verb == "READ")
    assert [b.kind for b in read.branches] == ["at_end", "not_at_end"] and read.terminated
    add = next(s for s in p.paragraphs[0].walk() if s.verb == "ADD")
    assert [b.kind for b in add.branches] == ["size_error"] and add.terminated
    perf = next(s for s in p.paragraphs[0].walk() if s.verb == "PERFORM" and s.branches == [])
    assert perf.text() == "PERFORM CALC-PARA"


def test_unterminated_conditional_statements_bind_correctly() -> None:
    src = """
IDENTIFICATION DIVISION.
PROGRAM-ID. T2.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 A PIC 9.
01 B PIC 9.
PROCEDURE DIVISION.
P1.
IF A = 1
ADD 1 TO B ON SIZE ERROR DISPLAY "E"
ELSE
MOVE 0 TO B.
DISPLAY B.
"""
    [p] = _parse(src)
    assert not p.parse_errors
    st = p.paragraphs[0].statements
    assert [s.verb for s in st] == ["IF", "DISPLAY"]
    if_st = st[0]
    assert [b.kind for b in if_st.branches] == ["then", "else"]
    assert if_st.branches[0].body[0].branches[0].body[0].verb == "DISPLAY"
    assert if_st.branches[1].body[0].verb == "MOVE"


@pytest.mark.docker
def test_layout_matches_gnucobol_byte_lengths(runner: DockerRunner, repo: Path, tmp_path: Path) -> None:
    spikes = repo / "docs" / "spikes" / "s6"
    pre = preprocess_all(runner, CobolConfig(), spikes, ["S6DISP.cbl", "S6FILE.cbl"], tmp_path)
    assert pre["S6DISP.cbl"].ok, pre["S6DISP.cbl"].diagnostics
    [p] = parse_source(tokenize(pre["S6DISP.cbl"].lines), "S6DISP.cbl")
    assert not p.parse_errors, p.parse_errors
    # byte lengths printed by GnuCOBOL FUNCTION BYTE-LENGTH in spike S6
    expected = {"D-U3": 3, "D-S3": 3, "D-SV": 5, "D-LS": 4, "D-TS": 4, "D-LE": 3, "D-TE": 3,
                "D-C3": 4, "D-C3U": 3, "D-CB": 2, "D-CB9": 4, "D-B18": 8, "D-C5": 2, "D-C5U": 1,
                "D-P": 3, "D-PL": 2, "D-X": 5, "D-GRP": 7, "D-TAB": 6}
    got = {k: p.resolve(k).size for k in expected}  # type: ignore[union-attr]
    assert got == expected
    # statement lines are original source lines (as in the trace): DISPLAY of U3 is on line 39
    first_display = next(s for s in p.walk_statements() if s.verb == "DISPLAY")
    assert (first_display.file, first_display.line) == ("S6DISP.cbl", 39)
    [f] = parse_source(tokenize(pre["S6FILE.cbl"].lines), "S6FILE.cbl")
    assert f.fd("FIX-OUT").record_size == 22  # type: ignore[union-attr]
    assert {s.name: s.assign_kind for s in f.selects}["PLAIN"] == "name"
