from __future__ import annotations

import json
from pathlib import Path

from verifier.langpacks.java.jbmc import decode_value, parse_javap, parse_jbmc_output, unmodelled_calls

REPO = Path(__file__).resolve().parents[2]
S2 = REPO / "docs" / "spikes" / "s2" / "out"
JAVAP = Path(__file__).with_name("data_javap_s2.txt")


def _out(name: str) -> str:
    return (S2 / name).read_text("utf-8")


def _rc(name: str) -> int:
    return int((S2 / f"{name}.rc").read_text().strip())


def test_proved_counterexample_bound_and_tool_error_from_spike_outputs() -> None:
    good = parse_jbmc_output(_out("e2_checkGood.json"), _rc("e2_checkGood.json"))
    assert good.verdict == "PROVED" and not good.failed and good.properties > 10
    loop = parse_jbmc_output(_out("e2_loop5_unwind3.json"), _rc("e2_loop5_unwind3.json"))
    assert loop.verdict == "BOUND_INSUFFICIENT" and loop.failed[0].kind == "unwind"
    err = parse_jbmc_output(_out("e2_err_nofunc.json"), _rc("e2_err_nofunc.json"))
    assert err.verdict == "TOOL_ERROR" and any("not found" in e for e in err.errors)
    reach = parse_jbmc_output(_out("e2_reachGood.json"), _rc("e2_reachGood.json"))
    assert reach.verdict == "COUNTEREXAMPLE" and reach.failed[0].kind == "assertion"
    assert set(reach.inputs) >= {"in_wsA", "in_wsB"}


def test_counterexample_inputs_use_binary_and_skip_declarations() -> None:
    def val(n: int) -> dict[str, object]:
        return {"binary": format(n & (2**64 - 1), "064b"), "data": f"{n}L", "type": "long", "width": 64}

    doc = [
        {"messageType": "STATUS-MESSAGE", "messageText": "x"},
        {"result": [{"property": "java::H.check:()V.assertion.2", "status": "FAILURE", "description": "a",
                     "sourceLocation": {"line": "40"},
                     "trace": [
                         {"stepType": "assignment", "hidden": False, "lhs": "in_wsA", "value": val(-1)},
                         {"stepType": "assignment", "hidden": False, "lhs": "in_wsA", "value": val(-3),
                          "sourceLocation": {"line": "30"}},
                         {"stepType": "assignment", "hidden": True, "lhs": "in_wsB", "value": val(9),
                          "sourceLocation": {"line": "31"}},
                     ]},
                    {"property": "java::H.check:()V.assertion.1", "status": "SUCCESS"}]},
        {"cProverStatus": "failure"},
    ]
    out = parse_jbmc_output(json.dumps(doc), 10)
    assert out.verdict == "COUNTEREXAMPLE" and out.inputs == {"in_wsA": -3}
    assert out.failed[0].line == 40 and out.failed[0].kind == "assertion"


def test_timeouts_and_kills() -> None:
    assert parse_jbmc_output("", 124).verdict == "TIMEOUT"
    assert parse_jbmc_output("", 137).verdict == "OUT_OF_MEMORY"
    assert parse_jbmc_output("Usage error!", 64).verdict == "TOOL_ERROR"


def test_decode_value() -> None:
    assert decode_value({"binary": "1" * 64, "type": "long", "width": 64}) == -1
    assert decode_value({"binary": "0000000001100001", "type": "char", "width": 16}) == 97
    assert decode_value({"data": "-3L"}) == -3


def test_javap_prescan_finds_unmodelled_jdk_calls() -> None:
    classes = parse_javap(JAVAP.read_text("utf-8"))
    assert "s2/Gotchas" in classes and "s2/Dec" in classes
    assert "<init>" in classes["s2/Dec"].methods and "pow10" in classes["s2/Dec"].methods
    # Math.abs is stubbed by JBMC -> must be reported
    reasons = unmodelled_calls(classes, "s2/Gotchas", "mathAbs")
    assert any("java.lang.Math.abs" in r for r in reasons)
    # the long-backed decimal runtime only calls itself and exception constructors
    assert unmodelled_calls(classes, "s2/Dec", "add") == []
    # String concatenation in the unit body is flagged (invokedynamic or StringBuilder)
    concat = unmodelled_calls(classes, "s2/Gotchas", "picXStringConcat")
    assert concat and all("JBMC does not model" in r for r in concat)
