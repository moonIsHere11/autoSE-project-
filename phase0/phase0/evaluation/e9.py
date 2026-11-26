"""E9: contract and integration checks."""

from __future__ import annotations

import filecmp
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from phase0.build import validate_kb
from phase0.evaluation.datasets import Built
from phase0.schemas import stale
from phase0.target import REPO, RUNTIME_SOURCES, load_gaps

GAP_ID = re.compile(r"\bG-[A-Z]+\b")
REFERENCING = ("phase1/phase1", "phase2/phase2_adapter", "integration")
TASK_GAPS = frozenset({"G-TRUNCATE", "G-OVERFLOW", "G-ROUNDING", "G-SIGN", "G-STORAGE", "G-NUMALPHA", "G-PACKED",
                       "G-GROUPMOVE", "G-GOTO", "G-FALLTHROUGH", "G-DIVZERO"})


def referenced_gap_ids() -> set[str]:
    """Gap ids written as string literals in Phase 1, Phase 2's adapter and the integration code."""
    ids: set[str] = set()
    for d in REFERENCING:
        for p in (REPO / d).rglob("*.py"):
            for line in p.read_text("utf-8").splitlines():
                if '"G-' in line or "'G-" in line:
                    ids |= set(GAP_ID.findall(line))
    return ids


def runtime_identical(kb: Path) -> bool:
    cmp = filecmp.dircmp(RUNTIME_SOURCES["java"], kb / "target" / "runtime")
    return not (cmp.left_only or cmp.right_only or cmp.diff_files)


def e2e_scripted() -> dict[str, Any]:
    """integration/e2e_scripted.py with PHASE0_CMD pointing at the real Phase 0."""
    env = dict(os.environ, PHASE0_CMD=str(REPO / "phase0" / "bin" / "phase0"))
    with tempfile.TemporaryDirectory(prefix="phase0-e2e-") as tmp:
        proc = subprocess.run([sys.executable, str(REPO / "integration" / "e2e_scripted.py"), str(Path(tmp) / "ws")],
                              env=env, capture_output=True, text=True, timeout=900)
    verdicts = re.findall(r"^S-\d+ (green|red|error)", proc.stdout, re.M)
    return {"exit_code": proc.returncode, "verdicts": verdicts,
            "pass": proc.returncode == 0 and verdicts[-1:] == ["green"] and "red" in verdicts}


def e9(built: list[Built], run_e2e: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    failures: list[dict[str, Any]] = []
    invalid = 0
    for b in built:
        problems = validate_kb(b.ws / "kb")
        invalid += bool(problems)
        failures += [{"metric": "E9", "kind": "schema", "program": b.program.name, "detail": p,
                      "repro": f"phase0/bin/phase0 build --workspace {b.ws}"} for p in problems]
    have = {g.gap_id for g in load_gaps()}
    missing = sorted((referenced_gap_ids() | TASK_GAPS) - have)
    runtime = all(runtime_identical(b.ws / "kb") for b in built)
    out: dict[str, Any] = {
        "kb_files_valid": invalid == 0,
        "workspaces_checked": len(built),
        "exported_json_schemas_current": not stale(),
        "gap_ids_closed": not missing,
        "gap_ids_missing": missing,
        "gap_ids_referenced": sorted(referenced_gap_ids()),
        "runtime_byte_identical": runtime,
    }
    if run_e2e:
        out["e2e_scripted"] = e2e_scripted()
    return out, failures
