"""Access to GnuCOBOL through the verifier's sandbox, configured exactly like Phase 2 (ADR-0001)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from verifier.config import VerifierConfig
from verifier.sandbox.docker_runner import DockerRunner
from verifier.sandbox.limits import SandboxLimits


@dataclass
class Toolbox:
    config: VerifierConfig
    runner: DockerRunner
    cache_dir: Path

    def versions(self) -> dict[str, str]:
        """Tool versions recorded in the manifest; stable across runs (no image digest timestamps)."""
        res = self.runner.run(["cat", "/opt/toolchain/versions.json"], mounts=[], timeout_s=60)
        out: dict[str, str] = {"image": self.config.image}
        if res.ok:
            data = json.loads(res.stdout.decode("utf-8", errors="replace"), strict=False)
            for k, v in data.items():
                out[str(k)] = str(v)
        cobc = self.runner.run(["cobc", "--version"], mounts=[], timeout_s=60)
        out["cobc"] = cobc.stdout.decode("utf-8", errors="replace").splitlines()[0].strip()
        return out


def make_toolbox(cache_dir: Path) -> Toolbox:
    # Phase 2 calls verifier.api.verify without a config file, i.e. VerifierConfig() defaults
    # (-std=default, default copy dirs); Phase 0 must see the same program (principle 2).
    cfg = VerifierConfig()
    runner = DockerRunner(cfg.image, SandboxLimits.from_config(cfg.limits))
    runner.check_available()
    return Toolbox(cfg, runner, cache_dir)
