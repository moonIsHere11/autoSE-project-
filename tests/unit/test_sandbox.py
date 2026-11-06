from __future__ import annotations

from pathlib import Path

import pytest

from verifier.config import Limits
from verifier.inputs.bundle import CaseSpec, InputFile, write_inputs
from verifier.sandbox.batch import run_batch
from verifier.sandbox.docker_runner import DockerRunner


@pytest.mark.docker
def test_batch_runner_captures_stdout_files_rc_and_isolation(runner: DockerRunner, tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    cases = [
        CaseSpec(program="P", stdin=b"hello\n", files_in=[InputFile("IN.DAT", b"abc")]),
        CaseSpec(program="P", stdin=b"bye\n"),
    ]
    ids = []
    for c in cases:
        write_inputs(c, inputs / c.case_id())
        ids.append(c.case_id())
    script = (
        "cat; ls; cat IN.DAT 2>/dev/null; echo out > OUT.TXT; "
        "(getent hosts example.com >/dev/null 2>&1 && echo NET) || echo NONET; exit 4"
    )
    res = run_batch(
        runner,
        inputs_root=inputs,
        results_root=tmp_path / "results",
        case_ids=ids,
        command=["sh", "-c", script],
        limits=Limits(case_timeout_s=10, workers=2),
    )
    assert not res.errors, res.errors
    r0 = res.runs[ids[0]]
    assert r0.stdout.startswith(b"hello\nIN.DAT\nabc")
    assert b"NONET" in r0.stdout
    assert r0.return_code == 4
    assert r0.files == {"IN.DAT": b"abc", "OUT.TXT": b"out\n"}
    r1 = res.runs[ids[1]]
    assert r1.files == {"OUT.TXT": b"out\n"}  # fresh working directory per case


@pytest.mark.docker
def test_batch_runner_timeout_and_faketime(runner: DockerRunner, tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    slow = CaseSpec(program="P", stdin=b"", args=["slow"])
    clock = CaseSpec(program="P", stdin=b"", args=["date"], fake_time="2024-01-15T10:30:00")
    for c in (slow, clock):
        write_inputs(c, inputs / c.case_id())
    script = 'if [ "$0" = slow ]; then sleep 30; else date -u +%Y%m%d%H%M%S; fi'
    res = run_batch(
        runner,
        inputs_root=inputs,
        results_root=tmp_path / "results",
        case_ids=[slow.case_id(), clock.case_id()],
        command=["sh", "-c", script],
        limits=Limits(case_timeout_s=2, workers=2),
        repeat=2,
    )
    assert res.runs[slow.case_id()].timed_out
    r = res.runs[clock.case_id()]
    assert r.stdout.strip() == b"20240115103000"
    assert r.flaky == []
