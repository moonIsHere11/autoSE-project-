"""The deterministic draft: KB -> graph (+ similarity) -> clusters -> modules with names, confidences,
evidence, roles and open questions. No LLM; the same KB and config always give the same plan."""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import replace

import networkx as nx

from ..kb import KnowledgeSource
from .cluster import cluster
from .config import PlannerConfig
from .features import add_similarity, comment_lines, program_tokens, similarity
from .graph import Evidence, build_graph
from .plan import ArchitecturePlan, Assignment, Module, OpenQuestion
from .render import RESERVED_PACKAGES, package_name
from .roles import assign_roles


def confidence(g: nx.Graph, program: str, members: set[str], ignore: set[str] = frozenset()) -> float:
    """Share of the program's edge weight that stays inside its module (0.0 when it has no edges). Edges to
    `ignore` (utility programs: everyone calls them, by design) do not count either way."""
    if program not in g:
        return 0.0
    total = inside = 0.0
    for _, other, d in g.edges(program, data=True):
        if other in ignore and other not in members:
            continue
        total += d["weight"]
        if other in members:
            inside += d["weight"]
    return inside / total if total else 0.0


def evidence_for(g: nx.Graph, program: str, members: set[str], k: int = 3) -> list[Evidence]:
    items = [replace(e, other=other) for _, other, d in g.edges(program, data=True) if other in members
             for e in d["evidence"]]
    return sorted(items, key=lambda e: (-e.weight, e.other, e.kind, e.item))[:k]


def module_names(groups: list[tuple[str, set[str]]], tokens: dict[str, Counter]) -> list[str]:
    """Top TF-IDF token per group (groups are documents), lower-cased and unique."""
    docs = [sum((tokens[p] for p in members), Counter()) for _, members in groups]
    df = Counter(t for d in docs for t in d)
    names: list[str] = []
    utilities = sum(1 for kind, _ in groups if kind == "utility")
    for (kind, members), doc in zip(groups, docs):
        total = sum(doc.values()) or 1
        ranked = sorted(doc, key=lambda t: (-(doc[t] / total) * math.log((len(docs) + 1) / df[t]), t))
        top = ranked[0].lower() if ranked else "module"
        if kind == "isolated":
            base = sorted(members)[0].lower()
        elif kind == "utility":
            base = "util" if utilities == 1 else f"util-{top}"
        else:
            base = top
        name, i = base, 2
        if package_name(name) in RESERVED_PACKAGES:
            name = base = f"{base}-module"
        while package_name(name) in {package_name(n) for n in names}:
            name, i = f"{base}-{i}", i + 1
        names.append(name)
    return names


def make_draft(kb: KnowledgeSource, cfg: PlannerConfig) -> tuple[ArchitecturePlan, nx.Graph]:
    g = build_graph(kb, cfg)
    add_similarity(g, similarity(kb, cfg), cfg)
    c = cluster(g, kb, cfg)
    groups = [("domain", s) for s in c.domain] + [("utility", s) for s in c.utilities] + \
             [("isolated", {p}) for p in sorted(c.isolated)]
    groups.sort(key=lambda x: (-len(x[1]), min(x[1])))
    progs = {p.id: p for p in kb.programs()}
    root = kb.source_root()
    tokens = {pid: Counter(program_tokens(p, comment_lines(root / p.file))) for pid, p in progs.items()}
    names = module_names(groups, tokens)

    utilities = {p for kind, members in groups if kind == "utility" for p in members}
    modules = []
    for i, ((kind, members), name) in enumerate(zip(groups, names), start=1):
        assignments = [Assignment(pid, round(confidence(g, pid, members, utilities), 4), evidence_for(g, pid, members),
                                  low_kb_confidence=progs[pid].confidence < cfg.low_kb_confidence)
                       for pid in sorted(members)]
        modules.append(Module(f"m{i:02}", name, "", kind, assignments))
    shared_types, shared_code, stores, jobs = assign_roles(kb, modules)
    plan = ArchitecturePlan(modules=modules, shared_types=shared_types, shared_code=shared_code, stores=stores,
                            jobs=jobs, inputs={"kb_version": kb.kb_version(), "seed": cfg.seed, "config": cfg.to_dict()})
    plan.open_questions = open_questions(plan, kb, g, cfg)
    return plan, g


def open_questions(plan: ArchitecturePlan, kb: KnowledgeSource, g: nx.Graph, cfg: PlannerConfig) -> list[OpenQuestion]:
    out = []
    home = {a.program: m for m in plan.modules for a in m.programs}
    for m in plan.modules:
        if m.kind == "domain" and len(m.programs) < cfg.band_min:
            out.append(OpenQuestion("undersized_module", m.id, f"{len(m.programs)} program(s), below the band of "
                                                               f"{cfg.band_min}; nothing to merge with in the KB"))
        if m.kind == "domain" and len(m.programs) > cfg.band_max:
            out.append(OpenQuestion("oversized_module", m.id, f"{len(m.programs)} programs, above the band of "
                                                              f"{cfg.band_max}; it did not split cleanly"))
        for a in m.programs:
            if m.kind == "isolated":
                out.append(OpenQuestion("isolated", a.program, "no calls, shared copybooks, shared data or similar "
                                                                "programs in the KB apart from shared utilities; "
                                                                "placed alone"))
            elif m.kind == "domain" and a.confidence < cfg.confidence_threshold and a.decided_by == "draft":
                pull = Counter()
                for _, other, d in g.edges(a.program, data=True):
                    if other in home and home[other] is not m and home[other].kind != "utility":
                        pull[home[other].id] += d["weight"]
                best = f"; strongest pull from {pull.most_common(1)[0][0]}" if pull else ""
                out.append(OpenQuestion("uncertain_program", a.program,
                                        f"confidence {a.confidence:.2f} in {m.id}{best}"))
            if a.low_kb_confidence:
                out.append(OpenQuestion("low_kb_confidence", a.program, "KB facts come from a tolerant/heuristic parse"))
    for s in plan.stores:
        if s.shared_write:
            mods = sorted({home[p].id for p in s.writers})
            out.append(OpenQuestion("shared_write", s.id, f"written by modules {', '.join(mods)}; owner {s.owner}"))
    if kb.programs() and not kb.store_uses():
        out.append(OpenQuestion("missing_kb_fact", "store_uses", "the KB lists no file, dataset or table use; "
                                                                 "data ownership and data coupling are unknown"))
    for job in plan.jobs:
        for step in job.steps:
            if step["program"] is None:
                out.append(OpenQuestion("missing_kb_fact", f"{job.id}.{step['step']}",
                                        "the KB does not say which program this step runs (e.g. IKJEFT01/DB2)"))
    return out
