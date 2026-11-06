"""Run commands inside the pinned toolchain image, sandboxed.

Every container gets: no network (unless a trusted build explicitly asks), CPU/memory/pids caps,
read-only root filesystem, tmpfs /tmp and /work, all capabilities dropped, no-new-privileges,
an unprivileged uid, and a host-side wall-clock timeout that kills the container.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from verifier.sandbox.limits import SandboxLimits


class SandboxUnavailable(RuntimeError):
    """Docker or the toolchain image is missing: a verifier error (exit code 2), never a PASS."""


@dataclass(frozen=True)
class Mount:
    host: Path
    container: str
    read_only: bool = True

    def arg(self) -> str:
        mode = "ro" if self.read_only else "rw"
        return f"{self.host.resolve()}:{self.container}:{mode}"


@dataclass
class RunResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    duration_s: float
    timed_out: bool
    command: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def text(self) -> str:
        return (self.stdout + self.stderr).decode("utf-8", errors="replace")


def _host_user() -> str:
    getuid = getattr(os, "getuid", None)
    getgid = getattr(os, "getgid", None)
    if getuid is None or getgid is None:
        return "10001:10001"
    return f"{getuid()}:{getgid()}"


class DockerRunner:
    def __init__(self, image: str, limits: SandboxLimits | None = None, docker: str = "docker") -> None:
        self.image = image
        self.limits = limits or SandboxLimits()
        self.docker = docker

    # ---- availability / identity ---------------------------------------------------------
    def check_available(self) -> None:
        if shutil.which(self.docker) is None:
            raise SandboxUnavailable(f"'{self.docker}' not found on PATH")
        proc = subprocess.run(
            [self.docker, "image", "inspect", "--format", "{{.Id}}", self.image],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise SandboxUnavailable(
                f"toolchain image {self.image!r} not available ({proc.stderr.strip()}); run `make image`"
            )

    def image_id(self) -> str:
        return _image_id(self.docker, self.image)

    def toolchain_versions(self) -> dict[str, str]:
        res = self.run(["cat", "/opt/toolchain/versions.json"], mounts=[], timeout_s=60)
        if not res.ok:
            return {"error": res.text()[:500]}
        try:
            data: dict[str, str] = json.loads(res.stdout.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            return {"error": "unparseable versions.json"}
        data["image"] = f"{self.image}@{self.image_id()}"
        return data

    # ---- run ---------------------------------------------------------------------------------
    def build_command(
        self,
        argv: list[str],
        mounts: list[Mount],
        env: dict[str, str] | None = None,
        workdir: str = "/work",
        network: bool = False,
        name: str | None = None,
        interactive: bool = False,
    ) -> list[str]:
        cmd = [self.docker, "run", "--rm"]
        if interactive:
            cmd.append("-i")
        if name:
            cmd += ["--name", name]
        cmd += ["--network", "bridge" if network else "none"]
        cmd += self.limits.docker_args()
        cmd += [
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            _host_user(),
            "-e",
            "HOME=/tmp",
            "-e",
            "LANG=C.UTF-8",
            "-e",
            "LC_ALL=C.UTF-8",
            "-e",
            "TZ=UTC",
        ]
        for k, v in sorted((env or {}).items()):
            cmd += ["-e", f"{k}={v}"]
        for m in mounts:
            cmd += ["-v", m.arg()]
        cmd += ["-w", workdir, self.image, *argv]
        return cmd

    def run(
        self,
        argv: list[str],
        mounts: list[Mount],
        env: dict[str, str] | None = None,
        workdir: str = "/work",
        network: bool = False,
        timeout_s: float | None = None,
        stdin: bytes | None = None,
    ) -> RunResult:
        name = f"cv-{uuid.uuid4().hex[:12]}"
        cmd = self.build_command(
            argv, mounts, env, workdir, network, name=name, interactive=stdin is not None
        )
        timeout = timeout_s if timeout_s is not None else self.limits.container_timeout_s
        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                input=stdin,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            subprocess.run([self.docker, "kill", name], capture_output=True, check=False)
            return RunResult(
                returncode=-9,
                stdout=exc.stdout or b"",
                stderr=exc.stderr or b"",
                duration_s=time.monotonic() - start,
                timed_out=True,
                command=cmd,
            )
        return RunResult(
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            duration_s=time.monotonic() - start,
            timed_out=False,
            command=cmd,
        )


@lru_cache(maxsize=8)
def _image_id(docker: str, image: str) -> str:
    proc = subprocess.run(
        [docker, "image", "inspect", "--format", "{{.Id}}", image],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else "unknown"


def batch_runner_source() -> Path:
    """Path of the in-container batch runner script (stdlib-only)."""
    return Path(__file__).with_name("batch_runner.py")
