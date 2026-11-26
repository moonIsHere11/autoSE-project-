"""Generic verifier adapter for ANY checker that follows the agreement's file contract:

    <cmd> check --workspace W --submission S-0001      ->  writes W/reports/S-0001/report.json

Swap checkers by changing `cmd` in config.yaml; the harness never imports a checker's internals."""
from __future__ import annotations

import json
import os
import shlex
import subprocess

from harness.types import Candidate, Verdict


class ContractVerifier:
    def __init__(self, cmd, timeout: int = 3600, env: dict | None = None):
        self.cmd = shlex.split(cmd) if isinstance(cmd, str) else list(cmd)
        self.timeout, self.env = timeout, env or {}

    def verify(self, c: Candidate) -> Verdict:
        argv = [*self.cmd, "check", "--workspace", str(c.workspace), "--submission", c.submission_id]
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=self.timeout, env={**os.environ, **self.env})
        except subprocess.TimeoutExpired:
            return Verdict("error", f"checker timed out after {self.timeout}s")
        report = c.workspace / "reports" / c.submission_id / "report.json"
        if r.returncode != 0 or not report.exists():
            return Verdict("error", f"checker exited {r.returncode}: {(r.stderr or r.stdout)[-600:]}")
        rep = json.loads(report.read_text())
        return Verdict(rep["verdict"], rep.get("summary", ""), rep.get("findings", []), rep.get("units", []), rep)
