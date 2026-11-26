"""Append-only run log (agreement contract 6): one JSON object per line."""
import datetime
import json
from pathlib import Path


class EventLog:
    def __init__(self, path: Path, run_id: str, module: str = "phase1"):
        self.path, self.run_id, self.module = Path(path), run_id, module
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, kind: str, unit_id: str | None = None, submission_id: str | None = None, **data):
        ev = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(), "run_id": self.run_id,
              "module": self.module, "kind": kind, "unit_id": unit_id, "submission_id": submission_id, "data": data}
        with open(self.path, "a") as f:
            f.write(json.dumps(ev) + "\n")
