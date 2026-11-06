import argparse
import sys

from .adapter import ContractError, check


def main(argv=None):
    ap = argparse.ArgumentParser(prog="phase2")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--workspace", required=True)
    c.add_argument("--submission", required=True)
    c.add_argument("--until", choices=["build", "lint", "differential", "verification"])
    a = ap.parse_args(argv)
    try:
        rep = check(a.workspace, a.submission, a.until)
        print(f"{a.submission}: {rep['verdict']}")
        return 0  # red is not a failed command
    except (ContractError, FileNotFoundError, KeyError) as e:
        print(f"bad input: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"internal error: {type(e).__name__}: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
