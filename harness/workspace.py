"""Workspace layout and submit semantics (agreement section 5). Domain-agnostic.

workspace/ config.yaml · source/ (read-only input) · staging/ (agent's mutable project)
           submissions/S-NNNN/{submission.json, project/} (immutable) · reports/S-NNNN/ (verifier output)
           runs/<run_id>/events.jsonl"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import yaml

from .events import EventLog

DEFAULT_BUDGETS = {"attempts_per_unit": 5, "check_retries_on_error": 2}


class Workspace:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.config = yaml.safe_load((self.root / "config.yaml").read_text()) or {}
        self.config["budgets"] = {**DEFAULT_BUDGETS, **self.config.get("budgets", {})}
        self.config.setdefault("gate", {}).setdefault("required_tier", "tested")
        self.run_id = self.config.get("run", {}).get("id", "R-001")
        self.staging = self.root / "staging"
        self.staging.mkdir(exist_ok=True)
        self.run_dir = self.root / "runs" / self.run_id
        self.events = EventLog(self.run_dir / "events.jsonl", self.run_id)

    @property
    def source_dir(self) -> Path:
        src = self.config.get("source", {})
        if "dir" in src:
            return (self.root / src["dir"]).resolve()
        if "entry" in src:
            return (self.root / src["entry"]).resolve().parent
        return self.root / "source"

    def submit(self, scope: list[str], regression: list[str], attempt: int, notes: str | None = None) -> str:
        """mkdir-allocated id -> copy staging -> write submission.json last -> event."""
        base = self.root / "submissions"
        base.mkdir(exist_ok=True)
        n = len(list(base.iterdir())) + 1
        while True:
            sid = f"S-{n:04d}"
            try:
                (base / sid).mkdir()
                break
            except FileExistsError:
                n += 1
        shutil.copytree(self.staging, base / sid / "project", ignore=shutil.ignore_patterns(".git", "__pycache__"))
        sub = {"schema_version": "1.0", "submission_id": sid, "run_id": self.run_id,
               "kb_version": self.config.get("kb_version", "none"), "attempt": attempt,
               "scope": {"unit_ids": scope, "regression_unit_ids": regression,
                         "required_tier": self.config["gate"]["required_tier"]},
               "project_root": "project/", "driver_cmd": [], "notes": notes}
        tmp = base / sid / "submission.json.tmp"
        tmp.write_text(json.dumps(sub, indent=2))
        os.rename(tmp, base / sid / "submission.json")
        self.events.emit("submission_created", submission_id=sid, scope=sub["scope"])
        return sid
