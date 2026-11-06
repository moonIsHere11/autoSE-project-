"""End-to-end checks of the Python and Go packs (T0 build/static, T1 differential testing, T2a)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from verifier.api import verify
from verifier.config import VerifierConfig
from verifier.report.schema import Status

FIX = Path(__file__).parent / "fixtures"
S1_TARGETS = {"python": "s1prog.py", "go": "s1prog/main.go"}
# planted bug: CALC-PARA forgets ROUNDED (truncates instead)
ROUNDING_BUG = {
    "python": ("self.ws_r = tmod(round_div(exact, 10), 10_000_000)", "self.ws_r = tmod(tdiv(exact, 10), 10_000_000)"),
    "go": ("if r >= 5 || r <= -5 {", "if false {"),
}
SYMBOLS = {"python": ("main_para", "ws_r"), "go": ("MainPara", "WsR")}


@pytest.mark.docker
@pytest.mark.parametrize("lang", ["python", "go"])
def test_t0_build_errors_are_mapped_to_file_and_line(tmp_path: Path, config: VerifierConfig, lang: str) -> None:
    tgt = tmp_path / lang
    shutil.copytree(FIX / "s1" / lang, tgt)
    src = tgt / S1_TARGETS[lang]
    text = src.read_text()
    if lang == "python":
        broken = text.replace("    def never_para(self) -> None:", "    def never_para(self) -> None\n")
        line = broken.splitlines().index("    def never_para(self) -> None") + 1
    else:
        broken = text.replace('\tp.display("NEVER")', '\tp.display("NEVER")\n\tundefinedThing()')
        line = broken.splitlines().index("\tundefinedThing()") + 1
    src.write_text(broken)
    rep = verify(FIX / "s1" / "cobol", tgt, lang, tmp_path / "out", tiers=[0, 1], config=config)
    t0 = rep.units[0].tiers["T0"]
    build = next(c for c in t0.checks if c.name == "build")
    assert t0.status == Status.FAIL and build.status == Status.FAIL
    err = next(f for f in build.findings if f.severity == "ERROR")
    assert err.file == S1_TARGETS[lang] and err.line == line, err
    assert err.excerpt and ">" in err.excerpt
    assert rep.units[0].tiers["T1"].status == Status.SKIPPED


@pytest.mark.docker
def test_mypy_findings_are_warnings_only(tmp_path: Path, config: VerifierConfig) -> None:
    tgt = tmp_path / "python"
    shutil.copytree(FIX / "s1" / "python", tgt)
    src = tgt / "s1prog.py"
    src.write_text(src.read_text().replace('        self.display("NEVER")',
                                           '        bad: int = "NEVER"\n        self.display(bad)'))
    rep = verify(FIX / "s1" / "cobol", tgt, "python", tmp_path / "out", tiers=[0], config=config)
    t0 = rep.units[0].tiers["T0"]
    build = next(c for c in t0.checks if c.name == "build")
    assert build.status == Status.PASS and t0.status == Status.PASS
    assert any(f.check == "T0a.mypy" and f.severity == "WARNING" and f.file == "s1prog.py" for f in build.findings)


@pytest.mark.docker
@pytest.mark.slow
@pytest.mark.parametrize("lang", ["python", "go"])
def test_t0_t1_pass_on_correct_translation(tmp_path: Path, config: VerifierConfig, lang: str) -> None:
    rep = verify(FIX / "s1" / "cobol", FIX / "s1" / lang, lang, tmp_path / "out", tiers=[0, 1], config=config)
    assert not rep.errors, rep.errors
    prog = rep.programs[0]
    t0, t1 = prog.tiers["T0"], prog.tiers["T1"]
    assert t0.status == Status.PASS, [f.message for c in t0.checks for f in c.findings if f.severity == "ERROR"]
    assert t1.status == Status.PASS, t1.reason
    assert t1.cases_run and t1.cases_run > 40 and t1.cases_failed == 0
    assert t1.coverage is not None and t1.coverage.uncovered == ["NEVER-PARA"]
    assert rep.units[0].target_symbol == SYMBOLS[lang][0]


@pytest.mark.docker
@pytest.mark.slow
@pytest.mark.parametrize("lang", ["python", "go"])
def test_t1_finds_shrinks_and_classifies_a_rounding_bug(tmp_path: Path, config: VerifierConfig, lang: str) -> None:
    tgt = tmp_path / lang
    shutil.copytree(FIX / "s1" / lang, tgt)
    src = tgt / S1_TARGETS[lang]
    old, new = ROUNDING_BUG[lang]
    assert old in src.read_text()
    src.write_text(src.read_text().replace(old, new))
    out = tmp_path / "out"
    rep = verify(FIX / "s1" / "cobol", tgt, lang, out, tiers=[0, 1], config=config)
    t1 = rep.programs[0].tiers["T1"]
    assert rep.programs[0].tiers["T0"].status == Status.PASS
    assert t1.status == Status.FAIL and t1.cases_failed
    cx = t1.counterexamples[0]
    assert cx.signature == "VALUE_MISMATCH stdout:S1PROG.cbl:22:WS-R"
    assert cx.confirmed_concretely and cx.shrunk
    assert cx.classification is not None and cx.classification.label == "ROUNDING_MISSING"
    assert any(s.line == 26 for s in cx.cobol_statements)  # COMPUTE WS-R ROUNDED
    assert cx.field_mapping and cx.field_mapping["target"] == SYMBOLS[lang][1]
    assert (out / "feedback" / "S1PROG__CALC-PARA.md").exists()


@pytest.mark.docker
@pytest.mark.slow
@pytest.mark.parametrize("lang", ["python", "go"])
def test_t2a_proves_equivalence_over_the_declared_domain(tmp_path: Path, config: VerifierConfig, lang: str) -> None:
    rep = verify(FIX / "t2a" / "cobol", FIX / "t2a" / lang, lang, tmp_path / "out", tiers=[0, 1, 2], config=config)
    unit = next(u for u in rep.units if u.paragraph == "CALC-PARA")
    t2 = unit.tiers["T2"]
    assert t2.status == Status.PASS and t2.method and "exhaustive" in t2.method
    assert t2.cases_run == 1000 and t2.scope is not None and t2.scope.domain
    assert unit.level == 2 and "T2a" in unit.evidence and unit.accepted
