"""`phase0 build`: run stages A-F in order, write kb/ as a whole, validate it, emit `kb_built`."""

from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from phase0 import __version__, jsonio
from phase0.report import write_docs
from phase0.schema import (
    SCHEMA_VERSION,
    CallGraph,
    Coverage,
    DataFlow,
    ExtractorInfo,
    Field_,
    Gap,
    Inventory,
    KbManifest,
    RejectedSummary,
    Rule,
    Summaries,
    Toolchain,
    Unit,
)
from phase0.stages.inventory import build_inventory, read_tree
from phase0.stages.source_kb import build_source_kb, call_graph, coverage_doc, data_flow, summary
from phase0.stages.summaries import SummaryConfig, summarise
from phase0.target import (
    copy_driver_template,
    copy_encoding_fixtures,
    copy_runtime,
    load_gaps,
    load_rules,
    toolchain,
)
from phase0.toolbox import Toolbox
from phase0.workspace import ContractError, Workspace

T = TypeVar("T")

# every contract file under kb/ and the model it must validate against (list files: element model)
LIST_FILES: dict[str, type[BaseModel]] = {
    "source/units.json": Unit,
    "source/data_dictionary.json": Field_,
    "target/mapping_rules.json": Rule,
    "target/semantic_gaps.json": Gap,
}
OBJECT_FILES: dict[str, type[BaseModel]] = {
    "manifest.json": KbManifest,
    "source/inventory.json": Inventory,
    "source/call_graph.json": CallGraph,
    "source/data_flow.json": DataFlow,
    "source/coverage.json": Coverage,
    "target/toolchain.json": Toolchain,
}


@dataclass
class BuildResult:
    kb_version: str
    timings: dict[str, float] = field(default_factory=dict)
    lines: int = 0


class Timer:
    def __init__(self) -> None:
        self.timings: dict[str, float] = {}

    def run(self, name: str, fn: Callable[[], T]) -> T:
        start = time.perf_counter()
        out = fn()
        self.timings[name] = round(time.perf_counter() - start, 4)
        return out


def validate_kb(kb: Path) -> list[str]:
    """Every contract file parses and validates; returns the problems (empty = valid)."""
    problems: list[str] = []
    for rel, model in LIST_FILES.items():
        problems += _validate(kb / rel, model, True)
    for rel, model in OBJECT_FILES.items():
        problems += _validate(kb / rel, model, False)
    return problems


def _validate(path: Path, model: type[BaseModel], is_list: bool) -> list[str]:
    if not path.exists():
        return [f"{path.name}: missing"]
    data = jsonio.read(path)
    try:
        if not is_list:
            model.model_validate(data)
            return []
        if not isinstance(data, list):
            return [f"{path.name}: expected a JSON list"]
        for item in data:
            model.model_validate(item)
    except ValidationError as exc:
        return [f"{path.name}: {exc}"]
    return []


def build(ws: Workspace, toolbox: Toolbox) -> BuildResult:
    if not ws.source.is_dir():
        raise ContractError(f"no source/ directory in workspace {ws.root}")
    timer = Timer()
    staging = ws.root / "kb.building"
    if staging.exists():
        shutil.rmtree(staging)
    files = timer.run("A_read", lambda: read_tree(ws.source))
    inventory = timer.run("A_inventory", lambda: build_inventory(files))
    skb = timer.run("B_F_source", lambda: build_source_kb(toolbox, ws.source, inventory, files))
    scfg = SummaryConfig.from_config(ws.config.phase0)
    sreport = timer.run("G_summaries", lambda: summarise(skb.units, skb.fields, skb.files, ws.source, ws.cache, scfg))
    src = staging / "source"
    if scfg.enabled:
        jsonio.write_model(src / "summaries.json", Summaries(model=sreport.model, generated=sreport.generated,
                                                              accepted=sreport.accepted,
                                                              rejected=[RejectedSummary(**r) for r in sreport.rejected]))
    jsonio.write_model(src / "inventory.json", Inventory(files=inventory))
    jsonio.write_model(src / "units.json", skb.units)
    jsonio.write_model(src / "data_dictionary.json", skb.fields)
    jsonio.write_model(src / "call_graph.json", call_graph(skb))
    jsonio.write_model(src / "data_flow.json", data_flow(skb))
    jsonio.write_model(src / "coverage.json", coverage_doc(skb))
    tc = toolchain(ws.config)
    jsonio.write_model(staging / "target" / "toolchain.json", tc)
    jsonio.write_model(staging / "target" / "semantic_gaps.json", load_gaps())
    jsonio.write_model(staging / "target" / "mapping_rules.json", load_rules())
    copy_runtime(tc.language, staging / "target" / "runtime")
    copy_driver_template(tc.language, staging / "target" / "driver_template")
    copy_encoding_fixtures(staging / "target" / "encoding_fixtures.json")
    timer.run("report", lambda: write_docs(staging, ws.source))
    versions = timer.run("tool_versions", toolbox.versions)
    extractors = [ExtractorInfo(name="phase0", version=__version__)]
    extractors += [ExtractorInfo(name=k, version=v) for k, v in sorted(versions.items())]
    manifest = KbManifest(
        schema_version=SCHEMA_VERSION,
        kb_version=jsonio.tree_hash(staging, frozenset({"manifest.json"})),
        source_hash=jsonio.tree_hash(ws.source),
        target=tc,
        extractors=extractors,
        coverage_summary=summary(skb, inventory),
    )
    jsonio.write_model(staging / "manifest.json", manifest)
    problems = validate_kb(staging)
    if problems:
        raise ContractError("kb/ failed validation:\n" + "\n".join(problems))
    if ws.kb.exists():
        shutil.rmtree(ws.kb)
    staging.rename(ws.kb)
    if sreport.failed:
        ws.emit("llm_failures", {"model": sreport.model, "units": sreport.failed})
    if sreport.tokens_in or sreport.tokens_out:
        ws.emit("llm_usage", {"model": sreport.model, "tokens_in": sreport.tokens_in, "tokens_out": sreport.tokens_out,
                              "stage": "G_summaries"})
    ws.emit("kb_built", {"kb_version": manifest.kb_version, "timings_s": timer.timings})
    lines = sum(e.lines for e in inventory)
    jsonio.write(ws.cache / "last_build.json", {"kb_version": manifest.kb_version, "timings_s": timer.timings, "lines": lines,
                                                "llm_tokens": sreport.tokens_in + sreport.tokens_out,
                                                "llm_cache_hits": sreport.cache_hits})
    return BuildResult(manifest.kb_version, timer.timings, lines)
