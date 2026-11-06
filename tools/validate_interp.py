"""Validation gate for the COBOL semantic model: the IR interpreter must reproduce GnuCOBOL.

    python -m tools.validate_interp DIR [DIR ...] [--seed N] [--mode fast|full] [--show 5]
    python -m tools.validate_interp --fuzz 20 [--seed N]     # random programs (tests/semantics/fuzz.py)

For every COBOL program in DIR (a directory of COBOL sources, e.g. corpus/<name>/cobol), generate
the T1 cases with the verifier's own generator (verifier.inputs.strategies), run them under the
pinned GnuCOBOL in one batched sandbox container, run the interpreter in-process on the same
bytes, and compare stdout, every file of the working directory and the return code byte for byte.

Library use (the pipeline's validation gate): `validate_program(...) -> list[ValidationResult]`.
A `ValidationResult.passed` is True only when the program is interpretable, at least one case was
compared, every compared case agreed, and the interpreter refused no case.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from verifier.cobol import analysis
from verifier.cobol.gnucobol import build_all
from verifier.cobol.interp import CobolRuntimeError, InterpUnsupported, run_program
from verifier.cobol.ir import IrProgram, lower_program
from verifier.cobol.lexer import tokenize
from verifier.cobol.parser import parse_source
from verifier.cobol.preprocess import find_cobol_sources, preprocess_all
from verifier.cobol.syntax import Program
from verifier.config import VerifierConfig
from verifier.inputs.bundle import CaseSpec, write_inputs
from verifier.inputs.strategies import Generator, ProgramInputs
from verifier.sandbox.batch import CaseRun, run_batch
from verifier.sandbox.docker_runner import DockerRunner
from verifier.sandbox.limits import SandboxLimits


@dataclass
class CaseMismatch:
    case_id: str
    strategy: str
    what: str  # stdout | return_code | file:<name> | runtime_error
    expected: bytes | str | int | None
    actual: bytes | str | int | None
    stdin: bytes = b""


@dataclass
class ValidationResult:
    program_id: str
    interpretable: bool
    reason: str | None = None
    cases: int = 0
    excluded: int = 0
    compared: int = 0
    agreed: int = 0
    mismatches: list[CaseMismatch] = field(default_factory=list)
    refused: list[tuple[str, str]] = field(default_factory=list)  # (case id, interpreter refusal)

    @property
    def passed(self) -> bool:
        return self.interpretable and self.compared > 0 and self.agreed == self.compared and not self.refused

    @property
    def agreement(self) -> float:
        return self.agreed / self.compared if self.compared else 0.0

    def summary(self) -> str:
        if not self.interpretable:
            return f"{self.program_id}: not interpretable ({self.reason})"
        return (f"{self.program_id}: {self.cases} cases, {self.excluded} excluded (COBOL runtime error/timeout), "
                f"{self.compared} compared, {self.agreed} agree ({100 * self.agreement:.1f}%), "
                f"{len(self.mismatches)} mismatching, {len(self.refused)} refused by the interpreter"
                f" -> {'PASS' if self.passed else 'FAIL'}")


def _excluded(run: CaseRun | None) -> str | None:
    if run is None:
        return "no COBOL result"
    if run.runner_error:
        return run.runner_error
    if run.timed_out:
        return "COBOL timed out"
    if b"libcob: error" in run.stderr:
        return "COBOL runtime error"
    return None


def compare_case(ir: IrProgram, spec: CaseSpec, exp: CaseRun) -> tuple[list[CaseMismatch], str | None]:
    """Run the interpreter on one case and compare with GnuCOBOL's result."""
    cid = spec.case_id()
    files = {f.name: f.data for f in spec.files_in}
    try:
        res = run_program(ir, spec.stdin, files, spec.args, spec.env)
    except InterpUnsupported as exc:
        return [], str(exc)
    out: list[CaseMismatch] = []

    def mm(what: str, e: bytes | str | int | None, a: bytes | str | int | None) -> None:
        out.append(CaseMismatch(cid, spec.strategy, what, e, a, spec.stdin))

    if res.runtime_error is not None:
        mm("runtime_error", None, res.runtime_error)
        return out, None
    if res.stdout != exp.stdout:
        mm("stdout", exp.stdout, res.stdout)
    if res.return_code != exp.return_code:
        mm("return_code", exp.return_code, res.return_code)
    for name in sorted(set(exp.files) | set(res.files)):
        if exp.files.get(name) != res.files.get(name):
            mm(f"file:{name}", exp.files.get(name), res.files.get(name))
    return out, None


def load_programs(cobol_dir: Path, cfg: VerifierConfig, runner: DockerRunner) -> list[tuple[Program, object]]:
    srcs = find_cobol_sources(cobol_dir, cfg.cobol)
    pre = preprocess_all(runner, cfg.cobol, cobol_dir, srcs, Path(cfg.cache_dir))
    out: list[tuple[Program, object]] = []
    for rel in srcs:
        if not pre[rel].ok:
            raise RuntimeError(f"cobc -E failed for {rel}: {pre[rel].diagnostics[:400]}")
        for p in parse_source(tokenize(pre[rel].lines), rel):
            out.append((p, pre[rel]))
    return out


def validate_program(cobol_dir: Path, *, cfg: VerifierConfig | None = None, runner: DockerRunner | None = None,
                     seed: int = 0, mode: str = "full", specs: dict[str, list[CaseSpec]] | None = None,
                     work_dir: Path | None = None) -> list[ValidationResult]:
    """Validate the interpreter on every program in `cobol_dir` (one result per PROGRAM-ID).

    `specs` (program id -> cases) replaces the generated T1 cases when given."""
    cfg = cfg or VerifierConfig()
    runner = runner or DockerRunner(cfg.image, SandboxLimits.from_config(cfg.limits))
    runner.check_available()
    progs = load_programs(cobol_dir, cfg, runner)
    results: list[ValidationResult] = []
    todo: list[tuple[Program, IrProgram, list[CaseSpec], object]] = []
    for prog, pre in progs:
        ir = lower_program(prog)
        reason = ir.interpretability()
        if reason is not None:
            results.append(ValidationResult(prog.program_id, False, reason))
            continue
        if specs is not None:
            cases = specs.get(prog.program_id, [])
        else:
            ch = analysis.channels(prog)
            pi = ProgramInputs.build(prog, ch.accepts, ch.files, analysis.literal_seeds(prog),
                                     bool(analysis.nondeterminism(prog)))
            t1 = cfg.t1
            fast = mode == "fast"
            gen = Generator(pi, seed, mode, case_cap=t1.fast_case_cap if fast else t1.full_case_cap,
                            random_n=t1.random_fast if fast else t1.random_full, pairwise=t1.pairwise,
                            extra_lines=t1.extra_stdin_lines, fake_time=cfg.fake_time)
            cases = [gen.materialise(m, s) for s, m in gen.generate()]
        todo.append((prog, ir, cases, pre))
    if not todo:
        return results
    version = str(runner.toolchain_versions().get("gnucobol", "?"))
    bins = build_all(runner, cfg.cobol, cobol_dir, [(p.program_id, pre) for p, _ir, _c, pre in todo],  # type: ignore[misc]
                     Path(cfg.cache_dir), version)
    with tempfile.TemporaryDirectory(prefix="cv-validate-") as tmp_s:
        root = work_dir or Path(tmp_s)
        for prog, ir, cases, _pre in todo:
            pid = prog.program_id
            r = ValidationResult(pid, True)
            results.append(r)
            b = bins.get(pid)
            if b is None or not b.ok:
                r.interpretable = False
                r.reason = f"GnuCOBOL build failed: {b.diagnostics[-300:] if b else 'not built'}"
                continue
            by_id: dict[str, CaseSpec] = {}
            for s in cases:
                by_id.setdefault(s.case_id(), s)
            inputs = root / "inputs" / pid
            for cid, s in by_id.items():
                write_inputs(s, inputs / cid)
            ids = list(by_id)
            r.cases = len(ids)
            if not ids:
                continue
            batch = run_batch(runner, inputs_root=inputs, results_root=root / "results" / pid, case_ids=ids,
                              command=b.command(), limits=cfg.limits, extra_mounts=[b.mount()],
                              env=dict(cfg.cobol.runtime_env))
            for cid in ids:
                exp = batch.runs.get(cid)
                if _excluded(exp) is not None:
                    r.excluded += 1
                    continue
                assert exp is not None
                mms, refusal = compare_case(ir, by_id[cid], exp)
                if refusal is not None:
                    r.refused.append((cid, refusal))
                    continue
                r.compared += 1
                if mms:
                    r.mismatches.extend(mms)
                else:
                    r.agreed += 1
    return results


def _show(v: bytes | str | int | None, n: int = 700) -> str:
    if isinstance(v, bytes):
        s = v.decode("latin-1")
        return (s if len(s) <= n else s[:n] + "...").replace("\n", "\\n\n")
    return str(v)


def print_report(results: list[ValidationResult], show: int = 3) -> None:
    for r in results:
        print(r.summary())
        shown = 0
        seen: set[str] = set()
        for m in r.mismatches:
            if m.case_id in seen:
                continue
            seen.add(m.case_id)
            if shown >= show:
                break
            shown += 1
            print(f"  -- {m.case_id} [{m.strategy}] {m.what}; stdin={m.stdin[:200]!r}")
            if isinstance(m.expected, bytes) and isinstance(m.actual, bytes):
                el, al = m.expected.split(b"\n"), m.actual.split(b"\n")
                k = next((i for i in range(max(len(el), len(al)))
                          if (el[i] if i < len(el) else None) != (al[i] if i < len(al) else None)), 0)
                print(f"     first difference at line {k + 1}:")
                for i in range(max(0, k - 2), k + 1):
                    print(f"       expected {el[i] if i < len(el) else None!r}")
                print(f"       actual   {al[k] if k < len(al) else None!r}")
            else:
                print(f"     expected (GnuCOBOL): {_show(m.expected)}\n     actual (interpreter): {_show(m.actual)}")
        reasons: dict[str, int] = {}
        for _cid, why in r.refused:
            reasons[why] = reasons.get(why, 0) + 1
        for why, n in sorted(reasons.items(), key=lambda kv: -kv[1])[:5]:
            print(f"  refused {n}x: {why}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="*", type=Path)
    ap.add_argument("--fuzz", type=int, default=0, help="also validate N random programs")
    ap.add_argument("--stmts", type=int, default=120)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--mode", choices=["fast", "full"], default="full")
    ap.add_argument("--show", type=int, default=3)
    a = ap.parse_args(argv)
    cfg = VerifierConfig()
    runner = DockerRunner(cfg.image, SandboxLimits.from_config(cfg.limits))
    ok = True
    for d in a.dirs:
        try:
            results = validate_program(d, cfg=cfg, runner=runner, seed=a.seed, mode=a.mode)
        except (RuntimeError, CobolRuntimeError) as exc:
            print(f"{d}: ERROR {exc}")
            ok = False
            continue
        print(f"== {d}")
        print_report(results, a.show)
        ok = ok and all(r.passed or not r.interpretable for r in results)
    if a.fuzz:
        results = fuzz(a.fuzz, a.seed, a.stmts, cfg=cfg, runner=runner)
        print(f"== fuzz: {a.fuzz} arithmetic + {a.fuzz} ACCEPT programs, seed {a.seed}")
        print_report(results, a.show)
        ok = ok and all(r.passed for r in results)
    return 0 if ok else 1


def fuzz(n: int, seed: int, n_stmts: int = 120, *, cfg: VerifierConfig | None = None,
         runner: DockerRunner | None = None, keep: Path | None = None) -> list[ValidationResult]:
    """Validate the interpreter on `n` random arithmetic programs and `n` random ACCEPT programs."""
    from tests.semantics.fuzz import accept_program, accept_stdin, random_program

    with tempfile.TemporaryDirectory(prefix="cv-fuzz-") as tmp_s:
        d = keep or Path(tmp_s)
        d.mkdir(parents=True, exist_ok=True)
        specs: dict[str, list[CaseSpec]] = {}
        for k in range(n):
            s = seed * 1000 + k
            pid = f"FZ{s:06d}"
            (d / f"{pid}.cbl").write_text(random_program(s, n_stmts, pid), "latin-1")
            specs[pid] = [CaseSpec(program=pid, strategy="fuzz")]
            pid = f"FA{s:06d}"
            src, items = accept_program(s, pid=pid)
            (d / f"{pid}.cbl").write_text(src, "latin-1")
            specs[pid] = [CaseSpec(program=pid, stdin=accept_stdin(s * 31 + j, len(items) + (j % 3) - 1),
                                   strategy=f"fuzz-accept:{j}") for j in range(12)]
        return validate_program(d, cfg=cfg, runner=runner, specs=specs)


if __name__ == "__main__":
    sys.exit(main())
