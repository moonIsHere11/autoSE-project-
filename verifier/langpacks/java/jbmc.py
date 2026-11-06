"""JBMC driver for Java T2b (spike S2, DECISIONS D15).

* `javac --release 8` for harness, reference and (when possible) the candidate: avoids
  `invokedynamic` string concatenation, which JBMC models as null.
* `prescan()` reads `javap -c -p` of the compiled classes and lists calls that JBMC does not model
  (it silently stubs JDK methods, giving spurious counterexamples *or* hiding side effects).
  Any hit in the unit's call closure makes T2b NOT_APPLICABLE with that reason.
* `run_jbmc()` runs `jbmc … --json-ui --trace` inside the sandbox under `timeout -k` and a memory
  cap; `parse_jbmc_output()` turns exit code + JSON into one of
  PROVED / COUNTEREXAMPLE / BOUND_INSUFFICIENT / TOOL_ERROR / TIMEOUT / OUT_OF_MEMORY.
"""

from __future__ import annotations

import json
import re
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from verifier.sandbox.docker_runner import DockerRunner, Mount

CPROVER_JAR = "/usr/lib/cprover-api.jar"
Verdict = Literal["PROVED", "COUNTEREXAMPLE", "BOUND_INSUFFICIENT", "TOOL_ERROR", "TIMEOUT", "OUT_OF_MEMORY"]

# Owners whose methods JBMC models (or that are ours and pure bytecode on the classpath).
MODELLED_OWNERS = ("java/lang/Object", "org/cprover/")
# Exception construction / assertion plumbing is modelled by JBMC's core models.
_EXCEPTION_OWNER = re.compile(r"^java/lang/(\w*(Exception|Error)|Throwable)$")
# In constructors / static initialisers we tolerate inert JDK objects (I/O handles, buffers) that
# the unit under check never touches; their stubs cannot affect the compared fields.
INIT_TOLERATED = ("java/io/", "java/nio/charset/", "java/lang/StringBuilder", "java/lang/String",
                  "java/lang/System.in", "java/lang/System.out", "java/util/", "java/lang/Object",
                  "java/math/BigDecimal.<init>", "java/math/BigDecimal.valueOf", "java/lang/Long.valueOf")


@dataclass
class FailedProperty:
    property: str
    description: str
    line: int | None
    kind: Literal["assertion", "unwind", "exception"]


@dataclass
class JbmcOutcome:
    verdict: Verdict
    exit_code: int
    failed: list[FailedProperty] = field(default_factory=list)
    inputs: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    duration_s: float = 0.0
    command: str = ""
    properties: int = 0

    @property
    def real_failures(self) -> list[FailedProperty]:
        return [f for f in self.failed if f.kind != "unwind"]


# ---------------------------------------------------------------------------------------------
# output parsing
# ---------------------------------------------------------------------------------------------
def decode_value(value: dict[str, Any]) -> int | None:
    """Trace value → int, from the two's-complement `binary` field (`data` is a Java literal)."""
    bits, width = value.get("binary"), value.get("width")
    if bits is None or width is None:
        data = str(value.get("data", "")).rstrip("Ll")
        try:
            return int(data)
        except ValueError:
            return None
    n = int(bits, 2)
    if value.get("type") in ("byte", "short", "int", "long") and n >= 1 << (int(width) - 1):
        n -= 1 << int(width)
    return n


def _kind(prop: str) -> Literal["assertion", "unwind", "exception"]:
    if ".unwind." in prop:
        return "unwind"
    if ".assertion." in prop:
        return "assertion"
    return "exception"


def parse_jbmc_output(text: str, rc: int, input_prefix: str = "in_") -> JbmcOutcome:
    if rc == 124:
        return JbmcOutcome("TIMEOUT", rc, errors=["jbmc exceeded its time budget"])
    if rc == 137:
        return JbmcOutcome("OUT_OF_MEMORY", rc, errors=["jbmc was killed (memory cap)"])
    try:
        doc = json.loads(text)
        if not isinstance(doc, list):
            raise ValueError("not a JSON array")
    except ValueError as exc:
        tail = text.strip()[-400:]
        return JbmcOutcome("TOOL_ERROR", rc, errors=[f"unparsable jbmc output (exit {rc}): {exc}; {tail}"])
    status: str | None = None
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for item in doc:
        if not isinstance(item, dict):
            continue
        if item.get("messageType") == "ERROR":
            errors.append(str(item.get("messageText")))
        if "cProverStatus" in item:
            status = str(item["cProverStatus"])
        if "result" in item and isinstance(item["result"], list):
            results = item["result"]
    if rc not in (0, 10) or status is None:
        return JbmcOutcome("TOOL_ERROR", rc, errors=errors or [f"jbmc exit {rc} without a verdict"],
                           properties=len(results))
    failed_raw = [r for r in results if r.get("status") == "FAILURE"]
    failed = []
    for r in failed_raw:
        loc = r.get("sourceLocation") or {}
        line = loc.get("line")
        failed.append(FailedProperty(str(r.get("property")), str(r.get("description", "")),
                                     int(line) if line and str(line).isdigit() else None, _kind(str(r.get("property")))))
    out = JbmcOutcome("TOOL_ERROR", rc, failed=failed, errors=errors, properties=len(results))
    real = [r for r in failed_raw if ".unwind." not in str(r.get("property"))]
    if not failed_raw:
        out.verdict = "PROVED" if status == "success" and rc == 0 else "TOOL_ERROR"
    elif real:
        out.verdict = "COUNTEREXAMPLE"
    else:
        out.verdict = "BOUND_INSUFFICIENT"
    witness = real[0] if real else (failed_raw[0] if failed_raw else None)
    if witness is not None:
        for step in witness.get("trace", []) or []:
            if step.get("stepType") != "assignment" or step.get("hidden"):
                continue
            lhs = str(step.get("lhs", ""))
            if lhs.startswith(input_prefix) and re.fullmatch(r"\w+", lhs) and "sourceLocation" in step:
                v = decode_value(step.get("value") or {})
                if v is not None:
                    out.inputs[lhs] = v
    return out


# ---------------------------------------------------------------------------------------------
# javap pre-scan
# ---------------------------------------------------------------------------------------------
_METHOD_HDR = re.compile(r"^  (?:[\w.$<>\[\], ?]+ )?(?P<name>[\w.$<>]+)\((?P<params>[^)]*)\)(?: throws [\w.$, ]+)?;$")
_CLINIT_HDR = re.compile(r"^  static \{\};$")
_INVOKE = re.compile(r"^\s+\d+: (?P<op>invoke\w+)\s+#\d+(?:,\s*\d+)?\s+// (?:Method|InterfaceMethod|InvokeDynamic) "
                     r"(?P<target>\S+)")
_CLASS_HDR = re.compile(r"^(?:Compiled from .*)?(?:public |final |abstract |\s)*(?:class|interface|enum) (?P<name>[\w.$]+)")


@dataclass
class ClassCode:
    name: str  # internal name a/b/C
    methods: dict[str, list[tuple[str, str]]] = field(default_factory=dict)  # name -> [(op, owner.method:desc)]


def parse_javap(text: str) -> dict[str, ClassCode]:
    classes: dict[str, ClassCode] = {}
    cur: ClassCode | None = None
    meth: str | None = None
    for line in text.splitlines():
        m = _CLASS_HDR.match(line)
        if m and not line.startswith(" "):
            cur = ClassCode(m.group("name").replace(".", "/"))
            classes[cur.name] = cur
            meth = None
            continue
        if cur is None:
            continue
        if _CLINIT_HDR.match(line):
            meth = "<clinit>"
            cur.methods.setdefault(meth, [])
            continue
        mh = _METHOD_HDR.match(line)
        if mh:
            name = mh.group("name")
            meth = "<init>" if name == cur.name.replace("/", ".") else name.split(".")[-1]
            cur.methods.setdefault(meth, [])
            continue
        mi = _INVOKE.match(line)
        if mi and meth is not None:
            target = mi.group("target")
            if mi.group("op") == "invokedynamic":
                target = "invokedynamic:" + target
            elif "." not in target.split(":")[0]:
                target = f"{cur.name}.{target}"  # same-class call: javap omits the owner
            cur.methods[meth].append((mi.group("op"), target))
    return classes


def unmodelled_calls(classes: dict[str, ClassCode], cls: str, method: str,
                     extra_ok: tuple[str, ...] = ("cobolrt/",)) -> list[str]:
    """Calls in the closure of `cls.method` (plus constructors) that JBMC would silently stub."""
    reasons: list[str] = []
    seen: set[tuple[str, str]] = set()
    stack: list[tuple[str, str, bool]] = [(cls, method, False), (cls, "<init>", True), (cls, "<clinit>", True)]
    while stack:
        owner, name, in_init = stack.pop()
        if (owner, name) in seen:
            continue
        seen.add((owner, name))
        code = classes.get(owner)
        if code is None or name not in code.methods:
            continue
        for _op, target in code.methods[name]:
            if target.startswith("invokedynamic:"):
                if not in_init:
                    reasons.append(f"{owner.split('/')[-1]}.{name} uses invokedynamic ({target.split(':')[1]}) "
                                   "(lambda or string concatenation), which JBMC does not model")
                continue
            t_owner, _, rest = target.partition(".")
            t_name = rest.split(":")[0].strip('"')
            if t_owner in classes:
                stack.append((t_owner, t_name, in_init or t_name == "<init>"))
                continue
            if t_owner.startswith(extra_ok) or any(t_owner.startswith(o) for o in MODELLED_OWNERS):
                continue
            if _EXCEPTION_OWNER.match(t_owner) or (t_owner == "java/lang/Class" and t_name == "desiredAssertionStatus"):
                continue
            if in_init and any(f"{t_owner}.{t_name}".startswith(x) or t_owner.startswith(x) for x in INIT_TOLERATED):
                continue
            reasons.append(f"{owner.split('/')[-1]}.{name} calls {t_owner.replace('/', '.')}.{t_name}, "
                           "which JBMC does not model (it would be stubbed)")
    return sorted(set(reasons))


# ---------------------------------------------------------------------------------------------
# running tools in the sandbox
# ---------------------------------------------------------------------------------------------
@dataclass
class ToolRun:
    ok: bool
    output: str
    command: str
    duration_s: float


def javac(runner: DockerRunner, work: Path, sources: list[str], classpath: list[str], out_dir: str,
          extra_mounts: list[Mount] | None = None, timeout_s: float = 300) -> ToolRun:
    cp = ":".join(classpath)
    cmd = (f"mkdir -p {shlex.quote(out_dir)} && javac --release 8 -g -nowarn -encoding UTF-8 -Xlint:none "
           f"-cp {shlex.quote(cp)} -d {shlex.quote(out_dir)} " + " ".join(shlex.quote(s) for s in sources))
    start = time.monotonic()
    res = runner.run(["bash", "-c", cmd], mounts=[Mount(work, "/w", read_only=False), *(extra_mounts or [])],
                     workdir="/w", timeout_s=timeout_s)
    return ToolRun(res.ok, res.text(), cmd, time.monotonic() - start)


def javap(runner: DockerRunner, work: Path, classes_dir: str, extra_mounts: list[Mount] | None = None) -> ToolRun:
    cmd = (f"cd {shlex.quote(classes_dir)} && find . -name '*.class' | sed 's|^./||' | sort | "
           "xargs -r javap -c -p")
    start = time.monotonic()
    res = runner.run(["bash", "-c", cmd], mounts=[Mount(work, "/w", read_only=False), *(extra_mounts or [])],
                     workdir="/w", timeout_s=300)
    return ToolRun(res.ok, res.text(), cmd, time.monotonic() - start)


def run_jbmc(runner: DockerRunner, work: Path, classpath: list[str], cls: str, function: str, *,
             unwind: int | None, timeout_s: float, tag: str, extra_mounts: list[Mount] | None = None,
             input_prefix: str = "in_", extra_flags: list[str] | None = None) -> JbmcOutcome:
    """Run one JBMC entry point; the JSON output is kept as `<work>/<tag>.json`."""
    cp = ":".join([*classpath, CPROVER_JAR])
    flags = ["--sat-solver", "cadical", "--java-assume-inputs-non-null", "--json-ui", "--trace"]
    if unwind is not None:
        flags = ["--unwind", str(unwind), "--unwinding-assertions", *flags]
    flags = [*(extra_flags or []), *flags]
    jbmc_cmd = ["jbmc", cls, "--function", function, "-cp", cp, *flags]
    t = max(5, int(timeout_s))
    script = (f"timeout -k 10 {t} {' '.join(shlex.quote(a) for a in jbmc_cmd)} > /w/{tag}.json 2> /w/{tag}.err; "
              f"echo $? > /w/{tag}.rc")
    start = time.monotonic()
    res = runner.run(["bash", "-c", script], mounts=[Mount(work, "/w", read_only=False), *(extra_mounts or [])],
                     workdir="/w", timeout_s=t + 60)
    dur = time.monotonic() - start
    command = " ".join(shlex.quote(a) for a in jbmc_cmd)
    if res.timed_out:
        return JbmcOutcome("TIMEOUT", -9, errors=["sandbox wall-clock exceeded"], duration_s=dur, command=command)
    try:
        rc = int((work / f"{tag}.rc").read_text().strip())
    except (OSError, ValueError):
        return JbmcOutcome("TOOL_ERROR", res.returncode, errors=[f"no exit code: {res.text()[-400:]}"],
                           duration_s=dur, command=command)
    text = (work / f"{tag}.json").read_text("utf-8", errors="replace") if (work / f"{tag}.json").exists() else ""
    out = parse_jbmc_output(text, rc, input_prefix)
    if out.verdict == "TOOL_ERROR":
        err = (work / f"{tag}.err").read_text("utf-8", errors="replace") if (work / f"{tag}.err").exists() else ""
        if err.strip():
            out.errors.append(err.strip()[-600:])
    out.duration_s = dur
    out.command = command
    return out
