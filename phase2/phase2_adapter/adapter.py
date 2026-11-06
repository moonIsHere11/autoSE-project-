"""`phase2 check` backed by Nan's verifier (verifier.api.verify): contract glue only.
 - reads submissions/<sid>/submission.json, writes reports/<sid>/report.json (agreement 4.3/4.4)
 - verifier output lives in reports/<sid>/artifacts/verifier/ (report.json, summary.md, feedback/, cases/)"""
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


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class ContractError(Exception):
    pass


def emit(ws, kind, sid=None, **data):
    run = ws["cfg"].get("run", {}).get("id", "R-001")
    p = ws["root"] / "runs" / run / "events.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps({"ts": now(), "run_id": run, "module": "phase2", "kind": kind, "unit_id": None,
                            "submission_id": sid, "data": data}) + "\n")


def cobol_program_id(path):
    m = re.search(r"PROGRAM-ID\.?\s+([A-Za-z0-9-]+)", Path(path).read_text(errors="replace"), re.I)
    return m.group(1).upper() if m else Path(path).stem.upper()


def resolve_units(ws, unit_ids):
    """agreement unit_id -> verifier id (PROGRAM::PARAGRAPH, or PROGRAM for a whole program).
    Accepts 'PROG::PARA', 'PROG.PARA', 'PARA' (single-program run) or a program id."""
    entry = ws["root"] / ws["cfg"]["source"]["entry"]
    entry_prog = cobol_program_id(entry)
    progs = {entry_prog}
    for p in entry.parent.glob("*"):
        if p.suffix.lower() in (".cbl", ".cob") and p.is_file():
            progs.add(cobol_program_id(p))
    out = {}
    for u in unit_ids:
        if "::" in u:
            v = u
        elif u.upper() in progs or u == "PROGRAM":
            v = entry_prog if u == "PROGRAM" else u.upper()
        elif "." in u and u.split(".")[0].upper() in progs:
            v = u.split(".")[0].upper() + "::" + u.split(".", 1)[1]
        else:
            v = f"{entry_prog}::{u}"
        out[v] = u
    return out


def check_runtime_unchanged(ws, project, tc):
    """Agreement section 5: the project's runtime library must equal kb/target/runtime byte for byte."""
    kb_rt = ws["root"] / "kb" / "target" / "runtime"
    rd = (tc or {}).get("runtime_dir")
    if not rd or not kb_rt.exists():
        return None
    mine = project / rd
    if not mine.exists():
        return "runtime library missing from project at " + rd
    cmp = filecmp.dircmp(kb_rt, mine)
    bad = cmp.left_only + cmp.right_only + cmp.diff_files
    return f"runtime library differs from KB: {sorted(bad)[:5]}" if bad else None


def check(workspace, sid, until=None):
    root = Path(workspace).resolve()
    cfg = yaml.safe_load((root / "config.yaml").read_text())
    ws = {"root": root, "cfg": cfg}
    sdir = root / "submissions" / sid
    if not (sdir / "submission.json").exists():
        raise ContractError(f"{sid}: no submission.json (incomplete submission)")
    sub = json.loads((sdir / "submission.json").read_text())
    rdir = root / "reports" / sid
    art = rdir / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    emit(ws, "check_started", sid)
    t0 = time.time()
    required = sub["scope"].get("required_tier") or cfg["gate"]["required_tier"]

    def finish(report):
        report.update({"schema_version": "1.0", "submission_id": sid, "kb_version": sub["kb_version"]})
        tmp = rdir / "report.json.tmp"
        tmp.write_text(json.dumps(report, indent=2))
        os.rename(tmp, rdir / "report.json")
        emit(ws, "check_finished", sid, verdict=report["verdict"], tiers={u["unit_id"]: u["tier"] for u in report["units"]},
             duration_s=round(time.time() - t0, 2), oracle="GnuCOBOL (verifier toolchain image)")
        return report

    def infra(msg):
        return finish({"verdict": "error", "stages": [], "units": [], "summary": msg,
                       "findings": [{"finding_id": "F-001", "stage": "build", "unit_id": None, "severity": "blocker",
                                     "category": "infra_error", "message": msg, "location": None, "cobol_ref": None,
                                     "counterexample": None, "kb_refs": [], "reproduce": None}]})

    mf = root / "kb" / "manifest.json"
    if mf.exists():
        cur = json.loads(mf.read_text())["kb_version"]
        if cur != sub["kb_version"]:
            return infra(f"KB version mismatch: submission built on {sub['kb_version']}, current KB is {cur}")
    tc = json.loads((root / "kb" / "target" / "toolchain.json").read_text()) if \
        (root / "kb" / "target" / "toolchain.json").exists() else {}
    project = sdir / sub.get("project_root", "project/")
    rt_problem = check_runtime_unchanged(ws, project, tc)
    if rt_problem:
        return finish({"verdict": "red", "stages": [{"name": "build", "status": "fail", "duration_s": 0.0}],
                       "units": [{"unit_id": u, "tier": "unchecked", "status": "fail"} for u in sub["scope"]["unit_ids"]],
                       "summary": rt_problem, "findings": [{
                           "finding_id": "F-001", "stage": "build", "unit_id": None, "severity": "blocker",
                           "category": "build_error", "message": rt_problem, "location": None, "cobol_ref": None,
                           "counterexample": None, "kb_refs": [], "reproduce": None}]})
    # the verifier supplies its own (verified) cobolrt: give it the project without the runtime copy
    view = art / "target"
    if view.exists():
        shutil.rmtree(view)
    shutil.copytree(project, view, ignore=shutil.ignore_patterns(*( [tc["runtime_dir"].strip("/").split("/")[-1]] if tc.get("runtime_dir") else [])))
    scope = sub["scope"]
    id_map = resolve_units(ws, scope["unit_ids"] + scope.get("regression_unit_ids", []))
    tiers = UNTIL_TIERS.get(until) if until else REQUIRED_TIERS[required]
    prev = None
    for p in sorted((root / "reports").glob("S-*/artifacts/verifier/report.json")):
        if p.parent.parent.parent.name < sid:
            prev = p  # most recent earlier report: seeds rotate, feedback gets a delta section
    try:
        from verifier.api import verify
    except ImportError as e:
        return infra(f"verifier package not importable (run under the cobol-verifier venv): {e}")
    out = art / "verifier"
    try:
        vrep = verify(cobol=(root / cfg["source"]["entry"]).parent, target=view, lang=cfg["target"]["language"],
                      out=out, mode="full" if required == "proven" and not until else "fast",
                      units=list(id_map), tiers=tiers, previous_report=prev)
    except Exception as e:  # docker missing, bad manifest, tool crash -> checker error, not a red verdict
        return infra(f"verifier failed: {type(e).__name__}: {e}")
    rep = json.loads(vrep.to_json())
    return finish(convert(rep, out, sid, id_map, required))
