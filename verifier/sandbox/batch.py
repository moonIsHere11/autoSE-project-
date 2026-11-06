"""Host side of batched sandbox execution (see batch_runner.py for the in-container side)."""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from verifier.config import FAKETIME_LIB, Limits
from verifier.sandbox.docker_runner import DockerRunner, Mount, RunResult, batch_runner_source

TRACE_FORMAT = "%F|%I|%L|%S"


@dataclass
class CaseRun:
    case_id: str
    stdout: bytes
    stderr: bytes
    return_code: int
    files: dict[str, bytes]
    meta: dict[str, Any]
    trace: str | None
    results_dir: Path

    @property
    def timed_out(self) -> bool:
        return bool(self.meta.get("timed_out"))

    @property
    def runner_error(self) -> str | None:
        err = self.meta.get("runner_error")
        return str(err) if err else None

    @property
    def flaky(self) -> list[str]:
        return list(self.meta.get("flaky", []))


@dataclass
class BatchOutcome:
    runs: dict[str, CaseRun]
    container: RunResult
    errors: list[str] = field(default_factory=list)


def read_case_results(results_dir: Path, case_id: str) -> CaseRun:
    meta_path = results_dir / "meta.json"
    meta: dict[str, Any] = json.loads(meta_path.read_text("utf-8")) if meta_path.exists() else {
        "runner_error": "no meta.json produced"
    }

    def _read(name: str) -> bytes:
        p = results_dir / name
        return p.read_bytes() if p.exists() else b""

    rc_text = _read("return_code").decode("ascii", errors="replace").strip()
    files: dict[str, bytes] = {}
    out_dir = results_dir / "out"
    if out_dir.is_dir():
        for p in sorted(out_dir.rglob("*")):
            if p.is_file():
                files[p.relative_to(out_dir).as_posix()] = p.read_bytes()
    trace_p = results_dir / "trace.txt"
    return CaseRun(
        case_id=case_id,
        stdout=_read("stdout"),
        stderr=_read("stderr"),
        return_code=int(rc_text) if rc_text.lstrip("-").isdigit() else -1,
        files=files,
        meta=meta,
        trace=trace_p.read_text("utf-8", errors="replace") if trace_p.exists() else None,
        results_dir=results_dir,
    )


def run_batch(
    runner: DockerRunner,
    *,
    inputs_root: Path,
    results_root: Path,
    case_ids: list[str],
    command: list[str],
    limits: Limits,
    extra_mounts: list[Mount] | None = None,
    env: dict[str, str] | None = None,
    trace: bool = False,
    repeat: int = 1,
    force_fake_time: str | None = None,
    workers: int | None = None,
) -> BatchOutcome:
    """Run `command` once per case inside one sandboxed container."""
    if results_root.exists():
        shutil.rmtree(results_root)
    results_root.mkdir(parents=True)
    job_dir = results_root.parent / f"job-{uuid.uuid4().hex[:8]}"
    job_dir.mkdir(parents=True)
    job = {
        "inputs_root": "/inputs",
        "results_root": "/results",
        "command": command,
        "timeout_s": limits.case_timeout_s,
        "fsize_bytes": limits.fsize_mb * 1024 * 1024,
        "stdout_cap": limits.stdout_cap_bytes,
        "workers": workers or limits.workers,
        "env": env or {},
        "trace": {"format": TRACE_FORMAT} if trace else None,
        "repeat": repeat,
        "faketime_lib": FAKETIME_LIB,
        "force_fake_time": force_fake_time,
        "cases": case_ids,
    }
    (job_dir / "job.json").write_text(json.dumps(job, indent=1), "utf-8")
    mounts = [
        Mount(inputs_root, "/inputs", read_only=True),
        Mount(results_root, "/results", read_only=False),
        Mount(job_dir, "/jobs", read_only=True),
        Mount(batch_runner_source(), "/opt/verifier/batch_runner.py", read_only=True),
        *(extra_mounts or []),
    ]
    # whole-container budget: every case may hit its timeout, divided over the workers
    budget = 120.0 + repeat * len(case_ids) * limits.case_timeout_s / max(1, workers or limits.workers)
    res = runner.run(
        ["python3", "/opt/verifier/batch_runner.py", "/jobs/job.json"],
        mounts=mounts,
        timeout_s=min(budget, limits.container_timeout_s * 4),
    )
    shutil.rmtree(job_dir, ignore_errors=True)
    errors: list[str] = []
    if not res.ok:
        errors.append(
            f"batch container failed (rc={res.returncode}, timed_out={res.timed_out}): {res.text()[-800:]}"
        )
    runs: dict[str, CaseRun] = {}
    for cid in case_ids:
        rdir = results_root / cid
        if rdir.is_dir():
            runs[cid] = read_case_results(rdir, cid)
        else:
            errors.append(f"no results for {cid}")
    return BatchOutcome(runs=runs, container=res, errors=errors)
