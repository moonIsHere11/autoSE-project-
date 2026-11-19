"""`phase0 build` end to end on a corpus program (needs the toolchain image)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from phase0.build import build, validate_kb
from phase0.toolbox import make_toolbox
from phase0.workspace import Workspace

REPO = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.docker


def workspace(tmp_path: Path, prog: str) -> Workspace:
    src = next((REPO / "corpus" / prog / "cobol").glob("*.cbl"))
    (tmp_path / "source").mkdir(parents=True)
    shutil.copy(src, tmp_path / "source" / src.name)
    (tmp_path / "config.yaml").write_text(
        f"run: {{id: R-T}}\nsource: {{entry: source/{src.name}, dialect: default}}\ntarget: {{language: java, version: '21'}}\n")
    return Workspace(tmp_path)


def test_build_is_valid_and_deterministic(tmp_path: Path) -> None:
    ws = workspace(tmp_path / "a", "payroll")
    first = build(ws, make_toolbox(ws.cache))
    assert validate_kb(ws.kb) == []
    second = build(ws, make_toolbox(ws.cache))
    assert first.kb_version == second.kb_version
    other = workspace(tmp_path / "b", "payroll")
    assert build(other, make_toolbox(other.cache)).kb_version == first.kb_version
    events = (ws.root / "runs" / "R-T" / "events.jsonl").read_text().splitlines()
    assert len(events) == 2 and '"kind": "kb_built"' in events[0]
