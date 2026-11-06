"""Build the cobolrt runtimes into runtimes/build/ inside the pinned toolchain image (`make runtimes`).

Produces (mounted read-only at /opt/cobolrt in the sandbox by the verifier):

* runtimes/build/java/cobolrt.jar          classes compiled with `javac --release 8` (JBMC loads them)
* runtimes/build/java/cobolrt-sources.jar  the sources (for OpenJML / IDEs)
* runtimes/build/python/cobolrt/           the Python package (put /opt/cobolrt/python on PYTHONPATH)
* runtimes/build/go/cobolrt/               the Go module `cobolrt` (use a `replace` directive)
* runtimes/build/BUILD.json                versions + sha256 of the outputs

Everything is compiled/checked in the container with no network.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

from verifier.config import DEFAULT_IMAGE
from verifier.sandbox.docker_runner import DockerRunner, Mount
from verifier.sandbox.limits import SandboxLimits

REPO = Path(__file__).resolve().parents[1]
RUNTIMES = REPO / "runtimes"

SCRIPT = r"""
set -eu
mkdir -p /tmp/cls /out/java /out/python /out/go
echo "== java"
javac -encoding UTF-8 --release 8 -Xlint:-options -d /tmp/cls /src/java/src/cobolrt/*.java
(cd /tmp/cls && jar cf /out/java/cobolrt.jar cobolrt)
(cd /src/java/src && jar cf /out/java/cobolrt-sources.jar cobolrt)
javap -verbose -cp /out/java/cobolrt.jar cobolrt.Num | grep -m1 'major version'
echo "== python"
rm -rf /out/python/cobolrt && mkdir -p /out/python/cobolrt
cp /src/python/cobolrt/*.py /out/python/cobolrt/
cp /src/python/cobolrt/py.typed /out/python/cobolrt/ 2>/dev/null || true
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/out/python python3 -c 'import cobolrt; print("cobolrt", cobolrt.__version__)'
echo "== go"
rm -rf /out/go/cobolrt && mkdir -p /out/go/cobolrt
cp /src/go/cobolrt/*.go /src/go/cobolrt/go.mod /out/go/cobolrt/
rm -f /out/go/cobolrt/*_test.go
export GOCACHE=/tmp/gocache GOPATH=/tmp/gopath GOFLAGS=-mod=mod GOTOOLCHAIN=local GOPROXY=off
cd /out/go/cobolrt && go vet ./... && go build ./... && go version
"""


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def build(out: Path, runner: DockerRunner | None = None) -> int:
    runner = runner or DockerRunner(DEFAULT_IMAGE, SandboxLimits(cpus=2, memory_mb=2048))
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    src = RUNTIMES
    res = runner.run(["bash", "-c", SCRIPT],
                     mounts=[Mount(src, "/src", read_only=True), Mount(out, "/out", read_only=False)],
                     workdir="/tmp", timeout_s=900)
    sys.stdout.write(res.text())
    if not res.ok:
        print(f"build failed (rc={res.returncode})", file=sys.stderr)
        return 1
    files = sorted(p for p in out.rglob("*") if p.is_file())
    manifest = {
        "image": DEFAULT_IMAGE,
        "files": {p.relative_to(out).as_posix(): sha256(p) for p in files},
    }
    (out / "BUILD.json").write_text(json.dumps(manifest, indent=1) + "\n", "utf-8")
    print(f"built {len(files)} files into {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=RUNTIMES / "build")
    a = ap.parse_args(argv)
    return build(a.out)


if __name__ == "__main__":
    sys.exit(main())
