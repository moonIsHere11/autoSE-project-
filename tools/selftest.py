"""`make selftest`: measure the verifier on the seed corpus (spec section 9).

    python -m tools.selftest --out out/selftest --results docs/RESULTS.md
           [--lang java[,python,go]] [--programs NAME,...] [--mutants N] [--mode fast|full]
           [--tiers 0,1,2,3] [--seed S] [--gated]

For every corpus program with a translation in the language:
1. **False positives:** run the verifier on the correct translation. Any FAIL is a verifier bug
   (or a wrong "correct" translation); the spec requires zero.
2. **Planted bugs:** sample N COBOL-semantic mutants (verifier.mutation; stratified over the ten
   bug categories), apply each to a copy of the translation and run the verifier. A mutant that does
   not build is *stillborn* and excluded from the denominators. By default tiers run **ungated**
   (`VerifierConfig.gating = False`) so each tier's own catch rate is measured; "first catching tier"
   is what a gated run would report.
3. Report per tier and per category: caught / survived, mutants accepted despite the bug (the
   dangerous case), time per tier, and T2b/T3 eligibility. Survivors are listed for manual review
   (some mutants are semantically equivalent and can never be caught).

Writes `<out>/results.json` and replaces the generated block of `--results` (between
`<!-- selftest:begin -->` and `<!-- selftest:end -->`).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from verifier.api import verify
from verifier.config import VerifierConfig
from verifier.mutation import CATEGORIES, Mutant, apply_mutant, find_mutants, sample_mutants
from verifier.report.schema import Report, Status

REPO = Path(__file__).resolve().parents[1]
TIERS = ("T0", "T1", "T2", "T3")
BEGIN, END = "<!-- selftest:begin -->", "<!-- selftest:end -->"


@dataclass
class ProgramEntry:
    name: str
    cobol: Path
    target: Path
    manifest: Path | None


@dataclass
class RunSummary:
    statuses: dict[str, str]  # tier -> worst status across units (FAIL > ERROR > TIMEOUT > PASS > NA > SKIPPED)
    sub_statuses: dict[str, str]
    accepted_units: int
    units: int
    levels: dict[str, int]
    timings: dict[str, float]
    duration_s: float
    errors: list[str]
    fail_reasons: list[str] = field(default_factory=list)
    t2b_eligible: int = 0
    t3_eligible: int = 0


_RANK = {Status.FAIL: 0, Status.ERROR: 1, Status.TIMEOUT: 2, Status.PASS: 3, Status.NOT_APPLICABLE: 4,
         Status.SKIPPED: 5}


def discover(lang: str, only: list[str] | None) -> list[ProgramEntry]:
    out = []
    for d in sorted((REPO / "corpus").iterdir()):
        if not d.is_dir() or not (d / "cobol").is_dir() or not (d / lang).is_dir():
            continue
        if only and d.name not in only:
            continue
        man = d / f"manifest.{lang}.json"
        out.append(ProgramEntry(d.name, d / "cobol", d / lang, man if man.exists() else None))
    return out


def summarise(rep: Report, duration: float) -> RunSummary:
    worst: dict[str, Status] = {}
    sub_worst: dict[str, Status] = {}
    fail_reasons: list[str] = []
    t2b_el = t3_el = 0
    for u in rep.units:
        for k in TIERS:
            t = u.tiers.get(k)
            if t is None:
                continue
            if k not in worst or _RANK[t.status] < _RANK[worst[k]]:
                worst[k] = t.status
            if t.status == Status.FAIL:
                sig = t.failure_signatures[0].signature if t.failure_signatures else (t.reason or "")
                fail_reasons.append(f"{u.id} {k}: {sig}")
            for sk, st in t.sub.items():
                if sk not in sub_worst or _RANK[st.status] < _RANK[sub_worst[sk]]:
                    sub_worst[sk] = st.status
        t2 = u.tiers.get("T2")
        t2b = t2.sub.get("T2b") if t2 is not None else None
        if t2b is not None and t2b.status not in (Status.NOT_APPLICABLE, Status.SKIPPED):
            t2b_el += 1
        t3 = u.tiers.get("T3")
        if t3 is not None and t3.status not in (Status.NOT_APPLICABLE, Status.SKIPPED):
            t3_el += 1
    return RunSummary(
        statuses={k: v.value for k, v in worst.items()}, sub_statuses={k: v.value for k, v in sub_worst.items()},
        accepted_units=rep.summary.accepted, units=rep.summary.units,
        levels=dict(rep.summary.level_histogram), timings=dict(rep.summary.tier_timings_s),
        duration_s=round(duration, 2), errors=list(rep.errors), fail_reasons=sorted(set(fail_reasons))[:10],
        t2b_eligible=t2b_el, t3_eligible=t3_el,
    )


def run_one(entry: ProgramEntry, target: Path, out: Path, lang: str, args: argparse.Namespace,
            cfg: VerifierConfig) -> RunSummary:
    if out.exists():
        shutil.rmtree(out)
    start = time.monotonic()
    rep = verify(entry.cobol, target, lang, out, manifest=entry.manifest, mode=args.mode, tiers=args.tiers,
                 seed=args.seed, config=cfg)
    return summarise(rep, time.monotonic() - start)


def stillborn(s: RunSummary) -> bool:
    return s.statuses.get("T0") in ("FAIL", "ERROR") and s.sub_statuses.get("T0a") in ("FAIL", "ERROR", "TIMEOUT")


def caught_by(s: RunSummary) -> list[str]:
    tiers = [k for k in TIERS if s.statuses.get(k) == "FAIL"]
    for sk in ("T2a", "T2b"):
        if s.sub_statuses.get(sk) == "FAIL":
            tiers.append(sk)
    return tiers


# ---------------------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="selftest")
    ap.add_argument("--out", type=Path, default=REPO / "out" / "selftest")
    ap.add_argument("--results", type=Path, default=REPO / "docs" / "RESULTS.md")
    ap.add_argument("--lang", default="java")
    ap.add_argument("--programs", type=lambda s: [x for x in s.split(",") if x])
    ap.add_argument("--mutants", type=int, default=10, help="mutants sampled per program")
    ap.add_argument("--mode", choices=["fast", "full"], default="fast")
    ap.add_argument("--tiers", type=lambda s: [int(x) for x in s.split(",")], default=None)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--gated", action="store_true", help="keep normal gating (per-tier rates then undercount)")
    ap.add_argument("--no-write", action="store_true", help="do not touch the results markdown")
    args = ap.parse_args(argv)
    cfg = VerifierConfig(gating=args.gated)
    results: dict[str, Any] = {"config": {"mode": args.mode, "tiers": args.tiers, "seed": args.seed,
                                          "mutants_per_program": args.mutants, "gated": args.gated},
                               "languages": {}}
    t_start = time.monotonic()
    for lang in args.lang.split(","):
        progs = discover(lang, args.programs)
        lang_res: dict[str, Any] = {"programs": {}}
        for entry in progs:
            print(f"[{lang}] {entry.name}: correct translation", flush=True)
            base = run_one(entry, entry.target, args.out / lang / entry.name / "correct", lang, args, cfg)
            fp = [f"{k}={v}" for k, v in base.statuses.items() if v == "FAIL"]
            print(f"    statuses={base.statuses} accepted={base.accepted_units}/{base.units} "
                  f"{'FALSE POSITIVE ' + str(base.fail_reasons) if fp else ''}", flush=True)
            muts = sample_mutants(find_mutants(entry.target, lang), args.mutants, args.seed)
            mres = []
            for i, m in enumerate(muts):
                work = args.out / lang / entry.name / "mutants" / f"m{i:02d}"
                tgt = work / "target"
                if work.exists():
                    shutil.rmtree(work)
                shutil.copytree(entry.target, tgt, ignore=shutil.ignore_patterns(".verifier-build", "*.class"))
                apply_mutant(tgt, m)
                s = run_one(entry, tgt, work / "out", lang, args, cfg)
                status = "stillborn" if stillborn(s) else ("caught" if caught_by(s) else "survived")
                rec = {"mutant": m.to_dict(), "status": status, "caught_by": caught_by(s),
                       "accepted_units": s.accepted_units, "units": s.units, "summary": asdict(s)}
                mres.append(rec)
                print(f"    m{i:02d} {m.category:12s} {m.operator:22s} line {m.line:4d}: {status} "
                      f"{','.join(rec['caught_by'])}", flush=True)
            lang_res["programs"][entry.name] = {"correct": asdict(base), "false_positive": bool(fp),
                                                "false_positive_detail": base.fail_reasons, "mutants": mres}
        results["languages"][lang] = lang_res
    results["duration_s"] = round(time.monotonic() - t_start, 1)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(json.dumps(results, indent=1, default=str), "utf-8")
    md = render(results)
    print(md)
    if not args.no_write:
        write_results(args.results, md)
    any_fp = any(p["false_positive"] for lr in results["languages"].values() for p in lr["programs"].values())
    return 1 if any_fp else 0


# ---------------------------------------------------------------------------------------------
def _pct(a: int, b: int) -> str:
    return f"{100.0 * a / b:.0f}% ({a}/{b})" if b else "n/a"


def render(results: dict[str, Any]) -> str:
    cfg = results["config"]
    lines = [f"_Generated by `make selftest` (mode `{cfg['mode']}`, tiers {cfg['tiers'] or 'default'}, seed "
             f"{cfg['seed']}, {cfg['mutants_per_program']} mutants/program, "
             f"{'gated' if cfg['gated'] else 'ungated: every tier runs on every mutant'}); "
             f"total {results['duration_s']} s._", ""]
    for lang, lr in results["languages"].items():
        progs = lr["programs"]
        lines += [f"### {lang}", ""]
        # correct translations
        lines += ["**Correct translations (false positives must be 0):**", "",
                  "| program | T0 | T1 | T2 (T2a / T2b) | T3 | accepted units | levels | time (s) |",
                  "|---|---|---|---|---|---|---|---|"]
        n_fp = 0
        tier_time: dict[str, list[float]] = defaultdict(list)
        units = el_t2b = el_t3 = 0
        for name, p in progs.items():
            c = p["correct"]
            st, sub = c["statuses"], c["sub_statuses"]
            n_fp += int(p["false_positive"])
            units += c["units"]
            el_t2b += c["t2b_eligible"]
            el_t3 += c["t3_eligible"]
            for k, v in c["timings"].items():
                tier_time[k].append(v)
            lv = ", ".join(f"L{k}:{v}" for k, v in sorted(c["levels"].items()) if v)
            lines.append(f"| {name} | {st.get('T0', '-')} | {st.get('T1', '-')} | {st.get('T2', '-')} "
                         f"({sub.get('T2a', '-')} / {sub.get('T2b', '-')}) | {st.get('T3', '-')} | "
                         f"{c['accepted_units']}/{c['units']} | {lv} | {c['duration_s']} |")
        lines += ["", f"**False positives: {n_fp}** (programs with any FAIL on the correct translation).", ""]
        # mutants
        all_m = [m for p in progs.values() for m in p["mutants"]]
        live = [m for m in all_m if m["status"] != "stillborn"]
        caught = [m for m in live if m["status"] == "caught"]
        accepted_bad = [m for m in live if m["status"] == "survived" and m["accepted_units"] > 0]
        lines += [f"**Planted bugs:** {len(all_m)} mutants, {len(all_m) - len(live)} stillborn (do not compile; "
                  f"excluded), {len(live)} live. **Caught overall: {_pct(len(caught), len(live))}.** "
                  f"Survivors accepted by the verifier (a wrong ACCEPT): {len(accepted_bad)}.", ""]
        lines += ["| tier | catches (any) | first catching tier (as a gated run reports) |", "|---|---|---|"]
        first: Counter[str] = Counter()
        anyc: Counter[str] = Counter()
        for m in caught:
            order = [t for t in ("T0", "T1", "T2a", "T2b", "T2", "T3") if t in m["caught_by"]]
            first[order[0]] += 1
            for t in set(m["caught_by"]):
                anyc[t] += 1
        for t in ("T0", "T1", "T2", "T2a", "T2b", "T3"):
            lines.append(f"| {t} | {_pct(anyc[t], len(live))} | {first[t]} |")
        lines += ["", "| category | live | caught | rate |", "|---|---|---|---|"]
        for cat in CATEGORIES:
            lv = [m for m in live if m["mutant"]["category"] == cat]
            cc = [m for m in lv if m["status"] == "caught"]
            lines.append(f"| {cat} ({CATEGORIES[cat]}) | {len(lv)} | {len(cc)} | {_pct(len(cc), len(lv))} |")
        lines += ["", "Time per tier (mean seconds per program, correct translations): "
                  + ", ".join(f"{k} {sum(v) / len(v):.1f}" for k, v in sorted(tier_time.items())) + ".", "",
                  f"Units eligible for T2b: {_pct(el_t2b, units)}; for T3: {_pct(el_t3, units)} "
                  "(eligible = status other than NOT_APPLICABLE/SKIPPED on the correct translation).", ""]
        surv = [m for m in live if m["status"] == "survived"]
        if surv:
            lines += ["<details><summary>Surviving mutants (review: some are semantically equivalent)</summary>", ""]
            for m in surv:
                mm = Mutant.from_dict(m["mutant"])
                lines.append(f"- `{mm.file}:{mm.line}` {mm.operator}: {mm.description}"
                             f"{' — **accepted**' if m['accepted_units'] else ''}")
            lines += ["", "</details>", ""]
    return "\n".join(lines)


def write_results(path: Path, block: str) -> None:
    text = path.read_text("utf-8") if path.exists() else "# Results\n\n" + BEGIN + "\n" + END + "\n"
    if BEGIN not in text:
        text = text.rstrip("\n") + "\n\n## Self-test (generated)\n\n" + BEGIN + "\n" + END + "\n"
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    path.write_text(head + BEGIN + "\n" + block + "\n" + END + tail, "utf-8")


if __name__ == "__main__":
    sys.exit(main())
