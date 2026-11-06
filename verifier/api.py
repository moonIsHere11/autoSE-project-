"""Python API: `verifier.api.verify(...) -> Report` (same parameters as the CLI)."""

from __future__ import annotations

from pathlib import Path

from verifier.config import VerifierConfig, load_config
from verifier.pipeline import Pipeline, VerifyRequest
from verifier.report.schema import Report


def verify(
    cobol: str | Path,
    target: str | Path,
    lang: str,
    out: str | Path,
    manifest: str | Path | None = None,
    mode: str = "fast",
    units: list[str] | None = None,
    tiers: list[int] | None = None,
    seed: int = 0,
    previous_report: str | Path | None = None,
    config: VerifierConfig | str | Path | None = None,
    argv: list[str] | None = None,
) -> Report:
    cfg = config if isinstance(config, VerifierConfig) else load_config(config)
    req = VerifyRequest(
        cobol=Path(cobol).resolve(),
        target=Path(target).resolve(),
        lang=lang,
        out=Path(out).resolve(),
        manifest=Path(manifest).resolve() if manifest else None,
        mode=mode,
        units=units,
        tiers=tiers,
        seed=seed,
        previous_report=Path(previous_report).resolve() if previous_report else None,
        argv=argv or [],
    )
    return Pipeline(req, cfg).run()
