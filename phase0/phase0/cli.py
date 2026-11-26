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
    if method == "context_packet":
        from phase0.context import context_packet

        if not args or len(args) > 2:
            raise QueryError("context_packet takes a unit id and an optional character budget (default 6000)")
        budget = 6000
        if len(args) == 2:
            budget = int(args[1])
        return context_packet(kb, args[0], budget)
    valid = sorted(ONE_ID | LIST_ARG | NO_ARG | {"context_packet"})
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


def cmd_eval(a: argparse.Namespace) -> int:
    from phase0.evaluation.render import render
    from phase0.evaluation.runner import run
    from phase0.target import REPO

    out = Path(a.out)
    gold: Path | None = None
    if a.gold:
        gold = Path(a.gold)
    ev = run(Path(a.workspace), out, a.datasets.split(","), Path(a.carddemo or REPO / "data" / "carddemo"), gold,
             a.baseline == "phase1", a.e2e, a.only, a.summaries)
    render(out, out / "RESULTS.md")
    print(json.dumps({"out": str(out), "seconds": ev.seconds, "failures": len(ev.failures)}))
    return 0


def cmd_report(a: argparse.Namespace) -> int:
    from phase0.report import stale_docs, write_docs

    ws = Workspace(Path(a.workspace))
    stale = stale_docs(ws.kb, ws.source)
    if stale:
        raise ContractError("kb/docs differs from the facts (kb built by another Phase 0 version?): "
                            + ", ".join(stale[:10]) + "; rebuild with `phase0 build`")
    docs = write_docs(ws.kb, ws.source)
    print(json.dumps({"docs": sorted(docs), "root": str(ws.kb / "docs")}))
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
    r = sub.add_parser("report", help="check and list the generated views and decision records under kb/docs")
    r.add_argument("--workspace", required=True)
    r.set_defaults(fn=cmd_report)
    e = sub.add_parser("eval", help="evaluate Phase 0 against GnuCOBOL, traces, Java and gold (task section 7)")
    e.add_argument("--workspace", required=True, help="scratch directory for the per-program workspaces")
    e.add_argument("--out", required=True, help="where metrics.json, failures.jsonl and RESULTS.md go")
    e.add_argument("--gold", help="directory with <annotator>.json gold files")
    e.add_argument("--baseline", choices=["phase1", "none"], default="phase1")
    e.add_argument("--datasets", default="D1,D2,D3")
    e.add_argument("--carddemo", help="CardDemo checkout (default: data/carddemo)")
    e.add_argument("--e2e", action="store_true", help="also run integration/e2e_scripted.py (E9)")
    e.add_argument("--only", help="evaluate one program (repro)")
    e.add_argument("--summaries", help="enable stage G on D1 and score E11, e.g. ollama:qwen2.5:3b or groq:<model>; '@N' summarises the first N paragraphs per program; ',num_gpu=-1' etc. passes Ollama memory options")
    e.set_defaults(fn=cmd_eval)
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
