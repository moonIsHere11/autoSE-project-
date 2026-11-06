import argparse
import json
import sys
from pathlib import Path


def main(argv=None):
    ap = argparse.ArgumentParser(prog="phase1")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--workspace", required=True)
    r.add_argument("--units")
    r.add_argument("--max-steps", type=int, default=40)
    an = sub.add_parser("analyze", help="static analysis only (no LLM): writes <ws>/phase1/{index.json,architecture.md}")
    an.add_argument("--workspace", required=True)
    rp = sub.add_parser("report", help="interactive HTML atlas of the analysis (no LLM)")
    rp.add_argument("--workspace", required=True)
    rp.add_argument("--out", default=None)
    t = sub.add_parser("tool", help="call one exploration tool directly (no LLM), for testing")
    t.add_argument("--workspace", required=True)
    t.add_argument("name")
    t.add_argument("args", nargs="?", default="{}")
    a = ap.parse_args(argv)
    try:
        from .workspace import Workspace
        from .agent import ensure_analysis, run
        from .tools import ToolBox
        ws = Workspace(a.workspace)
        if a.cmd == "analyze":
            ix = ensure_analysis(ws, force=True)
            print(ix.overview())
            return 0
        if a.cmd == "report":
            from .report import render
            out = Path(a.out or Path(a.workspace) / "phase1" / "atlas.html")
            out.write_text(render(ensure_analysis(ws, force=True)))
            print(out)
            return 0
        if a.cmd == "tool":
            print(ToolBox(ws, ensure_analysis(ws)).call(a.name, json.loads(a.args)))
            return 0
        res = run(ws, wanted=a.units.split(",") if a.units else None, max_steps=a.max_steps)
        print(json.dumps(res))
        return 0
    except (FileNotFoundError, KeyError) as e:
        print(f"bad input: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"internal error: {type(e).__name__}: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
