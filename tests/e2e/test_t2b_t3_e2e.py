"""End-to-end T2b (JBMC, with the validation gate) and T3 (OpenJML) on the seed corpus."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from verifier.api import verify
from verifier.config import VerifierConfig
from verifier.report.schema import Status

CORPUS = Path(__file__).resolve().parents[2] / "corpus"


def _t2b(unit: object) -> object:
    return unit.tiers["T2"].sub["T2b"]  # type: ignore[attr-defined]


@pytest.mark.docker
@pytest.mark.slow
def test_t2b_complete_proof_with_gate_and_vacuity(tmp_path: Path, config: VerifierConfig) -> None:
    d = CORPUS / "divrem"
    rep = verify(d / "cobol", d / "java", "java", tmp_path / "out", mode="full", tiers=[0, 1, 2],
                 units=["DIVREM::SET-RETURN"], config=config)
    unit = next(u for u in rep.units if u.paragraph == "SET-RETURN")
    t2b = _t2b(unit)
    assert t2b.status == Status.PASS, t2b.reason  # type: ignore[attr-defined]
    assert t2b.bound == "complete" and not t2b.stub  # type: ignore[attr-defined]
    assert t2b.vacuity and "reachable" in t2b.vacuity["reachability"]  # type: ignore[attr-defined]
    assert unit.tiers["T1u"].status == Status.PASS


@pytest.mark.docker
@pytest.mark.slow
def test_t2b_refutes_a_planted_bug_with_a_concrete_counterexample(tmp_path: Path, config: VerifierConfig) -> None:
    d = CORPUS / "divrem"
    tgt = tmp_path / "java"
    shutil.copytree(d / "java", tgt)
    src = tgt / "src/main/java/corpus/Divrem.java"
    text = src.read_text("utf-8")
    assert "if (wsDivisor == 0) {" in text
    # A bug no program input can reach: whenever the divisor is 0 the program's remainder is 0, so T1
    # (and the program-level T2a proof) cannot see it; the paragraph-level tiers can.
    src.write_text(text.replace("if (wsDivisor == 0) {", "if (wsDivisor == 0 && wsRem == 0) {"), "utf-8")
    rep = verify(d / "cobol", tgt, "java", tmp_path / "out", mode="full", tiers=[0, 1, 2],
                 units=["DIVREM::SET-RETURN"], config=config)
    unit = next(u for u in rep.units if u.paragraph == "SET-RETURN")
    assert unit.tiers["T1"].status == Status.PASS
    t2b = _t2b(unit)
    assert t2b.status == Status.FAIL  # type: ignore[attr-defined]
    cx = t2b.counterexamples[0]  # type: ignore[attr-defined]
    assert cx.confirmed_concretely and any(diff.field == "RETURN-CODE" for diff in cx.diffs)
    assert not unit.accepted


@pytest.mark.docker
@pytest.mark.slow
def test_t3_contract_proved_despite_openjml_deferred_crash_in_helpers(tmp_path: Path,
                                                                      config: VerifierConfig) -> None:
    d = CORPUS / "taxcalc"
    rep = verify(d / "cobol", d / "java", "java", tmp_path / "out", manifest=d / "manifest.java.json",
                 mode="full", tiers=[0, 1, 3], config=config)
    unit = next(u for u in rep.units if u.paragraph == "COMPUTE-TAX")
    t3 = unit.tiers["T3"]
    assert t3.status == Status.PASS, t3.reason
    assert t3.details["elided_non_unit_method_bodies"] > 0
    assert unit.accepted
