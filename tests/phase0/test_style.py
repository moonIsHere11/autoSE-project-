"""House rules for Phase 0 code that ruff cannot express."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "phase0"


def python_files() -> list[Path]:
    return sorted(p for p in ROOT.rglob("*.py") if ".mypy_cache" not in p.parts)


def test_no_conditional_expressions() -> None:
    offenders = []
    for p in python_files():
        for node in ast.walk(ast.parse(p.read_text("utf-8"))):
            if isinstance(node, ast.IfExp):
                offenders.append(f"{p.relative_to(ROOT)}:{node.lineno}")
    assert offenders == []


def test_no_catch_all_except() -> None:
    offenders = []
    for p in python_files():
        for node in ast.walk(ast.parse(p.read_text("utf-8"))):
            if isinstance(node, ast.ExceptHandler):
                name = ast.unparse(node.type) if node.type else ""
                if name in ("", "Exception", "BaseException"):
                    offenders.append(f"{p.relative_to(ROOT)}:{node.lineno}")
    assert offenders == []
