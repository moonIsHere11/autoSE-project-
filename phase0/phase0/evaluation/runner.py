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
from phase0.evaluation.o1 import CompileJob, probe_items, probe_source, run_o1
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
    ce = ControlEval()
    for b in ev.of("D1", "D2"):
        evaluate_program(ce, b, ev.toolbox, ev.out)
    ev.failures += ce.tally.violations + ce.errors
    ev.metrics["E2"] = e2_metrics(ce)
    ev.metrics["E4"] = e4_metrics(ce)


# ---- E8 determinism and cost --------------------------------------------------------------------
def e8(ev: Eval) -> None:
    per: dict[str, Any] = {}
    for ds in sorted({b.program.dataset for b in ev.built}):
        bs = ev.of(ds)
        lines = sum(b.lines for b in bs)
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
            "llm_tokens": 0,
        }
        for b in bs:
            if b.kb_version != b.kb_version_again:
                ev.failures.append({"metric": "E8", "program": b.program.name, "kind": "kb_version differs",
                                    "repro": f"phase0/bin/phase0 build --workspace {b.ws} (twice)"})
    ev.metrics["E8"] = per


def run(out: Path, datasets: list[str], carddemo: Path) -> Eval:
    out.mkdir(parents=True, exist_ok=True)
    ev = Eval(out, make_toolbox(out / "cache"))
    programs = select(datasets, carddemo)
    ev.timed("build", lambda: ev.built.extend(build_program(p, out / "ws", ev.toolbox) for p in programs))
    ev.timed("E1", lambda: e1(ev))
    ev.timed("E3", lambda: e3(ev))
    ev.timed("E2_E4", lambda: e2_e4(ev))
    ev.timed("E8", lambda: e8(ev))
    ev.metrics["eval_seconds"] = ev.seconds
    jsonio.write(out / "metrics.json", ev.metrics)
    with (out / "failures.jsonl").open("w", encoding="utf-8") as fh:
        for f in ev.failures:
            fh.write(json.dumps(f, sort_keys=True, default=str) + "\n")
    return ev
