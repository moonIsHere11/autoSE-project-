"""T3 — contracts from the COBOL side, checked by OpenJML ESC (Java). Spec section 6, T3.

Per program: copy the target into the workspace, insert one generated JML contract above each unit's
method (`langpacks/java/jml.py`), optionally insert loop-invariant *hints* proposed by the generation
team (`.verifier/invariants.json` in the target repo — checked by the tool, never trusted), and run
OpenJML once for all units. Each unit is classified with spike S3's table.

A contract violation is only reported as FAIL when a concrete counterexample confirms it (the unit's
T1u result, which runs the validated reference against the candidate on random states); otherwise it
is NOT_APPLICABLE ("ESC warning not confirmed") — principle 4, as recommended by S3.
Python T3 (CrossHair contracts) lives in t3_crosshair.py; Go is NOT_APPLICABLE (Gobra is a stretch goal).
"""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from verifier.cobol import ir
from verifier.langpacks import ts
from verifier.langpacks.java import openjml
from verifier.langpacks.java.jml import Contract, ContractUnsupported, build_contract
from verifier.langpacks.java.pack import BUILD_DIR, COBOLRT_JAR, JavaPack
from verifier.manifest import camel
from verifier.report.schema import Scope, Status, TierResult, ToolInfo
from verifier.sandbox.docker_runner import Mount

if TYPE_CHECKING:
    from verifier.langpacks.base import MethodSym
    from verifier.pipeline import Pipeline, ProgramCtx

METHOD = "deductive_verification"
HINTS_FILE = ".verifier/invariants.json"


def run_t3(pl: Pipeline, pc: ProgramCtx) -> dict[str, TierResult]:
    paras = pc.selected_paragraphs
    if pl.req.lang == "go":
        return {p: TierResult.not_applicable("no Go contract checker (Gobra is a documented stretch goal)", METHOD)
                for p in paras}
    if pl.req.lang == "python":
        from verifier.pipeline import optional

        run_py = optional("verifier.tiers.t3_crosshair", "run_t3_python")
        if run_py is None:
            return {p: TierResult(status=Status.NOT_APPLICABLE, stub=True, reason="Python T3 not implemented yet")
                    for p in paras}
        res_py: dict[str, TierResult] = run_py(pl, pc)
        return res_py
    out: dict[str, TierResult] = {}
    try:
        irp = ir.lower_program(pc.program)
    except Exception as exc:  # our model failed, never the candidate
        return {p: TierResult.error(f"COBOL IR lowering failed: {exc}", METHOD) for p in paras}
    res = pc.resolved
    if res is None or res.type_sym is None:
        return {p: TierResult.not_applicable("no target class for the program", METHOD) for p in paras}
    cand_fields = {f.name: f.type_text for f in res.type_sym.fields}
    mapping: dict[str, dict[str, Any]] = {k: dict(v) for k, v in res.fields.items()}
    for item in pc.program.all_items():
        if item.name not in mapping and camel(item.name) in cand_fields:
            mapping[item.name] = {"target": camel(item.name), "target_type": cand_fields[camel(item.name)]}
    targets = {str(v.get("target")) for v in mapping.values()}
    index = pl.index
    unmapped = []
    for f in res.type_sym.fields:
        if f.name in targets:
            continue
        line = index.line_text(f.file, f.line) if index is not None else ""
        if re.search(r"\b(final|static)\b", line):
            continue
        unmapped.append(f.name)
    # ---- contracts per unit -------------------------------------------------------------------
    plans: dict[str, tuple[Contract, MethodSym, list[str]]] = {}
    for para in paras:
        p = irp.paragraph(para)
        if p is None:
            out[para] = TierResult.not_applicable(f"paragraph {para} not in the IR", METHOD)
            continue
        if p.t2_eligibility is not None:
            out[para] = TierResult.not_applicable(f"no contract generated: {p.t2_eligibility}", METHOD)
            continue
        m = res.units.get(para)
        loc = res.unit_locations.get(para)
        if not m or loc is None:
            out[para] = TierResult.not_applicable(f"no target method for paragraph {para}", METHOD)
            continue
        closure = [para] + [x for x in ir.perform_closure(irp, para) if x != para]
        try:
            c = build_contract(irp, closure, cand_fields, mapping, unmapped)
        except ContractUnsupported as exc:
            out[para] = TierResult.not_applicable(exc.reason, METHOD)
            continue
        plans[para] = (c, loc, closure)
    if not plans:
        return out
    # ---- instrument a copy --------------------------------------------------------------------
    work = pl.req.out / "t3" / pc.program.program_id
    if work.exists():
        shutil.rmtree(work)
    src = work / "src"
    shutil.copytree(pl.ws_target, src, ignore=shutil.ignore_patterns(BUILD_DIR, "*.class", ".git"))
    hints = _load_hints(pl.ws_target)
    per_file: dict[str, list[tuple[int, str]]] = {}
    unit_methods = {str(res.units[p]): p for p in plans}
    for para, (c, loc, _cl) in plans.items():
        indent = re.match(r"\s*", _line(src / loc.file, loc.line)).group(0)  # type: ignore[union-attr]
        per_file.setdefault(loc.file, []).append((loc.line, c.jml(indent)))
        for h in hints.get(str(res.units[para]), []):
            per_file[loc.file].append((int(h["line"]), f"//@ maintaining {h['invariant']};"))
    for rel, inserts in per_file.items():
        path = src / rel
        lines = path.read_text("utf-8").split("\n")
        for ln, text in sorted(inserts, key=lambda x: -x[0]):
            lines.insert(ln - 1, text)
        path.write_text("\n".join(lines), "utf-8")
    loops = {para: _has_unannotated_loop(pl, loc, hints.get(str(res.units[para]), []))
             for para, (_c, loc, _cl) in plans.items()}
    calls = {para: _calls_unspecified(pl, loc, set(unit_methods)) for para, (_c, loc, _cl) in plans.items()}
    # ---- run OpenJML ---------------------------------------------------------------------------
    files = [f"/w/src/{s}" for s in JavaPack().sources(src)]
    per = int(pl.cfg.t3.per_method_timeout_s)
    wall = 60 + len(plans) * (per + 10)  # OpenJML has ~10 s fixed start-up (spike S3)
    mounts = []
    rd = pl.runtime_dir()
    if rd is not None:
        mounts.append(Mount(rd, "/opt/cobolrt", True))
    start = time.monotonic()
    esc = openjml.run_esc(pl.runner, work, files, per_method_timeout=per, wall_s=min(wall, pl.cfg.t3.timeout_s),
                          classpath=[COBOLRT_JAR], methods=sorted(unit_methods), extra_mounts=mounts)
    (work / "esc_command.txt").write_text(esc.command, "utf-8")
    dur = time.monotonic() - start
    for para, (c, _loc, closure) in plans.items():
        method = str(res.units[para])
        v = openjml.classify(esc, method, has_unannotated_loop=loops[para], calls_unspecified=calls[para])
        scope = Scope(level="unit", what=_what(c, closure), domain="all states satisfying the generated requires "
                      "(every touched numeric field within its PIC)", bound="unbounded (deductive)",
                      oracle="contracts generated from the COBOL IR and PICTUREs",
                      tools=[ToolInfo(name="openjml", version=str(pl.toolchain.get("openjml", "21.0.28")))],
                      commands=[esc.command])
        details = {"contract": c.jml(""), "notes": c.notes, "esc_seconds": v.seconds,
                   "warnings": [f"{w.key} at {w.file}:{w.line} {w.detail}" for w in v.warnings][:10]}
        if v.status == Status.PASS:
            out[para] = TierResult(status=Status.PASS, method=METHOD, scope=scope, duration_s=dur / len(plans),
                                   details={**details, "functional_postcondition": c.functional})
        elif v.status == Status.FAIL:
            t1u = pc.unit_tiers.get(para, {}).get("T1u")
            if t1u is not None and t1u.status == Status.FAIL:
                out[para] = TierResult(status=Status.FAIL, method=METHOD, scope=scope, reason=v.reason,
                                       counterexamples=t1u.counterexamples, failure_signatures=t1u.failure_signatures,
                                       details=details)
            else:
                out[para] = TierResult(status=Status.NOT_APPLICABLE, method=METHOD, details=details,
                                       reason=f"ESC reports {v.reason}, but no concrete counterexample confirms it "
                                       "(T1u " + (t1u.status.value if t1u else "not available") + ")")
        else:
            # ERROR / TIMEOUT / NOT_APPLICABLE: no positive result, so no scope is claimed
            out[para] = TierResult(status=v.status, method=METHOD, reason=v.reason, details=details)
    return out


def _what(c: Contract, closure: list[str]) -> str:
    kinds = ["PIC-domain requires/ensures", "assignable frame"] + (["exact functional postcondition"]
                                                                    if c.functional else [])
    return f"JML contract ({', '.join(kinds)}) for {', '.join(closure)}"


def _line(path: Path, n: int) -> str:
    lines = path.read_text("utf-8").split("\n")
    return lines[n - 1] if 0 < n <= len(lines) else ""


def _load_hints(root: Path) -> dict[str, list[dict[str, Any]]]:
    """Loop-invariant hints proposed by the generation team (never trusted: OpenJML checks them)."""
    p = root / HINTS_FILE
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text("utf-8"))
    except ValueError:
        return {}
    return {str(k): [h for h in v if isinstance(h, dict) and "line" in h and "invariant" in h]
            for k, v in data.items() if isinstance(v, list)}


def _method_node(pl: Pipeline, loc: MethodSym) -> Any:
    data = (pl.ws_target / loc.file).read_bytes()
    tree = ts.parser_for("java").parse(data)
    for n in ts.walk(tree.root_node):
        if n.type == "method_declaration" and ts.line(n) == loc.line:
            return n
    return None


def _has_unannotated_loop(pl: Pipeline, loc: MethodSym, hints: list[dict[str, Any]]) -> bool:
    node = _method_node(pl, loc)
    if node is None:
        return False
    hinted = {int(h["line"]) for h in hints}
    return any(n.type in ("for_statement", "while_statement", "do_statement", "enhanced_for_statement")
               and ts.line(n) not in hinted for n in ts.walk(node))


def _calls_unspecified(pl: Pipeline, loc: MethodSym, contracted: set[str]) -> bool:
    node = _method_node(pl, loc)
    if node is None:
        return False
    for n in ts.walk(node):
        obj = n.child_by_field_name("object") if n.type == "method_invocation" else None
        if n.type == "method_invocation" and (obj is None or ts.text(obj) == "this"):
            name = ts.text(n.child_by_field_name("name"))
            if name not in contracted:
                return True
    return False
