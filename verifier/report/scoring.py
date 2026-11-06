"""Levels, evidence, score and the acceptance policy (spec section 8)."""

from __future__ import annotations

from collections import Counter

from verifier.config import AcceptancePolicy
from verifier.report.schema import Acceptance, Report, Status, Summary, TierResult, UnitResult

TIER_KEYS = ("T0", "T1", "T2", "T3")


def _passed(t: TierResult | None) -> bool:
    return t is not None and t.status == Status.PASS


def compute_level(unit: UnitResult) -> int:
    level = -1
    for i, key in enumerate(TIER_KEYS):
        if _passed(unit.tiers.get(key)):
            level = i
        else:
            break
    return level


def compute_evidence(unit: UnitResult) -> list[str]:
    ev: list[str] = []
    for key in ("T0", "T1", "T1u"):
        if _passed(unit.tiers.get(key)):
            ev.append(key)
    t2 = unit.tiers.get("T2")
    if t2 is not None:
        for sub in ("T2a", "T2b"):
            if _passed(t2.sub.get(sub)):
                ev.append(sub)
    if _passed(unit.tiers.get("T3")):
        ev.append("T3")
    return ev


def compute_score(unit: UnitResult) -> float:
    score = 0.0
    if _passed(unit.tiers.get("T0")):
        score += 1.0
    t1 = unit.tiers.get("T1")
    if t1 is not None:
        if t1.status == Status.PASS:
            score += 1.0
        elif t1.status == Status.FAIL and t1.pass_fraction is not None:
            score += max(0.0, min(1.0, t1.pass_fraction))
    if _passed(unit.tiers.get("T2")):
        score += 1.0
    if _passed(unit.tiers.get("T3")):
        score += 1.0
    return round(score, 4)


def decide_acceptance(unit: UnitResult, selected: list[str], policy: AcceptancePolicy) -> Acceptance:
    reasons: list[str] = []
    t0 = unit.tiers.get("T0")
    if not _passed(t0):
        reasons.append(f"T0 {t0.status.value if t0 else 'missing'}")
    t1 = unit.tiers.get("T1")
    if "T1" in selected:
        if not _passed(t1):
            reasons.append(f"T1 {t1.status.value if t1 else 'missing'}")
        elif t1 is not None:
            cov = t1.coverage.paragraph if t1.coverage else 0.0
            if cov < policy.coverage_threshold:
                reasons.append(
                    f"T1 paragraph coverage {cov:.2f} < threshold {policy.coverage_threshold:.2f}"
                )
    else:
        reasons.append("T1 not selected (acceptance requires T1)")
    for key in ("T2", "T3"):
        if key not in selected:
            continue
        t = unit.tiers.get(key)
        if t is None:
            reasons.append(f"{key} missing")
        elif t.status.value not in policy.t2_t3_allowed:
            detail = f": {t.reason}" if t.reason else ""
            reasons.append(f"{key} {t.status.value}{detail}")
    if policy.require_integrity and not unit.integrity_clean:
        reasons.append("integrity checks not clean")
    return Acceptance(
        accepted=not reasons,
        tiers_considered=selected,
        reasons=reasons,
        policy=policy.model_dump(),
    )


def finalise_unit(unit: UnitResult, selected: list[str], policy: AcceptancePolicy) -> None:
    unit.level = compute_level(unit)
    unit.evidence = compute_evidence(unit)
    unit.score = compute_score(unit)
    unit.acceptance = decide_acceptance(unit, selected, policy)
    unit.accepted = unit.acceptance.accepted


def summarise(report: Report, tier_timings: dict[str, float]) -> Summary:
    units = report.units
    n = len(units)
    hist = Counter(str(u.level) for u in units)
    level_hist = {str(k): hist.get(str(k), 0) for k in range(-1, 4)}
    pct = {}
    for k in range(0, 4):
        at_least = sum(1 for u in units if u.level >= k)
        pct[str(k)] = round(100.0 * at_least / n, 1) if n else 0.0
    ev = Counter(e for u in units for e in u.evidence)
    stubs: set[str] = set()
    for u in units:
        for key, t in u.tiers.items():
            if t.stub:
                stubs.add(key)
            for c in t.checks:
                if c.stub:
                    stubs.add(f"{key}:{c.name}")
            for sk, s in t.sub.items():
                if s.stub:
                    stubs.add(f"{key}:{sk}")
    return Summary(
        units=n,
        accepted=sum(1 for u in units if u.accepted),
        level_histogram=level_hist,
        pct_units_at_least_level=pct,
        evidence_histogram=dict(sorted(ev.items())),
        tier_timings_s={k: round(v, 3) for k, v in tier_timings.items()},
        stubs=sorted(stubs),
        programs=len(report.programs),
        programs_out_of_scope=sum(1 for p in report.programs if p.out_of_scope),
    )
