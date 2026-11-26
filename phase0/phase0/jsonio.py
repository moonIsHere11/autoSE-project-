"""Deterministic JSON: sorted keys, fixed indent, trailing newline, so equal facts give equal bytes."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel


def dumps(data: object) -> str:
    return json.dumps(data, sort_keys=True, indent=1, ensure_ascii=False) + "\n"


def to_data(obj: BaseModel | Sequence[BaseModel]) -> object:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    return [m.model_dump(mode="json") for m in obj]


def write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(dumps(data), "utf-8")
    os.replace(tmp, path)


def write_model(path: Path, obj: BaseModel | Sequence[BaseModel]) -> None:
    write(path, to_data(obj))


def read(path: Path) -> object:
    return json.loads(path.read_text("utf-8"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree_hash(root: Path, exclude: frozenset[str] = frozenset()) -> str:
    """sha256 over sorted (relative path, file sha256) pairs; `exclude` holds relative posix paths."""
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if rel in exclude:
            continue
        h.update(rel.encode("utf-8") + b"\0")
        h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()
