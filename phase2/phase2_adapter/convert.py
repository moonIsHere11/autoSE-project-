"""Translate Nan's verifier report (verifier/report/schema.py, INTERFACE.md section 4/5) into the
agreement's Report (section 4.4). Pure functions: no I/O except reading the feedback JSON."""
import json
from pathlib import Path

TIER_RANK = {"unchecked": 0, "tested": 1, "bounded": 2, "proven": 3}
REQUIRED_TIERS = {"tested": [0, 1], "bounded": [0, 1, 2], "proven": [0, 1, 2, 3]}
UNTIL_TIERS = {"build": [0], "lint": [0], "differential": [0, 1], "verification": [0, 1, 2, 3]}
STATUS = {"PASS": "pass", "FAIL": "fail", "ERROR": "error", "TIMEOUT": "error",
          "SKIPPED": "skipped", "NOT_APPLICABLE": "skipped"}
# verifier "likely cause" labels -> KB semantic-gap ids (shared with Phase 1's hazard scanner)
CAUSE_TO_GAP = {"SIGN_LOST": ["G-SIGN"], "NEGATIVE_ZERO": ["G-SIGN"],
                "MISSING_HIGH_ORDER_TRUNCATION": ["G-TRUNCATE", "G-OVERFLOW"],
                "ROUNDING_MISSING": ["G-ROUNDING"], "ROUNDING_MODE": ["G-ROUNDING"],
                "SIZE_ERROR_HANDLING": ["G-OVERFLOW", "G-TRUNCATE"], "PADDING_OR_JUSTIFICATION": ["G-NUMALPHA"],
                "DISPLAY_FORMAT": ["G-NUMALPHA"]}


def _st(t):
    return (t or {}).get("status")


def unit_tier(unit):
    """Strongest evidence reached -> agreement tier."""
    ev = set(unit.get("evidence", []))
    t2b = ((unit.get("tiers", {}).get("T2") or {}).get("sub") or {}).get("T2b") or {}
    complete = "complete" in (t2b.get("bound") or "")
    if "T3" in ev or "T2a" in ev or ("T2b" in ev and complete):
        return "proven"
    if "T2b" in ev:
        return "bounded"
    if "T1" in ev:
        return "tested"
    return "unchecked"


def stage_results(rep):
    """build / lint / differential / verification from program- and unit-level tiers."""
    def agg(statuses, dur):
        statuses = [s for s in statuses if s]
        if not statuses:
            return {"status": "skipped", "duration_s": dur}
        for bad in ("FAIL", "ERROR", "TIMEOUT"):
            if bad in statuses:
                return {"status": STATUS[bad], "duration_s": dur}
        return {"status": "pass" if "PASS" in statuses else "skipped", "duration_s": dur}

    t0s, t0checks, t1s, vs = [], {}, [], []
    for p in rep.get("programs", []):
        for k, t in (p.get("tiers") or {}).items():
            if k.startswith("T0"):
                t0s.append(_st(t))
            if k == "T1":
                t1s.append(_st(t))
    for u in rep.get("units", []):
        t = u.get("tiers", {})
        for c in (t.get("T0") or {}).get("checks", []):
            t0checks.setdefault(c["name"], []).append(c["status"])
        if t.get("T1"):
            t1s.append(_st(t["T1"]))
        vs += [_st(t.get("T2")), _st(t.get("T3"))]
    tim = rep.get("summary", {}).get("tier_timings_s", {})
    build = [s for n, ss in t0checks.items() if "build" in n for s in ss] or t0s
    lint = [s for n, ss in t0checks.items() if "build" not in n for s in ss]
    return [{"name": "build", **agg(build, tim.get("T0", 0.0))},
            {"name": "lint", **agg(lint, 0.0)},
            {"name": "differential", **agg(t1s, tim.get("T1", 0.0))},
            {"name": "verification", **agg(vs, tim.get("T2", 0.0) + tim.get("T3", 0.0))}]


def _load_feedback(out_dir, unit_id):
    p = Path(out_dir) / "feedback" / (unit_id.replace("::", "__") + ".json")
    return json.loads(p.read_text()) if p.exists() else None


def _finding(fid, stage, uid, sev, cat, msg, loc=None, cobol=None, ce=None, refs=(), repro=None):
    return {"finding_id": f"F-{fid:03d}", "stage": stage, "unit_id": uid, "severity": sev, "category": cat,
            "message": msg, "location": loc, "cobol_ref": cobol, "counterexample": ce,
            "kb_refs": list(refs), "reproduce": repro}


def convert(rep, out_dir, sub, id_map, required):
    """rep: verifier report dict. id_map: verifier unit id -> agreement unit_id."""
    findings, units_out, n, seen_sig = [], [], [0], {}

    def nid():
        n[0] += 1
        return n[0]

    # infrastructure problems: the verifier itself failed
    if rep.get("errors"):
        for e in rep["errors"]:
            findings.append(_finding(nid(), "build", None, "blocker", "infra_error", str(e)))
        return {"verdict": "error", "units": [], "findings": findings,
                "stages": stage_results(rep), "summary": "Checker infrastructure error: " + "; ".join(map(str, rep["errors"]))[:300]}
    for p in rep.get("programs", []):
        if p.get("out_of_scope"):
            findings.append(_finding(nid(), "build", None, "warning", "verification_unknown",
                                     f"program {p['id']} out of verifier scope: {p['out_of_scope']}"))
    all_green = True
    for u in rep.get("units", []):
        uid = id_map.get(u["id"], u["id"])
        tier = unit_tier(u)
        fails = {k: t for k, t in u.get("tiers", {}).items() if _st(t) in ("FAIL", "ERROR", "TIMEOUT")}
        accepted = bool(u.get("accepted"))
        if fails:
            status = "fail"
        elif accepted and TIER_RANK[tier] >= TIER_RANK[required]:
            status = "pass"
        else:
            status = "unchecked"
        units_out.append({"unit_id": uid, "tier": tier, "status": status})
        fb = _load_feedback(out_dir, u["id"]) or {}
        # T0: build / static findings
        t0 = u.get("tiers", {}).get("T0") or {}
        for c in t0.get("checks", []):
            for f in c.get("findings", []):
                if f["severity"] != "ERROR":
                    continue
                cat = "build_error" if "build" in c["name"] else "lint"
                findings.append(_finding(nid(), "build" if cat == "build_error" else "lint", uid, "blocker", cat,
                                         f["message"], {"file": f.get("file") or "?", "line": f.get("line") or 0}
                                         if f.get("file") else None))
        # T1 / T2 / T3: counterexamples (at most 3, from the paste-ready feedback)
        for sig in fb.get("signatures", [])[:3]:
            ce = sig.get("counterexample") or {}
            cause = sig.get("likely_cause") or {}
            tl, cs, fm = sig.get("target_location"), (sig.get("cobol_statements") or [None])[0], sig.get("field_mapping") or {}
            key = (sig.get("signature"), json.dumps(ce.get("input_fields") or ce.get("inputs"), sort_keys=True, default=str))
            if key in seen_sig:  # program-level failure is reported once, not once per paragraph
                seen_sig[key]["affects"].append(uid)
                continue
            failed_tier = fb.get("failed_tier", "T1")
            diffs = ce.get("diffs") or []
            ce_out = {"inputs": {k: str(v) for k, v in (ce.get("input_fields") or {}).items()} or
                                {k: json.dumps(v) for k, v in (ce.get("inputs") or {}).items() if v},
                      "expected": {(d.get("field") or d["location"]): str(d["expected"]) for d in diffs},
                      "actual": {(d.get("field") or d["location"]): str(d["actual"]) for d in diffs}} if ce else None
            fnd = _finding(
                nid(), "differential" if failed_tier == "T1" else "verification", uid, "blocker",
                "behavior_mismatch" if failed_tier == "T1" else "verification_failed",
                f"{sig.get('signature')}. {cause.get('explanation') or cause.get('text', '')}"
                + (f" Field {fm['cobol']} PIC {fm.get('pic')} -> {fm.get('target')}:{fm.get('target_type', '')}." if fm.get("cobol") else ""),
                {"file": tl["file"], "line": tl["line"]} if tl else None,
                {"file": cs["file"], "start_line": cs["line"], "end_line": cs["line"]} if cs else None,
                ce_out, CAUSE_TO_GAP.get(cause.get("label"), []), sig.get("repro"))
            fnd["affects"] = [uid]
            seen_sig[key] = fnd
            findings.append(fnd)
        for k, t in fails.items():
            if k != "T0" and not fb.get("signatures"):
                cat = "timeout" if _st(t) == "TIMEOUT" else "verification_failed" if _st(t) == "FAIL" else "infra_error"
                findings.append(_finding(nid(), "verification" if k in ("T2", "T3") else "differential", uid,
                                         "blocker" if cat == "verification_failed" else "warning", cat,
                                         f"{k} {_st(t)}: {t.get('reason') or 'see reports/' + sub + '/artifacts/verifier/report.json'}"))
        if not fails and TIER_RANK[tier] < TIER_RANK[required]:
            why = (u.get("tiers", {}).get("T2") or u.get("tiers", {}).get("T3") or {}).get("reason", "tier not reached")
            findings.append(_finding(nid(), "verification", uid, "blocker", "verification_unknown",
                                     f"required tier '{required}' not reached (got '{tier}'): {why}"))
        elif not fails and not accepted:
            reasons = "; ".join((u.get("acceptance") or {}).get("reasons", [])) or "acceptance policy not met"
            findings.append(_finding(nid(), "differential", uid, "blocker", "verification_unknown",
                                     f"verifier did not accept the unit: {reasons}"))
        all_green &= status == "pass"
    for f in findings:
        aff = f.pop("affects", [])
        if len(aff) > 1:
            f["message"] += f" (same failure affects {len(aff)} units: {', '.join(x.split('::')[-1] for x in aff[:6])})"
    blockers = [f for f in findings if f["severity"] == "blocker"]
    verdict = "green" if all_green and units_out and not blockers else "red"
    nb = len(blockers)
    s = rep.get("summary", {})
    summary = (f"{s.get('accepted', 0)}/{s.get('units', 0)} units accepted by the verifier; required tier '{required}'.\n"
               f"Tiers reached: " + ", ".join(f"{u['unit_id']}={u['tier']}" for u in units_out[:6])
               + ("\n" + f"{nb} blocker finding(s); fix the first counterexample first." if nb else ""))
    return {"verdict": verdict, "units": units_out, "findings": findings,
            "stages": stage_results(rep), "summary": summary}
