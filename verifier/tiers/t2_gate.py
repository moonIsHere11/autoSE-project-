"""T2b validation gate (spec section 6, T2b.4).

The Java reference used by T2b/T1u is only trusted when both checks hold:

(a) **model vs GnuCOBOL** (once per program): the COBOL IR interpreter reproduces GnuCOBOL on every
    non-excluded T1 case of the program — stdout, every file of the working directory and the
    return code, byte for byte. The expected results are the ones T1 recorded from the real
    GnuCOBOL binary (`<out>/cases/<PROGRAM>/<case>/expected`); the comparison is
    `tools.validate_interp.compare_case`.
(b) **reference vs model** (per unit): the emitted Java reference and the interpreter's
    `run_paragraph` agree on every field of the unit after running from the same random PIC-domain
    states (the reference is run with plain `java` through the T2b replay driver).

A disagreement is a bug in *our* model, never in the candidate: it is reported as ERROR. When a
check cannot be performed (no T1 cases, constructs the interpreter refuses, OCCURS state the
cross-check cannot load) the unit is NOT_APPLICABLE with that reason — never PASS.
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING

from verifier.cobol import interp
from verifier.inputs.bundle import read_bundle
from verifier.report.schema import Status, TierResult
from verifier.sandbox.batch import read_case_results

if TYPE_CHECKING:
    from verifier.cobol import ir
    from verifier.langpacks.java.harness import Harness
    from verifier.pipeline import Pipeline, ProgramCtx

METHOD = "bounded_model_checking"
MAX_SHOWN = 3


@dataclass
class GateAResult:
    compared: int = 0
    excluded: int = 0
    mismatches: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)


def _case_excluded(case_dir: Path) -> bool:
    meta_p = case_dir / "expected" / "meta.json"
    if not meta_p.exists():
        return True
    try:
        meta = json.loads(meta_p.read_text("utf-8"))
    except ValueError:
        return True
    if meta.get("excluded") or meta.get("runner_error") or meta.get("timed_out"):
        return True
    stderr_p = case_dir / "expected" / "stderr"
    return stderr_p.exists() and b"libcob: error" in stderr_p.read_bytes()


def validate_against_cobol(irp: ir.IrProgram, cases_root: Path) -> GateAResult:
    """Gate (a): the interpreter vs GnuCOBOL's recorded results on the T1 bundles."""
    from tools.validate_interp import compare_case

    r = GateAResult()
    for case_dir in sorted(p for p in cases_root.iterdir() if p.is_dir() and (p / "case.json").exists()):
        if _case_excluded(case_dir):
            r.excluded += 1
            continue
        spec = read_bundle(case_dir)
        exp = read_case_results(case_dir / "expected", case_dir.name)
        mms, refusal = compare_case(irp, spec, exp)
        if refusal is not None:
            r.refused.append(f"{case_dir.name}: {refusal}")
            continue
        r.compared += 1
        if mms:
            r.mismatches.append(f"{case_dir.name}: {', '.join(sorted({m.what for m in mms}))}")
    return r


def check_gate(pl: Pipeline, pc: ProgramCtx, irp: ir.IrProgram) -> TierResult | None:
    """Gate (a). None when the model reproduces GnuCOBOL on the program's T1 cases; otherwise the result
    every unit of the program gets."""
    pid = pc.program.program_id
    reason = irp.interpretability()
    if reason is not None:
        return TierResult.not_applicable(f"validation gate: the COBOL model cannot interpret {pid} ({reason})", METHOD)
    cases_root = pl.req.out / "cases" / pid
    if not cases_root.is_dir():
        return TierResult.not_applicable("validation gate needs the program's T1 cases (run T1 together with T2)",
                                         METHOD)
    try:
        r = validate_against_cobol(irp, cases_root)
    except Exception as exc:  # our model crashed: never the candidate's fault
        return TierResult.error(f"validation gate: COBOL model crashed ({type(exc).__name__}: {exc})", METHOD)
    details = {"validation_gate": {"compared": r.compared, "excluded": r.excluded,
                                   "mismatching": len(r.mismatches), "refused": len(r.refused)}}
    if r.mismatches:
        return TierResult(status=Status.ERROR, method=METHOD, details=details,
                          reason=f"validation gate: COBOL model disagrees with GnuCOBOL on {len(r.mismatches)}/"
                          f"{r.compared} T1 cases (model bug, not the candidate): "
                          + "; ".join(r.mismatches[:MAX_SHOWN]))
    if r.refused:
        return TierResult(status=Status.NOT_APPLICABLE, method=METHOD, details=details,
                          reason=f"validation gate: the COBOL model refused {len(r.refused)} T1 cases: "
                          + "; ".join(r.refused[:MAX_SHOWN]))
    if r.compared == 0:
        return TierResult.not_applicable(f"validation gate: no usable T1 case ({r.excluded} excluded)", METHOD)
    return None


# ---------------------------------------------------------------------------------------------
def _num_text(v: int, scale: int) -> str:
    return format(Decimal(v).scaleb(-scale), "f") if scale else str(v)


def _scaled(text: str, scale: int) -> int | None:
    try:
        return int(Decimal(text.strip() or "0").scaleb(scale))
    except (InvalidOperation, ValueError):
        return None


def cross_check_unit(irp: ir.IrProgram, para: str, h: Harness, replay: Callable[[list[str]], str],
                     n: int, seed: int) -> TierResult | None:
    """Gate (b): emitted reference vs interpreter on `n` random PIC-domain states. None when they agree."""
    from verifier.langpacks.java.harness import parse_replay, state_line
    from verifier.tiers.t2_symbolic import _domain_value

    by_cobol = {s.cobol: s for s in h.slots}
    ref_slots = [s for s in h.slots if s.ref is not None]
    if any(s.occurs for s in ref_slots):
        return TierResult.not_applicable("validation gate (b): cross-checking OCCURS state between the reference "
                                         "and the COBOL model is not implemented", METHOD)
    keys: dict[str, str] = {}  # COBOL name -> key of ParagraphResult.fields
    for s in ref_slots:
        if s.cobol.upper() == "RETURN-CODE":  # special register: set/read by name in the interpreter
            keys[s.cobol] = "RETURN-CODE"
            continue
        item = irp.program.resolve(s.cobol)
        if item is None:
            return TierResult.not_applicable(f"validation gate (b): {s.cobol} not found in the COBOL model", METHOD)
        keys[s.cobol] = ".".join(reversed(item.path()))
    rng = random.Random(seed)
    lines: list[str] = []
    states: list[dict[str, str]] = []
    for _ in range(n):
        vals = {sv.name: _domain_value(sv.kind, by_cobol[sv.cobol], rng) for sv in h.state}
        lines.append(state_line(h, vals))
        texts: dict[str, str] = {}
        for s in ref_slots:
            svs = [sv for sv in h.state if sv.cobol == s.cobol]
            if s.kind == "num":
                texts[s.cobol] = _num_text(vals[svs[0].name], s.scale)
            else:
                texts[s.cobol] = "".join(chr(vals[sv.name]) for sv in sorted(svs, key=lambda x: x.char_pos or 0))
        states.append(texts)
    cases = parse_replay(replay(lines))
    if len(cases) != n:
        return TierResult.error(f"validation gate (b): reference replay produced {len(cases)}/{n} results", METHOD)
    compared = 0
    bad: list[str] = []
    for k, (case, texts) in enumerate(zip(cases, states, strict=True)):
        if case.ref_out_of_model or case.ref_throw:
            continue
        try:
            res = interp.run_paragraph(irp, para, values=texts)
        except interp.CobolRuntimeError:
            continue
        except interp.InterpUnsupported as exc:
            return TierResult.not_applicable(f"validation gate (b): COBOL model refused {para}: {exc}", METHOD)
        compared += 1
        for s in ref_slots:
            model = res.fields.get(keys[s.cobol])
            got = case.ref.get(s.cobol)
            if model is None or got is None:
                continue
            if s.kind == "num":
                want = _scaled(model, s.scale)
                same = want is not None and str(want) == got.strip()
            else:
                same = ",".join(str(ord(c)) for c in model) == got.strip()
            if not same:
                bad.append(f"state #{k}: {s.cobol} reference={got} model={model}")
                break
    if bad:
        return TierResult.error(f"validation gate (b): emitted reference disagrees with the COBOL model on "
                                f"{len(bad)}/{compared} states (verifier bug, not the candidate): "
                                + "; ".join(bad[:MAX_SHOWN]), METHOD)
    if compared == 0:
        return TierResult.not_applicable("validation gate (b): no state could be compared", METHOD)
    return None
