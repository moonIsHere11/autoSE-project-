"""Build GnuCOBOL executables (plain + `-ftraceall`) inside the sandbox image, cached.

Cache key = sha256(`cobc -E` text, cobc version, flags, include dirs) — binaries themselves are not
reproducible (spike S1), the preprocessed source is.
"""

from __future__ import annotations

import hashlib
import json
import shlex
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from verifier.cobol.preprocess import Preprocessed, copy_dirs
from verifier.config import CobolConfig
from verifier.sandbox.docker_runner import DockerRunner, Mount

EXE = "prog"
TRACED = "prog.trace"


@dataclass
class CobolBinary:
    program_id: str
    source_rel: str
    key: str
    dir: Path
    ok: bool
    diagnostics: str
    commands: list[str] = field(default_factory=list)
    cached: bool = False

    def command(self, traced: bool = False) -> list[str]:
        return [f"/cobol/{TRACED if traced else EXE}"]

    def mount(self) -> Mount:
        return Mount(self.dir, "/cobol", read_only=True)


def build_key(pre: Preprocessed, cobc_version: str, incs: list[str]) -> str:
    payload = json.dumps([pre.sha256, cobc_version, pre.flags, incs, pre.source_rel])
    return hashlib.sha256(payload.encode()).hexdigest()


def build_all(
    runner: DockerRunner,
    cfg: CobolConfig,
    repo: Path,
    items: list[tuple[str, Preprocessed]],
    cache_dir: Path,
    cobc_version: str,
) -> dict[str, CobolBinary]:
    incs = copy_dirs(repo, cfg, sorted({pre.source_rel for _, pre in items}))
    inc_args = " ".join(f"-I {shlex.quote(d)}" for d in incs)
    root = cache_dir / "cobol-builds"
    root.mkdir(parents=True, exist_ok=True)
    out: dict[str, CobolBinary] = {}
    todo: list[CobolBinary] = []
    for pid, pre in items:
        key = build_key(pre, cobc_version, incs)
        d = root / key
        flags = " ".join(shlex.quote(f) for f in pre.flags)
        cmds = [
            f"cobc -x {flags} {inc_args} -o /build/{EXE} {shlex.quote(pre.source_rel)}",
            f"cobc -x {flags} -ftraceall {inc_args} -o /build/{TRACED} {shlex.quote(pre.source_rel)}",
        ]
        b = CobolBinary(pid, pre.source_rel, key, d, ok=False, diagnostics="", commands=cmds)
        if (d / EXE).exists() and (d / TRACED).exists() and (d / "ok").exists():
            b.ok, b.cached = True, True
            b.diagnostics = (d / "diagnostics.txt").read_text("utf-8") if (d / "diagnostics.txt").exists() else ""
        else:
            todo.append(b)
        out[pid] = b
    for b in todo:
        if b.dir.exists():
            shutil.rmtree(b.dir)
        b.dir.mkdir(parents=True)
        script = "set -e\ncd /src\n" + "\n".join(b.commands) + "\n"
        res = runner.run(["bash", "-c", script], mounts=[Mount(repo, "/src", True), Mount(b.dir, "/build", False)],
                         timeout_s=600)
        b.diagnostics = res.text()
        (b.dir / "diagnostics.txt").write_text(b.diagnostics, "utf-8")
        b.ok = res.ok and (b.dir / EXE).exists() and (b.dir / TRACED).exists()
        if b.ok:
            (b.dir / "ok").write_text("ok", "utf-8")
    return out
