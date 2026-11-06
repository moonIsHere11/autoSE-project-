from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from verifier.api import verify
from verifier.config import VerifierConfig
from verifier.report.schema import Status

FIX = Path(__file__).parent / "fixtures" / "s1"


@pytest.mark.docker
def test_t0_passes_on_correct_translation(tmp_path: Path, config: VerifierConfig) -> None:
    rep = verify(FIX / "cobol", FIX / "java", "java", tmp_path / "out", tiers=[0], config=config)
    assert not rep.errors, rep.errors
    assert [u.id for u in rep.units] == ["S1PROG::MAIN-PARA", "S1PROG::CALC-PARA", "S1PROG::NEVER-PARA"]
    t0 = rep.units[0].tiers["T0"]
    assert t0.status == Status.PASS, [f.message for c in t0.checks for f in c.findings]
    assert rep.units[0].target_symbol == "mainPara"
    assert (tmp_path / "out" / "summary.md").exists()
    data = json.loads((tmp_path / "out" / "report.json").read_text())
    assert data["schema_version"] == "1.0"


@pytest.mark.docker
def test_t0_build_error_and_static_errors_are_reported(tmp_path: Path, config: VerifierConfig) -> None:
    tgt = tmp_path / "java"
    shutil.copytree(FIX / "java", tgt)
    src = tgt / "src/main/java/demo/S1prog.java"
    text = src.read_text()
    # forbidden representation + wall clock + swallowed exception + undeclared file
    text = text.replace("long wsR;   // S9(5)V99, scale 2", "double wsR;")
    text = text.replace("signed(wsR, 7, 2)", "signed((long) wsR, 7, 2)")
    text = text.replace(
        "    void neverPara() {",
        "    void spy() { try { new java.io.FileReader(\"expected/stdout\"); long t = System.currentTimeMillis(); }"
        " catch (Exception e) { } }\n    void neverPara() {",
    )
    src.write_text(text)
    rep = verify(FIX / "cobol", tgt, "java", tmp_path / "out", tiers=[0], config=config)
    t0 = rep.units[0].tiers["T0"]
    assert t0.status == Status.FAIL
    msgs = {c.name: [f.message for f in c.findings if f.severity == "ERROR"] for c in t0.checks}
    assert msgs["build"] == []  # the mutated code still compiles
    assert any("floating point" in m for m in msgs["forbidden_representation"]), msgs
    assert any("wall clock" in m for m in msgs["forbidden_api"]), msgs
    assert any("swallows" in m for m in msgs["forbidden_api"]), msgs
    assert any("undeclared file path" in m for m in msgs["forbidden_api"]), msgs
    assert any("expected/stdout" in m for m in msgs["integrity"]), msgs
    assert not rep.units[0].integrity_clean
    fb = tmp_path / "out" / "feedback" / "S1PROG__MAIN-PARA.md"
    assert fb.exists() and "Static check errors" in fb.read_text()

    # a compile error is mapped to file:line with an excerpt
    src.write_text(text.replace("void calcPara() {", "void calcPara() { int x = ;"))
    rep2 = verify(FIX / "cobol", tgt, "java", tmp_path / "out2", tiers=[0], config=config)
    t0b = rep2.units[0].tiers["T0"]
    build = next(c for c in t0b.checks if c.name == "build")
    assert build.status == Status.FAIL
    assert build.findings[0].file == "src/main/java/demo/S1prog.java" and build.findings[0].line
    assert build.findings[0].excerpt and ">" in build.findings[0].excerpt
