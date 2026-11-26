"""`phase0 eval`: run every check in section 7 and write metrics.json + failures.jsonl."""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from phase0 import jsonio
from phase0.evaluation.datasets import Built, Program, build_program, d1, d2, d3
from phase0.evaluation.e2_e4_run import ControlEval, e2_metrics, e4_metrics, evaluate_program
from phase0.evaluation.e3_data import Tally, score_listing, score_manifest, score_probe
from phase0.evaluation.e5_run import check_program, kb_units
from phase0.evaluation.e5_run import metrics as e5_metrics
from phase0.evaluation.e6_gold import agreement, load_gold, score
from phase0.evaluation.e7_run import run_baseline
from phase0.evaluation.e9 import e9
from phase0.evaluation.e10 import e10
from phase0.evaluation.hazard_counts import hazard_counts
from phase0.evaluation.o1 import CompileJob, O1Outcome, probe_items, probe_source, run_o1
from phase0.evaluation.o4 import E5Tally
from phase0.toolbox import Toolbox, make_toolbox
from verifier.cobol.preprocess import detect_format


@dataclass
class Eval:
    out: Path
    toolbox: Toolbox
    built: list[Built] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    failures: list[dict[str, Any]] = field(default_factory=list)
    seconds: dict[str, float] = field(default_factory=dict)
    control: ControlEval = field(default_factory=ControlEval)  # O2 runs, reused by E7
    o1: O1Outcome = field(default_factory=O1Outcome)  # O1 runs, reused by E7
    phase1_units: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)  # E7 baseline, reused by E6

    def timed(self, name: str, fn: Callable[[], None]) -> None:
        start = time.perf_counter()
        fn()
        self.seconds[name] = round(time.perf_counter() - start, 2)

    def of(self, *datasets: str) -> list[Built]:
        return [b for b in self.built if b.program.dataset in datasets]


def select(datasets: list[str], carddemo: Path) -> list[Program]:
    out: list[Program] = []
    if "D1" in datasets:
        out += d1()
    if "D2" in datasets:
        out += d2()
    if "D3" in datasets:
        out += d3(carddemo)
    return out


# ---- E1 coverage --------------------------------------------------------------------------------
def e1(ev: Eval) -> None:
    per: dict[str, Any] = {}
    for ds in sorted({b.program.dataset for b in ev.built}):
        files: list[dict[str, Any]] = []
        progs: list[dict[str, Any]] = []
        unsupported: Counter[str] = Counter()
        for b in ev.of(ds):
            files += b.kb("source/inventory.json")["files"]
            progs += b.kb("source/coverage.json")["programs"]
            for p in b.kb("source/coverage.json")["programs"]:
                for construct in p["unsupported"]:
                    unsupported[construct] += 1
        total = sum(p["lines_total"] for p in progs)
        unattributed = [u for p in progs for u in p["unattributed"]]
        status = Counter(f["parse_status"] for f in files if f["kind"] == "program")
        recognised = sum(1 for f in files if f["kind"] != "other" or f["subkind"] is not None)
        per[ds] = {
            "files": len(files),
            "files_by_kind": dict(Counter(f"{f['kind']}/{f['subkind']}" for f in files)),
            "files_classified_share": share(recognised, len(files)),
            "programs": dict(status),
            "lines_total": total,
            "lines_accounted_share": share(total - len(unattributed), total),
            "lines_unattributed": len(unattributed),
            "lines_unexplained": sum(1 for u in unattributed if not u["reason"]),
            "unattributed_by_reason": dict(Counter(u["reason"] for u in unattributed)),
            "unsupported_constructs": dict(sorted(unsupported.items())),
        }
    ev.metrics["E1"] = per


def share(a: int, b: int) -> float:
    if b == 0:
        return 1.0
    return round(a / b, 4)


# ---- E3 data dictionary -------------------------------------------------------------------------
def e3(ev: Eval) -> None:
    t = Tally()
    inventory: dict[str, dict[str, int]] = {}
    targets = ev.of("D1", "D2")
    jobs: list[CompileJob] = []
    for b in targets:
        rel = (b.ws / "source" / b.program.entry).relative_to(ev.out / "ws").as_posix()
        text = (b.ws / "source" / b.program.entry).read_text("latin-1")
        items = probe_items(b.kb("source/data_dictionary.json"))
        jobs.append(CompileJob(f"{b.program.dataset}/{b.program.name}", rel,
                               ev.toolbox.config.cobol.flags(detect_format(text)), probe_source(text, items), items))
    o1 = run_o1(ev.toolbox, ev.out / "ws", jobs, [])
    ev.o1 = o1
    for b in targets:
        key = f"{b.program.dataset}/{b.program.name}"
        fields = b.kb("source/data_dictionary.json")
        repro = f"phase0/bin/phase0 query get_field <field_id> --workspace {b.ws}"
        if key in o1.errors:
            ev.failures.append({"metric": "E3", "program": key, "kind": "listing failed", "detail": o1.errors[key],
                                "repro": repro})
        if key in o1.listing:
            inventory[key] = score_listing(t, key, fields, o1.listing[key], repro)
        probe = o1.probe.get(key)
        if probe is not None and probe.error is None:
            score_probe(t, key, fields, probe, repro)
        elif probe is not None:
            ev.failures.append({"metric": "E3", "program": key, "kind": "probe failed",
                                "detail": probe.error, "repro": repro})
        if b.program.manifest is not None:
            score_manifest(t, key, fields, b.program.manifest, repro)
    ev.failures += t.failures
    aligned = sum(v["aligned"] for v in inventory.values())
    ev.metrics["E3"] = {
        "attributes": t.rates(),
        "field_inventory": {"aligned": aligned, "kb_only": sum(v["kb_only"] for v in inventory.values()),
                            "listing_only": sum(v["listing_only"] for v in inventory.values())},
        "mismatches": len(t.failures),
    }


# ---- E2 unit inventory and E4 control-flow soundness -------------------------------------------
def e2_e4(ev: Eval) -> None:
    ce = ev.control
    for b in ev.of("D1", "D2"):
        evaluate_program(ce, b, ev.toolbox, ev.out)
    ev.failures += ce.tally.violations + ce.errors
    ev.metrics["E2"] = e2_metrics(ce)
    ev.metrics["E4"] = e4_metrics(ce)


# ---- E5 data-flow soundness (model-based) -------------------------------------------------------
def e5(ev: Eval) -> None:
    tally = E5Tally()
    for b in ev.of("D1", "D2"):
        check_program(b, ev.toolbox, kb_units(b), "phase0", tally)
    ev.failures += tally.write_violations + tally.read_violations
    ev.metrics["E5"] = e5_metrics(tally)


# ---- E7 baseline: Phase 1's tolerant analyser ------------------------------------------------------
def e7(ev: Eval) -> None:
    res = run_baseline(ev.of("D1", "D2"), ev.toolbox, ev.control, ev.o1, ev.out)
    ev.failures += res.pop("failures")
    ev.phase1_units = res.pop("units")
    ev.metrics["E7"] = {"phase1": res, "table": comparison(ev.metrics, res)}


def comparison(m: dict[str, Any], p1: dict[str, Any]) -> list[dict[str, Any]]:
    """Side-by-side rows: (metric, Phase 0, Phase 1, better is higher)."""
    rows = [
        ("E2 traced units found", m["E2"]["traced_unit_recall"], p1["E2"]["traced_unit_recall"], True),
        ("E2 span start = trace", m["E2"]["span_start_exact"], p1["E2"]["span_start_exact"], True),
        ("E2 Java methods precision", m["E2"]["java_methods"]["precision"], p1["E2"]["java_methods"]["precision"], True),
        ("E2 Java methods recall", m["E2"]["java_methods"]["recall"], p1["E2"]["java_methods"]["recall"], True),
    ]
    for attr in ("signed(probe)", "digits(probe)", "scale(probe)", "offset(probe)", "byte_length(probe)"):
        rows.append((f"E3 {attr}", m["E3"]["attributes"][attr]["rate"], p1["E3"].get(attr, {}).get("rate", 0.0), True))
    rows += [
        ("E4 soundness violations", m["E4"]["soundness_violations"], p1["E4"]["soundness_violations"], False),
        ("E4 static edges exercised", m["E4"]["static_edges_exercised_share"], p1["E4"]["static_edges_exercised_share"],
         True),
        ("E5 write violations", m["E5"]["write_violations"], p1["E5"]["write_violations"], False),
        ("E5 read violations", m["E5"]["read_violations"], p1["E5"]["read_violations"], False),
    ]
    return [{"metric": a, "phase0": b, "phase1": c, "higher_is_better": d} for a, b, c, d in rows]


# ---- E6 gold annotations ----------------------------------------------------------------------------
def e6(ev: Eval, gold_dir: Path | None) -> None:
    gold = {}
    if gold_dir is not None and gold_dir.is_dir():
        gold = load_gold(gold_dir)
    if not gold:
        ev.metrics["E6"] = {"status": "pending: no gold annotations yet (phase0/eval/gold/<initials>.json)"}
        return
    kb_units = {b.program.name: {u["unit_id"]: u for u in b.kb("source/units.json")} for b in ev.of("D1", "D2")}
    p0, f0 = score(kb_units, gold, "phase0")
    p1, f1 = score(ev.phase1_units, gold, "phase1")
    ev.failures += f0
    ev.metrics["E6"] = {"status": "scored", "annotators": sorted(gold), "phase0": p0, "agreement": agreement(gold)}
    if ev.phase1_units:
        ev.failures += f1
        ev.metrics["E6"]["phase1"] = p1
    if "E7" not in ev.metrics:
        return
    for k in ("reads", "writes", "performs"):
        ev.metrics["E7"]["table"].append({"metric": f"E6 {k} F1", "phase0": p0["overall"][k]["f1"],
                                          "phase1": p1["overall"][k]["f1"], "higher_is_better": True})
    ev.metrics["E7"]["table"].append({"metric": "E6 falls_through_to accuracy", "phase0": p0["falls_through_to_accuracy"],
                                      "phase1": p1["falls_through_to_accuracy"], "higher_is_better": True})


# ---- E9 contract and integration ----------------------------------------------------------------
def run_e9(ev: Eval, run_e2e: bool) -> None:
    metrics, failures = e9(ev.built, run_e2e)
    ev.metrics["E9"] = metrics
    ev.failures += failures


# ---- E11 summary grounding (stage G) ---------------------------------------------------------------
def e11(ev: Eval, model: str) -> None:
    generated = accepted = 0
    for b in ev.of("D1"):
        path = b.ws / "kb" / "source" / "summaries.json"
        if not path.exists():
            continue
        s = json.loads(path.read_text("utf-8"))
        generated += s["generated"]
        accepted += s["accepted"]
        ev.failures += [{"metric": "E11", "program": b.program.name, **r} for r in s["rejected"]]
    tokens = sum(b.llm_tokens for b in ev.of("D1"))
    ev.metrics["E11"] = {"model": model, "summaries": generated, "accepted": accepted,
                         "unsupported_entity_share": round((generated - accepted) / max(generated, 1), 4),
                         "llm_tokens_first_build": tokens}


# ---- E10 metamorphic robustness -------------------------------------------------------------------
def run_e10(ev: Eval) -> None:
    metrics, failures = e10(ev.of("D1", "D2"), ev.out, ev.toolbox)
    ev.metrics["E10"] = metrics
    ev.failures += failures


# ---- E8 determinism and cost --------------------------------------------------------------------
def e8(ev: Eval) -> None:
    per: dict[str, Any] = {}
    for ds in sorted({b.program.dataset for b in ev.built}):
        bs = ev.of(ds)
        lines = sum(p["lines_total"] for b in bs for p in b.kb("source/coverage.json")["programs"])
        cold = sum(b.seconds for b in bs)
        stages: dict[str, float] = {}
        for b in bs:
            for k, v in b.timings.items():
                stages[k] = stages.get(k, 0.0) + v
        per[ds] = {
            "deterministic": all(b.kb_version == b.kb_version_again for b in bs),
            "builds": len(bs),
            "lines": lines,
            "seconds_cold": round(cold, 2),
            "seconds_warm": round(sum(b.seconds_again for b in bs), 2),
            "seconds_per_kloc_cold": round(1000 * cold / max(lines, 1), 3),
            "stage_seconds": {k: round(v, 3) for k, v in sorted(stages.items())},
            "llm_tokens": sum(b.llm_tokens for b in bs),
        }
        for b in bs:
            if b.kb_version != b.kb_version_again:
                ev.failures.append({"metric": "E8", "program": b.program.name, "kind": "kb_version differs",
                                    "repro": f"phase0/bin/phase0 build --workspace {b.ws} (twice)"})
    ev.metrics["E8"] = per


def run(work: Path, out: Path, datasets: list[str], carddemo: Path, gold: Path | None = None, baseline: bool = True,
        run_e2e: bool = False, only: str | None = None, summaries: str | None = None) -> Eval:
    """`work` holds the per-program workspaces and caches; `out` receives metrics.json, failures.jsonl."""
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    ev = Eval(work, make_toolbox(work / "cache"))
    programs = [p for p in select(datasets, carddemo) if only is None or p.name == only.upper()]
    ev.timed("build", lambda: ev.built.extend(build_program(p, work / "ws", ev.toolbox, summaries) for p in programs))
    if summaries is not None:
        ev.timed("E11", lambda: e11(ev, summaries))
    ev.timed("E1", lambda: e1(ev))
    ev.timed("E3", lambda: e3(ev))
    ev.timed("E2_E4", lambda: e2_e4(ev))
    ev.timed("E5", lambda: e5(ev))
    if baseline:
        ev.timed("E7", lambda: e7(ev))
    ev.timed("E6", lambda: e6(ev, gold))
    ev.timed("E9", lambda: run_e9(ev, run_e2e))
    ev.timed("E10", lambda: run_e10(ev))
    ev.timed("F", lambda: ev.metrics.update(F_hazards=hazard_counts(ev.built)))
    ev.timed("E8", lambda: e8(ev))
    ev.metrics["eval_seconds"] = ev.seconds
    jsonio.write(out / "metrics.json", ev.metrics)
    with (out / "failures.jsonl").open("w", encoding="utf-8") as fh:
        for f in ev.failures:
            fh.write(json.dumps(f, sort_keys=True, default=str) + "\n")
    return ev
