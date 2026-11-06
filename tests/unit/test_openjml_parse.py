from __future__ import annotations

import re
from pathlib import Path

from verifier.langpacks.java.openjml import classify, parse_esc_output
from verifier.report.schema import Status

S3 = Path(__file__).resolve().parents[2] / "docs" / "spikes" / "s3" / "out"


def _load(name: str):  # type: ignore[no-untyped-def]
    text = (S3 / f"{name}.txt").read_text("utf-8")
    m = re.search(r"### exit=(\d+)", text)
    return parse_esc_output(text, int(m.group(1)) if m else 0)


def test_pass_and_frame_violation() -> None:
    out = _load("Account")
    assert classify(out, "deposit").status == Status.PASS
    v = classify(out, "depositBad")
    assert v.status == Status.FAIL and "Assignable" in v.reason
    assert v.warnings[0].declaration == "src/Account.java:23"


def test_postcondition_failure_on_88_level_setter() -> None:
    out = _load("Status")
    assert classify(out, "setStatusB").status == Status.PASS
    assert classify(out, "setStatusBuggy").status == Status.FAIL


def test_loops_without_or_with_bad_invariants_are_not_applicable() -> None:
    out = _load("Loops")
    assert classify(out, "sumTo").status == Status.PASS
    assert classify(out, "sumToNoInv", has_unannotated_loop=True).reason == "needs loop invariant"
    assert classify(out, "sumToBadInv").status == Status.NOT_APPLICABLE
    assert classify(out, "sumToBadVariant").status == Status.NOT_APPLICABLE


def test_unknown_is_timeout_and_parse_errors_are_errors() -> None:
    # S3's Hard.txt run had a genuine overflow *and* an unknown: rule 9 (FAIL) precedes rule 10
    assert classify(_load("Hard"), "fermat3").status == Status.FAIL
    only_unknown = parse_esc_output(
        "Starting proof of Hard.f(long) with prover z3-5.1.0\n"
        "src/Hard.java:5: verify: Validity is unknown - no model available method Hard.f -  (possible timeout)\n"
        "Completed proof of Hard.f(long) with prover z3-5.1.0 - UNKNOWN [30.01 secs]\n", 6)
    assert classify(only_unknown, "f").status == Status.TIMEOUT
    bad = classify(_load("Bad"), "anything")
    assert bad.status == Status.ERROR and "illegal start of expression" in bad.reason


def test_missing_method_and_wall_clock() -> None:
    out = _load("Account")
    assert classify(out, "nope").status == Status.ERROR
    assert classify(parse_esc_output("", 124, timed_out=True), "deposit").status == Status.TIMEOUT
