"""Thin tree-sitter helpers shared by the language packs (one engine for all three languages)."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Any

from tree_sitter import Language, Node, Parser


@lru_cache(maxsize=4)
def parser_for(lang: str) -> Parser:
    if lang == "java":
        import tree_sitter_java as mod
    elif lang == "python":
        import tree_sitter_python as mod  # type: ignore[no-redef]
    elif lang == "go":
        import tree_sitter_go as mod  # type: ignore[no-redef]
    else:
        raise ValueError(lang)
    language: Any = mod.language()
    return Parser(Language(language))


def text(node: Node | None) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.decode("utf-8", errors="replace")


def line(node: Node) -> int:
    return int(node.start_point[0]) + 1


def end_line(node: Node) -> int:
    return int(node.end_point[0]) + 1


def walk(node: Node) -> Iterator[Node]:
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(n.children))


def has_error(node: Node) -> bool:
    return bool(node.has_error)


def normalise_number(raw: str) -> str | None:
    s = raw.strip().replace("_", "")
    s = s.rstrip("lLdDfF") if not s.lower().startswith("0x") else s
    try:
        if s.lower().startswith("0x"):
            return str(int(s, 16))
        d = Decimal(s)
    except (InvalidOperation, ValueError):
        return None
    d = d.normalize()
    out = format(d, "f")
    return "0" if out in ("-0", "0") else out


_ESC = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'", "0": "\0", "b": "\b", "f": "\f"}


def unescape(s: str) -> str:
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            out.append(_ESC.get(s[i + 1], s[i + 1]))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)
