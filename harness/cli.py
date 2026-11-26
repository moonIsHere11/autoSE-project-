import argparse
import json
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog="harness")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the agent over the profile's tasks, verifying every submission")
    r.add_argument("--workspace", required=True)
    r.add_argument("--tasks", help="comma-separated task ids (default: all)")
    r.add_argument("--max-steps", type=int, default=40)
    t = sub.add_parser("tasks", help="list the tasks the profile finds (no LLM)")
    t.add_argument("--workspace", required=True)
    a = ap.parse_args(argv)
    try:
        from .config import build_runner
        only = a.tasks.split(",") if getattr(a, "tasks", None) else None
        if a.cmd == "tasks":
            runner = build_runner(a.workspace, llm=object(), verifier=object())
            for task in runner.profile.tasks(runner.ws, only):
                print(task.id, json.dumps(task.data))
            return 0
        print(json.dumps(build_runner(a.workspace).run(only, a.max_steps)))
        return 0  # failed tasks are a result, not a failed command
    except (FileNotFoundError, KeyError, ValueError) as e:
        print(f"bad input: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"internal error: {type(e).__name__}: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
