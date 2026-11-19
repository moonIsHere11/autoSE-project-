"""`phase0 build|query|eval|report` (agreement 4.6). Exit codes: 0 ran, 2 bad input/contract, 3 internal."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from phase0.query import KnowledgeBase, QueryError, split_list
from phase0.workspace import ContractError, Workspace

ONE_ID = {"get_unit", "source_text", "get_field", "callers", "callees", "writers_of", "readers_of", "fields_of",
          "hazards_for"}
LIST_ARG = {"rules_for", "gaps_for"}
NO_ARG = {"list_units", "toolchain", "coverage"}


def to_json(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [to_json(v) for v in value]
    return value


def run_query(kb: KnowledgeBase, method: str, args: list[str]) -> object:
    if method in NO_ARG:
        fn: Callable[..., object] = getattr(kb, method)
        return to_json(fn())
    if method in ONE_ID:
        if len(args) != 1:
            raise QueryError(f"{method} takes exactly one id, got {args}")
        return to_json(getattr(kb, method)(args[0]))
    if method in LIST_ARG:
        keys: list[str] = []
        for a in args:
            keys += split_list(a)
        return to_json(getattr(kb, method)(keys))
    valid = sorted(ONE_ID | LIST_ARG | NO_ARG)
    raise QueryError(f"unknown method {method!r}. Valid methods: {', '.join(valid)}")


def cmd_build(a: argparse.Namespace) -> int:
    from phase0.build import build
    from phase0.toolbox import make_toolbox

    ws = Workspace(Path(a.workspace))
    res = build(ws, make_toolbox(ws.cache))
    print(json.dumps({"kb_version": res.kb_version, "timings_s": res.timings, "lines": res.lines}))
    return 0


def cmd_query(a: argparse.Namespace) -> int:
    root = Path(a.workspace)
    kb = KnowledgeBase(root / "kb", root / "source")
    print(json.dumps(run_query(kb, a.method, a.args)))
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="phase0")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build kb/ from source/ and config.yaml")
    b.add_argument("--workspace", required=True)
    b.set_defaults(fn=cmd_build)
    q = sub.add_parser("query", help="answer one KB query as JSON on stdout")
    q.add_argument("method")
    q.add_argument("args", nargs="*")
    q.add_argument("--workspace", required=True)
    q.set_defaults(fn=cmd_query)
    return ap


def main(argv: list[str] | None = None) -> int:
    a = parser().parse_args(argv)
    fn: Callable[[argparse.Namespace], int] = a.fn
    try:
        return fn(a)
    except (ContractError, QueryError) as exc:
        print(f"phase0: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
