"""Human-readable `summary.md`."""

from __future__ import annotations

from verifier.report.schema import Report, Status, TierResult

_ICON = {
    Status.PASS: "PASS",
    Status.FAIL: "FAIL",
    Status.ERROR: "ERROR",
    Status.TIMEOUT: "TIMEOUT",
    Status.NOT_APPLICABLE: "N/A",
    Status.SKIPPED: "skip",
}


def cell(t: TierResult | None) -> str:
    if t is None:
        return "—"
    s = _ICON[t.status]
    if t.stub:
        s = f"STUB {s}"
    if t.method in ("exhaustive",) and t.status == Status.PASS:
        s += " (exhaustive)"
    if t.bound and t.status == Status.PASS:
        s += f" (bound {t.bound})"
    return s


def render_summary(report: Report) -> str:
    r = report.run
    s = report.summary
    out: list[str] = []
    out.append(f"# Verification summary — {r.lang}, mode `{r.mode}`\n")
    out.append(f"- COBOL: `{r.cobol}`  \n- Target: `{r.target}`  \n- Tiers: {r.tiers}; seed {r.seed}, "
               f"iteration {r.iteration} (effective seed {r.effective_seed})")
    out.append(f"- Verifier {report.verifier_version}; GnuCOBOL: {report.toolchain.get('gnucobol', '?')}; "
               f"image `{report.toolchain.get('image', '?')}`")
    out.append(f"- cobc flags: `{' '.join(report.config.get('cobc_flags', []))}`; normalisers: "
               f"{report.config.get('normalisers') or 'none'}\n")
    out.append("## Headline: units reaching each level\n")
    out.append("| level | meaning | units ≥ level |")
    out.append("|---|---|---|")
    meaning = {"0": "builds + static checks", "1": "+ differential testing (GnuCOBOL oracle)",
               "2": "+ exhaustive / bounded symbolic equivalence", "3": "+ contracts"}
    for k in ("0", "1", "2", "3"):
        out.append(f"| {k} | {meaning[k]} | {s.pct_units_at_least_level.get(k, 0.0):.1f}% |")
    out.append(f"\n**{s.accepted}/{s.units} units accepted.** Level histogram: {s.level_histogram}. "
               f"Evidence: {s.evidence_histogram or '{}'}.\n")
    if s.stubs:
        out.append(f"> STUB components (not real evidence): {', '.join(s.stubs)}\n")
    out.append("## Programs\n")
    out.append("| program | out of scope | T0 | T1 | T2 | notes |")
    out.append("|---|---|---|---|---|---|")
    for p in report.programs:
        t1 = p.tiers.get("T1")
        note = ""
        if t1 is not None and t1.cases_run is not None:
            cov = f", para cov {t1.coverage.paragraph:.2f}" if t1.coverage else ""
            note = f"{t1.cases_run} cases, {t1.cases_failed or 0} failed, {t1.cases_excluded or 0} excluded{cov}"
        out.append(f"| {p.id} | {', '.join(p.out_of_scope) or '—'} | {cell(p.tiers.get('T0'))} | "
                   f"{cell(t1)} | {cell(p.tiers.get('T2'))} | {note} |")
    out.append("\n## Units\n")
    out.append("| unit | level | evidence | accepted | T0 | T1 | T2 | T3 | score | why not accepted |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    for u in report.units:
        reasons = "; ".join(u.acceptance.reasons) if u.acceptance and not u.accepted else ""
        out.append(
            f"| {u.id} | {u.level} | {','.join(u.evidence) or '—'} | {'yes' if u.accepted else 'abstain'} | "
            f"{cell(u.tiers.get('T0'))} | {cell(u.tiers.get('T1'))} | {cell(u.tiers.get('T2'))} | "
            f"{cell(u.tiers.get('T3'))} | {u.score:.2f} | {reasons} |"
        )
    na_reasons = sorted({f"{k}: {t.reason}" for p in report.programs for k, t in p.tiers.items()
                      if t.status in (Status.NOT_APPLICABLE, Status.ERROR, Status.TIMEOUT) and t.reason})
    if reasons:
        out.append("\n## Not-applicable / error reasons\n")
        out.extend(f"- {x}" for x in reasons[:40])
    if s.tier_timings_s:
        out.append("\n## Time per tier (s)\n")
        out.append(" · ".join(f"{k}: {v:.1f}" for k, v in s.tier_timings_s.items()))
    if report.errors:
        out.append("\n## Verifier errors\n")
        out.extend(f"- {e}" for e in report.errors)
    return "\n".join(out) + "\n"
