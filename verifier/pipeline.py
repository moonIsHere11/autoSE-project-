"""The verification pipeline: workspace, COBOL front end, target index, tiers, report.

Gating (DECISIONS D9): T0a build FAIL ⇒ T1–T3 SKIPPED (nothing can run); any T0 FAIL or T1 FAIL ⇒
T2/T3 SKIPPED; out-of-scope programs ⇒ T1+ NOT_APPLICABLE "uses <feature>".
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import importlib
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from verifier.cobol import analysis
from verifier.cobol.gnucobol import CobolBinary
from verifier.cobol.lexer import Token, tokenize
from verifier.cobol.parser import ParseError, parse_source
from verifier.cobol.preprocess import Preprocessed, find_cobol_sources, preprocess_all
from verifier.cobol.syntax import Program
from verifier.config import VERIFIER_VERSION, VerifierConfig
from verifier.langpacks.base import LangPack, PackContext, ResolvedProgram, SymbolIndex
from verifier.manifest import Manifest, load_manifest
from verifier.report.feedback import write_feedback
from verifier.report.render_md import render_summary
from verifier.report.schema import (
    Check,
    ProgramResult,
    Report,
    RunInfo,
    Scope,
    Status,
    TierResult,
    UnitResult,
)
from verifier.report.scoring import finalise_unit, summarise
from verifier.sandbox.docker_runner import DockerRunner
from verifier.sandbox.limits import SandboxLimits
from verifier.tiers.t0_build import run_t0a
from verifier.tiers.t0_static import StaticInput, cobol_literal_values, run_t0b


class VerifierError(RuntimeError):
    """Configuration / infrastructure error: exit code 2."""


class HeldOutViolation(VerifierError):
    pass


IGNORE_COPY = shutil.ignore_patterns(".git", "__pycache__", ".verifier-build", "*.class", ".mypy_cache")


@dataclass
class VerifyRequest:
    cobol: Path
    target: Path
    lang: str
    out: Path
    manifest: Path | None = None
    mode: str = "fast"
    units: list[str] | None = None
    tiers: list[int] | None = None
    seed: int = 0
    previous_report: Path | None = None
    argv: list[str] = field(default_factory=list)

    def selected_tiers(self) -> list[int]:
        if self.tiers is not None:
            return sorted(set(self.tiers))
        return [0, 1, 2] if self.mode == "fast" else [0, 1, 2, 3]


@dataclass
class ProgramCtx:
    program: Program
    pre: Preprocessed
    tokens: list[Token]
    resolved: ResolvedProgram | None = None
    out_of_scope: list[str] = field(default_factory=list)
    nondeterminism: list[str] = field(default_factory=list)
    channels: analysis.Channels | None = None
    tiers: dict[str, TierResult] = field(default_factory=dict)
    unit_tiers: dict[str, dict[str, TierResult]] = field(default_factory=dict)
    integrity_clean: bool = True
    selected_paragraphs: list[str] = field(default_factory=list)


def optional(module: str, attr: str) -> Any:
    """Look up a tier/pack implementation; None while the milestone that adds it is pending."""
    try:
        mod = importlib.import_module(module)
    except ModuleNotFoundError as exc:
        if exc.name != module:
            raise
        return None
    return getattr(mod, attr)


_PACKS = {"java": ("verifier.langpacks.java.pack", "JavaPack"),
          "python": ("verifier.langpacks.python.pack", "PythonPack"),
          "go": ("verifier.langpacks.go.pack", "GoPack")}


def get_pack(lang: str) -> LangPack:
    if lang not in _PACKS:
        raise VerifierError(f"unknown language {lang!r}")
    cls = optional(*_PACKS[lang])
    if cls is None:
        raise VerifierError(f"the {lang} language pack is not implemented yet (milestone M3)")
    pack: LangPack = cls()
    return pack


def effective_seed(seed: int, iteration: int) -> int:
    h = hashlib.sha256(f"{seed}:{iteration}".encode()).digest()
    return int.from_bytes(h[:4], "big")


def _stub(reason: str) -> TierResult:
    return TierResult(status=Status.NOT_APPLICABLE, reason=reason, stub=True)


class Pipeline:
    def __init__(self, req: VerifyRequest, config: VerifierConfig) -> None:
        self.req = req
        self.cfg = config
        self.timings: dict[str, float] = {}
        self.errors: list[str] = []
        self.programs: list[ProgramCtx] = []
        self.manifest: Manifest | None = None
        self.previous: Report | None = None
        self.index: SymbolIndex | None = None
        self.pack = get_pack(req.lang)
        self.runner = DockerRunner(config.image, SandboxLimits.from_config(config.limits))
        self.selected = [f"T{t}" for t in req.selected_tiers()]
        self.toolchain: dict[str, Any] = {}
        self.cobol_bins: dict[str, CobolBinary] = {}

    @property
    def iteration(self) -> int:
        return (self.previous.run.iteration + 1) if self.previous else 1

    @property
    def effective_seed(self) -> int:
        return effective_seed(self.req.seed, self.iteration)

    # ------------------------------------------------------------------------------------------
    def guard_heldout(self) -> None:
        held = self.cfg.all_heldout_dirs()
        paths = {"--cobol": self.req.cobol, "--target": self.req.target, "--out": self.req.out,
                 "--manifest": self.req.manifest, "--previous-report": self.req.previous_report}
        for flag, p in paths.items():
            if p is None:
                continue
            rp = Path(p).expanduser().resolve()
            for h in held:
                if rp == h or rp.is_relative_to(h) or h.is_relative_to(rp):
                    raise HeldOutViolation(
                        f"{flag} {p} overlaps the held-out evaluation directory {h}; the verifier never reads held-out data"
                    )

    def prepare(self) -> None:
        out = self.req.out
        out.mkdir(parents=True, exist_ok=True)
        ws = out / "workspace"
        if ws.exists():
            shutil.rmtree(ws)
        for name, src in (("cobol", self.req.cobol), ("target", self.req.target)):
            if not src.is_dir():
                raise VerifierError(f"{name} repo {src} is not a directory")
            shutil.copytree(src, ws / name, ignore=IGNORE_COPY)
        if self.req.manifest is not None:
            self.manifest = load_manifest(self.req.manifest, self.req.lang)
        if self.req.previous_report is not None:
            self.previous = Report.load(str(self.req.previous_report))
        self.runner.check_available()
        self.toolchain = self.runner.toolchain_versions()

    @property
    def ws_cobol(self) -> Path:
        return self.req.out / "workspace" / "cobol"

    @property
    def ws_target(self) -> Path:
        return self.req.out / "workspace" / "target"

    def runtime_dir(self) -> Path | None:
        d = Path(__file__).resolve().parents[1] / "runtimes" / "build"
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
        return d

    def pack_ctx(self) -> PackContext:
        return PackContext(self.cfg, self.runner, self.ws_target, self.manifest, self.runtime_dir())

    # ------------------------------------------------------------------------------------------
    def cobol_frontend(self) -> None:
        start = time.monotonic()
        sources = find_cobol_sources(self.ws_cobol, self.cfg.cobol)
        if not sources:
            raise VerifierError(f"no COBOL programs (PROGRAM-ID + PROCEDURE DIVISION) found under {self.req.cobol}")
        pre = preprocess_all(self.runner, self.cfg.cobol, self.ws_cobol, sources, Path(self.cfg.cache_dir))
        for rel in sources:
            p = pre[rel]
            if not p.ok:
                self.errors.append(f"cobc -E failed for {rel}: {p.diagnostics.strip()[:500]}")
                continue
            try:
                toks = tokenize(p.lines)
                progs = parse_source(toks, rel)
            except (ParseError, ValueError) as exc:
                self.errors.append(f"cannot parse {rel}: {exc}")
                continue
            for prog in progs:
                ctx = ProgramCtx(prog, p, toks)
                ctx.out_of_scope = analysis.out_of_scope(prog)
                ctx.nondeterminism = analysis.nondeterminism(prog)
                ctx.channels = analysis.channels(prog)
                self.programs.append(ctx)
        self._select_units()
        self.timings["frontend"] = time.monotonic() - start

    def _select_units(self) -> None:
        wanted = [u.upper() for u in (self.req.units or [])]
        for pc in self.programs:
            paras = [p.name for p in pc.program.paragraphs] or ["(MAIN)"]
            if not wanted:
                pc.selected_paragraphs = paras
                continue
            sel = [p for p in paras if pc.program.program_id in wanted or f"{pc.program.program_id}::{p}" in wanted]
            pc.selected_paragraphs = sel
        if wanted and not any(pc.selected_paragraphs for pc in self.programs):
            raise VerifierError(f"--units {self.req.units} matched no unit")

    def active(self) -> list[ProgramCtx]:
        return [pc for pc in self.programs if pc.selected_paragraphs]

    def target_index(self) -> None:
        start = time.monotonic()
        self.index = self.pack.index(self.ws_target)
        ctx = self.pack_ctx()
        for pc in self.programs:
            entry = self.manifest.program(pc.program.program_id) if self.manifest else None
            pc.resolved = self.pack.resolve_program(ctx, self.index, pc.program, entry)
        self.timings["index"] = time.monotonic() - start

    # ------------------------------------------------------------------------------------------
    def tier0(self) -> None:
        start = time.monotonic()
        assert self.index is not None
        java_ver = str(self.toolchain.get("javac" if self.req.lang == "java" else self.req.lang, ""))
        t0a, _build = run_t0a(self.pack, self.pack_ctx(), java_ver)
        cobol_lits = cobol_literal_values([pc.program for pc in self.programs],
                                          {pc.program.program_id: pc.tokens for pc in self.programs})
        dep_files = {}
        for name in ("pom.xml", "build.gradle", "go.mod", "requirements.txt", "pyproject.toml"):
            p = self.ws_target / name
            if p.exists():
                dep_files[name] = p.read_text("utf-8", errors="replace")
        si = StaticInput(self.req.lang, self.pack.static_rules(), self.index, self.ws_target,
                         [(pc.program, pc.resolved) for pc in self.active() if pc.resolved is not None],
                         cobol_lits, self.previous, self.cfg.all_heldout_dirs(), dep_files)
        st = run_t0b(si)
        for pc in self.active():
            checks: list[Check] = []
            build_check = t0a.checks[0] if t0a.checks else Check(name="build", status=t0a.status, reason=t0a.reason)
            checks.append(build_check)
            checks.extend(st.by_program.get(pc.program.program_id, []))
            failed = t0a.status != Status.PASS or any(c.status == Status.FAIL for c in checks)
            status: Status
            reason: str | None
            if t0a.status in (Status.ERROR, Status.TIMEOUT):
                status, reason = t0a.status, t0a.reason
            else:
                status, reason = (Status.FAIL if failed else Status.PASS), None
            scope = Scope(level="program", what="build + static checks (data mapping, representations, "
                          "completeness, forbidden APIs, integrity, anti-overfitting)",
                          tools=t0a.scope.tools if t0a.scope else [], commands=t0a.scope.commands if t0a.scope else [])
            pc.tiers["T0"] = TierResult(status=status, reason=reason, method="build+static", scope=scope,
                                        checks=checks, duration_s=t0a.duration_s + st.duration_s,
                                        sub={"T0a": t0a})
            pc.integrity_clean = st.integrity_clean.get(pc.program.program_id, True)
        self.timings["T0"] = time.monotonic() - start

    def tier1(self) -> None:
        start = time.monotonic()
        run_t1 = optional("verifier.tiers.t1_diff", "run_t1")
        if run_t1 is None:
            for pc in self.active():
                pc.tiers["T1"] = _stub("T1 differential testing not implemented yet (milestone M2)")
            return
        for pc in self.active():
            gate = self._gate_t1(pc)
            if gate is not None:
                pc.tiers["T1"] = gate
                continue
            pc.tiers["T1"] = run_t1(self, pc)
        self.timings["T1"] = time.monotonic() - start

    def _gate_t1(self, pc: ProgramCtx) -> TierResult | None:
        if pc.out_of_scope:
            return TierResult.not_applicable("; ".join(pc.out_of_scope))
        t0 = pc.tiers.get("T0")
        if t0 is not None and t0.sub.get("T0a") is not None and t0.sub["T0a"].status != Status.PASS:
            return TierResult.skipped(f"gated by T0a build {t0.sub['T0a'].status.value}")
        return None

    def _gate_t2_t3(self, pc: ProgramCtx) -> TierResult | None:
        if pc.out_of_scope:
            return TierResult.not_applicable("; ".join(pc.out_of_scope))
        for k in ("T0", "T1"):
            t = pc.tiers.get(k)
            if t is not None and t.status in (Status.FAIL, Status.ERROR, Status.TIMEOUT):
                return TierResult.skipped(f"gated by {k} {t.status.value}")
            if t is not None and t.status == Status.SKIPPED:
                return TierResult.skipped(f"gated by {k} SKIPPED")
        return None

    def tier2(self) -> None:
        start = time.monotonic()
        for pc in self.active():
            gate = self._gate_t2_t3(pc)
            if gate is not None:
                pc.tiers["T2"] = gate
                continue
            run_t2a = optional("verifier.tiers.t2_exhaustive", "run_t2a")
            if run_t2a is None:
                pc.tiers["T2"] = TierResult(status=Status.NOT_APPLICABLE, stub=True,
                                            reason="T2 not implemented yet (milestones M3/M4)",
                                            sub={"T2a": _stub("T2a not implemented yet (M3)"),
                                                 "T2b": _stub("T2b not implemented yet (M4)")})
                continue
            pc.tiers["T2"] = run_t2a(self, pc)
        self.timings["T2"] = time.monotonic() - start

    def tier3(self) -> None:
        start = time.monotonic()
        for pc in self.active():
            gate = None
            t1 = pc.tiers.get("T1")
            if pc.out_of_scope:
                gate = TierResult.not_applicable("; ".join(pc.out_of_scope))
            elif t1 is not None and t1.status == Status.FAIL:
                gate = TierResult.skipped("gated by T1 FAIL")
            pc.tiers["T3"] = gate or _stub("T3 contracts not implemented yet (milestone M5)")
        self.timings["T3"] = time.monotonic() - start

    # ------------------------------------------------------------------------------------------
    def assemble(self) -> Report:
        iteration = self.iteration
        run = RunInfo(
            cobol=str(self.req.cobol), target=str(self.req.target), lang=self.req.lang,
            mode="full" if self.req.mode == "full" else "fast", tiers=self.req.selected_tiers(),
            seed=self.req.seed, iteration=iteration, effective_seed=self.effective_seed,
            previous_report=str(self.req.previous_report) if self.req.previous_report else None,
            manifest=str(self.req.manifest) if self.req.manifest else None,
            units_filter=self.req.units, argv=self.req.argv,
        )
        flags = self.programs[0].pre.flags if self.programs else self.cfg.cobol.flags()
        config = {
            "cobc_flags": ["-x", *flags],
            "runtime_env": self.cfg.cobol.runtime_env,
            "normalisers": self.cfg.normalisers,
            "acceptance": self.cfg.acceptance.model_dump(),
            "limits": self.cfg.limits.model_dump(),
            "t1": self.cfg.t1.model_dump(),
            "t2": self.cfg.t2.model_dump(),
            "fake_time": self.cfg.fake_time,
        }
        report = Report(verifier_version=VERIFIER_VERSION,
                        generated_at=_dt.datetime.now(_dt.UTC).isoformat(timespec="seconds"),
                        run=run, toolchain=self.toolchain, config=config, errors=list(self.errors))
        for pc in self.active():
            prog = pc.program
            for key in ("T0", "T1", "T2", "T3"):
                if key not in pc.tiers:
                    pc.tiers[key] = TierResult.skipped("not selected")
            report.programs.append(ProgramResult(
                id=prog.program_id, cobol_file=prog.source_file,
                paragraphs=[p.name for p in prog.paragraphs],
                out_of_scope=pc.out_of_scope, nondeterminism=pc.nondeterminism,
                channels=pc.channels.summary() if pc.channels else {},
                target={"symbol": pc.resolved.type_sym.qualified if pc.resolved and pc.resolved.type_sym else None,
                        "run_command": pc.resolved.run_command if pc.resolved else None,
                        "mapping_source": pc.resolved.source if pc.resolved else None,
                        "notes": pc.resolved.notes if pc.resolved else []},
                tiers={k: v for k, v in pc.tiers.items() if k in ("T0", "T1", "T2")},
            ))
            for para in pc.selected_paragraphs:
                unit = UnitResult(id=f"{prog.program_id}::{para}", program=prog.program_id, paragraph=para,
                                  target_symbol=pc.resolved.units.get(para) if pc.resolved else None,
                                  integrity_clean=pc.integrity_clean,
                                  repro=[])
                for key in ("T0", "T1", "T2", "T3"):
                    t = pc.unit_tiers.get(para, {}).get(key) or pc.tiers[key]
                    unit.tiers[key] = t
                t1 = unit.tiers.get("T1")
                if t1 is not None and t1.coverage is not None:
                    t1 = t1.model_copy(update={"unit_covered": para in t1.coverage.covered_paragraphs})
                    unit.tiers["T1"] = t1
                unit.repro = sorted({cx.repro for t in unit.tiers.values() for cx in t.counterexamples if cx.repro})
                finalise_unit(unit, self.selected, self.cfg.acceptance)
                report.units.append(unit)
        report.summary = summarise(report, {k: v for k, v in self.timings.items() if k.startswith("T")})
        return report

    def write(self, report: Report) -> None:
        out = self.req.out
        (out / "report.json").write_text(report.to_json(), "utf-8")
        (out / "summary.md").write_text(render_summary(report), "utf-8")
        write_feedback(report, out, self.previous, self.cfg.feedback_token_cap)

    def run(self) -> Report:
        self.guard_heldout()
        self.prepare()
        self.cobol_frontend()
        self.target_index()
        sel = self.req.selected_tiers()
        if 0 in sel:
            self.tier0()
        if 1 in sel:
            self.tier1()
        if 2 in sel:
            self.tier2()
        if 3 in sel:
            self.tier3()
        report = self.assemble()
        self.write(report)
        return report
