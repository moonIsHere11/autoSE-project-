#!/usr/bin/env python3
"""Classify a `jbmc --json-ui --trace` run and extract counterexample inputs.

Usage: parse_jbmc.py <jbmc-json-output-file> <jbmc-exit-code>
Prints one JSON object: {"verdict": ..., "failed": [...], "inputs": {...}, "errors": [...]}

Verdicts
  PROVED              cProverStatus == "success", exit 0, every property SUCCESS
  COUNTEREXAMPLE      some non-unwind property FAILURE (equivalence assertion or runtime exception)
  BOUND_INSUFFICIENT  only unwinding assertions (property id contains ".unwind.") failed
  TOOL_ERROR          exit code not in {0, 10}, unparsable JSON, or no cProverStatus
"""
import json
import re
import sys

IN_VAR = re.compile(r"^in_\w+$")          # harness convention: one local per COBOL input field


def main() -> None:
    path, rc = sys.argv[1], int(sys.argv[2])
    out = {"verdict": None, "exit_code": rc, "failed": [], "inputs": {}, "errors": []}
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        out["verdict"] = "TOOL_ERROR"
        out["errors"].append(f"unparsable output: {exc}")
        print(json.dumps(out, indent=1))
        return

    status, results = None, []
    for item in doc:
        if item.get("messageType") == "ERROR":
            out["errors"].append(item.get("messageText"))
        if "cProverStatus" in item:
            status = item["cProverStatus"]
        if "result" in item:
            results = item["result"]

    if rc not in (0, 10) or status is None:
        out["verdict"] = "TOOL_ERROR"
        print(json.dumps(out, indent=1))
        return

    failed = [r for r in results if r.get("status") == "FAILURE"]
    out["failed"] = [{"property": r["property"], "description": r.get("description"),
                      "line": (r.get("sourceLocation") or {}).get("line")} for r in failed]
    real = [r for r in failed if ".unwind." not in r["property"]]
    if not failed:
        out["verdict"] = "PROVED" if status == "success" and rc == 0 else "TOOL_ERROR"
    elif real:
        out["verdict"] = "COUNTEREXAMPLE"
    else:
        out["verdict"] = "BOUND_INSUFFICIENT"

    # Counterexample inputs: last value assigned to each in_* local on the first real failure's
    # trace. Steps without a sourceLocation are JBMC's entry-time declarations of the locals
    # (garbage values) and are skipped. Values are decoded from the two's-complement "binary"
    # field ("data" is a Java literal such as "-3L" / "'a'").
    witness = real[0] if real else (failed[0] if failed else None)
    if witness is not None:
        for step in witness.get("trace", []):
            if step.get("stepType") != "assignment" or step.get("hidden"):
                continue
            lhs = step.get("lhs", "")
            if IN_VAR.match(lhs) and "sourceLocation" in step:
                out["inputs"][lhs] = decode(step["value"])
    print(json.dumps(out, indent=1))


def decode(value: dict):
    """Integer/char/boolean trace value -> Python int (signed for Java integral types)."""
    bits, width = value.get("binary"), value.get("width")
    if bits is None or width is None:
        return value.get("data")
    n = int(bits, 2)
    if value.get("type") in ("byte", "short", "int", "long") and n >= 1 << (width - 1):
        n -= 1 << width
    return n


if __name__ == "__main__":
    main()
