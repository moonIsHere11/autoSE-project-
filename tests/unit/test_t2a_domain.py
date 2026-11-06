from __future__ import annotations

from verifier.cobol import analysis
from verifier.cobol.lexer import map_lines, tokenize
from verifier.cobol.parser import parse_source
from verifier.cobol.syntax import Program
from verifier.inputs.strategies import ProgramInputs
from verifier.langpacks.base import NotApplicable
from verifier.tiers.t2_exhaustive import Domain, input_domain


def _prog(src: str) -> Program:
    text = '#line 1 "T.cbl"\n' + "\n".join(" " + ln.strip() for ln in src.strip().splitlines())
    return parse_source(tokenize(map_lines(text, "T.cbl")), "T.cbl")[0]


def _domain(src: str, limit: int = 20000) -> Domain | NotApplicable:
    p = _prog(src)
    ch = analysis.channels(p)
    pi = ProgramInputs.build(p, ch.accepts, ch.files, [], False)
    return input_domain(pi, limit)


HEAD = """IDENTIFICATION DIVISION.
PROGRAM-ID. P.
DATA DIVISION.
WORKING-STORAGE SECTION.
"""


def test_display_numeric_domains_respect_the_accept_window() -> None:
    d = _domain(HEAD + """01 A PIC 9(2).
01 B PIC S9.
01 C PIC S9(2).
01 D PIC 9V9.
PROCEDURE DIVISION.
MAIN-PARA.
    ACCEPT A ACCEPT B ACCEPT C ACCEPT D
    STOP RUN.
""", limit=10**7)
    assert isinstance(d, Domain)
    a, b, c, dd = (f.texts for f in d.fields)
    assert len(a) == 100 and a[0] == "0" and a[-1] == "99"
    assert b == [str(i) for i in range(10)]  # "-1" does not fit the 1-character window
    assert "-9" in c and "-10" not in c and "-0" in c and "99" in c and len(c) == 9 + 100 + 1
    assert dd == [str(i) for i in range(10)]  # "0.1" (3 chars) does not fit the 2-character window
    assert d.size == 100 * 10 * 110 * 10


def test_comp_fields_read_the_whole_line() -> None:
    d = _domain(HEAD + """01 A PIC S9 COMP-3.
PROCEDURE DIVISION.
MAIN-PARA.
    ACCEPT A
    STOP RUN.
""")
    assert isinstance(d, Domain)
    assert d.fields[0].texts == [str(i) for i in range(-9, 10)] + ["-0"]


def test_not_applicable_reasons() -> None:
    loop = _domain(HEAD + """01 A PIC 9.
PROCEDURE DIVISION.
MAIN-PARA.
    PERFORM READ-ONE 3 TIMES
    STOP RUN.
READ-ONE.
    ACCEPT A.
""")
    assert isinstance(loop, NotApplicable) and "inside a loop" in loop.reason
    big = _domain(HEAD + """01 A PIC 9(5).
PROCEDURE DIVISION.
MAIN-PARA.
    ACCEPT A
    STOP RUN.
""", limit=2000)
    assert isinstance(big, NotApplicable) and "exhaustive limit" in big.reason
    alnum = _domain(HEAD + """01 A PIC X.
PROCEDURE DIVISION.
MAIN-PARA.
    ACCEPT A
    STOP RUN.
""")
    assert isinstance(alnum, Domain) and len(alnum.fields[0].texts) == 95


def test_no_input_is_a_single_case() -> None:
    d = _domain(HEAD + """01 A PIC 9.
PROCEDURE DIVISION.
MAIN-PARA.
    DISPLAY A
    STOP RUN.
""")
    assert isinstance(d, Domain) and d.size == 1 and d.enumerate() == [[]]
