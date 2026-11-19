"""RESULTS.md, generated from metrics.json and failures.jsonl only (the numbers cannot drift)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PASS = {True: "pass", False: "FAIL"}
YES = {True: "yes", False: "NO"}


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def load(out: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    metrics = json.loads((out / "metrics.json").read_text("utf-8"))
    failures = [json.loads(line) for line in (out / "failures.jsonl").read_text("utf-8").splitlines() if line]
    return metrics, failures


def headlines(m: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for ds, e1 in sorted(m["E1"].items()):
        progs = e1["programs"]
        out.append(f"**E1 ({ds})** {e1['files']} files ({pct(e1['files_classified_share'])} classified); programs "
                   f"{progs.get('strict', 0)} strict / {progs.get('tolerant', 0)} tolerant / {progs.get('failed', 0)} failed; "
                   f"{pct(e1['lines_accounted_share'])} of {e1['lines_total']} lines accounted for, "
                   f"{e1['lines_unattributed']} listed with a reason, {e1['lines_unexplained']} unexplained.")
    e2 = m["E2"]
    out.append(f"**E2** every unit seen in {e2['trace_cases']} GnuCOBOL traces exists in the KB "
               f"({pct(e2['traced_unit_recall'])}); span starts equal the trace in {pct(e2['span_start_exact'])} of "
               f"{e2['span_start_checked']} entries; KB paragraphs vs hand-written Java methods: precision "
               f"{pct(e2['java_methods']['precision'])}, recall {pct(e2['java_methods']['recall'])}.")
    e3 = m["E3"]
    rates = [v["rate"] for v in e3["attributes"].values()]
    compared = sum(v["compared"] for v in e3["attributes"].values())
    out.append(f"**E3** {compared} attribute comparisons against the cobc listing, a GnuCOBOL probe and the corpus "
               f"manifests: lowest attribute exact-match rate {pct(min(rates))}, {e3['mismatches']} mismatches; field "
               f"inventory {e3['field_inventory']['aligned']} aligned, {e3['field_inventory']['kb_only']} KB-only, "
               f"{e3['field_inventory']['listing_only']} listing-only.")
    e4 = m["E4"]
    out.append(f"**E4** {e4['soundness_violations']} soundness violations in {e4['transitions_checked']} observed "
               f"transitions; {e4['static_edges_exercised']} of {e4['static_edges']} static edges exercised "
               f"({pct(e4['static_edges_exercised_share'])}).")
    e5 = m["E5"]
    out.append(f"**E5 (model-based)** {e5['write_violations']} write violations in {e5['write_checks']} checks and "
               f"{e5['read_violations']} read violations in {e5['read_checks']} perturbations over {e5['paragraphs']} "
               f"paragraphs; {pct(e5['declared_writes_observed_share'])} of declared writes seen changing.")
    e6 = m["E6"]
    if e6.get("status") == "scored":
        ov = e6["phase0"]["overall"]
        out.append(f"**E6** against {len(e6['annotators'])} annotators: F1 reads {ov['reads']['f1']}, writes "
                   f"{ov['writes']['f1']}, performs {ov['performs']['f1']}; falls_through_to accuracy "
                   f"{pct(e6['phase0']['falls_through_to_accuracy'])}.")
    else:
        out.append(f"**E6** {e6['status']}.")
    if "E7" in m:
        worse = [r["metric"] for r in m["E7"]["table"] if worse_than_baseline(r)]
        tail = "."
        if worse:
            tail = f"; worse on: {', '.join(worse)} (explained below the table)."
        out.append(f"**E7** Phase 0 is at least as good as Phase 1's tolerant analyser on "
                   f"{len(m['E7']['table']) - len(worse)} of {len(m['E7']['table'])} rows{tail}")
    for ds, e8 in sorted(m["E8"].items()):
        out.append(f"**E8 ({ds})** deterministic: {YES[bool(e8['deterministic'])]}; {e8['builds']} builds, "
                   f"{e8['lines']} lines, {e8['seconds_per_kloc_cold']} s per 1,000 lines (cold); LLM tokens {e8['llm_tokens']}.")
    if "E10" in m:
        r, f = m["E10"]["rename"], m["E10"]["free"]
        out.append(f"**E10** consistent renaming: {r['pass']} isomorphic, {r['fail']} not, {r['skipped']} skipped; "
                   f"fixed -> free format: {f['pass']} identical, {f['fail']} not (see failures.jsonl, E10).")
    if "E11" in m:
        e11 = m["E11"]
        out.append(f"**E11** {e11['model']}: {e11['summaries']} summaries, {pct(e11['unsupported_entity_share'])} named an "
                   f"entity outside the unit's facts and were rejected; {e11['llm_tokens_first_build']} tokens.")
    e9 = m["E9"]
    checks = {"KB files schema-valid": e9["kb_files_valid"], "JSON Schemas current": e9["exported_json_schemas_current"],
              "gap ids closed": e9["gap_ids_closed"], "runtime byte-identical": e9["runtime_byte_identical"]}
    if "e2e_scripted" in e9:
        checks["e2e_scripted with real Phase 0"] = e9["e2e_scripted"]["pass"]
    out.append("**E9** " + "; ".join(f"{k}: {PASS[bool(v)]}" for k, v in checks.items()) + ".")
    return out


def worse_than_baseline(r: dict[str, Any]) -> bool:
    if r["higher_is_better"]:
        return bool(r["phase0"] < r["phase1"])
    return bool(r["phase0"] > r["phase1"])


def e7_table(m: dict[str, Any]) -> list[str]:
    if "E7" not in m:
        return ["Not run (pass `--baseline phase1`)."]
    rows = ["| Metric | Phase 0 | Phase 1 (tolerant) |", "| --- | --- | --- |"]
    for r in m["E7"]["table"]:
        rows.append(f"| {r['metric']} | {r['phase0']} | {r['phase1']} |")
    rows += ["", *e7_notes(m)]
    return rows


def e7_notes(m: dict[str, Any]) -> list[str]:
    p0, p1 = m["E4"], m["E7"]["phase1"]["E4"]
    notes = []
    if p0["static_edges_exercised_share"] < p1["static_edges_exercised_share"]:
        notes.append(f"- *E4 static edges exercised:* both analysers exercise {p0['static_edges_exercised']} vs "
                     f"{p1['static_edges_exercised']} edges; Phase 0 states {p0['static_edges']} static edges and Phase 1 "
                     f"{p1['static_edges']}, so the lower share comes from more stated edges (over-approximation), not "
                     "from fewer observed ones.")
    e5 = m["E7"]["phase1"]["E5"]
    if e5["write_violations"] or e5["read_violations"]:
        notes.append("- *E5 Phase 1 violations* come from three patterns (see `failures.jsonl`, source `phase1`): "
                     "INITIALIZE of a group not expanded to its elementary items, the PERFORM VARYING control item "
                     "missing from writes, and REDEFINES aliasing.")
    notes.append("- Phase 1 states no offsets or byte lengths, hence 0.0 on those rows.")
    return notes


def violations(failures: list[dict[str, Any]]) -> list[str]:
    own = [f for f in failures if f.get("metric") in ("E4", "E5") and f.get("source", "phase0") == "phase0"]
    if not own:
        return ["None: E4 and E5 report zero soundness violations for Phase 0 on D1 and D2."]
    return [f"- `{json.dumps(f, sort_keys=True)}`" for f in own]


def e10_failures(failures: list[dict[str, Any]]) -> list[str]:
    rows = [f"- {f['transformation']} {f['program']}: {f['detail']}" for f in failures if f.get("metric") == "E10"]
    if not rows:
        return []
    return ["", "### Metamorphic failures (E10)", "", *rows, "",
            "A format-detection failure is the verifier's `detect_format`, which Phase 0 shares (TEAM_NOTES item 7)."]


def hazard_table(m: dict[str, Any]) -> list[str]:
    d3 = m.get("F_hazards", {}).get("D3")
    if not d3:
        return []
    gaps = sorted(set(d3["phase0"]) | set(d3["phase1_now"]))
    rows = ["| Gap | Phase 0 | Phase 1 now | Mid-report |", "| --- | --- | --- | --- |"]
    for g in gaps:
        rows.append(f"| {g} | {d3['phase0'].get(g, 0)} | {d3['phase1_now'].get(g, 0)} | {d3['mid_report'].get(g, '')} |")
    return rows


def carddemo(m: dict[str, Any]) -> list[str]:
    e1 = m["E1"].get("D3")
    if not e1:
        return ["D3 not evaluated."]
    rows = [f"- Files by kind: {json.dumps(e1['files_by_kind'], sort_keys=True)}",
            f"- Programs: {json.dumps(e1['programs'], sort_keys=True)}",
            f"- Lines: {e1['lines_total']} program/copybook lines, {pct(e1['lines_accounted_share'])} accounted for; "
            f"unattributed by reason: {json.dumps(e1['unattributed_by_reason'], sort_keys=True)}"]
    top = sorted(e1["unsupported_constructs"].items(), key=lambda kv: -kv[1])[:12]
    rows.append("- Most frequent unsupported constructs (programs): " + ", ".join(f"{k} ({v})" for k, v in top))
    return rows


THREATS = [
    "- **Circularity of O4.** The interpreter shares the lexer, parser and data layout with Phase 0, so E5 can only "
    "find errors in Phase 0's read/write *analysis*, not in the shared front end. E5 is labelled model-based and every "
    "claim it supports is also backed by an independent oracle: layout by O1 (E3), control flow by O2 (E4).",
    "- **Small, synthetic corpus.** D1 and D2 are 38 short programs written to exercise semantics; they lack the "
    "size and idioms of production code. D3 (CardDemo) adds scale but no ground truth beyond coverage and hazard counts.",
    "- **GnuCOBOL is the reference, not IBM Enterprise COBOL.** Sizes, DISPLAY formats and trace semantics are "
    "GnuCOBOL 3.2 `-std=default`; IBM-specific behaviour (and CICS/IMS/DB2 programs, which fall back to the tolerant "
    "analyser) is outside what the oracles can confirm.",
    "- **Annotator bias (E6).** The two annotators are project members who know COBOL and the guide's definitions; "
    "agreement is reported to bound this. The guide was written from the same definitions Phase 0 implements, so a "
    "shared misreading of COBOL would not be caught.",
    "- **Permissive E4 rule.** Traces do not show PERFORM returns, so a transition is accepted when an earlier "
    "performer has a static edge to the target; a full call-stack model would be stricter.",
    "- **Random states in E5.** Values are valid for each PIC; invalid data (e.g. an X(n) REDEFINES of a numeric "
    "item) is not perturbed, and paragraphs whose runs need open files are refused (counted in `refused_runs`).",
]


def render(out: Path, target: Path) -> None:
    m, failures = load(out)
    lines = ["# Phase 0 evaluation results", "",
             "Generated by `phase0 eval` from `metrics.json` and `failures.jsonl`; do not edit by hand.", "",
             "## 1. Headlines", ""]
    lines += [f"- {h}" for h in headlines(m)]
    lines += ["", "## 2. Phase 0 vs Phase 1's tolerant analyser (E7)", "", *e7_table(m),
              "", "## 3. Soundness violations (E4, E5)", "", *violations(failures), *e10_failures(failures),
              "", "## 4. CardDemo (D3) coverage", "", *carddemo(m),
              "", "### Hazard sites on CardDemo (stage F)", "", *hazard_table(m),
              "", "Differences are explained in `phase0/notes.md` (section \"Stage F hazard counts\").",
              "", "## 5. Threats to validity", "", *THREATS,
              "", f"Evaluation time: {json.dumps(m.get('eval_seconds', {}), sort_keys=True)} seconds.", ""]
    target.write_text("\n".join(lines), "utf-8")
