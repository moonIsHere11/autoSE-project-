"""Test-case bundles (docs/INTERFACE.md section 3), shared with the evaluation teammate.

    case_<hash>/case.json  stdin.txt  in/<files>  expected/  actual/
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BUNDLE_SCHEMA = "1.0"


@dataclass(frozen=True)
class InputFile:
    name: str
    data: bytes


@dataclass
class CaseSpec:
    program: str
    stdin: bytes = b""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    fake_time: str | None = None
    files_in: list[InputFile] = field(default_factory=list)
    strategy: str = "manual"
    seed: int | None = None
    model: dict[str, Any] | None = None
    tool: str = "verifier"

    def case_id(self) -> str:
        payload = {
            "program": self.program,
            "stdin": hashlib.sha256(self.stdin).hexdigest(),
            "args": self.args,
            "env": dict(sorted(self.env.items())),
            "fake_time": self.fake_time,
            "files": sorted((f.name, hashlib.sha256(f.data).hexdigest()) for f in self.files_in),
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        return f"case_{digest[:16]}"

    def case_json(self) -> dict[str, Any]:
        return {
            "schema_version": BUNDLE_SCHEMA,
            "id": self.case_id(),
            "program": self.program,
            "args": self.args,
            "env": self.env,
            "fake_time": self.fake_time,
            "stdin": "stdin.txt",
            "files_in": [
                {"name": f.name, "sha256": hashlib.sha256(f.data).hexdigest()} for f in self.files_in
            ],
            "generator": {"strategy": self.strategy, "seed": self.seed, "tool": self.tool},
            "model": self.model,
        }


def write_inputs(case: CaseSpec, case_dir: Path) -> Path:
    """Write the input part of a bundle (case.json, stdin.txt, in/)."""
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "case.json").write_text(json.dumps(case.case_json(), indent=1), "utf-8")
    (case_dir / "stdin.txt").write_bytes(case.stdin)
    in_dir = case_dir / "in"
    in_dir.mkdir(exist_ok=True)
    for f in case.files_in:
        dst = in_dir / f.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(f.data)
    return case_dir


def read_bundle(case_dir: Path) -> CaseSpec:
    data = json.loads((case_dir / "case.json").read_text("utf-8"))
    stdin_p = case_dir / data.get("stdin", "stdin.txt")
    files: list[InputFile] = []
    in_dir = case_dir / "in"
    if in_dir.is_dir():
        for p in sorted(in_dir.rglob("*")):
            if p.is_file():
                files.append(InputFile(p.relative_to(in_dir).as_posix(), p.read_bytes()))
    gen = data.get("generator") or {}
    return CaseSpec(
        program=data.get("program", ""),
        stdin=stdin_p.read_bytes() if stdin_p.exists() else b"",
        args=list(data.get("args") or []),
        env=dict(data.get("env") or {}),
        fake_time=data.get("fake_time"),
        files_in=files,
        strategy=gen.get("strategy", "external"),
        seed=gen.get("seed"),
        model=data.get("model"),
        tool=gen.get("tool", "external"),
    )


def store_outputs(results_dir: Path, dest: Path) -> None:
    """Copy a sandbox results dir into bundle `expected/` or `actual/`."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for name in ("stdout", "stderr", "return_code", "meta.json", "trace.txt"):
        src = results_dir / name
        if src.exists():
            shutil.copyfile(src, dest / name)
    out = results_dir / "out"
    if out.is_dir():
        shutil.copytree(out, dest / "out")
    else:
        (dest / "out").mkdir()
