from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from verifier.api import verify
from verifier.config import VerifierConfig
from verifier.report.schema import Status

FIX = Path(__file__).parent / "fixtures" / "t2a"
JAVA = "src/main/java/demo/T2aprog.java"


@pytest.mark.docker
def test_t2a_proves_equivalence_over_the_declared_domain(tmp_path: Path, config: VerifierConfig) -> None:
    rep = verify(FIX / "cobol", FIX / "java", "java", tmp_path / "out", tiers=[0, 1, 2], config=config)
    unit = next(u for u in rep.units if u.paragraph == "CALC-PARA")
    t2 = unit.tiers["T2"]
    assert t2.status == Status.PASS and t2.method and "exhaustive" in t2.method
    assert t2.cases_run == 1000 and t2.scope is not None and t2.scope.domain
    assert "WS-QTY PIC 9(2)" in t2.scope.domain and "100 values" in t2.scope.domain
    assert unit.level == 2 and "T2a" in unit.evidence and unit.accepted


@pytest.mark.docker
def test_t2a_finds_a_bug_that_sampling_missed(tmp_path: Path, config: VerifierConfig) -> None:
    tgt = tmp_path / "java"
    shutil.copytree(FIX / "java", tgt)
    src = tgt / JAVA
    # a planted special case on one input pair that no T1 strategy derives from the COBOL source
    src.write_text(src.read_text().replace("wsNet = (wsTotal - wsDisc) % 1000000;",
                                           "wsNet = (wsTotal - wsDisc) % 1000000;\n"
                                           "        if (wsQty == 73 && wsCode == 7) { wsNet = wsNet + 1; }"))
    rep = verify(FIX / "cobol", tgt, "java", tmp_path / "out", tiers=[0, 1, 2], config=config)
    prog = rep.programs[0]
    assert prog.tiers["T1"].status == Status.PASS  # the sampled cases miss (73, 7)
    t2 = prog.tiers["T2"]
    assert t2.status == Status.FAIL and t2.cases_failed == 1
    cx = t2.counterexamples[0]
    assert cx.source_tier == "T2a" and cx.inputs["stdin_lines"] == ["73", "7"]
    assert all(not u.accepted for u in rep.units)
