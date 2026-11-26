"""`check` backed by Nan's verifier (verifier.api.verify). Contract glue only:
 - reads submissions/<sid>/submission.json, writes reports/<sid>/report.json (agreement 4.3 / 4.4)
 - raw verifier output (report.json, summary.md, feedback/, cases/) stays in reports/<sid>/artifacts/verifier/"""
import datetime
import filecmp
import json
import os
import re
import shutil
import time
from pathlib import Path

import yaml

from .convert import REQUIRED_TIERS, UNTIL_TIERS, convert


class ContractError(Exception):
    pass


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def emit(root, cfg, kind, sid=None, **data):
    run = cfg.get("run", {}).get("id", "R-001")
    p = root / "runs" / run / "events.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps({"ts": now(), "run_id": run, "module": "phase2", "kind": kind, "unit_id": None,
                            "submission_id": sid, "data": data}) + "\n")


def cobol_dir(root, cfg):
    src = cfg.get("source", {})
    return (root / src["dir"]) if "dir" in src else (root / src["entry"]).parent if "entry" in src else root / "source"


def program_id(path):
    m = re.search(r"PROGRAM-ID\.?\s+([A-Za-z0-9-]+)", Path(path).read_text(errors="replace"), re.I)
    return m.group(1).upper() if m else Path(path).stem.upper()


def resolve_units(root, cfg, unit_ids):
    """agreement unit id -> verifier id ('PROGRAM::PARAGRAPH', or 'PROGRAM' = all its paragraphs).
    Accepts 'PROG::PARA', 'PROG.PARA', a bare program id, or a bare paragraph (single-program runs)."""
    d = cobol_dir(root, cfg)
    progs = {program_id(p) for p in sorted(d.glob("*")) if p.suffix.lower() in (".cbl", ".cob") and p.is_file()}
    default = program_id(root / cfg["source"]["entry"]) if "entry" in cfg.get("source", {}) else next(iter(sorted(progs)), "")
    out = {}
    for u in unit_ids:
        if "::" in u:
            v = u
        elif u.upper() in progs:
            v = u.upper()
        elif "." in u and u.split(".")[0].upper() in progs:
            v = u.split(".")[0].upper() + "::" + u.split(".", 1)[1]
        else:
            v = f"{default}::{u}"
        out[v] = u
    return out


def runtime_problem(root, cfg, project):
    """Optional (agreement section 5): the project's runtime copy must equal the reference byte for byte."""
    t = cfg.get("target", {})
    rd, ref = (t.get("runtime_dir") or "").strip("/"), t.get("runtime_ref")
    if not rd or not ref:
        return None
    if not (project / rd).exists():
        return f"runtime library missing from project at {rd}"
    cmp = filecmp.dircmp(root / ref, project / rd)
    bad = cmp.left_only + cmp.right_only + cmp.diff_files
    return f"runtime library differs from reference: {sorted(bad)[:5]}" if bad else None


def _blocker(msg, cat="infra_error"):
    return {"finding_id": "F-001", "stage": "build", "unit_id": None, "severity": "blocker", "category": cat,
            "message": msg, "location": None, "cobol_ref": None, "counterexample": None, "kb_refs": [], "reproduce": None}


def check(workspace, sid, until=None):
    root = Path(workspace).resolve()
    cfg = yaml.safe_load((root / "config.yaml").read_text())
    sdir = root / "submissions" / sid
    if not (sdir / "submission.json").exists():
        raise ContractError(f"{sid}: no submission.json (incomplete submission)")
    sub = json.loads((sdir / "submission.json").read_text())
    rdir = root / "reports" / sid
    art = rdir / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    emit(root, cfg, "check_started", sid)
    t0 = time.time()
    scope = sub["scope"]
    required = scope.get("required_tier") or cfg["gate"]["required_tier"]

    def finish(report):
        report.update({"schema_version": "1.0", "submission_id": sid, "kb_version": sub.get("kb_version", "none")})
        tmp = rdir / "report.json.tmp"
        tmp.write_text(json.dumps(report, indent=2))
        os.rename(tmp, rdir / "report.json")
        emit(root, cfg, "check_finished", sid, verdict=report["verdict"], duration_s=round(time.time() - t0, 2),
             tiers={u["unit_id"]: u["tier"] for u in report["units"]}, oracle="GnuCOBOL (verifier toolchain image)")
        return report

    def infra(msg, cat="infra_error", verdict="error"):
        return finish({"verdict": verdict, "stages": [], "summary": msg, "findings": [_blocker(msg, cat)],
                       "units": [{"unit_id": u, "tier": "unchecked", "status": "fail"} for u in scope["unit_ids"]]
                       if verdict == "red" else []})

    project = sdir / sub.get("project_root", "project/")
    problem = runtime_problem(root, cfg, project)
    if problem:
        return infra(problem, "build_error", "red")
    # the verifier supplies its own verified cobolrt: hand it the project without the runtime copy
    view = art / "target"
    if view.exists():
        shutil.rmtree(view)
    rd = (cfg.get("target", {}).get("runtime_dir") or "").strip("/").split("/")[-1]
    shutil.copytree(project, view, ignore=shutil.ignore_patterns(rd) if rd else None)
    id_map = resolve_units(root, cfg, scope["unit_ids"] + scope.get("regression_unit_ids", []))
    tiers = UNTIL_TIERS[until] if until else REQUIRED_TIERS[required]
    prev = None
    for p in sorted((root / "reports").glob("S-*/artifacts/verifier/report.json")):
        if p.parent.parent.parent.name < sid:
            prev = p  # most recent earlier report: rotates the random seed, adds a delta to the feedback
    try:
        from verifier.api import verify
    except ImportError as e:
        return infra(f"verifier package not importable (run under the cobol-verifier venv): {e}")
    out = art / "verifier"
    try:
        vrep = verify(cobol=cobol_dir(root, cfg), target=view, lang=cfg["target"]["language"], out=out,
                      mode="full" if required == "proven" and not until else "fast",
                      units=list(id_map), tiers=tiers, previous_report=prev)
    except Exception as e:  # docker missing, bad manifest, tool crash: a checker error, not a red verdict
        return infra(f"verifier failed: {type(e).__name__}: {e}")
    return finish(convert(json.loads(vrep.to_json()), out, sid, id_map, required))
