from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from verifier.api import verify
from verifier.config import VerifierConfig
from verifier.report.schema import Status
from verifier.tiers.t1_diff import repro_case

FIX = Path(__file__).parent / "fixtures" / "s1"


@pytest.mark.docker
def test_t1_pass_on_correct_translation(tmp_path: Path, config: VerifierConfig) -> None:
    rep = verify(FIX / "cobol", FIX / "java", "java", tmp_path / "out", tiers=[0, 1], config=config)
    t1 = rep.programs[0].tiers["T1"]
    assert t1.status == Status.PASS, t1.reason
    assert t1.cases_run and t1.cases_run > 40 and t1.cases_failed == 0
    assert t1.coverage is not None and t1.coverage.uncovered == ["NEVER-PARA"]
    assert t1.scope is not None and "GnuCOBOL" in (t1.scope.oracle or "")
    unit = next(u for u in rep.units if u.paragraph == "CALC-PARA")
    assert unit.level == 1 and not unit.accepted  # paragraph coverage 2/3 < 0.8: abstain
    assert any("coverage" in r for r in unit.acceptance.reasons)  # type: ignore[union-attr]


@pytest.mark.docker
def test_t1_finds_shrinks_classifies_and_reproduces_a_rounding_bug(tmp_path: Path, config: VerifierConfig) -> None:
    tgt = tmp_path / "java"
    shutil.copytree(FIX / "java", tgt)
    src = tgt / "src/main/java/demo/S1prog.java"
    src.write_text(src.read_text().replace("if (Math.abs(r) >= 5) {", "if (false) {"))
    out = tmp_path / "out"
    rep = verify(FIX / "cobol", tgt, "java", out, tiers=[0, 1], config=config)
    t1 = rep.programs[0].tiers["T1"]
    assert t1.status == Status.FAIL
    cx = t1.counterexamples[0]
    assert cx.signature == "VALUE_MISMATCH stdout:S1PROG.cbl:22:WS-R"
    assert cx.confirmed_concretely and cx.shrunk
    assert cx.classification is not None and cx.classification.label == "ROUNDING_MISSING"
    assert any(s.line == 26 for s in cx.cobol_statements)  # COMPUTE WS-R ROUNDED
    assert cx.field_mapping and cx.field_mapping["target"] == "wsR"
    assert rep.units[0].tiers["T2"].status == Status.SKIPPED
    # the one-line repro reproduces the failure
    assert repro_case(out / cx.case_dir, out / "report.json") == 1  # type: ignore[operator]
    md = (out / "feedback" / "S1PROG__CALC-PARA.md").read_text()
    assert "expected (GnuCOBOL)" in md and "ROUNDING_MISSING" in md
