"""Quick differential check for corpus authors (a T1-lite; T1 itself supersedes it).

    python -m tools.corpus_check corpus/<name> --lang java [--cases FILE]

Builds the COBOL program(s) in `<dir>/cobol` with the pinned GnuCOBOL, builds the translation in
`<dir>/<lang>` with the language pack, runs both in the sandbox on every case in
`<dir>/check_cases.json` and prints byte-level differences. Exit 0 iff everything matches.

check_cases.json: [{"stdin": "12.34\\n7\\n", "files": {"IN.DAT": "line1\\n"}, "args": [], "program": "PROG"}]
("program" may be omitted when the directory has one program.)
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

from verifier.cobol.gnucobol import build_all
from verifier.cobol.lexer import tokenize
from verifier.cobol.parser import parse_source
from verifier.cobol.preprocess import find_cobol_sources, preprocess_all
from verifier.config import VerifierConfig
from verifier.inputs.bundle import CaseSpec, InputFile, write_inputs
from verifier.langpacks.base import NotApplicable, PackContext
from verifier.pipeline import get_pack
from verifier.sandbox.batch import run_batch
from verifier.sandbox.docker_runner import DockerRunner, Mount
from verifier.sandbox.limits import SandboxLimits


def _show(b: bytes) -> str:
    return b.decode("latin-1").replace("\n", "\\n\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", type=Path)
    ap.add_argument("--lang", default="java", choices=["java", "python", "go"])
    ap.add_argument("--cases", type=Path)
    a = ap.parse_args(argv)
    cfg = VerifierConfig()
    runner = DockerRunner(cfg.image, SandboxLimits.from_config(cfg.limits))
    runner.check_available()
    cases_file = a.cases or a.dir / "check_cases.json"
    raw_cases = json.loads(cases_file.read_text("utf-8"))
    with tempfile.TemporaryDirectory(prefix="cv-check-") as tmp_s:
        tmp = Path(tmp_s)
        cob = tmp / "cobol"
        tgt = tmp / "target"
        shutil.copytree(a.dir / "cobol", cob)
        shutil.copytree(a.dir / a.lang, tgt)
        srcs = find_cobol_sources(cob, cfg.cobol)
        pre = preprocess_all(runner, cfg.cobol, cob, srcs, Path(cfg.cache_dir))
        progs = {}
        for rel in srcs:
            if not pre[rel].ok:
                print(f"cobc -E failed for {rel}:\n{pre[rel].diagnostics}")
                return 2
            for p in parse_source(tokenize(pre[rel].lines), rel):
                if p.parse_errors:
                    print(f"note: parse issues in {rel}: {p.parse_errors[:5]}")
                progs[p.program_id] = (p, pre[rel])
        version = runner.toolchain_versions().get("gnucobol", "?")
        bins = build_all(runner, cfg.cobol, cob, [(pid, pp[1]) for pid, pp in progs.items()], Path(cfg.cache_dir), version)
        for pid, b in bins.items():
            if not b.ok:
                print(f"COBOL build failed for {pid}:\n{b.diagnostics}")
                return 2
        pack = get_pack(a.lang)
        manifest = None
        mpath = a.dir / f"manifest.{a.lang}.json"
        if mpath.exists():
            from verifier.manifest import load_manifest

            manifest = load_manifest(mpath, a.lang)
        ctx = PackContext(cfg, runner, tgt, manifest, Path(__file__).resolve().parents[1] / "runtimes" / "build")
        br = pack.build(ctx)
        if not br.ok:
            print(f"target build failed:\n{br.output}")
            return 1
        index = pack.index(tgt)
        failures = 0
        for pid, (prog, _pre) in progs.items():
            entry = manifest.program(pid) if manifest else None
            rp = pack.resolve_program(ctx, index, prog, entry)
            cmd = pack.run_command(ctx, rp)
            if isinstance(cmd, NotApplicable):
                print(f"{pid}: {cmd.reason}")
                failures += 1
                continue
            specs = []
            for c in raw_cases:
                if c.get("program", pid).upper() != pid:
                    continue
                specs.append(CaseSpec(program=pid, stdin=c.get("stdin", "").encode("latin-1"), args=c.get("args", []),
                                      files_in=[InputFile(k, v.encode("latin-1")) for k, v in c.get("files", {}).items()],
                                      fake_time=c.get("fake_time")))
            inputs = tmp / "inputs" / pid
            ids = []
            for s in specs:
                write_inputs(s, inputs / s.case_id())
                ids.append(s.case_id())
            env = dict(cfg.cobol.runtime_env)
            cres = run_batch(runner, inputs_root=inputs, results_root=tmp / "res-cobol" / pid, case_ids=ids,
                             command=bins[pid].command(), limits=cfg.limits, extra_mounts=[bins[pid].mount()], env=env)
            mounts = [Mount(tgt, "/tgt", True)]
            if ctx.runtime_dir is not None:
                mounts.append(Mount(ctx.runtime_dir, "/opt/cobolrt", True))
            tres = run_batch(runner, inputs_root=inputs, results_root=tmp / "res-target" / pid, case_ids=ids,
                             command=cmd, limits=cfg.limits, extra_mounts=mounts,
                             env={"TARGET_ROOT": "/tgt", "COBOLRT": "/opt/cobolrt"})
            for cid, s in zip(ids, specs, strict=True):
                e, t = cres.runs.get(cid), tres.runs.get(cid)
                if e is None or t is None:
                    print(f"{pid} {cid}: missing results {cres.errors + tres.errors}")
                    failures += 1
                    continue
                if b"libcob: error" in e.stderr:
                    print(f"{pid} {cid}: COBOL runtime error (case would be excluded): {e.stderr.decode()[:200]}")
                    continue
                diffs = []
                if e.stdout != t.stdout:
                    diffs.append(f"stdout differs:\n--- expected (GnuCOBOL)\n{_show(e.stdout)}\n--- actual\n{_show(t.stdout)}")
                if e.return_code != t.return_code:
                    diffs.append(f"return code {e.return_code} vs {t.return_code}")
                if e.files != t.files:
                    for name in sorted(set(e.files) | set(t.files)):
                        if e.files.get(name) != t.files.get(name):
                            diffs.append(f"file {name}: expected {e.files.get(name)!r} actual {t.files.get(name)!r}")
                if diffs:
                    failures += 1
                    print(f"\n### {pid} case stdin={s.stdin!r} files={[f.name for f in s.files_in]}")
                    print("\n".join(diffs))
                    if t.stderr:
                        print(f"target stderr: {t.stderr.decode(errors='replace')[:500]}")
            print(f"{pid}: {len(ids)} cases, {failures} with differences so far")
        return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
