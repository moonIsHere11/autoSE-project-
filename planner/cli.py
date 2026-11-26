"""planner architecture --workspace W [--target java|python|go] [--no-agent] [--fixture PATH]

Reads the KB (W/kb/ written by Phase 0, or a fixture JSON), builds the deterministic draft, lets the planner
agent review the uncertain parts (unless --no-agent), and writes W/plan/architecture.json + architecture.md.
Exit codes: 0 ok, 2 bad input (missing KB, invalid config, unknown target), 3 internal error."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from harness.registry import load_adapter

from .architecture.config import PlannerConfig
from .architecture.draft import make_draft
from .architecture.render import TARGETS, layout, render_markdown
from .architecture.review import review
from .architecture.validate import validate_plan
from .kb import FixtureKb
from .kb_phase0 import Phase0Kb

DEFAULT_LLM = "harness.llm.groq:GroqLLM"


class BadInput(Exception):
    pass


def _config(w: Path) -> dict:
    path = w / "config.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def _llm(config: dict):
    spec = (config.get("harness") or {}).get("llm") or {}
    spec = {"adapter": spec} if isinstance(spec, str) else dict(spec)
    return load_adapter(spec.pop("adapter", DEFAULT_LLM), **spec)


def architecture(args: argparse.Namespace) -> dict:
    w = Path(args.workspace).resolve()
    config = _config(w)
    try:
        cfg = PlannerConfig.from_dict((config.get("planner") or {}).get("architecture"))
    except (TypeError, ValueError) as e:
        raise BadInput(f"config.yaml planner.architecture: {e}") from e
    target = (args.target or (config.get("target") or {}).get("language") or "java").lower()
    if target not in TARGETS:
        raise BadInput(f"unknown target {target!r}; one of {sorted(TARGETS)}")
    if args.fixture:
        kb = FixtureKb(Path(args.fixture))
    else:
        if not (w / "kb" / "manifest.json").exists():
            raise BadInput(f"no KB at {w / 'kb'} (run `phase0 build --workspace {w}` first, or pass --fixture)")
        kb = Phase0Kb(w)
    plan, g = make_draft(kb, cfg)
    if not args.no_agent:
        plan = review(plan, g, kb, _llm(config), cfg, target=target.capitalize(), log=lambda *a: print(*a, file=sys.stderr))
    plan.layout = layout(plan, target, cfg.root_package)
    plan.inputs = {**plan.inputs, "target": target}
    problems = validate_plan(plan, kb)
    if problems:  # never write a plan that breaks its own invariants
        raise RuntimeError("plan failed validation: " + "; ".join(problems[:5]))
    out = w / "plan"
    out.mkdir(parents=True, exist_ok=True)
    (out / "architecture.json").write_text(json.dumps(plan.to_dict(), indent=1) + "\n")
    (out / "architecture.md").write_text(render_markdown(plan))
    return {"plan": str(out / "architecture.json"), "modules": len(plan.modules),
            "open_questions": len(plan.open_questions), "edits": len(plan.edits)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="planner")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("architecture", help="plan the target architecture from the KB")
    a.add_argument("--workspace", required=True)
    a.add_argument("--target", help="java | python | go (default: config.yaml target.language, else java)")
    a.add_argument("--no-agent", action="store_true", help="deterministic draft only, no LLM")
    a.add_argument("--fixture", help="read the KB from a FixtureKb JSON file instead of W/kb/")
    args = ap.parse_args(argv)
    try:
        print(json.dumps(architecture(args)))
        return 0
    except (BadInput, FileNotFoundError, json.JSONDecodeError, yaml.YAMLError) as e:
        print(f"bad input: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 - report, never a traceback, to the caller
        print(f"internal error: {type(e).__name__}: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
