"""Capture the golden outputs of the COBOL semantics suite from the pinned GnuCOBOL.

    python -m tools.capture_semantics [NAME ...]      # default: every tests/semantics/programs/*.cbl

For each program `tests/semantics/programs/<NAME>.cbl` (stdin from `<NAME>.in`, input files from
`<NAME>.files/`), compile with the pinned flags, run once in the sandbox and store
`tests/semantics/expected/<NAME>/`:

    stdout          exact bytes
    return_code     decimal text
    files/<f>       every file left in the working directory (inputs included)
    preprocessed.i  the `cobc -E` text (lets the interpreter test run without Docker)
    meta.json       toolchain version, flags, whether libcob reported a runtime error
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from verifier.cobol.gnucobol import build_all
from verifier.cobol.preprocess import preprocess_all
from verifier.config import VerifierConfig
from verifier.inputs.bundle import CaseSpec, InputFile, write_inputs
from verifier.sandbox.batch import run_batch
from verifier.sandbox.docker_runner import DockerRunner
from verifier.sandbox.limits import SandboxLimits

ROOT = Path(__file__).resolve().parents[1]
PROGRAMS = ROOT / "tests" / "semantics" / "programs"
EXPECTED = ROOT / "tests" / "semantics" / "expected"


@dataclass
class GoldenRun:
    name: str
    stdout: bytes
    return_code: int
    files: dict[str, bytes]
    preprocessed: str
    runtime_error: bool
    meta: dict[str, object] = field(default_factory=dict)


def program_names() -> list[str]:
    return sorted(p.stem for p in PROGRAMS.glob("*.cbl"))


def case_for(name: str) -> CaseSpec:
    stdin_p = PROGRAMS / f"{name}.in"
    files_dir = PROGRAMS / f"{name}.files"
    files = []
    if files_dir.is_dir():
        for p in sorted(files_dir.rglob("*")):
            if p.is_file():
                files.append(InputFile(p.relative_to(files_dir).as_posix(), p.read_bytes()))
    return CaseSpec(program=name, stdin=stdin_p.read_bytes() if stdin_p.exists() else b"", files_in=files,
                    strategy="golden")


def run_goldens(names: list[str], runner: DockerRunner, cfg: VerifierConfig) -> dict[str, GoldenRun]:
    """Compile and run each golden program under GnuCOBOL (one container per program)."""
    out: dict[str, GoldenRun] = {}
    with tempfile.TemporaryDirectory(prefix="cv-golden-") as tmp_s:
        tmp = Path(tmp_s)
        src = tmp / "src"
        src.mkdir()
        for n in names:
            shutil.copyfile(PROGRAMS / f"{n}.cbl", src / f"{n}.cbl")
        rels = [f"{n}.cbl" for n in names]
        pre = preprocess_all(runner, cfg.cobol, src, rels, Path(cfg.cache_dir))
        for rel in rels:
            if not pre[rel].ok:
                raise RuntimeError(f"cobc -E failed for {rel}: {pre[rel].diagnostics}")
        version = str(runner.toolchain_versions().get("gnucobol", "?"))
        bins = build_all(runner, cfg.cobol, src, [(n, pre[f"{n}.cbl"]) for n in names], Path(cfg.cache_dir),
                         version)
        failed = [f"{n}: {bins[n].diagnostics[-1500:]}" for n in names if not bins[n].ok]
        if failed:
            raise RuntimeError("cobc failed:\n" + "\n".join(failed))
        for n in names:
            b = bins[n]
            spec = case_for(n)
            cid = spec.case_id()
            write_inputs(spec, tmp / "in" / n / cid)
            res = run_batch(runner, inputs_root=tmp / "in" / n, results_root=tmp / "res" / n, case_ids=[cid],
                            command=b.command(), limits=cfg.limits, extra_mounts=[b.mount()],
                            env=dict(cfg.cobol.runtime_env))
            run = res.runs.get(cid)
            if run is None or run.runner_error or run.timed_out:
                raise RuntimeError(f"{n}: no usable GnuCOBOL result ({res.errors})")
            out[n] = GoldenRun(n, run.stdout, run.return_code, dict(run.files), pre[f"{n}.cbl"].text,
                               b"libcob: error" in run.stderr,
                               {"gnucobol": version, "flags": pre[f"{n}.cbl"].flags,
                                "stderr": run.stderr.decode("latin-1")[:2000],
                                "runtime_env": cfg.cobol.runtime_env})
    return out


def load_expected(name: str) -> GoldenRun:
    d = EXPECTED / name
    files: dict[str, bytes] = {}
    fdir = d / "files"
    if fdir.is_dir():
        for p in sorted(fdir.rglob("*")):
            if p.is_file():
                files[p.relative_to(fdir).as_posix()] = p.read_bytes()
    meta = json.loads((d / "meta.json").read_text("utf-8"))
    return GoldenRun(name, (d / "stdout").read_bytes(), int((d / "return_code").read_text().strip()), files,
                     (d / "preprocessed.i").read_text("latin-1"), bool(meta.get("runtime_error")), meta)


def store(g: GoldenRun) -> None:
    d = EXPECTED / g.name
    if d.exists():
        shutil.rmtree(d)
    (d / "files").mkdir(parents=True)
    (d / "stdout").write_bytes(g.stdout)
    (d / "return_code").write_text(f"{g.return_code}\n", "ascii")
    for name, data in g.files.items():
        p = d / "files" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    (d / "preprocessed.i").write_bytes(g.preprocessed.encode("latin-1"))
    (d / "meta.json").write_text(json.dumps({**g.meta, "runtime_error": g.runtime_error}, indent=1) + "\n",
                                 "utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="*")
    a = ap.parse_args(argv)
    cfg = VerifierConfig()
    runner = DockerRunner(cfg.image, SandboxLimits.from_config(cfg.limits))
    runner.check_available()
    names = [n.upper() for n in a.names] or program_names()
    for g in run_goldens(names, runner, cfg).values():
        store(g)
        print(f"{g.name}: rc={g.return_code} stdout={len(g.stdout)} bytes files={sorted(g.files)}"
              f"{' RUNTIME ERROR' if g.runtime_error else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
