"""LLM-ready feedback per unit: `feedback/<unit>.md` and `feedback/<unit>.json` (spec section 8).

Never includes held-out data: only the verifier's own cases and the COBOL/target sources.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from verifier.report.schema import Counterexample, Report, Status, UnitResult

CHARS_PER_TOKEN = 4
MAX_SIGNATURES = 3


def unit_filename(unit_id: str) -> str:
    return unit_id.replace("::", "__").replace("(", "").replace(")", "").replace("/", "_")


def _failed_tier(u: UnitResult) -> str | None:
    for k in ("T0", "T1", "T2", "T3"):
        t = u.tiers.get(k)
        if t is not None and t.status in (Status.FAIL, Status.ERROR, Status.TIMEOUT):
            return k
    return None


def _cx_json(cx: Counterexample, previous_sigs: set[str]) -> dict[str, Any]:
    return {
        "signature": cx.signature,
        "source_tier": cx.source_tier,
        "counterexample": {
            "inputs": cx.inputs,
            "input_fields": {f.field: f.value for f in cx.input_fields},
            "diffs": [d.model_dump() for d in cx.diffs],
            "case": cx.case_dir,
            "shrunk": cx.shrunk,
        },
        "likely_cause": cx.classification.model_dump() if cx.classification else None,
        "cobol_statements": [s.model_dump() for s in cx.cobol_statements],
        "field_mapping": cx.field_mapping,
        "target_location": cx.target_location.model_dump() if cx.target_location else None,
        "repro": cx.repro,
        "repeats_previous": cx.signature in previous_sigs,
    }


def build_feedback(u: UnitResult, previous: Report | None) -> dict[str, Any]:
    failed = _failed_tier(u)
    passed = [k for k in ("T0", "T1", "T2", "T3") if (t := u.tiers.get(k)) is not None and t.status == Status.PASS]
    prev_unit = next((p for p in previous.units if p.id == u.id), None) if previous else None
    prev_sigs: set[str] = set()
    if prev_unit is not None:
        for t in prev_unit.tiers.values():
            prev_sigs.update(cx.signature for cx in t.counterexamples)
    cxs: list[Counterexample] = []
    for k in ("T1", "T2", "T3"):
        t = u.tiers.get(k)
        if t is not None:
            cxs.extend(t.counterexamples)
    build_errors: list[dict[str, Any]] = []
    static_errors: list[dict[str, Any]] = []
    t0 = u.tiers.get("T0")
    if t0 is not None:
        for c in t0.checks:
            for f in c.findings:
                if f.severity != "ERROR":
                    continue
                entry = {"check": f.check, "message": f.message, "file": f.file, "line": f.line,
                         "excerpt": f.excerpt, "cobol_ref": f.cobol_ref}
                (build_errors if c.name == "build" else static_errors).append(entry)
    delta: dict[str, Any] = {}
    if prev_unit is not None:
        improved, regressed = [], []
        for k in ("T0", "T1", "T2", "T3"):
            a, b = prev_unit.tiers.get(k), u.tiers.get(k)
            if a is None or b is None:
                continue
            if a.status != Status.PASS and b.status == Status.PASS:
                improved.append(k)
            if a.status == Status.PASS and b.status in (Status.FAIL, Status.ERROR):
                regressed.append(k)
        now = {cx.signature for cx in cxs}
        delta = {"improved": improved, "regressed": regressed,
                 "repeated_signatures": sorted(now & prev_sigs),
                 "previous_level": prev_unit.level, "level": u.level}
    return {
        "unit": u.id,
        "accepted": u.accepted,
        "level": u.level,
        "failed_tier": failed,
        "passed_tiers": passed,
        "acceptance_reasons": u.acceptance.reasons if u.acceptance else [],
        "build_errors": build_errors[:10],
        "static_errors": static_errors[:10],
        "signatures": [_cx_json(cx, prev_sigs) for cx in cxs[:MAX_SIGNATURES]],
        "delta": delta,
    }


def render_feedback_md(fb: dict[str, Any], token_cap: int) -> str:
    cap = token_cap * CHARS_PER_TOKEN
    lines: list[str] = []
    lines.append(f"# Verifier feedback for {fb['unit']}")
    lines.append(f"Failed tier: {fb['failed_tier'] or 'none'}; already passed: {', '.join(fb['passed_tiers']) or 'none'}; "
                 f"level {fb['level']}; {'accepted' if fb['accepted'] else 'NOT accepted'}.")
    if fb["acceptance_reasons"]:
        lines.append("Why not accepted: " + "; ".join(fb["acceptance_reasons"]))
    d = fb.get("delta") or {}
    if d:
        lines.append(f"Since the previous attempt: level {d.get('previous_level')} -> {d.get('level')}; "
                     f"improved {d.get('improved') or '-'}; regressed {d.get('regressed') or '-'}"
                     + (f"; REPEATED failure signatures: {d['repeated_signatures']}" if d.get("repeated_signatures") else ""))
    if fb["build_errors"]:
        lines.append("\n## Build errors")
        for e in fb["build_errors"]:
            lines.append(f"- {e['file']}:{e['line']}: {e['message']}")
            if e.get("excerpt"):
                lines.append("```\n" + e["excerpt"] + "\n```")
    if fb["static_errors"]:
        lines.append("\n## Static check errors")
        for e in fb["static_errors"]:
            loc = f"{e['file']}:{e['line']}: " if e.get("file") else ""
            ref = f" (COBOL: {e['cobol_ref']})" if e.get("cobol_ref") else ""
            lines.append(f"- [{e['check']}] {loc}{e['message']}{ref}")
    for i, s in enumerate(fb["signatures"], 1):
        cx = s["counterexample"]
        lines.append(f"\n## Failure {i}: {s['signature']}" + (" (repeats previous attempt)" if s["repeats_previous"] else ""))
        if cx["input_fields"]:
            lines.append("Input (shrunk)" if cx.get("shrunk") else "Input:")
            for k, v in cx["input_fields"].items():
                lines.append(f"- {k} = {v!r}")
        elif cx.get("inputs"):
            lines.append(f"Input: {json.dumps(cx['inputs'])[:400]}")
        for diff in cx["diffs"][:6]:
            fld = f" {diff['field']}" if diff.get("field") else ""
            pic = f" (PIC {diff['pic']})" if diff.get("pic") else ""
            lines.append(f"- at {diff['location']}{fld}{pic}: expected (GnuCOBOL) `{diff['expected']}`, actual (target) `{diff['actual']}`")
        if s.get("likely_cause"):
            lines.append(f"Likely cause ({s['likely_cause']['label']}): {s['likely_cause']['explanation']}")
        if s["cobol_statements"]:
            lines.append("Implicated COBOL statements:")
            for st in s["cobol_statements"][:4]:
                lines.append(f"- {st['file']}:{st['line']}: `{st['text']}`")
        if s.get("field_mapping"):
            lines.append(f"Field mapping: {json.dumps(s['field_mapping'])[:300]}")
        if s.get("target_location"):
            tl = s["target_location"]
            lines.append(f"Target code: {tl['file']}:{tl['line']} `{tl.get('text', '')}`")
        lines.append(f"Reproduce: `{s['repro']}`")
    text = "\n".join(lines) + "\n"
    if len(text) > cap:
        text = text[: cap - 60].rsplit("\n", 1)[0] + "\n\n[... truncated to the feedback token cap ...]\n"
    return text


def write_feedback(report: Report, out_dir: Path, previous: Report | None, token_cap: int) -> list[str]:
    fdir = out_dir / "feedback"
    fdir.mkdir(parents=True, exist_ok=True)
    written = []
    for u in report.units:
        if u.accepted:
            continue
        fb = build_feedback(u, previous)
        name = unit_filename(u.id)
        (fdir / f"{name}.json").write_text(json.dumps(fb, indent=2), "utf-8")
        (fdir / f"{name}.md").write_text(render_feedback_md(fb, token_cap), "utf-8")
        written.append(name)
    return written
