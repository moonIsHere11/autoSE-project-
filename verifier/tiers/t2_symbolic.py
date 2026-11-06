"""T2b — bounded symbolic equivalence at unit level, plus T1u (spec section 6, T2b and T1u).

Java pipeline per unit (cheapest first; every step that cannot be done honestly yields
NOT_APPLICABLE with the exact reason):

1. eligibility from the IR (no I/O, no unsupported construct in the PERFORM closure);
2. Java reference emitted from the IR (`langpacks/java/emit.py`); the program's reference is only
   trusted after the **validation gate** (`validation_gate`);
3. mapping to the candidate class/method/fields (manifest or conventions), checkable
   representations only (integer-scaled numerics, char[] alphanumerics), and a `javap` pre-scan for
   JDK calls JBMC would silently stub;
4. **T1u**: random PIC-domain states through reference and candidate (plain `java`): a mismatch is a
   concrete counterexample — T2b FAIL without running JBMC;
5. JBMC `check` with `--unwinding-assertions` (complete proof) or, if the bound is insufficient,
   without (bounded proof, `bound: unwind K`); a counterexample is replayed concretely and only a
   confirmed one is FAIL (otherwise ERROR);
6. vacuity: the `reach` run must FAIL, and mutation sanity must kill most COBOL-semantic mutants of
   the candidate unit; otherwise a PASS is downgraded to ERROR.

Python T2b (CrossHair) is in `t2_crosshair.py`; Go is NOT_APPLICABLE (no mature model checker).
"""

from __future__ import annotations

import random
import re
import shutil
import time
import zlib
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from verifier.cobol import ir
from verifier.diagnose.classifier import classify
from verifier.diagnose.compare import Mismatch
from verifier.langpacks.base import MethodSym
from verifier.langpacks.java import jbmc
from verifier.langpacks.java.emit import EmittedRef, EmitUnsupported, classify_item, emit_reference
from verifier.langpacks.java.harness import (
    Harness,
    HarnessUnsupported,
    Slot,
    build_harness,
    parse_replay,
    slot_for,
    state_line,
)
from verifier.langpacks.java.pack import COBOLRT_JAR
from verifier.manifest import camel
from verifier.mutation import apply_mutant, find_mutants, sample_mutants
from verifier.report.schema import (
    Classification,
    Counterexample,
    FailureSignature,
    FieldDiff,
    FieldValue,
    Scope,
    SourceRef,
    Status,
    TierResult,
    ToolInfo,
)
from verifier.sandbox.docker_runner import Mount

if TYPE_CHECKING:
    from verifier.pipeline import Pipeline, ProgramCtx

METHOD = "bounded_model_checking"
DOMAIN = ("every state in which each numeric field holds a value of its PIC (valid digits, no negative zero) "
          "and each alphanumeric field holds printable ASCII (0x20-0x7E)")


@dataclass
class ProgramT2b:
    """Per-program state shared by its units."""

    irp: ir.IrProgram | None
    gate: TierResult | None  # None = reference trusted; else the result to report for every unit
    work: Path
    cand_cp: str | None = None  # container classpath of the compiled candidate
    classes: dict[str, jbmc.ClassCode] = field(default_factory=dict)
    cand_error: str | None = None
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------------------------
def run_t2b(pl: Pipeline, pc: ProgramCtx) -> dict[str, TierResult]:
    paras = pc.selected_paragraphs
    if pl.req.lang == "go":
        return {p: TierResult.not_applicable("no mature model checker for Go (spec section 6, T2b.6)", METHOD)
                for p in paras}
    if pl.req.lang == "python":
        from verifier.pipeline import optional

        run_py = optional("verifier.tiers.t2_crosshair", "run_t2b_python")
        if run_py is None:
            return {p: TierResult(status=Status.NOT_APPLICABLE, stub=True, reason="Python T2b not implemented yet")
                    for p in paras}
        result: dict[str, TierResult] = run_py(pl, pc)
        return result
    prog = pc.program
    start = time.monotonic()
    work = pl.req.out / "t2b" / prog.program_id
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    try:
        irp: ir.IrProgram | None = ir.lower_program(prog)
    except Exception as exc:  # the lowering itself failed: our model, not the candidate
        irp = None
        pt = ProgramT2b(None, TierResult.error(f"COBOL IR lowering failed: {exc}", METHOD), work)
    else:
        pt = ProgramT2b(irp, None, work)
    out: dict[str, TierResult] = {}
    budget = pl.cfg.t2.fast_budget_s if pl.req.mode == "fast" else pl.cfg.t2.full_budget_s
    for para in paras:
        if time.monotonic() - start > budget:
            out[para] = TierResult.skipped(f"T2b time budget ({budget:.0f} s, mode {pl.req.mode}) exhausted")
            continue
        t1u, t2b = _unit(pl, pc, pt, para)
        if t1u is not None:
            pc.unit_tiers.setdefault(para, {})["T1u"] = t1u
        out[para] = t2b
    return out


def _na(reason: str) -> tuple[TierResult | None, TierResult]:
    return None, TierResult.not_applicable(reason, METHOD)


# ---------------------------------------------------------------------------------------------
def _unit(pl: Pipeline, pc: ProgramCtx, pt: ProgramT2b, para: str) -> tuple[TierResult | None, TierResult]:
    if pt.irp is None:
        assert pt.gate is not None
        return None, pt.gate
    irp = pt.irp
    ip = irp.paragraph(para)
    if ip is None:
        return _na(f"paragraph {para} not in the IR")
    if ip.t2_eligibility is not None:
        return _na(ip.t2_eligibility)
    closure = [para] + [p for p in ir.perform_closure(irp, para) if p != para]
    slug = re.sub(r"[^A-Za-z0-9]", "_", para)
    try:
        ref = emit_reference(irp, closure, f"t2bref.u_{slug.lower()}", "Ref")
    except EmitUnsupported as exc:
        return _na(exc.reason)
    res = pc.resolved
    if res is None or res.type_sym is None:
        return _na("no target class for the program")
    cand_method = res.units.get(para)
    loc = res.unit_locations.get(para)
    if not cand_method or loc is None:
        return _na(f"no target method for paragraph {para} (manifest units / naming convention)")
    if loc.params:
        return _na(f"target method {cand_method} takes parameters ({', '.join(loc.params)}); T2b expects a "
                   "parameterless method operating on the object's fields")
    try:
        slots = _slots(pc, ref)
    except HarnessUnsupported as exc:
        return _na(exc.reason)
    # ---- validation gate (once per program) ----------------------------------------------------
    if pt.gate is None and not getattr(pt, "_gate_done", False):
        pt.gate = validation_gate(pl, pc, irp)
        pt._gate_done = True  # type: ignore[attr-defined]
    if pt.gate is not None:
        return None, pt.gate
    # ---- candidate classes + pre-scan --------------------------------------------------------------
    if pt.cand_cp is None and pt.cand_error is None:
        _compile_candidate(pl, pt)
    if pt.cand_error is not None:
        return None, TierResult.error(pt.cand_error, METHOD)
    cand_class = res.type_sym.qualified
    internal = cand_class.replace(".", "/")
    reasons = jbmc.unmodelled_calls(pt.classes, internal, cand_method)
    if reasons:
        return _na("; ".join(reasons[:3]))
    package = cand_class.rsplit(".", 1)[0] if "." in cand_class else ""
    h = build_harness(ref, ref.methods[para], cand_class, cand_method, package, slots, slug)
    uw = pt.work / slug
    ok, msg = _compile_harness(pl, pt, uw, ref, h)
    if not ok:
        return None, TierResult.error(f"generated harness does not compile (verifier bug): {msg[-600:]}", METHOD)
    # ---- validation gate (b): emitted reference vs the validated COBOL model ---------------------
    from verifier.tiers.t2_gate import cross_check_unit

    n_gate = min(200, pl.cfg.t2.t1u_fast)
    gate_b = cross_check_unit(irp, para, h, lambda lines: _replay(pl, pt, uw, h, lines), n_gate,
                              pl.effective_seed ^ (zlib.crc32(b"gate:" + para.encode()) & 0xFFFF))
    if gate_b is not None:
        return None, gate_b
    # ---- T1u ------------------------------------------------------------------------------------
    t1u, t1u_fail = _t1u(pl, pc, pt, uw, h, para, cand_method, loc)
    if t1u_fail is not None:
        return t1u, t1u_fail
    # ---- JBMC -----------------------------------------------------------------------------------
    fast = pl.req.mode == "fast"
    k = max(pl.cfg.t2.unwind_fast if fast else pl.cfg.t2.unwind_full, ref.loop_bound + 2)
    k = min(k, 64)
    tmo = pl.cfg.t2.checker_timeout_fast_s if fast else pl.cfg.t2.checker_timeout_s
    cp = _harness_cp(pt, uw)
    mounts = _mounts(pl)
    eq = jbmc.run_jbmc(pl.runner, pt.work, cp, h.qualified_harness, h.check_function, unwind=k, timeout_s=tmo,
                       tag=f"{slug}_check", extra_mounts=mounts)
    bound = "complete"
    commands = [eq.command]
    if eq.verdict == "BOUND_INSUFFICIENT":
        bounded = _bounded(pl, pt.work, f"{slug}_bounded", cp, h, k, tmo, mounts)
        commands.append(bounded.command)
        eq, bound = bounded, f"unwind {k} (loops not fully unwound: bounded proof)"
    scope = Scope(level="unit", what=f"all mapped fields after {para} (closure {', '.join(closure)}) vs "
                  f"{cand_class}.{cand_method}", domain=DOMAIN, bound=bound,
                  oracle="COBOL IR reference (validated against GnuCOBOL via the interpreter)",
                  tools=[ToolInfo(name="jbmc", version=str(pl.toolchain.get("jbmc", "?")))], commands=commands)
    if eq.verdict == "COUNTEREXAMPLE":
        return t1u, _confirm(pl, pc, pt, uw, h, para, cand_method, loc, eq, scope)
    if eq.verdict == "TIMEOUT":
        return t1u, TierResult(status=Status.TIMEOUT, reason=f"JBMC did not finish within {tmo:.0f} s "
                               "(typical for multiply-heavy units, spike S2)", method=METHOD, scope=scope)
    if eq.verdict != "PROVED":
        return t1u, TierResult.error(f"JBMC {eq.verdict}: {'; '.join(eq.errors)[:500]}", METHOD)
    # ---- vacuity ------------------------------------------------------------------------------------
    reach = jbmc.run_jbmc(pl.runner, pt.work, cp, h.qualified_harness, h.reach_function, unwind=k, timeout_s=tmo,
                          tag=f"{slug}_reach", extra_mounts=mounts)
    reach_ok = reach.verdict in ("COUNTEREXAMPLE", "BOUND_INSUFFICIENT") and any(
        f.kind == "assertion" for f in reach.failed)
    vac: dict[str, Any] = {"reachability": "end of both units reachable" if reach_ok else f"FAILED ({reach.verdict})"}
    if not reach_ok:
        return t1u, TierResult(status=Status.ERROR, reason="vacuous proof: the end of the harness is unreachable "
                               "(contradictory assumptions?)", method=METHOD, scope=scope, vacuity=vac)
    _killed, detail = _mutation_sanity(pl, pc, pt, uw, h, ref, loc, k, tmo)
    vac["mutation_sanity"] = detail
    rate = None if detail["live"] == 0 else detail["killed"] / detail["live"]
    if rate is not None and detail["live"] >= 2 and rate < pl.cfg.t2.min_kill_rate:
        return t1u, TierResult(status=Status.ERROR, reason=f"mutation sanity failed: only {detail['killed']}/"
                               f"{detail['live']} planted bugs refuted (harness may not observe the unit)",
                               method=METHOD, scope=scope, vacuity=vac, mutation_kill_rate=round(rate, 3))
    return t1u, TierResult(status=Status.PASS, method=METHOD, scope=scope, bound=bound, vacuity=vac,
                           mutation_kill_rate=round(rate, 3) if rate is not None else None,
                           duration_s=eq.duration_s + reach.duration_s,
                           details={"unwind": k, "properties": eq.properties, "notes": h.notes})


# ---------------------------------------------------------------------------------------------
def _slots(pc: ProgramCtx, ref: EmittedRef) -> list[Slot]:
    res = pc.resolved
    assert res is not None and res.type_sym is not None
    cand_fields = {f.name: f.type_text for f in res.type_sym.fields}
    slots: list[Slot] = []
    # A manifest may map several COBOL items onto one Java field (e.g. an output-record copy PR-HOURS and
    # WS-HOURS both -> wsHours). The harness loads one independent value per slot, so a Java field may
    # back only one slot: two *unit* fields sharing one is not checkable; a frame-only alias of a unit
    # field is skipped (its value is the unit field's value, already loaded and compared).
    claimed: dict[str, str] = {}  # Java field -> COBOL item that owns it
    for cobol, rf in sorted(ref.fields.items()):
        mapping = res.fields.get(cobol)
        if mapping is None:
            want = camel(cobol)
            if want in cand_fields:
                mapping = {"target": want, "target_type": cand_fields[want]}
        if mapping is None or not mapping.get("target"):
            raise HarnessUnsupported(f"COBOL field {cobol} used by the unit has no target counterpart")
        if not mapping.get("target_type"):
            mapping = {**mapping, "target_type": cand_fields.get(mapping["target"])}
        target = str(mapping["target"])
        if target in claimed:
            raise HarnessUnsupported(f"COBOL fields {claimed[target]} and {cobol}, both used by the unit, map to "
                                     f"the same target field `{target}`")
        claimed[target] = cobol
        slots.append(slot_for(cobol, rf, {}, mapping))
    # frame: every other mapped elementary item must stay unchanged
    for cobol, mapping in sorted(res.fields.items()):
        if cobol in ref.fields or not mapping.get("target"):
            continue
        if str(mapping["target"]) in claimed:
            continue  # alias of a field already in the harness (see above)
        item = pc.program.resolve(cobol)
        if item is None:
            continue
        try:
            rf = classify_item(item)
        except EmitUnsupported:
            continue
        info = {"kind": rf.kind, "digits": rf.digits, "scale": rf.scale, "signed": rf.signed, "length": rf.length,
                "occurs": rf.occurs}
        try:
            slots.append(slot_for(cobol, None, info, mapping))
        except HarnessUnsupported:
            continue
        claimed[str(mapping["target"])] = cobol
    return slots


def _mounts(pl: Pipeline) -> list[Mount]:
    out = [Mount(pl.ws_target, "/tgt", True)]
    rd = pl.runtime_dir()
    if rd is not None:
        out.append(Mount(rd, "/opt/cobolrt", True))
    return out


def _compile_candidate(pl: Pipeline, pt: ProgramT2b) -> None:
    from verifier.langpacks.java.pack import BUILD_DIR, JavaPack

    srcs = [f"/tgt/{s}" for s in JavaPack().sources(pl.ws_target)]
    run = jbmc.javac(pl.runner, pt.work, srcs, [COBOLRT_JAR], "/w/cand", extra_mounts=_mounts(pl))
    if run.ok:
        pt.cand_cp = "/w/cand"
        classes_dir = "/w/cand"
    elif (pl.ws_target / BUILD_DIR / "classes").exists():
        pt.cand_cp = f"/tgt/{BUILD_DIR}/classes"
        classes_dir = pt.cand_cp
        pt.notes.append("candidate does not compile with --release 8; using the T0a class files")
    else:
        pt.cand_error = f"cannot compile the candidate for T2b: {run.output[-400:]}"
        return
    jp = jbmc.javap(pl.runner, pt.work, classes_dir, extra_mounts=_mounts(pl))
    if not jp.ok:
        pt.cand_error = f"javap failed: {jp.output[-300:]}"
        return
    pt.classes = jbmc.parse_javap(jp.output)


def _harness_cp(pt: ProgramT2b, uw: Path) -> list[str]:
    rel = uw.relative_to(pt.work).as_posix()
    assert pt.cand_cp is not None
    return [f"/w/{rel}/h", pt.cand_cp, COBOLRT_JAR]


def _compile_harness(pl: Pipeline, pt: ProgramT2b, uw: Path, ref: EmittedRef, h: Harness) -> tuple[bool, str]:
    rel = uw.relative_to(pt.work).as_posix()
    src = uw / "src"
    ref_path = src / Path(*ref.package.split(".")) / f"{ref.class_name}.java"
    pkg_dir = src / Path(*h.package.split(".")) if h.package else src
    for path, text in ((ref_path, ref.source), (pkg_dir / f"{h.harness_class}.java", h.harness_source),
                       (pkg_dir / f"{h.replay_class}.java", h.replay_source)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, "utf-8")
    files = [f"/w/{rel}/src/{p.relative_to(src).as_posix()}" for p in (ref_path, pkg_dir / f"{h.harness_class}.java",
                                                                      pkg_dir / f"{h.replay_class}.java")]
    assert pt.cand_cp is not None
    run = jbmc.javac(pl.runner, pt.work, files, [pt.cand_cp, COBOLRT_JAR, jbmc.CPROVER_JAR], f"/w/{rel}/h",
                     extra_mounts=_mounts(pl))
    return run.ok, run.output


def _bounded(pl: Pipeline, work: Path, tag: str, cp: list[str], h: Harness, k: int, tmo: float,
             mounts: list[Mount]) -> jbmc.JbmcOutcome:
    """Bounded check: `--unwind k` without unwinding assertions (paths beyond k are cut)."""
    return jbmc.run_jbmc(pl.runner, work, cp, h.qualified_harness, h.check_function, unwind=None, timeout_s=tmo,
                         tag=tag, extra_mounts=mounts, extra_flags=["--unwind", str(k)])


def _replay(pl: Pipeline, pt: ProgramT2b, uw: Path, h: Harness, lines: list[str]) -> str:
    cp = ":".join(c for c in _harness_cp(pt, uw))
    res = pl.runner.run(["java", "-Xss16m", "-cp", cp, h.qualified_replay], mounts=[Mount(pt.work, "/w", False),
                        *_mounts(pl)], workdir="/w", timeout_s=300, stdin=("\n".join(lines) + "\n").encode())
    return res.stdout.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------------------------
def _domain_value(sv_kind: str, slot: Slot, rng: random.Random) -> int:
    if sv_kind == "alnum":
        return int(rng.choice([32, 32, rng.randint(48, 57), rng.randint(65, 90), rng.randint(33, 126)]))
    lim = 10**slot.digits
    lo = -(lim - 1) if slot.signed else 0
    pick = rng.random()
    if pick < 0.15:
        return int(rng.choice([0, 1, lim - 1, lo]))
    if pick < 0.4:
        return rng.randint(max(lo, -1000), min(lim - 1, 1000))
    return rng.randint(lo, lim - 1)


def _t1u(pl: Pipeline, pc: ProgramCtx, pt: ProgramT2b, uw: Path, h: Harness, para: str, cand_method: str,
         loc: MethodSym) -> tuple[TierResult, TierResult | None]:
    n = pl.cfg.t2.t1u_fast if pl.req.mode == "fast" else pl.cfg.t2.t1u_full
    seed = pl.effective_seed ^ (zlib.crc32(para.encode()) & 0xFFFF)  # stable across runs (not hash())
    rng = random.Random(seed)
    by_cobol = {s.cobol: s for s in h.slots}
    lines = []
    for _ in range(n):
        vals = {sv.name: _domain_value(sv.kind, by_cobol[sv.cobol], rng) for sv in h.state}
        lines.append(state_line(h, vals))
    start = time.monotonic()
    text = _replay(pl, pt, uw, h, lines)
    cases = parse_replay(text)
    dur = time.monotonic() - start
    scope = Scope(level="unit", what=f"{para} reference vs {cand_method} on random states", domain=DOMAIN,
                  inputs=f"{n} random states (seed {seed})", oracle="validated COBOL IR reference",
                  tools=[ToolInfo(name="java", version=str(pl.toolchain.get("java", "?")))])
    if len(cases) != n:
        return TierResult.error(f"replay produced {len(cases)}/{n} results: {text[-300:]}", "unit_differential"), None
    bad = [i for i, c in enumerate(cases) if c.mismatch]
    excluded = sum(1 for c in cases if c.ref_out_of_model or c.ref_throw)
    if not bad:
        return TierResult(status=Status.PASS, method="unit_differential", scope=scope, cases_run=n - excluded,
                          cases_failed=0, cases_excluded=excluded, duration_s=dur), None
    i = bad[0]
    cx = _counterexample(pc, h, para, lines[i], cases[i], loc, "T1u", "random state")
    t1u = TierResult(status=Status.FAIL, method="unit_differential", scope=scope, cases_run=n - excluded,
                     cases_failed=len(bad), cases_excluded=excluded, duration_s=dur, counterexamples=[cx],
                     failure_signatures=[_sig(cx, len(bad))])
    t2b = TierResult(status=Status.FAIL, method="unit_differential (before model checking)",
                     reason="T1u found a concrete counterexample; JBMC not needed", counterexamples=[cx],
                     failure_signatures=[_sig(cx, len(bad))])
    return t1u, t2b


def _confirm(pl: Pipeline, pc: ProgramCtx, pt: ProgramT2b, uw: Path, h: Harness, para: str, cand_method: str,
             loc: MethodSym, eq: jbmc.JbmcOutcome, scope: Scope) -> TierResult:
    line = state_line(h, eq.inputs)
    cases = parse_replay(_replay(pl, pt, uw, h, [line]))
    if not cases or not cases[0].mismatch:
        prop = eq.real_failures[0] if eq.real_failures else None
        return TierResult(status=Status.ERROR, method=METHOD, scope=scope,
                          reason="JBMC counterexample not confirmed by concrete replay (unmodelled library call or "
                          f"encoding issue): {prop.property if prop else '?'}")
    cx = _counterexample(pc, h, para, line, cases[0], loc, "T2b", "JBMC counterexample")
    return TierResult(status=Status.FAIL, method=METHOD, scope=scope, counterexamples=[cx],
                      failure_signatures=[_sig(cx, 1)])


def _fmt(slot: Slot | None, raw: str) -> str:
    if slot is None:
        return raw
    if slot.kind == "alnum":
        try:
            return '"' + "".join(chr(int(x)) for x in raw.split(",") if x) + '"'
        except ValueError:
            return raw
    try:
        return str(Decimal(int(raw)).scaleb(-slot.scale)) if slot.scale else raw
    except ValueError:
        return raw


def _counterexample(pc: ProgramCtx, h: Harness, para: str, line: str, case: Any, loc: MethodSym, tier: str,
                    origin: str) -> Counterexample:
    by_cobol = {s.cobol: s for s in h.slots}
    vals = [int(x) for x in line.split()]
    inputs: list[FieldValue] = []
    seen: set[str] = set()
    for sv, v in zip(h.state, vals, strict=False):
        key = sv.cobol + ("" if sv.index is None else f"({sv.index + 1})")
        if key in seen:
            continue
        seen.add(key)
        slot = by_cobol[sv.cobol]
        if sv.kind == "alnum":
            chars = [str(vv) for s2, vv in zip(h.state, vals, strict=False) if s2.cobol == sv.cobol
                     and s2.index == sv.index]
            shown = _fmt(slot, ",".join(chars))
        else:
            shown = _fmt(slot, str(v))
        inputs.append(FieldValue(field=key, value=shown, pic=None, location=f"state before {para}"))
    diffs: list[FieldDiff] = []
    classification: Classification | None = None
    if case.cand_throw:
        diffs.append(FieldDiff(location=f"after {para}", field=None, expected="normal completion",
                               actual=f"throws {case.cand_throw}"))
        classification = Classification(label="TARGET_CRASH", explanation="likely the target throws where COBOL "
                                        "completes normally")
    for name, exp, act in case.differences()[:8]:
        base = name.rsplit("_", 1)[0] if name not in by_cobol and "_" in name else name
        dslot = by_cobol.get(base)
        diffs.append(FieldDiff(location=f"after {para}", field=name, pic=None, expected=_fmt(dslot, exp),
                               actual=_fmt(dslot, act)))
    if diffs and classification is None and diffs[0].field:
        item = pc.program.resolve(diffs[0].field.split("_")[0]) or pc.program.resolve(diffs[0].field)
        if item is not None:
            m = Mismatch("VALUE_MISMATCH", f"after {para}", "", diffs[:1], [item])
            classification = classify(m, False)
    first = (diffs[0].field or "exception") if diffs else "?"
    sig = f"{tier}_MISMATCH {pc.program.program_id}::{para}:{first}"
    return Counterexample(
        id=f"cx_{pc.program.program_id}_{tier}_{re.sub(r'[^A-Za-z0-9]', '_', para)}", source_tier=tier,
        signature=sig, inputs={"state": line, "origin": origin}, input_fields=inputs[:40],
        expected={d.field or "outcome": d.expected for d in diffs}, actual={d.field or "outcome": d.actual for d in diffs},
        diffs=diffs, classification=classification,
        target_location=SourceRef(file=loc.file, line=loc.line, text=f"method {loc.name}"),
        repro=f"echo '{line}' | java -cp <out>/t2b/{pc.program.program_id}/{h.harness_class.split('_', 1)[1]}/h:"
              f"<candidate classes> {h.qualified_replay}",
        confirmed_concretely=True)


def _sig(cx: Counterexample, count: int) -> FailureSignature:
    return FailureSignature(signature=cx.signature, kind="UNIT_STATE_MISMATCH", location=cx.signature.split(" ", 1)[1],
                            count=count, severity=4, example_case=cx.inputs.get("state", "")[:60],
                            counterexample_id=cx.id)


# ---------------------------------------------------------------------------------------------
def _mutation_sanity(pl: Pipeline, pc: ProgramCtx, pt: ProgramT2b, uw: Path, h: Harness, ref: EmittedRef,
                     loc: MethodSym, k: int, tmo: float) -> tuple[int, dict[str, Any]]:
    n = pl.cfg.t2.mutants_fast if pl.req.mode == "fast" else pl.cfg.t2.mutants
    sites = find_mutants(pl.ws_target, "java", line_ranges={loc.file: [(loc.line, loc.end_line)]})
    muts = sample_mutants(sites, n, pl.effective_seed)
    killed = live = 0
    rows = []
    from verifier.langpacks.java.pack import JavaPack

    for i, m in enumerate(muts):
        mw = uw / f"mut{i}"
        tgt = mw / "tgt"
        if mw.exists():
            shutil.rmtree(mw)
        shutil.copytree(pl.ws_target, tgt, ignore=shutil.ignore_patterns(".verifier-build", "*.class"))
        apply_mutant(tgt, m)
        rel = mw.relative_to(pt.work).as_posix()
        srcs = [f"/w/{rel}/tgt/{s}" for s in JavaPack().sources(tgt)]
        hsrc = [f"/w/{uw.relative_to(pt.work).as_posix()}/src/{p.relative_to(uw / 'src').as_posix()}"
                for p in (uw / "src").rglob("*.java")]
        comp = jbmc.javac(pl.runner, pt.work, [*srcs, *hsrc], [COBOLRT_JAR, jbmc.CPROVER_JAR], f"/w/{rel}/cls",
                          extra_mounts=_mounts(pl))
        if not comp.ok:
            rows.append({"mutant": m.id, "result": "stillborn"})
            continue
        live += 1
        out = jbmc.run_jbmc(pl.runner, pt.work, [f"/w/{rel}/cls", COBOLRT_JAR], h.qualified_harness,
                            h.check_function, unwind=k, timeout_s=min(tmo, 120), tag=f"{uw.name}_mut{i}",
                            extra_mounts=_mounts(pl))
        hit = out.verdict == "COUNTEREXAMPLE"
        killed += int(hit)
        rows.append({"mutant": m.id, "operator": m.operator, "result": "killed" if hit else out.verdict})
    return killed, {"live": live, "killed": killed, "sampled": len(muts), "mutants": rows}


def validation_gate(pl: Pipeline, pc: ProgramCtx, irp: ir.IrProgram) -> TierResult | None:
    """Spec T2b.4: trust the reference only if (a) the IR interpreter reproduces GnuCOBOL on every T1
    case of the program and (b) the emitted reference reproduces the interpreter's paragraph
    transitions on those same executions. Returns None when trusted, else the unit result."""
    from verifier.tiers.t2_gate import check_gate

    return check_gate(pl, pc, irp)
