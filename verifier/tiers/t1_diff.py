"""T1 — program-level differential testing against GnuCOBOL (spec section 6, T1).

PASS means: every non-excluded generated case produced byte-identical stdout, files and return code.
Exclusions (COBOL runtime error, COBOL timeout, flaky COBOL output) are counted and reported.
"""

from __future__ import annotations

import json
import shutil
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from verifier.cobol import analysis
from verifier.cobol.gnucobol import CobolBinary, build_all
from verifier.cobol.trace import case_coverage, combine, greedy_minimise, parse_trace
from verifier.diagnose.classifier import classify
from verifier.diagnose.compare import CompareCtx, Mismatch, compare
from verifier.diagnose.localize import localise, paragraph_of, target_location
from verifier.inputs.bundle import CaseSpec, store_outputs, write_inputs
from verifier.inputs.strategies import Generator, Model, ProgramInputs, shrink_candidates
from verifier.langpacks.base import NotApplicable
from verifier.report.schema import (
    Counterexample,
    Coverage,
    Exclusion,
    FailureSignature,
    FieldValue,
    Scope,
    SourceRef,
    Status,
    TierResult,
    ToolInfo,
)
from verifier.sandbox.batch import CaseRun, run_batch
from verifier.sandbox.docker_runner import Mount

if TYPE_CHECKING:
    from verifier.pipeline import Pipeline, ProgramCtx


@dataclass
class CaseOutcome:
    spec: CaseSpec
    expected: CaseRun | None
    actual: CaseRun | None
    excluded: str | None
    mismatches: list[Mismatch]
    error: str | None = None


# ---------------------------------------------------------------------------------------------
def ensure_cobol_builds(pl: Pipeline) -> dict[str, CobolBinary]:
    if pl.cobol_bins:
        return pl.cobol_bins
    items = [(pc.program.program_id, pc.pre) for pc in pl.active() if not pc.out_of_scope]
    if items:
        pl.cobol_bins = build_all(pl.runner, pl.cfg.cobol, pl.ws_cobol, items, Path(pl.cfg.cache_dir),
                                  str(pl.toolchain.get("gnucobol", "?")))
    return pl.cobol_bins


class SideRunner:
    """Runs batches of cases on both sides for one program."""

    def __init__(self, pl: Pipeline, pc: ProgramCtx, binary: CobolBinary, target_cmd: list[str]) -> None:
        self.pl, self.pc, self.binary, self.target_cmd = pl, pc, binary, target_cmd
        prog = pc.program
        assert pc.channels is not None
        self.ctx = CompareCtx(
            prog,
            {(s.file, s.line): s for s in analysis.display_sites(prog)},
            {f.path: f for f in pc.channels.files if f.path},
            list(pl.cfg.normalisers),
        )
        self.root = pl.req.out / "runs" / prog.program_id

    def run(self, specs: list[CaseSpec], tag: str, repeat: int) -> dict[str, CaseOutcome]:
        pl = self.pl
        inputs = pl.req.out / "inputs" / self.pc.program.program_id / tag
        if inputs.exists():
            shutil.rmtree(inputs)
        by_id: dict[str, CaseSpec] = {}
        for s in specs:
            by_id.setdefault(s.case_id(), s)
        for cid, s in by_id.items():
            write_inputs(s, inputs / cid)
        ids = list(by_id)
        if not ids:
            return {}
        env = dict(pl.cfg.cobol.runtime_env)
        cres = run_batch(pl.runner, inputs_root=inputs, results_root=self.root / tag / "cobol", case_ids=ids,
                         command=self.binary.command(traced=True), limits=pl.cfg.limits,
                         extra_mounts=[self.binary.mount()], env=env, trace=True, repeat=repeat)
        out: dict[str, CaseOutcome] = {}
        keep = []
        for cid in ids:
            exp = cres.runs.get(cid)
            reason = _exclusion(exp)
            out[cid] = CaseOutcome(by_id[cid], exp, None, reason, [])
            if reason is None:
                keep.append(cid)
        if keep:
            mounts = [Mount(pl.ws_target, "/tgt", True)]
            rd = pl.runtime_dir()
            if rd is not None:
                mounts.append(Mount(rd, "/opt/cobolrt", True))
            tres = run_batch(pl.runner, inputs_root=inputs, results_root=self.root / tag / "target", case_ids=keep,
                             command=self.target_cmd, limits=pl.cfg.limits, extra_mounts=mounts,
                             env={"TARGET_ROOT": "/tgt", "COBOLRT": "/opt/cobolrt", "PYTHONPATH": "/tgt",
                                  "PYTHONDONTWRITEBYTECODE": "1"})
            for cid in keep:
                act = tres.runs.get(cid)
                oc = out[cid]
                oc.actual = act
                if act is None or act.runner_error:
                    oc.error = act.runner_error if act else "no target result"
                    continue
                assert oc.expected is not None
                oc.mismatches = compare(oc.expected, act, self.ctx)
        return out


def _exclusion(exp: CaseRun | None) -> str | None:
    if exp is None:
        return "no COBOL result"
    if exp.runner_error:
        return f"runner error: {exp.runner_error}"
    if exp.timed_out:
        return "COBOL timed out"
    if b"libcob: error" in exp.stderr:
        line = next((ln for ln in exp.stderr.decode("latin-1").splitlines() if "libcob: error" in ln), "")
        return f"COBOL runtime error: {line.strip()[:160]}"
    if exp.meta.get("signal"):
        return f"COBOL killed by signal {exp.meta.get('signal')}"
    if exp.flaky:
        return f"nondeterministic COBOL output across two runs ({', '.join(exp.flaky)})"
    return None


# ---------------------------------------------------------------------------------------------
def run_t1(pl: Pipeline, pc: ProgramCtx) -> TierResult:
    start = time.monotonic()
    prog = pc.program
    bins = ensure_cobol_builds(pl)
    binary = bins.get(prog.program_id)
    if binary is None or not binary.ok:
        diag = binary.diagnostics[-600:] if binary else "not built"
        return TierResult.error(f"GnuCOBOL build of {prog.program_id} failed: {diag}", method="differential_testing")
    assert pc.resolved is not None
    cmd = pl.pack.run_command(pl.pack_ctx(), pc.resolved)
    if isinstance(cmd, NotApplicable):
        return TierResult.not_applicable(cmd.reason, method="differential_testing")
    assert pc.channels is not None
    unsupported = [f"{f.select.name} (dynamic file name)" for f in pc.channels.files if f.dynamic and f.is_input]
    if unsupported:
        return TierResult.not_applicable(f"input files with dynamic names cannot be generated: {', '.join(unsupported)}",
                                         method="differential_testing")
    t1 = pl.cfg.t1
    fast = pl.req.mode == "fast"
    pi = ProgramInputs.build(prog, pc.channels.accepts, pc.channels.files, analysis.literal_seeds(prog),
                             bool(pc.nondeterminism))
    eff_seed = pl.effective_seed
    gen = Generator(pi, eff_seed, pl.req.mode, case_cap=t1.fast_case_cap if fast else t1.full_case_cap,
                    random_n=t1.random_fast if fast else t1.random_full, pairwise=t1.pairwise,
                    extra_lines=t1.extra_stdin_lines, fake_time=pl.cfg.fake_time)
    specs = [gen.materialise(m, s) for s, m in gen.generate()]
    side = SideRunner(pl, pc, binary, cmd)
    outcomes = side.run(specs, "t1", repeat=2 if t1.run_cobol_twice else 1)
    # ---- tally -------------------------------------------------------------------------------
    excluded = [Exclusion(case_id=cid, reason=o.excluded) for cid, o in outcomes.items() if o.excluded]
    errors = {cid: o.error for cid, o in outcomes.items() if o.error}
    run_ok = {cid: o for cid, o in outcomes.items() if not o.excluded and not o.error}
    failed = {cid: o for cid, o in run_ok.items() if o.mismatches}
    per_case_cov = {}
    for cid, o in outcomes.items():
        if o.excluded or o.expected is None or not o.expected.trace:
            continue
        per_case_cov[cid] = case_coverage(prog, parse_trace(o.expected.trace))
    cov = combine(prog, list(per_case_cov.values()))
    minimised = greedy_minimise(per_case_cov) if t1.minimise else []
    coverage = Coverage(paragraph=round(cov.paragraph_ratio, 4), statement=round(cov.statement_ratio, 4),
                        uncovered=[p for p in cov.paragraphs_total if p not in cov.paragraphs_hit],
                        covered_paragraphs=sorted(cov.paragraphs_hit), minimised_case_count=len(minimised))
    _write_bundles(pl, prog.program_id, outcomes)
    strategies: dict[str, int] = defaultdict(int)
    for o in outcomes.values():
        strategies[o.spec.strategy.split(":", 1)[0]] += 1
    scope = Scope(
        level="program",
        what=f"stdout bytes, every output file's bytes and the return code of {prog.program_id}",
        inputs=f"{len(outcomes)} generated cases ({dict(sorted(strategies.items()))}), effective seed {eff_seed}, "
               f"mode {pl.req.mode}",
        oracle=f"{pl.toolchain.get('gnucobol', 'GnuCOBOL')} with {' '.join(pc.pre.flags)}",
        tools=[ToolInfo(name="gnucobol", version=str(pl.toolchain.get("gnucobol", "?"))),
               ToolInfo(name=f"{pl.req.lang} runtime", version=str(pl.toolchain.get("java", pl.toolchain.get(pl.req.lang, "?"))))],
        commands=[*binary.commands, " ".join(cmd)],
    )
    n_run = len(run_ok)
    base: dict[str, Any] = {
        "method": "differential_testing", "scope": scope, "cases_run": n_run, "cases_failed": len(failed),
        "cases_excluded": len(excluded), "exclusions": excluded[:50], "coverage": coverage,
        "pass_fraction": round((n_run - len(failed)) / n_run, 4) if n_run else 0.0,
        "details": {"strategies": dict(strategies), "infrastructure_errors": len(errors),
                    "minimised_cases": minimised[:50], "normalisers": pl.cfg.normalisers},
    }
    if failed:
        sigs, cxs = _diagnose(pl, pc, side, gen, failed)
        return TierResult(status=Status.FAIL, failure_signatures=sigs, counterexamples=cxs,
                          duration_s=time.monotonic() - start, **base)
    if errors:
        first = next(iter(errors.values()))
        return TierResult(status=Status.ERROR, reason=f"{len(errors)} target runs failed in the sandbox: {first}",
                          duration_s=time.monotonic() - start, **base)
    if n_run == 0:
        reasons = sorted({e.reason for e in excluded})[:3]
        return TierResult(status=Status.ERROR, reason=f"no usable test cases ({len(excluded)} excluded: {reasons})",
                          duration_s=time.monotonic() - start, **base)
    return TierResult(status=Status.PASS, duration_s=time.monotonic() - start, **base)


def _write_bundles(pl: Pipeline, pid: str, outcomes: dict[str, CaseOutcome]) -> None:
    root = pl.req.out / "cases" / pid
    for cid, o in outcomes.items():
        d = root / cid
        write_inputs(o.spec, d)
        if o.expected is not None:
            store_outputs(o.expected.results_dir, d / "expected")
            (d / "expected" / "meta.json").write_text(json.dumps(
                {**o.expected.meta, "excluded": o.excluded}, indent=1, default=str), "utf-8")
        if o.actual is not None:
            store_outputs(o.actual.results_dir, d / "actual")


# ---------------------------------------------------------------------------------------------
def _diagnose(pl: Pipeline, pc: ProgramCtx, side: SideRunner, gen: Generator,
              failed: dict[str, CaseOutcome]) -> tuple[list[FailureSignature], list[Counterexample]]:
    groups: dict[str, list[tuple[str, Mismatch]]] = defaultdict(list)
    for cid, o in failed.items():
        for m in o.mismatches:
            groups[m.signature].append((cid, m))
    ordered = sorted(groups.items(), key=lambda kv: (kv[1][0][1].severity, -len(kv[1]), kv[0]))
    sigs = [FailureSignature(signature=s, kind=v[0][1].kind, location=v[0][1].location, count=len(v),
                             severity=v[0][1].severity, example_case=v[0][0]) for s, v in ordered]
    top = ordered[: pl.cfg.t1.max_signatures]
    rounds = pl.cfg.t1.shrink_rounds_fast if pl.req.mode == "fast" else pl.cfg.t1.shrink_rounds_full
    shrunk = _shrink(pl, side, gen, [(s, failed[v[0][0]]) for s, v in top], rounds)
    cxs: list[Counterexample] = []
    for k, (sig, members) in enumerate(top):
        oc, steps = shrunk.get(sig, (failed[members[0][0]], 0))
        m = next((mm for mm in oc.mismatches if mm.signature == sig), members[0][1])
        cx = _counterexample(pl, pc, oc, m, steps, k)
        cxs.append(cx)
        sigs[k].counterexample_id = cx.id
    return sigs, cxs


def _shrink(pl: Pipeline, side: SideRunner, gen: Generator, targets: list[tuple[str, CaseOutcome]],
            rounds: int) -> dict[str, tuple[CaseOutcome, int]]:
    """Delta debugging on the input model, batched across signatures; keeps the signature."""
    state: dict[str, tuple[CaseOutcome, int]] = {sig: (oc, 0) for sig, oc in targets}
    active = {sig for sig, oc in targets if oc.spec.model}
    n_sites = len(gen.pi.stdin)
    for r in range(rounds):
        if not active:
            break
        batch: list[CaseSpec] = []
        owners: list[tuple[str, CaseSpec]] = []
        for sig in sorted(active):
            oc, _steps = state[sig]
            assert oc.spec.model is not None
            for label, model in shrink_candidates(oc.spec.model, n_sites)[:12]:
                spec = gen.materialise(model, f"shrunk:{label}")
                batch.append(spec)
                owners.append((sig, spec))
        if not batch:
            break
        results = side.run(batch, f"shrink{r}", repeat=1)
        progressed = set()
        for sig, spec in owners:
            if sig in progressed:
                continue
            res = results.get(spec.case_id())
            if res is None or res.excluded or res.error:
                continue
            if any(m.signature == sig for m in res.mismatches):
                state[sig] = (res, state[sig][1] + 1)
                progressed.add(sig)
        active &= progressed
    if any(steps for _oc, steps in state.values()):
        _write_bundles(pl, side.pc.program.program_id, {oc.spec.case_id(): oc for oc, steps in state.values() if steps})
    return state


def _input_fields(model: Model | None, pc: ProgramCtx) -> list[FieldValue]:
    out: list[FieldValue] = []
    if not model:
        return out
    for i, e in enumerate(model.get("stdin", [])):
        item = pc.program.resolve(e["field"])
        out.append(FieldValue(field=e["field"], value=e["text"], pic=item.pic_text() if item else None,
                              location=f"stdin line {i + 1} (ACCEPT)"))
    for path, spec in model.get("files", {}).items():
        recs = spec.get("records", [])
        out.append(FieldValue(field=f"{path}", value=f"{len(recs)} record(s)", location=f"file {path}"))
        for k, rec in enumerate(recs[:3]):
            for name, v in rec.items():
                item = pc.program.resolve(name)
                out.append(FieldValue(field=name, value=v, pic=item.pic_text() if item else None,
                                      location=f"file {path} record {k + 1}"))
    return out


def _counterexample(pl: Pipeline, pc: ProgramCtx, oc: CaseOutcome, m: Mismatch, steps: int, k: int) -> Counterexample:
    prog = pc.program
    cid = oc.spec.case_id()
    events = parse_trace(oc.expected.trace) if oc.expected and oc.expected.trace else []
    field = m.items[0].name if m.items else None
    refs: list[SourceRef] = []
    size_err = False
    if field:
        refs, size_err = localise(prog, field, events, pl.ws_cobol)
    if m.site is not None:
        refs = [*refs, SourceRef(file=m.site.file, line=m.site.line, text="(the DISPLAY that printed it)")]
    para = paragraph_of(prog, refs[0].file, refs[0].line) if refs else None
    fmap = None
    if field and pc.resolved is not None:
        item = prog.resolve(field)
        mapped = pc.resolved.fields.get(field, {})
        fmap = {"cobol": field, "pic": item.pic_text() if item else None,
                "declared_from_pic": item.declared_type() if item else None,
                "target": mapped.get("target"), "target_type": mapped.get("target_type")}
    case_dir = pl.req.out / "cases" / prog.program_id / cid
    exp, act = oc.expected, oc.actual
    return Counterexample(
        id=f"cx_{prog.program_id}_{k}_{cid[5:13]}", source_tier="T1", signature=m.signature, case_id=cid,
        case_dir=str(case_dir.relative_to(pl.req.out)),
        inputs={"stdin_lines": [e["text"] for e in (oc.spec.model or {}).get("stdin", [])]
                if oc.spec.model else oc.spec.stdin.decode("latin-1").splitlines()[:20],
                "files": [f.name for f in oc.spec.files_in], "args": oc.spec.args, "env": oc.spec.env,
                "strategy": oc.spec.strategy},
        input_fields=_input_fields(oc.spec.model, pc),
        expected={"stdout": _head(exp.stdout if exp else b""), "return_code": exp.return_code if exp else None},
        actual={"stdout": _head(act.stdout if act else b""), "return_code": act.return_code if act else None,
                "stderr": _head(act.stderr if act else b"", 400)},
        diffs=m.diffs[:8], shrunk=steps > 0, shrink_steps=steps,
        classification=classify(m, size_err), cobol_statements=refs, field_mapping=fmap,
        target_location=target_location(pc.resolved, field or "", para),
        repro=f"verify repro --case {case_dir} --report {pl.req.out / 'report.json'}",
        confirmed_concretely=True,
    )


def _head(b: bytes, n: int = 600) -> str:
    s = b.decode("latin-1")
    return s if len(s) <= n else s[:n] + "…"


# ---------------------------------------------------------------------------------------------
def repro_case(case_dir: Path, report_path: Path) -> int:
    """Re-run one bundle on both sides using the run's workspace; print the comparison."""
    from verifier.config import VerifierConfig
    from verifier.inputs.bundle import read_bundle
    from verifier.pipeline import Pipeline, VerifierError, VerifyRequest
    from verifier.report.schema import Report

    rep = Report.load(str(report_path))
    out = report_path.resolve().parent
    spec = read_bundle(case_dir)
    req = VerifyRequest(cobol=Path(rep.run.cobol), target=Path(rep.run.target), lang=rep.run.lang, out=out,
                        manifest=Path(rep.run.manifest) if rep.run.manifest else None, mode=rep.run.mode)
    pl = Pipeline(req, VerifierConfig())
    pl.runner.check_available()
    pl.toolchain = pl.runner.toolchain_versions()
    # reuse the existing workspace (already built) instead of copying the inputs again
    if not (out / "workspace" / "target").exists():
        raise VerifierError(f"no workspace under {out}; re-run verify first")
    pl.cobol_frontend()
    pl.target_index()
    pc = next((p for p in pl.programs if p.program.program_id == spec.program), None)
    if pc is None or pc.resolved is None:
        raise VerifierError(f"program {spec.program} not found in the report's workspace")
    binary = ensure_cobol_builds(pl).get(pc.program.program_id)
    cmd = pl.pack.run_command(pl.pack_ctx(), pc.resolved)
    if binary is None or isinstance(cmd, NotApplicable):
        raise VerifierError("cannot rebuild/run this program")
    res = SideRunner(pl, pc, binary, cmd).run([spec], "repro", repeat=1)
    oc = next(iter(res.values()))
    if oc.excluded:
        print(f"case excluded: {oc.excluded}")
        return 2
    if not oc.mismatches:
        print("no difference: both sides agree on this case")
        return 0
    for m in oc.mismatches:
        print(f"{m.signature} at {m.location}")
        for d in m.diffs:
            print(f"  {d.field or ''} expected={d.expected!r} actual={d.actual!r}")
    return 1
