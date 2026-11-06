"""T0a — build the target with the pack's build command, diagnostics mapped to file:line."""

from __future__ import annotations

from verifier.langpacks.base import BuildResult, LangPack, PackContext
from verifier.report.schema import Check, Scope, Status, TierResult, ToolInfo

MAX_ERRORS = 10


def run_t0a(pack: LangPack, ctx: PackContext, tool_version: str) -> tuple[TierResult, BuildResult]:
    res = pack.build(ctx)
    scope = Scope(
        level="program",
        what=f"{pack.name} build of the whole target repository",
        tools=[ToolInfo(name=f"{pack.name} build", version=tool_version)],
        commands=[res.command],
    )
    warnings = [d for d in res.diagnostics if d.severity != "ERROR"]
    errors = [d for d in res.diagnostics if d.severity == "ERROR"]
    if res.timed_out:
        tr = TierResult(status=Status.TIMEOUT, reason="build timed out", method="build", scope=scope,
                        duration_s=res.duration_s)
    elif res.ok:
        tr = TierResult(status=Status.PASS, method="build", scope=scope, duration_s=res.duration_s,
                        checks=[Check(name="build", status=Status.PASS, findings=warnings[:MAX_ERRORS],
                                      duration_s=res.duration_s)])
    elif "command not found" in res.output or res.output.rstrip().endswith(": not found"):
        tr = TierResult(status=Status.ERROR, reason="build tool not available in the toolchain image",
                        method="build", scope=scope, duration_s=res.duration_s,
                        checks=[Check(name="build", status=Status.ERROR, reason="tool missing",
                                      findings=errors[:MAX_ERRORS])])
    else:
        tr = TierResult(status=Status.FAIL, method="build", scope=scope, duration_s=res.duration_s,
                        checks=[Check(name="build", status=Status.FAIL, findings=errors[:MAX_ERRORS] + warnings[:3],
                                      duration_s=res.duration_s)],
                        details={"error_count": len(errors)})
    return tr, res
