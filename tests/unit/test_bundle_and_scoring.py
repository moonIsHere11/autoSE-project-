from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from verifier.config import AcceptancePolicy
from verifier.inputs.bundle import CaseSpec, InputFile, read_bundle, write_inputs
from verifier.report.schema import Coverage, Scope, Status, TierResult, UnitResult
from verifier.report.scoring import compute_evidence, compute_level, compute_score, finalise_unit


def test_case_id_is_content_hash_and_roundtrips(tmp_path: Path) -> None:
    a = CaseSpec(program="P", stdin=b"1\n", files_in=[InputFile("F.DAT", b"x")], strategy="s1", seed=1)
    b = CaseSpec(program="P", stdin=b"1\n", files_in=[InputFile("F.DAT", b"x")], strategy="s2", seed=9)
    c = CaseSpec(program="P", stdin=b"2\n")
    assert a.case_id() == b.case_id()  # strategy/seed are metadata, not identity
    assert a.case_id() != c.case_id()
    assert a.case_id().startswith("case_") and len(a.case_id()) == 21
    d = write_inputs(a, tmp_path / a.case_id())
    back = read_bundle(d)
    assert back.stdin == a.stdin and back.files_in == a.files_in and back.case_id() == a.case_id()


def test_status_honesty_rules() -> None:
    with pytest.raises(ValidationError):
        TierResult(status=Status.ERROR)  # needs a reason
    with pytest.raises(ValidationError):
        TierResult(status=Status.PASS)  # needs a scope
    TierResult(status=Status.PASS, scope=Scope(what="x"))
    TierResult.not_applicable("uses EXEC SQL")


def _pass() -> TierResult:
    return TierResult(status=Status.PASS, scope=Scope(what="t"))


def test_levels_evidence_score_acceptance() -> None:
    u = UnitResult(id="P::A", program="P", paragraph="A")
    u.tiers["T0"] = _pass()
    t1 = _pass()
    t1.coverage = Coverage(paragraph=0.9, statement=0.8)
    u.tiers["T1"] = t1
    u.tiers["T2"] = TierResult.not_applicable("uses STRING")
    u.tiers["T3"] = _pass()
    finalise_unit(u, ["T0", "T1", "T2", "T3"], AcceptancePolicy())
    assert u.level == 1  # T2 not passed -> stops at level 1
    assert compute_evidence(u) == ["T0", "T1", "T3"]
    assert compute_score(u) == 3.0
    assert u.accepted

    t1.coverage = Coverage(paragraph=0.5, statement=0.5)
    finalise_unit(u, ["T0", "T1", "T2", "T3"], AcceptancePolicy())
    assert not u.accepted and "coverage" in u.acceptance.reasons[0]  # type: ignore[union-attr]

    u.tiers["T1"] = TierResult(status=Status.FAIL, pass_fraction=0.75)
    u.tiers["T2"] = TierResult.skipped("gated by T1 FAIL")
    finalise_unit(u, ["T0", "T1", "T2", "T3"], AcceptancePolicy())
    assert compute_level(u) == 0 and u.score == 2.75 and not u.accepted


def test_unselected_tiers_do_not_block_acceptance() -> None:
    u = UnitResult(id="P::A", program="P", paragraph="A")
    u.tiers["T0"] = _pass()
    t1 = _pass()
    t1.coverage = Coverage(paragraph=1.0, statement=1.0)
    u.tiers["T1"] = t1
    u.tiers["T3"] = TierResult.skipped("not selected")
    finalise_unit(u, ["T0", "T1"], AcceptancePolicy())
    assert u.accepted and u.acceptance is not None and u.acceptance.tiers_considered == ["T0", "T1"]
