"""Render a Verdict as the text the agent reads (findings, concrete counterexamples, reproduce commands)."""
from .types import Verdict


def format_verdict(sid: str, v: Verdict) -> str:
    lines = [f"Submission {sid}: verdict={v.status.upper()}", v.summary]
    for f in v.findings:
        if f.get("severity") == "info":
            continue
        loc = f.get("location")
        lines.append(f"- [{f['severity']}/{f['category']}] {f['message']}" + (f" ({loc['file']}:{loc['line']})" if loc else ""))
        if f.get("kb_refs"):
            lines.append(f"  related: {', '.join(f['kb_refs'])}")
        ce = f.get("counterexample")
        if ce:
            lines.append(f"  counterexample: inputs={ce['inputs']} expected={ce['expected']} actual={ce['actual']}")
        if f.get("reproduce"):
            lines.append(f"  reproduce: {f['reproduce']}")
    return "\n".join(lines)
