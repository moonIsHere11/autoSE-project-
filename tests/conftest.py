from __future__ import annotations

from pathlib import Path

import pytest

from verifier.config import VerifierConfig
from verifier.sandbox.docker_runner import DockerRunner, SandboxUnavailable
from verifier.sandbox.limits import SandboxLimits

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def config() -> VerifierConfig:
    return VerifierConfig()


@pytest.fixture(scope="session")
def runner(config: VerifierConfig) -> DockerRunner:
    r = DockerRunner(config.image, SandboxLimits.from_config(config.limits))
    try:
        r.check_available()
    except SandboxUnavailable as exc:
        pytest.skip(f"toolchain image unavailable: {exc}")
    return r


@pytest.fixture(scope="session")
def repo() -> Path:
    return REPO
