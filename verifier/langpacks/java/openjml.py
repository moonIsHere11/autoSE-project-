"""OpenJML ESC driver and output classifier for Java T3 (spike S3, DECISIONS D11).

Command (one process per program): the `openjml` wrapper in the image with
`--esc -source 17 -Xlint:-options --progress --show-summary --timeout=<per-method>
--check-feasibility=precondition`, under an outer `timeout -k`.

Classification follows S3's table (first matching rule wins, per target method); a PASS is only
ever produced from a parsed `Completed proof of … - no warnings` line.
"""

from __future__ import annotations

import re
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path

from verifier.report.schema import Status
from verifier.sandbox.docker_runner import DockerRunner, Mount

_COMPLETED = re.compile(r"^Completed proof of (?P<sig>\S+\(.*\)) with prover \S+ - "
                        r"(?P<st>no warnings|with warnings|UNKNOWN|INFEASIBLE|ERROR) \[(?P<secs>[\d.]+) secs\]$")
_STARTING = re.compile(r"^Starting proof of (?P<sig>\S+\(.*\)) with prover ")
_WARN = re.compile(r"^(?P<file>[^:\s]+):(?P<line>\d+): verify: The prover cannot establish an assertion "
                   r"\((?P<key>\w+)(?::[^)]*)?\) in method (?P<m>[\w$]+)(?:: (?P<detail>.*))?$")
_ASSOC = re.compile(r"^(?P<file>[^:\s]+):(?P<line>\d+): verify: Associated declaration: (?P<decl>\S+)")
_UNKNOWN = re.compile(r"^\S+: verify: Validity is unknown|^verify: Validity is unknown")
_INFEASIBLE = re.compile(r"verify: Invariants\+Preconditions appear to be contradictory")
_ERROR = re.compile(r"^(?:\S+: )?error: (?P<msg>.*)$")

LOOP_KEYS = {"LoopInvariant", "LoopInvariantBeforeLoop", "LoopDecreases", "LoopInvariantAfterLoop"}
CALLEE_KEYS = {"UndefinedCalledMethodPrecondition", "Precondition"}
FAIL_KEYS = {"Postcondition", "Assignable", "ArithmeticOperationRange", "ExceptionalPostcondition",
             "PossiblyDivideByZero", "PossiblyNullDeReference", "PossiblyTooLargeIndex",
             "PossiblyNegativeIndex", "Assert", "InvariantExit", "Invariant", "PossiblyBadCast"}


@dataclass
class EscWarning:
    file: str
    line: int
    key: str
    method: str
    detail: str = ""
    declaration: str | None = None  # file:line of the violated clause


@dataclass
class MethodBlock:
    signature: str  # e.g. Prog.calcPara()
    status: str | None = None  # no warnings | with warnings | UNKNOWN | INFEASIBLE | ERROR
    seconds: float = 0.0
    warnings: list[EscWarning] = field(default_factory=list)
    unknown: bool = False
    infeasible: bool = False
    text: list[str] = field(default_factory=list)

    @property
    def method(self) -> str:
        return self.signature.split("(")[0].split(".")[-1]


@dataclass
class EscOutcome:
    exit_code: int
    timed_out: bool
    blocks: dict[str, MethodBlock]
    errors: list[str]
    parse_errors: bool
    duration_s: float = 0.0
    command: str = ""
    raw: str = ""

    def block_for(self, method: str) -> MethodBlock | None:
        hits = [b for b in self.blocks.values() if b.method == method]
        return hits[0] if len(hits) == 1 else None


def parse_esc_output(text: str, exit_code: int, timed_out: bool = False) -> EscOutcome:
    blocks: dict[str, MethodBlock] = {}
    errors: list[str] = []
    cur: MethodBlock | None = None
    last_warn: EscWarning | None = None
    for line in text.splitlines():
        m = _STARTING.match(line)
        if m:
            cur = blocks.setdefault(m.group("sig"), MethodBlock(m.group("sig")))
            last_warn = None
            continue
        m = _COMPLETED.match(line)
        if m:
            b = blocks.setdefault(m.group("sig"), MethodBlock(m.group("sig")))
            b.status = m.group("st")
            b.seconds = float(m.group("secs"))
            cur = None
            continue
        if cur is not None:
            cur.text.append(line)
        w = _WARN.match(line)
        if w and cur is not None:
            last_warn = EscWarning(w.group("file"), int(w.group("line")), w.group("key"), w.group("m"),
                                   w.group("detail") or "")
            cur.warnings.append(last_warn)
            continue
        a = _ASSOC.match(line)
        if a and last_warn is not None:
            last_warn.declaration = f"{a.group('file')}:{a.group('line')}"
            continue
        if _UNKNOWN.search(line) and cur is not None:
            cur.unknown = True
        if _INFEASIBLE.search(line) and cur is not None:
            cur.infeasible = True
        e = _ERROR.match(line)
        if e and "verify:" not in line:
            errors.append(e.group("msg").strip())
    parse_errors = "Operation not performed because of parse or type errors" in text
    return EscOutcome(exit_code, timed_out, blocks, errors, parse_errors, raw=text)


@dataclass
class MethodVerdict:
    status: Status
    reason: str
    warnings: list[EscWarning] = field(default_factory=list)
    seconds: float = 0.0


def classify(out: EscOutcome, method: str, *, has_unannotated_loop: bool = False,
             calls_unspecified: bool = False) -> MethodVerdict:
    """S3 classification table, rules 1–11."""
    if out.timed_out or out.exit_code in (124, 137):
        return MethodVerdict(Status.TIMEOUT, "OpenJML wall-clock limit")
    if out.exit_code not in (0, 6) or out.errors or out.parse_errors:
        msg = "; ".join(out.errors[:3]) or ("parse or type errors in the instrumented code" if out.parse_errors
                                             else f"openjml exit {out.exit_code}")
        return MethodVerdict(Status.ERROR, f"OpenJML error: {msg}")
    b = out.block_for(method)
    if b is None or b.status is None:
        return MethodVerdict(Status.ERROR, f"no completed proof for method {method} (not found or ambiguous)")
    if b.status == "ERROR":
        return MethodVerdict(Status.ERROR, f"prover error on {b.signature}", seconds=b.seconds)
    if b.status == "INFEASIBLE" or b.infeasible:
        return MethodVerdict(Status.ERROR, "contradictory preconditions (vacuous contract)", seconds=b.seconds)
    if b.status == "no warnings" and not b.warnings and not b.unknown:
        return MethodVerdict(Status.PASS, "all contracts verified", seconds=b.seconds)
    keys = {w.key for w in b.warnings}
    if has_unannotated_loop and (b.warnings or b.unknown):
        return MethodVerdict(Status.NOT_APPLICABLE, "needs loop invariant", b.warnings, b.seconds)
    if keys & LOOP_KEYS:
        return MethodVerdict(Status.NOT_APPLICABLE, "generated loop invariant/variant not provable", b.warnings,
                             b.seconds)
    library = any((w.declaration or "").startswith("/opt/openjml/specs/") for w in b.warnings)
    if calls_unspecified or keys & CALLEE_KEYS or library:
        return MethodVerdict(Status.NOT_APPLICABLE, "callee or library method without a usable contract",
                             b.warnings, b.seconds)
    fails = [w for w in b.warnings if w.key in FAIL_KEYS]
    if fails:
        w = fails[0]
        return MethodVerdict(Status.FAIL, f"{w.key} violated at {w.file}:{w.line}"
                             + (f" ({w.detail})" if w.detail else ""), b.warnings, b.seconds)
    if b.status == "UNKNOWN" or b.unknown:
        return MethodVerdict(Status.TIMEOUT, f"solver timeout/unknown after {b.seconds:.1f} s", b.warnings, b.seconds)
    return MethodVerdict(Status.ERROR, "unclassified ESC output", b.warnings, b.seconds)


def run_esc(runner: DockerRunner, work: Path, files: list[str], *, per_method_timeout: int,
            wall_s: float, classpath: list[str] | None = None, methods: list[str] | None = None,
            extra_flags: list[str] | None = None, extra_mounts: list[Mount] | None = None) -> EscOutcome:
    args = ["openjml", "--esc", "--os-name=linux", "-source", "17", "-Xlint:-options", "--progress",
            "--show-summary", f"--timeout={per_method_timeout}", "--check-feasibility=precondition"]
    if classpath:
        args += ["-cp", ":".join(classpath)]
    if methods:
        args.append("--method=" + ",".join(methods))
    args += list(extra_flags or [])
    args += files
    t = max(10, int(wall_s))
    script = f"timeout -k 10 {t} {' '.join(shlex.quote(a) for a in args)} > /w/esc.out 2>&1; echo $? > /w/esc.rc"
    start = time.monotonic()
    res = runner.run(["bash", "-c", script], mounts=[Mount(work, "/w", read_only=False), *(extra_mounts or [])],
                     workdir="/w", timeout_s=t + 60)
    dur = time.monotonic() - start
    text = (work / "esc.out").read_text("utf-8", errors="replace") if (work / "esc.out").exists() else res.text()
    try:
        rc = int((work / "esc.rc").read_text().strip())
    except (OSError, ValueError):
        rc = res.returncode
    out = parse_esc_output(text, rc, timed_out=res.timed_out or rc in (124, 137))
    out.duration_s = dur
    out.command = " ".join(shlex.quote(a) for a in args)
    return out
