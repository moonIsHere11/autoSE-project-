"""Verifier configuration: one place for every knob, recorded in every report.

All `cobc` flags live in `CobolConfig` (spec section 3). Load overrides from a TOML file with
`load_config(path)`; held-out directories also come from the `VERIFIER_HELDOUT_DIRS` env var.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

VERIFIER_VERSION = "0.1.0"
DEFAULT_IMAGE = "cobol-verifier-toolchain:0.1.0"

# GnuCOBOL runtime settings that influence observable behaviour. They are set explicitly (to the
# 3.2 defaults found in spike S6) so a host/global runtime.cfg can never change the oracle.
DEFAULT_COB_RUNTIME_ENV: dict[str, str] = {
    "COB_LS_FIXED": "false",
    "COB_LS_VALIDATE": "true",
    "COB_LS_NULLS": "false",
    "COB_FILE_PATH": ".",
}

FAKETIME_LIB = "/usr/lib/x86_64-linux-gnu/faketime/libfaketime.so.1"
DEFAULT_FAKE_TIME = "2024-01-15T10:30:00"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CobolConfig(_Strict):
    """Everything that defines the reference semantics."""

    std: str = "default"
    source_format: Literal["auto", "fixed", "free"] = "auto"
    extra_flags: list[str] = Field(default_factory=list)
    # directories (relative to the COBOL repo) searched for COPY books, in addition to every
    # directory that contains a COBOL source file
    copy_dirs: list[str] = Field(default_factory=lambda: ["copy", "copybooks", "cpy", "copylib"])
    runtime_env: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_COB_RUNTIME_ENV))
    source_suffixes: list[str] = Field(default_factory=lambda: [".cbl", ".cob", ".CBL", ".COB"])
    copy_suffixes: list[str] = Field(default_factory=lambda: [".cpy", ".CPY", ".cbl", ".cob"])

    def format_flag(self, detected: Literal["fixed", "free"]) -> str:
        fmt = detected if self.source_format == "auto" else self.source_format
        return "-fformat=free" if fmt == "free" else "-fformat=fixed"

    def flags(self, detected: Literal["fixed", "free"] = "fixed") -> list[str]:
        return [f"-std={self.std}", self.format_flag(detected), *self.extra_flags]


class Limits(_Strict):
    case_timeout_s: float = 10.0
    build_timeout_s: float = 600.0
    container_timeout_s: float = 1800.0
    cpus: float = 4.0
    memory_mb: int = 3072
    pids: int = 1024
    fsize_mb: int = 64
    tmpfs_mb: int = 1024
    workers: int = 4
    stdout_cap_bytes: int = 4 * 1024 * 1024


class T1Config(_Strict):
    fast_case_cap: int = 150
    full_case_cap: int = 2000
    random_fast: int = 40
    random_full: int = 400
    pairwise: bool = True
    shrink_rounds_fast: int = 6
    shrink_rounds_full: int = 20
    max_signatures: int = 3
    extra_stdin_lines: int = 2  # extra lines appended for ACCEPTs inside loops
    run_cobol_twice: bool = True  # flakiness detection
    minimise: bool = True  # greedy coverage-preserving minimisation (reported, never hides failures)


class T2Config(_Strict):
    exhaustive_limit: int = 20000
    exhaustive_limit_fast: int = 2000
    unwind_fast: int = 4
    unwind_full: int = 16
    checker_timeout_s: float = 300.0
    mutants: int = 5
    min_kill_rate: float = 0.6


class T3Config(_Strict):
    timeout_s: float = 300.0


class AcceptancePolicy(_Strict):
    coverage_threshold: float = 0.8
    t2_t3_allowed: list[str] = Field(default_factory=lambda: ["PASS", "NOT_APPLICABLE"])
    require_integrity: bool = True


class VerifierConfig(_Strict):
    image: str = DEFAULT_IMAGE
    cobol: CobolConfig = Field(default_factory=CobolConfig)
    limits: Limits = Field(default_factory=Limits)
    t1: T1Config = Field(default_factory=T1Config)
    t2: T2Config = Field(default_factory=T2Config)
    t3: T3Config = Field(default_factory=T3Config)
    acceptance: AcceptancePolicy = Field(default_factory=AcceptancePolicy)
    heldout_dirs: list[str] = Field(default_factory=list)
    normalisers: list[Literal["trailing_whitespace", "final_newline"]] = Field(default_factory=list)
    feedback_token_cap: int = 1500
    fake_time: str = DEFAULT_FAKE_TIME
    cache_dir: str = Field(
        default_factory=lambda: os.environ.get(
            "VERIFIER_CACHE_DIR", str(Path.home() / ".cache" / "cobol-verifier")
        )
    )
    allow_build_network: bool = False
    # False only for the self-test: run every selected tier even after an earlier FAIL (a build
    # failure still gates everything), so the planted-bug catch rate can be measured per tier.
    gating: bool = True

    def all_heldout_dirs(self) -> list[Path]:
        dirs = list(self.heldout_dirs)
        env = os.environ.get("VERIFIER_HELDOUT_DIRS", "")
        dirs += [d for d in env.split(os.pathsep) if d.strip()]
        return [Path(d).expanduser().resolve() for d in dirs]


def load_config(path: str | Path | None = None) -> VerifierConfig:
    if path is None:
        return VerifierConfig()
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    return VerifierConfig.model_validate(data)
