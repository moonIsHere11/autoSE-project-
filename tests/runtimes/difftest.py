"""Property-based differential test of the cobolrt runtimes against GnuCOBOL 3.2.

    python -m tests.runtimes.difftest --n 5000 --seed 1 [--langs python,java,go] [--batch 400]

Seeded random cases (MOVE, arithmetic incl. GIVING/REMAINDER/ROUNDED [MODE]/SIZE ERROR, COMPUTE,
numeric<->alphanumeric, alphanumeric MOVE/compare, DISPLAY, record encodings, ACCEPT) are rendered
as one COBOL program per batch and run under `cobc -x -std=default` in the toolchain image. The
same cases run through each runtime (Python in-process; Java and Go via small drivers in the same
container) and every output line and record byte is compared. GnuCOBOL is the oracle: any
disagreement is a runtime bug. Needs `make runtimes` first for Java/Go.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from tests.runtimes import pydriver
from tests.runtimes.cases import Case, Gen, eof_cases
from tests.runtimes.cobol_gen import REC_LEN, describe, render
from verifier.sandbox.docker_runner import DockerRunner, Mount
from verifier.sandbox.limits import SandboxLimits

REPO = Path(__file__).resolve().parents[2]
DRIVERS = Path(__file__).resolve().parent / "drivers"
IMAGE = "cobol-verifier-toolchain:0.1.0"
LANGS = ("python", "java", "go")


@dataclass
class Batch:
    index: int
    cases: list[Case]
    dir: Path


@dataclass
class Failure:
    lang: str
    case: Case
    expected: list[bytes]
    actual: list[bytes]

    def text(self) -> str:
        exp = b"".join(self.expected).decode("latin-1")
        act = b"".join(self.actual).decode("latin-1")
        return f"[{self.lang}] {describe(self.case)}\n  expected: {exp!r}\n  actual:   {act!r}"


@dataclass
class Result:
    total: Counter[tuple[str, str]] = field(default_factory=Counter)  # (lang, op) -> cases
    failed: Counter[tuple[str, str]] = field(default_factory=Counter)
    failures: list[Failure] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.failures and not self.errors

    def summary(self) -> str:
        ops = sorted({op for _, op in self.total})
        langs = [lang for lang in LANGS if any(k[0] == lang for k in self.total)]
        w = max([len(o) for o in ops] + [5])
        lines = [f"{'op'.ljust(w)} " + " ".join(f"{lang:>14}" for lang in langs)]
        for op in ops:
            cells = []
            for lang in langs:
                t, f = self.total[(lang, op)], self.failed[(lang, op)]
                cells.append(f"{t - f:>6}/{t:<6} ok")
            lines.append(f"{op.ljust(w)} " + " ".join(f"{c:>14}" for c in cells))
        tot = [sum(v for (lg, _), v in self.total.items() if lg == lang) for lang in langs]
        bad = [sum(v for (lg, _), v in self.failed.items() if lg == lang) for lang in langs]
        lines.append(f"{'TOTAL'.ljust(w)} " + " ".join(f"{t - b:>6}/{t:<6} ok" for t, b in zip(tot, bad, strict=True)))
        lines.append(f"time {self.seconds:.1f}s; failures {len(self.failures)}; errors {len(self.errors)}")
        return "\n".join(lines)


def generate(n: int, seed: int, batch: int, ops: list[str] | None = None) -> list[list[Case]]:
    gen = Gen(seed)
    out: list[list[Case]] = []
    cid = 1
    while n > 0:
        k = min(batch, n)
        cases = gen.batch(cid, k, ops)
        cid += k
        n -= k
        if ops is None or "ACC" in ops:
            cases += eof_cases(cid)
            cid += 3
        out.append(cases)
    return out


def prepare(batches: list[list[Case]], work: Path) -> list[Batch]:
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    out = []
    for i, cases in enumerate(batches):
        d = work / f"batch_{i:03d}"
        d.mkdir()
        src, stdin = render(cases)
        (d / "prog.cbl").write_text(src, "ascii")
        (d / "stdin.txt").write_bytes(stdin)
        (d / "script.txt").write_text("\n".join(c.script() for c in cases) + "\n", "ascii")
        (d / "run").mkdir()
        out.append(Batch(i, cases, d))
    return out


CONTAINER_SCRIPT = r"""
set -u
cd /w
compile() {
  b="$1"
  cobc -x -std=default -o "/tmp/$(basename "$b").exe" "$b/prog.cbl" > "$b/cobc.log" 2>&1
  echo $? > "$b/cobc.rc"
}
export -f compile
ls -d /w/batch_* | xargs -P {jobs} -I{} bash -c 'compile {}'
for b in /w/batch_*; do
  if [ "$(cat $b/cobc.rc)" = "0" ]; then
    (cd "$b/run" && "/tmp/$(basename "$b").exe" < ../stdin.txt > ../cobol.out 2> ../cobol.err; echo $? > ../cobol.rc)
  fi
done
if [ "{java}" = "1" ]; then
  mkdir -p /tmp/jdrv
  if javac -encoding UTF-8 --release 8 -nowarn -d /tmp/jdrv -cp /opt/cobolrt/java/cobolrt.jar /drv/java/Driver.java \
       > /w/java_build.log 2>&1; then
    java -Xss8m -cp /tmp/jdrv:/opt/cobolrt/java/cobolrt.jar Driver /w/batch_* > /w/java_run.log 2>&1
  fi
fi
if [ "{go}" = "1" ]; then
  export GOCACHE=/tmp/gocache GOPATH=/tmp/gopath GOFLAGS=-mod=mod GOTOOLCHAIN=local GOPROXY=off
  rm -rf /tmp/godrv && cp -r /drv/go /tmp/godrv && cd /tmp/godrv && \
    sed -i 's#=> .*cobolrt#=> /opt/cobolrt/go/cobolrt#' go.mod && \
    go build -o /tmp/godrv/drv . > /w/go_build.log 2>&1 && /tmp/godrv/drv /w/batch_* > /w/go_run.log 2>&1
fi
true
"""


def run_container(work: Path, langs: list[str], runner: DockerRunner, jobs: int = 3) -> str:
    script = (CONTAINER_SCRIPT.replace("{jobs}", str(jobs))
              .replace("{java}", "1" if "java" in langs else "0")
              .replace("{go}", "1" if "go" in langs else "0"))
    mounts = [Mount(work, "/w", read_only=False), Mount(DRIVERS, "/drv", read_only=True)]
    rt = REPO / "runtimes" / "build"
    if rt.is_dir():
        mounts.append(Mount(rt, "/opt/cobolrt", read_only=True))
    res = runner.run(["bash", "-c", script], mounts=mounts, workdir="/w", timeout_s=3600)
    return res.text()


def split_lines(out: bytes) -> dict[str, list[bytes]]:
    """Group output lines by case id (`#<id> ...`)."""
    groups: dict[str, list[bytes]] = defaultdict(list)
    for line in out.split(b"\n"):
        if line.startswith(b"#"):
            cid = line[1:6].decode("ascii", "replace")
            groups[cid].append(line + b"\n")
    return groups


def compare_batch(b: Batch, lang: str, out: bytes, enc: bytes, cobol_out: bytes, cobol_enc: bytes,
                  res: Result) -> None:
    exp, act = split_lines(cobol_out), split_lines(out)
    enc_cases = [c for c in b.cases if c.op == "ENC"]
    for c in b.cases:
        e, a = exp.get(c.name, []), act.get(c.name, [])
        if c.op == "ENC":
            k = enc_cases.index(c)
            e = [*e, b"REC " + cobol_enc[k * REC_LEN:(k + 1) * REC_LEN].hex().encode()]
            a = [*a, b"REC " + enc[k * REC_LEN:(k + 1) * REC_LEN].hex().encode()]
        res.total[(lang, c.op)] += 1
        if e != a or not e:
            res.failed[(lang, c.op)] += 1
            res.failures.append(Failure(lang, c, e, a))


def run(n: int, seed: int, langs: list[str], batch: int = 400, ops: list[str] | None = None,
        work: Path | None = None, runner: DockerRunner | None = None, jobs: int = 3) -> Result:
    t0 = time.monotonic()
    work = work or REPO / "out" / "rt-difftest" / f"seed{seed}"
    batches = prepare(generate(n, seed, batch, ops), work)
    runner = runner or DockerRunner(IMAGE, SandboxLimits(cpus=4, memory_mb=2560, tmpfs_mb=1024))
    log = run_container(work, langs, runner, jobs)
    res = Result()
    for lang in ("java", "go"):
        if lang in langs:
            for name in (f"{lang}_build.log", f"{lang}_run.log"):
                p = work / name
                if p.exists() and p.read_text("utf-8", "replace").strip():
                    res.errors.append(f"{lang} {name}: {p.read_text('utf-8', 'replace')[-2000:]}")
    for b in batches:
        rc = (b.dir / "cobc.rc").read_text().strip() if (b.dir / "cobc.rc").exists() else "?"
        if rc != "0":
            res.errors.append(f"batch {b.index}: cobc failed rc={rc}: "
                              + ((b.dir / "cobc.log").read_text("utf-8", "replace")[-3000:]
                                 if (b.dir / "cobc.log").exists() else log[-2000:]))
            continue
        cobol_out = (b.dir / "cobol.out").read_bytes() if (b.dir / "cobol.out").exists() else b""
        crc = (b.dir / "cobol.rc").read_text().strip() if (b.dir / "cobol.rc").exists() else "?"
        if crc != "0":
            res.errors.append(f"batch {b.index}: COBOL program rc={crc}: "
                              + (b.dir / "cobol.err").read_text("utf-8", "replace")[-1000:])
        enc_p = b.dir / "run" / "ENC.DAT"
        cobol_enc = enc_p.read_bytes() if enc_p.exists() else b""
        for lang in langs:
            if lang == "python":
                out, enc = pydriver.run_script((b.dir / "script.txt").read_text("ascii"),
                                               (b.dir / "stdin.txt").read_bytes())
            else:
                po, pe = b.dir / f"{lang}.out", b.dir / f"{lang}.enc"
                if not po.exists():
                    res.errors.append(f"batch {b.index}: no {lang} output")
                    continue
                out, enc = po.read_bytes(), pe.read_bytes() if pe.exists() else b""
            compare_batch(b, lang, out, enc, cobol_out, cobol_enc, res)
    res.seconds = time.monotonic() - t0
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=2000, help="number of random cases")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--langs", default="python,java,go")
    ap.add_argument("--batch", type=int, default=400, help="cases per COBOL program")
    ap.add_argument("--ops", default="", help="comma-separated subset of operations")
    ap.add_argument("--jobs", type=int, default=3, help="parallel cobc compiles")
    ap.add_argument("--show", type=int, default=15, help="failures to print")
    ap.add_argument("--json", type=Path, help="write a JSON summary here")
    a = ap.parse_args(argv)
    langs = [x for x in a.langs.split(",") if x]
    ops = [x for x in a.ops.split(",") if x] or None
    res = run(a.n, a.seed, langs, a.batch, ops, jobs=a.jobs)
    print(res.summary())
    for e in res.errors:
        print("ERROR:", e[:3000])
    for f in res.failures[: a.show]:
        print(f.text())
    if a.json:
        a.json.write_text(json.dumps({
            "seed": a.seed, "n": a.n, "langs": langs, "seconds": round(res.seconds, 1),
            "total": {f"{k[0]}:{k[1]}": v for k, v in sorted(res.total.items())},
            "failed": {f"{k[0]}:{k[1]}": v for k, v in sorted(res.failed.items())},
            "errors": res.errors,
        }, indent=1), "utf-8")
    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(main())
