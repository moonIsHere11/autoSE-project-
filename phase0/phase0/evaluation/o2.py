"""Oracle O2: GnuCOBOL at run time. Each program is built with `-ftraceall` (the verifier's cached
builds) and run on the corpus check cases plus inputs from `verifier.inputs.strategies`; the
trace lists every executed paragraph, section and statement with its source line.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from phase0.toolbox import Toolbox
from verifier.cobol import analysis
from verifier.cobol.gnucobol import build_all
from verifier.cobol.lexer import tokenize
from verifier.cobol.parser import parse_source
from verifier.cobol.preprocess import preprocess_all
from verifier.cobol.trace import TraceEvent, parse_trace
from verifier.inputs.bundle import CaseSpec, InputFile, write_inputs
from verifier.inputs.strategies import Generator, ProgramInputs
from verifier.sandbox.batch import run_batch

SEED = 20261119


@dataclass
class Traces:
    runs: list[list[TraceEvent]] = field(default_factory=list)
    cases: int = 0
    error: str | None = None


def specs_for(program: str, cases: list[dict[str, Any]], generated: list[CaseSpec]) -> list[CaseSpec]:
    out = [CaseSpec(program=program, stdin=c.get("stdin", "").encode("latin-1"),
                    files_in=[InputFile(k, v.encode("latin-1")) for k, v in c.get("files", {}).items()])
           for c in cases]
    seen = {s.case_id() for s in out}
    for s in generated:
        if s.case_id() not in seen:
            seen.add(s.case_id())
            out.append(s)
    return out


def generated_specs(toolbox: Toolbox, prog: Any) -> list[CaseSpec]:
    ch = analysis.channels(prog)
    if any(f.dynamic and f.is_input for f in ch.files):
        return []
    pi = ProgramInputs.build(prog, ch.accepts, ch.files, analysis.literal_seeds(prog), bool(analysis.nondeterminism(prog)))
    t1 = toolbox.config.t1
    gen = Generator(pi, SEED, "fast", case_cap=t1.fast_case_cap, random_n=t1.random_fast, pairwise=t1.pairwise,
                    extra_lines=t1.extra_stdin_lines, fake_time=toolbox.config.fake_time)
    return [gen.materialise(m, s) for s, m in gen.generate()]


def trace_program(toolbox: Toolbox, source_root: Path, rel: str, cases: list[dict[str, Any]]) -> Traces:
    cfg = toolbox.config
    pre = preprocess_all(toolbox.runner, cfg.cobol, source_root, [rel], toolbox.cache_dir)[rel]
    if not pre.ok:
        return Traces(error=f"cobc -E failed: {pre.diagnostics[:300]}")
    prog = parse_source(tokenize(pre.lines), rel)[0]
    version = toolbox.versions().get("gnucobol", "?")
    binary = build_all(toolbox.runner, cfg.cobol, source_root, [(prog.program_id, pre)], toolbox.cache_dir, version)
    b = binary[prog.program_id]
    if not b.ok:
        return Traces(error=f"build failed: {b.diagnostics[-300:]}")
    specs = specs_for(prog.program_id, cases, generated_specs(toolbox, prog))
    with tempfile.TemporaryDirectory(prefix="phase0-o2-") as tmp_s:
        tmp = Path(tmp_s)
        ids = []
        for s in specs:
            write_inputs(s, tmp / "in" / s.case_id())
            ids.append(s.case_id())
        res = run_batch(toolbox.runner, inputs_root=tmp / "in", results_root=tmp / "res", case_ids=ids,
                        command=b.command(traced=True), limits=cfg.limits, extra_mounts=[b.mount()],
                        env=dict(cfg.cobol.runtime_env), trace=True)
        out = Traces(cases=len(ids))
        for cid in ids:
            run = res.runs.get(cid)
            if run is not None and run.trace:
                out.runs.append(parse_trace(run.trace))
    return out
