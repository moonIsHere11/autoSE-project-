"""Planner settings. Every value can be overridden under `planner.architecture` in config.yaml."""
from __future__ import annotations

from dataclasses import dataclass, field, fields


@dataclass(frozen=True)
class Weights:
    call: float = 3.0         # CALL / LINK / XCTL between two programs
    copybook: float = 2.0     # shared record or code copybook, x IDF
    write_read: float = 2.0   # one writes a dataset/table the other reads, x IDF
    co_read: float = 1.0      # both read the same dataset/table, x IDF
    same_job: float = 0.5     # steps of the same JCL job
    similar: float = 1.0      # x similarity (vocabulary + I/O signature)


@dataclass(frozen=True)
class ReviewBudget:
    pass_steps: int = 25          # model calls per review pass
    explorer_calls: int = 5       # explore_program calls per pass
    explorer_steps: int = 15      # model calls per explorer run
    max_tokens: int | None = None  # per pass, sub-agents included


@dataclass(frozen=True)
class PlannerConfig:
    weights: Weights = field(default_factory=Weights)
    similarity_threshold: float = 0.35
    util_min_communities: int = 3
    util_min_fan_in: int = 5
    band_min: int = 3
    band_max: int = 25
    confidence_threshold: float = 0.6
    low_kb_confidence: float = 0.8
    seed: int = 7
    root_package: str = "app"
    review: ReviewBudget = field(default_factory=ReviewBudget)

    @classmethod
    def from_dict(cls, d: dict | None) -> PlannerConfig:
        d = dict(d or {})
        nested = {"weights": Weights, "review": ReviewBudget}
        known = {f.name for f in fields(cls)}
        unknown = set(d) - known
        if unknown:
            raise ValueError(f"unknown planner.architecture keys {sorted(unknown)}; known: {sorted(known)}")
        for key, typ in nested.items():
            if key in d:
                sub = dict(d[key] or {})
                bad = set(sub) - {f.name for f in fields(typ)}
                if bad:
                    raise ValueError(f"unknown planner.architecture.{key} keys {sorted(bad)}")
                d[key] = typ(**sub)
        return cls(**d)

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)
