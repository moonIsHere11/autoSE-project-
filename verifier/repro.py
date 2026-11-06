"""`verify repro --case DIR --report PATH`: re-run one test case on both sides and print the diff."""

from __future__ import annotations

from pathlib import Path

from verifier.pipeline import VerifierError, optional


def repro(case_dir: Path, report_path: Path) -> int:
    repro_case = optional("verifier.tiers.t1_diff", "repro_case")
    if repro_case is None:  # until T1 lands
        raise VerifierError("repro needs the T1 differential runner (milestone M2)")
    rc: int = repro_case(case_dir, report_path)
    return rc
