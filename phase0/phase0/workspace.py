"""Workspace layout (agreement 5), run configuration (agreement 8) and the event log (contract 6)."""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml


class ContractError(ValueError):
    """Bad input or a contract violation: exit code 2 (agreement 4.6)."""


@dataclass
class RunConfig:
    run_id: str | None
    entry: str | None
    dialect: str
    compile_flags: list[str]
    language: str
    version: str
    target_overrides: dict[str, object] = field(default_factory=dict)
    phase0: dict[str, object] = field(default_factory=dict)


def _section(data: dict[str, object], key: str) -> dict[str, object]:
    value = data.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ContractError(f"config.yaml: '{key}' must be a mapping, got {type(value).__name__}")
    return value


def _str(data: dict[str, object], key: str, default: str) -> str:
    value = data.get(key)
    if value is None:
        return default
    return str(value)


def _opt_str(data: dict[str, object], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    return str(value)


def load_config(path: Path) -> RunConfig:
    if not path.exists():
        raise ContractError(f"no config.yaml at {path}")
    raw = yaml.safe_load(path.read_text("utf-8"))
    if not isinstance(raw, dict):
        raise ContractError("config.yaml must be a mapping")
    run = _section(raw, "run")
    source = _section(raw, "source")
    target = _section(raw, "target")
    flags = source.get("compile_flags")
    if flags is None:
        flags = []
    if not isinstance(flags, list):
        raise ContractError("config.yaml: source.compile_flags must be a list")
    overrides = {k: v for k, v in target.items() if k not in ("language", "version")}
    return RunConfig(
        run_id=_opt_str(run, "id"),
        entry=_opt_str(source, "entry"),
        dialect=_str(source, "dialect", "default"),
        compile_flags=[str(f) for f in flags],
        language=_str(target, "language", "java"),
        version=_str(target, "version", "21"),
        target_overrides=overrides,
        phase0=_section(raw, "phase0"),
    )


class Workspace:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        if not self.root.is_dir():
            raise ContractError(f"workspace {root} is not a directory")
        self.config = load_config(self.root / "config.yaml")

    @property
    def source(self) -> Path:
        return self.root / "source"

    @property
    def kb(self) -> Path:
        return self.root / "kb"

    @property
    def cache(self) -> Path:
        return self.root / ".phase0-cache"

    def emit(self, kind: str, data: dict[str, object]) -> None:
        if self.config.run_id is None:
            return
        path = self.root / "runs" / self.config.run_id / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "ts": datetime.datetime.now(datetime.UTC).isoformat(),
            "run_id": self.config.run_id,
            "module": "phase0",
            "kind": kind,
            "unit_id": None,
            "submission_id": None,
            "data": data,
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")
