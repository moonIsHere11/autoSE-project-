"""`verify` command line. Exit codes: 0 all accepted, 1 some unit not accepted, 2 verifier error."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from verifier.manifest import ManifestError
from verifier.pipeline import VerifierError
from verifier.sandbox.docker_runner import SandboxUnavailable


def _tiers(s: str) -> list[int]:
    out = sorted({int(x) for x in s.split(",") if x.strip()})
    if any(t not in (0, 1, 2, 3) for t in out):
        raise argparse.ArgumentTypeError("tiers must be among 0,1,2,3")
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="verify", description="COBOL -> Java/Python/Go equivalence verifier")
    p.add_argument("--cobol", required=True, type=Path)
    p.add_argument("--target", required=True, type=Path)
    p.add_argument("--lang", required=True, choices=["java", "python", "go"])
    p.add_argument("--manifest", type=Path)
    p.add_argument("--mode", choices=["fast", "full"], default="fast")
    p.add_argument("--units", type=lambda s: [u.strip() for u in s.split(",") if u.strip()])
    p.add_argument("--tiers", type=_tiers)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--previous-report", type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--config", type=Path)
    return p


def repro_main(argv: list[str]) -> int:
    from verifier.repro import repro

    p = argparse.ArgumentParser(prog="verify repro", description="re-run one test case on both sides")
    p.add_argument("--case", required=True, type=Path)
    p.add_argument("--report", required=True, type=Path)
    a = p.parse_args(argv)
    return repro(a.case, a.report)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "repro":
        try:
            return repro_main(argv[1:])
        except (VerifierError, SandboxUnavailable) as exc:
            print(f"verify repro: error: {exc}", file=sys.stderr)
            return 2
    args = build_parser().parse_args(argv)
    from verifier.api import verify

    try:
        report = verify(
            cobol=args.cobol, target=args.target, lang=args.lang, out=args.out, manifest=args.manifest,
            mode=args.mode, units=args.units, tiers=args.tiers, seed=args.seed,
            previous_report=args.previous_report, config=args.config, argv=["verify", *argv],
        )
    except (VerifierError, SandboxUnavailable, ManifestError) as exc:
        print(f"verify: error: {exc}", file=sys.stderr)
        return 2
    s = report.summary
    print(f"{s.accepted}/{s.units} units accepted; level histogram {s.level_histogram}; "
          f"report: {Path(args.out) / 'report.json'}")
    if report.errors:
        for e in report.errors:
            print(f"verify: {e}", file=sys.stderr)
        return 2
    return 0 if s.units and s.accepted == s.units else 1


if __name__ == "__main__":
    sys.exit(main())
