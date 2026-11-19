"""Evaluation datasets: one workspace per program (D1, D2) or per repository (D3), built twice (E8)."""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from phase0.build import build
from phase0.target import REPO
from phase0.toolbox import Toolbox
from phase0.workspace import Workspace


@dataclass
class Program:
    dataset: str  # D1 | D2 | D3
    name: str  # workspace name
    sources: list[Path]  # files copied into source/ (D3: the repository root)
    entry: str  # path under source/
    cases: list[dict[str, Any]] = field(default_factory=list)  # check_cases.json entries (O2 inputs)
    java_dir: Path | None = None  # D1 hand translation (O3)
    manifest: Path | None = None  # D1 manifest.java.json (O3)


@dataclass
class Built:
    program: Program
    ws: Path
    kb_version: str
    kb_version_again: str
    seconds: float
    seconds_again: float
    timings: dict[str, float]
    lines: int

    def kb(self, rel: str) -> Any:
        return json.loads((self.ws / "kb" / rel).read_text("utf-8"))


def d1() -> list[Program]:
    out: list[Program] = []
    for d in sorted((REPO / "corpus").iterdir()):
        cbl = sorted((d / "cobol").glob("*.cbl"))
        if not cbl:
            continue
        cases: list[dict[str, Any]] = []
        if (d / "check_cases.json").exists():
            cases = json.loads((d / "check_cases.json").read_text("utf-8"))
        manifest: Path | None = None
        if (d / "manifest.java.json").exists():
            manifest = d / "manifest.java.json"
        java: Path | None = None
        if (d / "java").is_dir():
            java = d / "java"
        out.append(Program("D1", cbl[0].stem.upper(), [cbl[0]], cbl[0].name, cases, java, manifest))
    return out


def d2() -> list[Program]:
    out: list[Program] = []
    for cbl in sorted((REPO / "tests" / "semantics" / "programs").glob("*.cbl")):
        case: dict[str, Any] = {}
        stdin = cbl.with_suffix(".in")
        if stdin.exists():
            case["stdin"] = stdin.read_text("latin-1")
        files = cbl.with_suffix(".files")
        if files.is_dir():
            case["files"] = {f.name: f.read_text("latin-1") for f in sorted(files.iterdir()) if f.is_file()}
        out.append(Program("D2", cbl.stem.upper(), [cbl], cbl.name, [case]))
    return out


def d3(root: Path) -> list[Program]:
    if not root.is_dir():
        return []
    return [Program("D3", "CARDDEMO", [root], "")]


def make_workspace(p: Program, base: Path, summaries: str | None = None) -> Path:
    ws = base / p.dataset / p.name
    if ws.exists():
        shutil.rmtree(ws)
    (ws / "source").mkdir(parents=True)
    for src in p.sources:
        if src.is_dir():
            shutil.copytree(src, ws / "source", dirs_exist_ok=True)
        else:
            shutil.copy(src, ws / "source" / src.name)
    (ws / "config.yaml").write_text(
        f"run: {{id: EVAL}}\nsource: {{entry: source/{p.entry}, dialect: default}}\n"
        "target: {language: java, version: '21'}\n", "utf-8")
    if summaries is not None and p.dataset == "D1":
        provider, model = summaries.split(":", 1)
        with (ws / "config.yaml").open("a", encoding="utf-8") as fh:
            fh.write(f"phase0: {{summaries: {{enabled: true, provider: {provider}, model: '{model}'}}}}\n")
    return ws


def build_program(p: Program, base: Path, toolbox: Toolbox, summaries: str | None = None) -> Built:
    ws_dir = make_workspace(p, base, summaries)
    ws = Workspace(ws_dir)
    tb = Toolbox(toolbox.config, toolbox.runner, ws.cache, toolbox.versions())
    t0 = time.perf_counter()
    first = build(ws, tb)
    t1 = time.perf_counter()
    second = build(ws, tb)
    t2 = time.perf_counter()
    return Built(p, ws_dir, first.kb_version, second.kb_version, round(t1 - t0, 3), round(t2 - t1, 3),
                 first.timings, first.lines)
