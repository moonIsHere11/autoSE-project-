"""T0b — static / structural checks over the tree-sitter index (one engine, three languages).

Checks (spec section 6, T0b): data mapping, forbidden representations, completeness, forbidden APIs,
integrity, anti-overfitting. Each finding is ERROR (fails T0) or WARNING.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from verifier.cobol.analysis import channels
from verifier.cobol.lexer import HEX, NUM, STR
from verifier.cobol.syntax import Program
from verifier.langpacks.base import ResolvedProgram, SymbolIndex
from verifier.langpacks.ts import normalise_number
from verifier.report.schema import Check, Finding, Report, Status

CHECKS = ("data_mapping", "forbidden_representation", "completeness", "forbidden_api", "integrity",
          "anti_overfitting")
INTEGRITY_CHECKS = {"integrity", "anti_overfitting"}

SUSPICIOUS_PATH_PATTERNS = [
    r"(^|/)expected(/|$)", r"case\.json", r"(^|/)cases?/case_", r"(^|/)(inputs|results)/",
    r"(^|/)corpus(/|$)", r"(^|/)verifier(/|$)", r"report\.json", r"(^|/)feedback(/|$)", r"(^|/)heldout",
    r"(^|/)evaluation(/|$)",
]
TRIVIAL_NUMBERS = {"0", "1", "-1", "2", *(str(10**k) for k in range(1, 19))}


@dataclass
class StaticInput:
    lang: str
    rules: dict[str, Any]
    index: SymbolIndex
    target_root: Path
    programs: list[tuple[Program, ResolvedProgram]]
    cobol_literals: set[str]
    previous: Report | None
    heldout_dirs: list[Path]
    dependency_files: dict[str, str] = field(default_factory=dict)  # name -> content (pom.xml, go.mod, ...)


@dataclass
class StaticResult:
    by_program: dict[str, list[Check]]
    integrity_clean: dict[str, bool]
    duration_s: float


def cobol_literal_values(programs: list[Program], tokens_by_program: dict[str, list[Any]]) -> set[str]:
    vals: set[str] = set()
    for p in programs:
        for t in tokens_by_program.get(p.program_id, []):
            if t.kind == NUM:
                n = normalise_number(t.text)
                if n is not None:
                    vals.add(n)
            elif t.kind in (STR, HEX):
                vals.add(t.value)
                vals.add(t.value.strip())
        for item in p.all_items():
            for cond in item.conditions:
                for lo, hi in cond.values_88:
                    for v in (lo, hi):
                        if v is not None:
                            vals.add(normalise_number(v.text) or v.text)
    return vals


def _type_base(type_text: str) -> str:
    t = re.sub(r"<.*>", "", type_text).strip()
    return t.split(".")[-1] if not t.endswith("[]") else t


def check_data_mapping(si: StaticInput, prog: Program, rp: ResolvedProgram) -> list[Finding]:
    out: list[Finding] = []
    rules = si.rules
    for item in prog.all_items():
        if item.is_filler or not item.is_elementary or item.level in (66, 88):
            continue
        m = rp.fields.get(item.name)
        if m is None:
            continue
        truth = item.declared_type()
        decl = m.get("declared")
        cref = f"{item.name} {item.pic_text()} ({item.file}:{item.line})"
        if decl:
            mism = _declared_mismatch(decl, truth)
            if mism:
                out.append(Finding(check="data_mapping", severity="ERROR",
                                   message=f"manifest declares {item.name} as {decl} but its PIC means {truth}: {mism}",
                                   cobol_ref=cref))
        ttype = m.get("target_type")
        if not ttype:
            continue
        loc = m.get("location")
        file, line = (loc[0], loc[1]) if loc else (None, None)
        base = _type_base(str(ttype))
        if item.is_numeric and item.pic is not None:
            p = item.pic
            if base in rules["float_types"]:
                out.append(Finding(check="forbidden_representation", severity="ERROR",
                                   message=f"decimal field {item.name} ({p.describe()}) is held in binary floating point `{ttype}` (`{m['target']}`); use an exact decimal (e.g. CobolDecimal / scaled long / BigDecimal)",
                                   file=file, line=line, cobol_ref=cref))
            elif base in rules["integer_types"]:
                cap = rules["integer_types"][base]
                need = p.digits + (-p.scale if p.scale < 0 else 0)
                if p.scale > 0:
                    out.append(Finding(check="data_mapping", severity="WARNING",
                                       message=f"{item.name} has {p.scale} decimal places but `{m['target']}` is an integer type `{ttype}`; it must hold the value scaled by 10^{p.scale}",
                                       file=file, line=line, cobol_ref=cref))
                if need > cap:
                    out.append(Finding(check="forbidden_representation", severity="ERROR",
                                       message=f"`{ttype}` cannot hold {need} digits required by {item.name} {p.raw}",
                                       file=file, line=line, cobol_ref=cref))
            elif base in rules["string_types"]:
                out.append(Finding(check="data_mapping", severity="WARNING",
                                   message=f"numeric field {item.name} is mapped to a string type `{ttype}`",
                                   file=file, line=line, cobol_ref=cref))
        elif item.pic is not None and item.pic.category in ("alphanumeric", "alphabetic"):
            if base in rules["float_types"] or base in rules["integer_types"]:
                out.append(Finding(check="data_mapping", severity="ERROR",
                                   message=f"alphanumeric field {item.name} PIC {item.pic.raw} is mapped to numeric type `{ttype}`",
                                   file=file, line=line, cobol_ref=cref))
    return out


def _declared_mismatch(decl: dict[str, Any], truth: dict[str, Any]) -> str | None:
    usage_norm = {"BINARY": "COMP", "PACKED-DECIMAL": "COMP-3"}
    kind = decl.get("kind")
    if kind in ("decimal", "binary"):
        if truth.get("kind") != "decimal":
            return f"kind {kind} vs {truth.get('kind')}"
        for k in ("digits", "scale"):
            if decl.get(k) != truth.get(k):
                return f"{k} {decl.get(k)} != {truth.get(k)}"
        if decl.get("signed") is not None and bool(decl.get("signed")) != bool(truth.get("signed")):
            return f"signed {decl.get('signed')} != {truth.get('signed')}"
        du = usage_norm.get(str(decl.get("usage")), decl.get("usage"))
        if du is not None and du != truth.get("usage"):
            return f"usage {decl.get('usage')} != {truth.get('usage')}"
        return None
    if kind in ("alnum", "alpha"):
        if truth.get("kind") not in ("alnum", "alpha"):
            return f"kind {kind} vs {truth.get('kind')}"
        if decl.get("length") != truth.get("length"):
            return f"length {decl.get('length')} != {truth.get('length')}"
    return None


def check_completeness(prog: Program, rp: ResolvedProgram) -> list[Finding]:
    out: list[Finding] = []
    if rp.type_sym is None:
        out.append(Finding(check="completeness", severity="ERROR",
                           message=f"no counterpart for PROGRAM-ID {prog.program_id} ({'; '.join(rp.notes) or 'naming convention found nothing'})",
                           cobol_ref=f"{prog.source_file}:{prog.line}"))
        return out
    for para in prog.paragraphs:
        if rp.unit_locations.get(para.name) is None:
            declared = rp.units.get(para.name)
            sev: Literal["ERROR", "WARNING"] = "ERROR" if (rp.source != "convention" and declared) else "WARNING"
            why = (f"manifest maps it to `{declared}` which does not exist" if declared and sev == "ERROR"
                   else "no method found by convention; unit-level tiers will be NOT_APPLICABLE")
            out.append(Finding(check="completeness", severity=sev,
                               message=f"paragraph {para.name}: {why}", cobol_ref=f"{para.file}:{para.line}"))
    return out


def check_forbidden_apis(si: StaticInput, files: set[str], declared_paths: set[str], uses_env: bool) -> list[Finding]:
    out: list[Finding] = []
    r = si.rules
    idx = si.index
    for call in idx.calls:
        if call.file not in files:
            continue
        for rx, cat, msg in r["forbidden_calls"]:
            if re.search(rx, call.callee):
                out.append(Finding(check="forbidden_api", severity="ERROR", message=f"`{call.callee}` {msg} [{cat}]",
                                   file=call.file, line=call.line, excerpt=idx.line_text(call.file, call.line).strip()))
        for rx, cat, msg in r.get("warning_calls", []):
            if re.search(rx, call.callee) and not (cat == "env" and uses_env):
                out.append(Finding(check="forbidden_api", severity="WARNING", message=f"`{call.callee}` {msg} [{cat}]",
                                   file=call.file, line=call.line))
    for new in idx.news:
        if new.file not in files:
            continue
        for rx, cat, msg in r["forbidden_new"]:
            if re.search(rx, new.callee) and not (cat == "clock" and new.args_text):
                out.append(Finding(check="forbidden_api", severity="ERROR", message=f"`new {new.callee}(...)` {msg} [{cat}]",
                                   file=new.file, line=new.line))
    for imp, file, line in idx.imports:
        if file not in files:
            continue
        for rx, cat, msg in r["forbidden_imports"]:
            if re.search(rx, imp):
                out.append(Finding(check="forbidden_api", severity="ERROR", message=f"import `{imp}`: {msg} [{cat}]",
                                   file=file, line=line))
    for site in [*idx.calls, *idx.news]:
        if site.file not in files:
            continue
        if any(re.search(rx, site.callee) for rx in r["file_open_calls"]):
            for s in site.string_args:
                name = s.strip()
                if name and name not in declared_paths and Path(name).name not in declared_paths:
                    out.append(Finding(check="forbidden_api", severity="ERROR",
                                       message=f"opens undeclared file path {name!r} (declared: {sorted(declared_paths) or 'none'})",
                                       file=site.file, line=site.line))
    for c in idx.catches:
        if c.file in files and c.swallows:
            out.append(Finding(check="forbidden_api", severity="ERROR",
                               message=f"catch-all handler ({', '.join(c.types)}) swallows errors (no rethrow / exit)",
                               file=c.file, line=c.line, excerpt=idx.line_text(c.file, c.line).strip()))
    return out


def check_integrity(si: StaticInput, files: set[str]) -> list[Finding]:
    out: list[Finding] = []
    idx = si.index
    own_prefixes = {t.qualified.rsplit(".", 1)[0] for t in idx.types if "." in t.qualified}
    allowed = list(si.rules.get("allowed_import_prefixes", []))
    for imp, file, line in idx.imports:
        if file not in files:
            continue
        if any(imp == a or imp.startswith(a + ".") for a in allowed):
            continue
        if any(imp == o or imp.startswith(o + ".") for o in own_prefixes):
            continue
        if si.lang == "python" and _python_local_module(si.target_root, imp):
            continue
        if si.lang == "go" and _go_local_import(si, imp):
            continue
        out.append(Finding(check="integrity", severity="ERROR",
                           message=f"dependency `{imp}` is not in the allowlist", file=file, line=line))
    for name, content in si.dependency_files.items():
        for dep in si.rules.get("parse_dependencies", lambda c: [])(content):
            if not any(dep.startswith(a) for a in si.rules.get("allowed_dependencies", [])):
                out.append(Finding(check="integrity", severity="ERROR",
                                   message=f"build dependency `{dep}` in {name} is not in the allowlist", file=name))
    held = [str(h) for h in si.heldout_dirs] + [h.name for h in si.heldout_dirs if h.name]
    for lit in idx.literals:
        if lit.kind != "str" or lit.file not in files:
            continue
        v = lit.value
        if any(re.search(p, v) for p in SUSPICIOUS_PATH_PATTERNS) or any(h and h in v for h in held):
            out.append(Finding(check="integrity", severity="ERROR",
                               message=f"string literal {v!r} refers to verifier/corpus/evaluation artefacts",
                               file=lit.file, line=lit.line))
    return out


def _python_local_module(root: Path, imp: str) -> bool:
    head = imp.split(".")[0]
    return (root / f"{head}.py").exists() or (root / head).is_dir() or any(root.rglob(f"{head}.py"))


def _go_local_import(si: StaticInput, imp: str) -> bool:
    mod = si.dependency_files.get("go.mod", "")
    m = re.search(r"^module\s+(\S+)", mod, re.M)
    return bool(m and imp.startswith(m.group(1)))


def counterexample_values(prev: Report) -> set[str]:
    vals: set[str] = set()

    def add(v: Any) -> None:
        if v is None:
            return
        s = str(v)
        n = normalise_number(s.strip())
        if n is not None:
            vals.add(n)
        elif s.strip():
            vals.add(s.strip())

    for unit in prev.units:
        for tier in unit.tiers.values():
            for cx in tier.counterexamples:
                for fv in cx.input_fields:
                    add(fv.value)
                for d in cx.diffs:
                    add(d.expected)
                    add(d.actual)
                for line in cx.inputs.get("stdin_lines", []) if isinstance(cx.inputs.get("stdin_lines"), list) else []:
                    add(line)
    return vals


def check_anti_overfitting(si: StaticInput, files: set[str]) -> list[Finding]:
    if si.previous is None:
        return []
    cx_vals = counterexample_values(si.previous)
    out: list[Finding] = []
    for lit in si.index.literals:
        if lit.file not in files:
            continue
        v = lit.value if lit.kind != "str" else lit.value.strip()
        if not v or v in TRIVIAL_NUMBERS or (lit.kind == "str" and len(v) <= 1):
            continue
        if v in cx_vals and v not in si.cobol_literals:
            out.append(Finding(check="anti_overfitting", severity="ERROR",
                               message=f"possible special-casing of a counterexample: literal {lit.text} matches a previous counterexample value and does not appear in the COBOL source",
                               file=lit.file, line=lit.line, excerpt=si.index.line_text(lit.file, lit.line).strip()))
    return out


def run_t0b(si: StaticInput) -> StaticResult:
    start = time.monotonic()
    owned: dict[str, str] = {}  # file -> program id
    for prog, rp in si.programs:
        if rp.type_sym is not None:
            owned.setdefault(rp.type_sym.file, prog.program_id)
    all_files = set(si.index.files)
    shared = {f for f in all_files if f not in owned}
    by_program: dict[str, list[Check]] = {}
    integrity: dict[str, bool] = {}
    for prog, rp in si.programs:
        files = {f for f, pid in owned.items() if pid == prog.program_id} | shared
        declared = set(rp.files.values()) | {Path(v).name for v in rp.files.values()}
        uses_env = any(a.source == "env" for a in channels(prog).accepts)
        findings: dict[str, list[Finding]] = {c: [] for c in CHECKS}
        for f in check_data_mapping(si, prog, rp):
            findings[f.check].append(f)
        for f in check_completeness(prog, rp):
            findings["completeness"].append(f)
        for f in check_forbidden_apis(si, files, declared, uses_env):
            findings["forbidden_api"].append(f)
        for f in check_integrity(si, files):
            findings["integrity"].append(f)
        for f in check_anti_overfitting(si, files):
            findings["anti_overfitting"].append(f)
        uses_float = any(t[1] in files for t in si.index.float_uses)
        if uses_float and not any(i.usage in ("COMP-1", "COMP-2") for i in prog.all_items()):
            first = next(t for t in si.index.float_uses if t[1] in files)
            findings["forbidden_representation"].append(Finding(
                check="forbidden_representation", severity="WARNING",
                message=f"binary floating point type `{first[0]}` used; COBOL decimal arithmetic is exact",
                file=first[1], line=first[2]))
        checks = []
        for name in CHECKS:
            fs = findings[name]
            status = Status.FAIL if any(f.severity == "ERROR" for f in fs) else Status.PASS
            checks.append(Check(name=name, status=status, findings=fs))
        by_program[prog.program_id] = checks
        integrity[prog.program_id] = not any(
            f.severity == "ERROR" for n in INTEGRITY_CHECKS for f in findings[n]
        )
    return StaticResult(by_program, integrity, time.monotonic() - start)
