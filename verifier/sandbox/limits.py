"""Sandbox resource limits (principle 6: generated code is untrusted)."""

from __future__ import annotations

from dataclasses import dataclass

from verifier.config import Limits


@dataclass(frozen=True)
class SandboxLimits:
    cpus: float = 4.0
    memory_mb: int = 3072
    pids: int = 1024
    tmpfs_mb: int = 1024
    container_timeout_s: float = 1800.0

    @staticmethod
    def from_config(limits: Limits) -> SandboxLimits:
        return SandboxLimits(
            cpus=limits.cpus,
            memory_mb=limits.memory_mb,
            pids=limits.pids,
            tmpfs_mb=limits.tmpfs_mb,
            container_timeout_s=limits.container_timeout_s,
        )

    def docker_args(self) -> list[str]:
        return [
            "--cpus",
            f"{self.cpus:g}",
            "--memory",
            f"{self.memory_mb}m",
            "--memory-swap",
            f"{self.memory_mb}m",
            "--pids-limit",
            str(self.pids),
            "--tmpfs",
            f"/tmp:rw,exec,nosuid,size={self.tmpfs_mb}m",
            "--tmpfs",
            f"/work:rw,exec,nosuid,size={max(64, self.tmpfs_mb // 4)}m",
        ]
