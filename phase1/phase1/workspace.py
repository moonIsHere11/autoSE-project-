"""Workspace helpers: config, events, KB access (via `phase0 query`), submit."""
import datetime
import json
import os
import shutil
import subprocess
from pathlib import Path

import yaml


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class Workspace:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.config = yaml.safe_load((self.root / "config.yaml").read_text())
        self.run_id = self.config.get("run", {}).get("id", "R-001")
        self.staging = self.root / "staging"
        self.events_path = self.root / "runs" / self.run_id / "events.jsonl"
        self.events_path.parent.mkdir(parents=True, exist_ok=True)

    # ---- events (contract 6) ----
    def emit(self, kind, unit_id=None, submission_id=None, **data):
        ev = {"ts": now(), "run_id": self.run_id, "module": "phase1", "kind": kind,
              "unit_id": unit_id, "submission_id": submission_id, "data": data}
        with open(self.events_path, "a") as f:
            f.write(json.dumps(ev) + "\n")

    # ---- KB (contract 2): always through the phase0 CLI ----
    def kb(self, method, *args):
        cmd = os.environ.get("PHASE0_CMD", "phase0").split()
        cmd += ["query", method, *map(str, args), "--workspace", str(self.root)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"phase0 query {method} failed: {r.stderr.strip()[:500]}")
        return json.loads(r.stdout)

    def kb_version(self):
        return json.loads((self.root / "kb" / "manifest.json").read_text())["kb_version"]

    def run_state(self):
        p = self.root / "runs" / self.run_id / "state.json"
        return json.loads(p.read_text()) if p.exists() else {"units": {}}

    # ---- staging ----
    def seed_staging(self, runtime_dir):
        """Copy runtime library + driver template into an empty staging/."""
        if self.staging.exists() and any(self.staging.iterdir()):
            return
        self.staging.mkdir(exist_ok=True)
        tgt = self.root / "kb" / "target"
        if (tgt / "runtime").exists():
            shutil.copytree(tgt / "runtime", self.staging / runtime_dir, dirs_exist_ok=True)
        if (tgt / "driver_template").exists():
            shutil.copytree(tgt / "driver_template", self.staging, dirs_exist_ok=True)

    # ---- submit (section 5 semantics) ----
    def submit(self, unit_ids, regression_ids, driver_cmd, attempt, notes=None):
        sub_root = self.root / "submissions"
        sub_root.mkdir(exist_ok=True)
        n = len(list(sub_root.iterdir())) + 1
        while True:
            sid = f"S-{n:04d}"
            try:
                (sub_root / sid).mkdir()
                break
            except FileExistsError:
                n += 1
        shutil.copytree(self.staging, sub_root / sid / "project")
        sub = {
            "schema_version": "1.0", "submission_id": sid, "run_id": self.run_id,
            "kb_version": self.kb_version(), "attempt": attempt,
            "scope": {"unit_ids": unit_ids, "regression_unit_ids": regression_ids,
                      "required_tier": self.config["gate"]["required_tier"]},
            "project_root": "project/", "driver_cmd": driver_cmd, "notes": notes,
        }
        (sub_root / sid / "submission.json.tmp").write_text(json.dumps(sub, indent=2))
        os.rename(sub_root / sid / "submission.json.tmp", sub_root / sid / "submission.json")
        self.emit("submission_created", submission_id=sid, scope=sub["scope"])
        return sid

    def check(self, sid):
        cmd = os.environ.get("PHASE2_CMD", "phase2").split()
        cmd += ["check", "--workspace", str(self.root), "--submission", sid]
        r = subprocess.run(cmd, capture_output=True, text=True)
        rp = self.root / "reports" / sid / "report.json"
        if r.returncode != 0 or not rp.exists():
            return None, f"phase2 check exited {r.returncode}: {(r.stderr or r.stdout)[-800:]}"
        return json.loads(rp.read_text()), None
