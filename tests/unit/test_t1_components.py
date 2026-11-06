from __future__ import annotations

import random

from verifier.cobol.datadiv import DataItem, compute_layout, parse_pic
from verifier.cobol.trace import parse_trace
from verifier.diagnose.classifier import classify
from verifier.diagnose.compare import Mismatch
from verifier.inputs.encode import binary, decode_elementary, decode_record, encode_record, packed, zoned
from verifier.inputs.strategies import alnum_boundaries, numeric_boundaries, pairwise
from verifier.report.schema import FieldDiff


def _item(name: str, pic: str, usage: str = "DISPLAY", **kw: object) -> DataItem:
    it = DataItem(level=5, name=name, file="T.cbl", line=1, section="FILE", pic=parse_pic(pic), usage=usage, **kw)  # type: ignore[arg-type]
    compute_layout(it)
    return it


def test_encodings_match_gnucobol_bytes_from_spike_s6() -> None:
    # FIXOUT.DAT record observed with od in spike S6
    assert zoned(_item("A", "S9(3)"), "-123") == b"12s"
    assert zoned(_item("A", "S9(3)"), "123") == b"123"
    assert zoned(_item("A", "9(3)"), "-123") == b"123"  # unsigned drops the sign
    assert zoned(_item("A", "S9(3)", sign="LEADING", sign_separate=True), "-123") == b"-123"
    assert zoned(_item("A", "S9(3)", sign="TRAILING", sign_separate=True), "-7") == b"007-"
    assert zoned(_item("A", "S9(5)"), "-0") == b"0000p"  # explicit negative zero
    assert packed(_item("A", "S9(3)", "COMP-3"), "-123") == bytes([0x12, 0x3D])
    assert packed(_item("A", "9(4)", "COMP-3"), "1234") == bytes([0x01, 0x23, 0x4F])
    assert binary(_item("A", "S9(4)", "COMP"), "-123") == bytes([0xFF, 0x85])
    assert binary(_item("A", "S9(4)", "COMP-5"), "-123") == bytes([0x85, 0xFF])
    assert zoned(_item("A", "S9(5)V99"), "123.456") == b"0012345"  # truncation of extra decimals
    assert zoned(_item("A", "9(3)"), "12345") == b"345"  # high-order truncation


def test_decode_roundtrip() -> None:
    for pic, usage, val in [("S9(5)V99", "DISPLAY", "-123.45"), ("S9(5)V99", "COMP-3", "-0.01"),
                            ("S9(4)", "COMP", "-123"), ("9(9)", "COMP", "123456789"), ("S9(4)", "COMP-5", "77")]:
        it = _item("A", pic, usage)
        enc = {"DISPLAY": zoned, "COMP-3": packed, "COMP": binary, "COMP-5": binary}[usage](it, val)
        assert decode_elementary(it, enc) == val


def test_record_encode_decode_with_occurs() -> None:
    rec = DataItem(level=1, name="REC", file="T.cbl", line=1, section="FILE")
    a = DataItem(level=5, name="A", file="T.cbl", line=2, section="FILE", pic=parse_pic("X(3)"), parent=rec)
    t = DataItem(level=5, name="T", file="T.cbl", line=3, section="FILE", occurs=2, parent=rec)
    e = DataItem(level=10, name="E", file="T.cbl", line=4, section="FILE", pic=parse_pic("S9(2)"), parent=t)
    t.children = [e]
    rec.children = [a, t]
    compute_layout(rec)
    assert rec.size == 7
    data = encode_record(rec, {"A": "AB", "E": "-12"})
    assert data == b"AB 1r1r"
    assert [(i.name, v) for i, v in decode_record(rec, data)] == [("A", "AB "), ("E", "-12"), ("E", "-12")]


def test_boundaries_include_spec_values() -> None:
    vals = dict((v, k) for k, v in numeric_boundaries(_item("A", "S9(3)V99"), overlong=True))
    for v in ("0", "0.01", "999.99", "-999.99", "-0", "1000", "-1000", "2.05", "-2.05"):
        assert v in vals, v
    assert "1000" not in dict((v, k) for k, v in numeric_boundaries(_item("A", "S9(3)V99"), overlong=False))
    alns = [v for _k, v in alnum_boundaries(_item("X", "X(4)"), overlong=True)]
    assert "" in alns and "ABCD" in alns and "ABCDEFG" in alns


def test_pairwise_covers_all_pairs() -> None:
    sets = [[("a", str(i)) for i in range(3)], [("b", str(i)) for i in range(3)], [("c", str(i)) for i in range(2)]]
    tests = pairwise(sets, random.Random(1), cap=100)
    pairs = {(i, t[i][1], j, t[j][1]) for t in tests for i in range(3) for j in range(i + 1, 3)}
    assert len(pairs) == 3 * 3 + 3 * 2 + 3 * 2
    assert len(tests) < 3 * 3 * 2  # fewer than the full product


def test_parse_trace() -> None:
    txt = ("Source: 'P.cbl'\nProgram-Id:  P\n"
           "Source: P.cbl                     |P|    10|Paragraph: MAIN-PARA\n"
           "Source: P.cbl                     |P|    11|           DISPLAY\n")
    ev = parse_trace(txt)
    assert [(e.kind, e.name, e.line) for e in ev] == [("paragraph", "MAIN-PARA", 10), ("statement", "DISPLAY", 11)]


def _mm(pic: str, exp: str, act: str, usage: str = "DISPLAY") -> Mismatch:
    it = _item("WS-X", pic, usage)
    return Mismatch("VALUE_MISMATCH", "stdout line 1", "sig",
                    [FieldDiff(location="stdout line 1", field="WS-X", pic=pic, expected=exp, actual=act)], [it])


def test_classifier_labels() -> None:
    def label(m: Mismatch, se: bool = False) -> str | None:
        c = classify(m, se)
        return c.label if c else None

    assert label(_mm("S9(5)V99", "+00000.02", "+00000.01")) == "ROUNDING_MISSING"
    assert label(_mm("S9(5)V99", "-00012.50", "+00012.50")) == "SIGN_LOST"
    assert label(_mm("9(3)", "345", "12345")) == "MISSING_HIGH_ORDER_TRUNCATION"
    assert label(_mm("9(3)", "345", "12345"), se=True) == "SIZE_ERROR_HANDLING"
    assert label(_mm("S9(5)V99", "+00012.50", "+00125.00")) == "SCALE_OFF_BY_POWER_OF_10"
    assert label(_mm("S9(5)V99", "+00012.50", "12.5")) == "DISPLAY_FORMAT"
    assert label(_mm("X(5)", "AB   ", "AB")) == "PADDING_OR_JUSTIFICATION"
    lc = Mismatch("LINE_COUNT", "stdout", "LINE_COUNT stdout",
                  [FieldDiff(location="stdout line count", expected="10", actual="11")])
    assert label(lc) == "ITERATION_COUNT"
    for m in (_mm("S9(5)V99", "+00000.02", "+00000.01"),):
        c = classify(m)
        assert c is not None and c.explanation.startswith("likely")
