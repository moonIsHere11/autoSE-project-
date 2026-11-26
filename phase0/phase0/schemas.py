"""JSON Schema export of the KB contract (1.1), for modules that do not use pydantic."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, TypeAdapter

from phase0 import jsonio
from phase0.schema import (
    CallGraph,
    Coverage,
    DataFlow,
    Field_,
    Gap,
    Inventory,
    KbManifest,
    Rule,
    Summaries,
    Toolchain,
    Unit,
)

OBJECTS: dict[str, type[BaseModel]] = {
    "manifest": KbManifest,
    "inventory": Inventory,
    "call_graph": CallGraph,
    "data_flow": DataFlow,
    "coverage": Coverage,
    "toolchain": Toolchain,
    "summaries": Summaries,
}
LISTS: dict[str, type[BaseModel]] = {
    "units": Unit,
    "data_dictionary": Field_,
    "mapping_rules": Rule,
    "semantic_gaps": Gap,
}
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"


def all_schemas() -> dict[str, object]:
    out: dict[str, object] = {name: model.model_json_schema() for name, model in OBJECTS.items()}
    for name, model in LISTS.items():
        out[name] = TypeAdapter(list[model]).json_schema()  # type: ignore[valid-type]
    return out


def export(directory: Path = SCHEMA_DIR) -> list[Path]:
    paths: list[Path] = []
    for name, schema in sorted(all_schemas().items()):
        path = directory / f"{name}.schema.json"
        jsonio.write(path, schema)
        paths.append(path)
    return paths


def stale(directory: Path = SCHEMA_DIR) -> list[str]:
    """Exported schema files that no longer match the models."""
    out: list[str] = []
    for name, schema in sorted(all_schemas().items()):
        path = directory / f"{name}.schema.json"
        if not path.exists() or path.read_text("utf-8") != jsonio.dumps(schema):
            out.append(path.name)
    return out
