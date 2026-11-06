"""T2a — exhaustive small-domain proof (spec section 6, T2a).

Applies when a program's whole input space is finite and smaller than `exhaustive_limit`:
a fixed number of stdin ACCEPTs (none inside a loop), no input files, no command-line/environment
inputs, and small fields. Every input in the declared domain is run on GnuCOBOL and on the target;
an all-match result is `PASS` with `method: exhaustive` — a proof over the declared domain, which
is recorded verbatim in `scope.domain`.

Declared domain per ACCEPTed field (from spike S6):
* numeric DISPLAY: every value of the PIC whose canonical text `[-]digits[.digits]` fits the ACCEPT
  window (the field's byte length), plus `-0` for signed fields;
* numeric COMP / BINARY / COMP-3 / COMP-5 (whole line is read): every value of the PIC, canonical;
* alphanumeric/alphabetic X(n)/A(n): every string of printable ASCII (0x20–0x7E; alphabetic: letters
  and space) of exactly n characters.
Inputs outside the domain (EOF before the last ACCEPT, extra lines, non-canonical texts) are not
covered by the proof; T1 samples them.
"""

from __future__ import annotations

import itertools
import math
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from verifier.cobol import analysis
from verifier.cobol.datadiv import DataItem
from verifier.inputs.encode import from_scaled
from verifier.inputs.strategies import Generator, ProgramInputs, minimal_text
from verifier.langpacks.base import NotApplicable
from verifier.report.schema import Exclusion, Scope, Status, TierResult, ToolInfo

if TYPE_CHECKING:
    from verifier.pipeline import Pipeline, ProgramCtx

METHOD = "exhaustive"
_PRINTABLE = [chr(c) for c in range(0x20, 0x7F)]
_ALPHA = [" ", *[chr(c) for c in range(ord("A"), ord("Z") + 1)], *[chr(c) for c in range(ord("a"), ord("z") + 1)]]


@dataclass
class FieldDomain:
    field: str
    pic: str
    texts: list[str]
    description: str


@dataclass
class Domain:
    fields: list[FieldDomain]

    @property
    def size(self) -> int:
        return math.prod(len(f.texts) for f in self.fields) if self.fields else 1

    def describe(self) -> str:
        parts = [f"stdin line {i + 1} → {f.field} PIC {f.pic}: {f.description} ({len(f.texts)} values)"
                 for i, f in enumerate(self.fields)]
        head = f"{self.size} inputs = product of: " if self.fields else "the single empty input"
        return head + "; ".join(parts) + ("; stdin has exactly one line per ACCEPT" if self.fields else "")

    def enumerate(self) -> list[list[str]]:
        return [list(combo) for combo in itertools.product(*(f.texts for f in self.fields))]


def _numeric_texts(item: DataItem, limit: int) -> tuple[list[str], str] | NotApplicable:
    pic = item.pic
    assert pic is not None
    if "P" in pic.expanded:
        return NotApplicable(f"{item.name}: PIC {pic.raw} uses P scaling (domain not enumerated)")
    n_values = (10**pic.digits) * (2 if pic.signed else 1)
    if n_values > limit:
        return NotApplicable(f"{item.name}: PIC {pic.raw} has {n_values:,} values (> exhaustive limit {limit:,})")
    usage = item.usage.upper()
    lo = -(10**pic.digits - 1) if pic.signed else 0
    hi = 10**pic.digits - 1
    windowed = usage == "DISPLAY"
    window = item.unit_size or item.size
    texts: list[str] = []
    for n in range(lo, hi + 1):
        t = minimal_text(from_scaled(n, pic))
        if windowed and len(t) > window:
            continue
        texts.append(t)
    if pic.signed and (not windowed or window >= 2):
        texts.append("-0")
    if windowed:
        desc = (f"every value whose canonical text fits the {window}-character ACCEPT window"
                + (", plus -0" if pic.signed else ""))
    else:
        desc = f"every value of the PIC ({usage}; whole line read)" + (", plus -0" if pic.signed else "")
    return list(dict.fromkeys(texts)), desc


def _alnum_texts(item: DataItem, limit: int) -> tuple[list[str], str] | NotApplicable:
    n = item.unit_size or item.size
    pic = item.pic
    alphabet = _ALPHA if pic is not None and pic.category == "alphabetic" else _PRINTABLE
    if n <= 0 or len(alphabet) ** n > limit:
        return NotApplicable(f"{item.name}: {len(alphabet)}^{n} possible values (> exhaustive limit {limit:,})")
    texts = ["".join(p) for p in itertools.product(alphabet, repeat=n)]
    kind = "letters and space" if alphabet is _ALPHA else "printable ASCII 0x20-0x7E"
    return texts, f"every {n}-character string of {kind}"


def input_domain(pi: ProgramInputs, limit: int) -> Domain | NotApplicable:
    """The program's whole input space as a finite product domain, or why it is not finite/small."""
    if pi.files:
        names = ", ".join(sorted(f.path or f.select.name for f in pi.files))
        return NotApplicable(f"input space not finite: reads input file(s) {names} (unbounded record count)")
    if pi.args or pi.env:
        return NotApplicable("input space not enumerated: reads command-line arguments or environment variables")
    loops = [s.site for s in pi.stdin if s.site.in_loop]
    if loops:
        s = loops[0]
        return NotApplicable(f"input space not finite: ACCEPT {s.target} at line {s.line} is inside a loop "
                             "(unbounded number of input lines)")
    fields: list[FieldDomain] = []
    for slot in pi.stdin:
        item = slot.site.item
        if item is None or item.pic is None:
            return NotApplicable(f"ACCEPT target {slot.site.target} at line {slot.site.line} is not an elementary "
                                 "item with a PICTURE (group ACCEPTs are not enumerated)")
        res = _numeric_texts(item, limit) if item.is_numeric else _alnum_texts(item, limit)
        if isinstance(res, NotApplicable):
            return res
        texts, desc = res
        fields.append(FieldDomain(item.name, item.pic.raw, texts, desc))
    dom = Domain(fields)
    if dom.size > limit:
        return NotApplicable(f"input domain has {dom.size:,} cases (> exhaustive limit {limit:,}): "
                             + ", ".join(f"{f.field}={len(f.texts)}" for f in fields))
    return dom


def _model(pi: ProgramInputs, combo: list[str]) -> dict[str, Any]:
    return {"stdin": [{"field": s.site.target, "text": t} for s, t in zip(pi.stdin, combo, strict=True)],
            "files": {}, "args": [], "env": {}}


# ---------------------------------------------------------------------------------------------
def run_t2a(pl: Pipeline, pc: ProgramCtx) -> TierResult:
    from verifier.tiers.t1_diff import SideRunner, _diagnose, ensure_cobol_builds

    start = time.monotonic()
    prog = pc.program
    fast = pl.req.mode == "fast"
    limit = pl.cfg.t2.exhaustive_limit_fast if fast else pl.cfg.t2.exhaustive_limit
    assert pc.channels is not None and pc.resolved is not None
    pi = ProgramInputs.build(prog, pc.channels.accepts, pc.channels.files, analysis.literal_seeds(prog),
                             bool(pc.nondeterminism))
    dom = input_domain(pi, limit)
    if isinstance(dom, NotApplicable):
        return TierResult.not_applicable(dom.reason, method=METHOD)
    binary = ensure_cobol_builds(pl).get(prog.program_id)
    if binary is None or not binary.ok:
        return TierResult.error(f"GnuCOBOL build of {prog.program_id} failed", method=METHOD)
    cmd = pl.pack.run_command(pl.pack_ctx(), pc.resolved)
    if isinstance(cmd, NotApplicable):
        return TierResult.not_applicable(cmd.reason, method=METHOD)
    t1 = pl.cfg.t1
    gen = Generator(pi, pl.effective_seed, pl.req.mode, case_cap=dom.size, random_n=0, pairwise=False,
                    extra_lines=t1.extra_stdin_lines, fake_time=pl.cfg.fake_time)
    specs = [gen.materialise(_model(pi, combo), "exhaustive") for combo in dom.enumerate()]
    side = SideRunner(pl, pc, binary, cmd)
    outcomes = side.run(specs, "t2a", repeat=1)
    excluded = [Exclusion(case_id=cid, reason=o.excluded) for cid, o in outcomes.items() if o.excluded]
    errors = {cid: o.error for cid, o in outcomes.items() if o.error}
    run_ok = {cid: o for cid, o in outcomes.items() if not o.excluded and not o.error}
    failed = {cid: o for cid, o in run_ok.items() if o.mismatches}
    domain_text = dom.describe()
    if excluded:
        domain_text += (f"; {len(excluded)} input(s) excluded because GnuCOBOL itself failed on them "
                        "(listed in exclusions)")
    if pc.nondeterminism:
        domain_text += f"; clock frozen at {pl.cfg.fake_time}"
    scope = Scope(
        level="program",
        what=f"stdout bytes, output files and return code of {prog.program_id} on every input of the domain",
        domain=domain_text, inputs=f"{len(outcomes)} enumerated cases",
        oracle=f"{pl.toolchain.get('gnucobol', 'GnuCOBOL')} with {' '.join(pc.pre.flags)}",
        tools=[ToolInfo(name="gnucobol", version=str(pl.toolchain.get("gnucobol", "?"))),
               ToolInfo(name=f"{pl.req.lang} runtime",
                        version=str(pl.toolchain.get("java" if pl.req.lang == "java" else pl.req.lang, "?")))],
        commands=[*binary.commands, " ".join(cmd)],
    )
    n_run = len(run_ok)
    base: dict[str, Any] = {
        "method": METHOD, "scope": scope, "cases_run": n_run, "cases_failed": len(failed),
        "cases_excluded": len(excluded), "exclusions": excluded[:50],
        "pass_fraction": round((n_run - len(failed)) / n_run, 4) if n_run else 0.0,
        "details": {"domain_size": dom.size, "fields": [{"field": f.field, "pic": f.pic, "values": len(f.texts),
                                                          "domain": f.description} for f in dom.fields]},
    }
    if failed:
        sigs, cxs = _diagnose(pl, pc, side, gen, failed, tier="T2a")
        return TierResult(status=Status.FAIL, failure_signatures=sigs, counterexamples=cxs,
                          duration_s=time.monotonic() - start, **base)
    if errors:
        first = next(iter(errors.values()))
        return TierResult(status=Status.ERROR, reason=f"{len(errors)} target runs failed in the sandbox: {first}",
                          duration_s=time.monotonic() - start, **base)
    if n_run == 0:
        return TierResult(status=Status.ERROR, reason="every input of the domain was excluded",
                          duration_s=time.monotonic() - start, **base)
    return TierResult(status=Status.PASS, duration_s=time.monotonic() - start, **base)
