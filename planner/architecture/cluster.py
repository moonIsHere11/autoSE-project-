"""From the program graph to candidate modules.

    louvain on the whole graph            -> draft communities (only used to spot utilities)
    utilities out                         -> called from many communities, or high fan-in and no writes
    isolated out                          -> programs with no edge at all (own module, flagged for review)
    louvain on the rest, then size band   -> split oversized, merge undersized into their closest neighbour
Every step is deterministic for a fixed seed."""
from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from ..kb import KnowledgeSource
from .config import PlannerConfig


@dataclass
class Clusters:
    domain: list[set[str]] = field(default_factory=list)
    utilities: list[set[str]] = field(default_factory=list)
    isolated: set[str] = field(default_factory=set)


def _order(communities) -> list[set[str]]:
    return sorted((set(c) for c in communities if c), key=lambda c: (-len(c), min(c)))


def louvain(g: nx.Graph, seed: int, resolution: float = 1.0) -> list[set[str]]:
    if g.number_of_nodes() == 0:
        return []
    return _order(nx.community.louvain_communities(g, weight="weight", seed=seed, resolution=resolution))


def find_utilities(g: nx.Graph, communities: list[set[str]], kb: KnowledgeSource, cfg: PlannerConfig) -> set[str]:
    home = {p: i for i, c in enumerate(communities) for p in c}
    callers: dict[str, set[str]] = {}
    for p in kb.programs():
        for callee in set(p.calls):
            if callee != p.id:
                callers.setdefault(callee, set()).add(p.id)
    writers = {u.program for u in kb.store_uses() if u.mode == "write"}
    out = set()
    for prog, who in callers.items():
        if prog not in g:
            continue
        spread = {home[c] for c in who if c in home}
        if len(spread) >= cfg.util_min_communities or (len(who) >= cfg.util_min_fan_in and prog not in writers):
            out.add(prog)
    return out


def _split(g: nx.Graph, community: set[str], cfg: PlannerConfig) -> list[set[str]]:
    parts, resolution = [community], 1.0
    for _ in range(5):
        resolution *= 1.5
        new = louvain(g.subgraph(community), cfg.seed, resolution)
        if new == parts:
            break
        parts = new
        if all(len(p) <= cfg.band_max for p in parts):
            break
    return parts


def apply_band(g: nx.Graph, communities: list[set[str]], cfg: PlannerConfig) -> list[set[str]]:
    out: list[set[str]] = []
    for c in _order(communities):
        out += _split(g, c, cfg) if len(c) > cfg.band_max else [set(c)]
    groups = dict(enumerate(out))
    home = {p: gid for gid, members in groups.items() for p in members}
    changed = True
    while changed:  # each pass reads only the small groups' own edges
        changed = False
        for gid in sorted((k for k, c in groups.items() if len(c) < cfg.band_min),
                          key=lambda k: (len(groups[k]), min(groups[k]))):
            small = groups.get(gid)
            if small is None or len(small) >= cfg.band_min:
                continue
            cross: dict[int, float] = {}
            for p in small:
                for q, d in g.adj[p].items():
                    other = home.get(q)
                    if other is not None and other != gid:
                        cross[other] = cross.get(other, 0.0) + d.get("weight", 0.0)
            options = [(w, o) for o, w in cross.items() if w > 0 and len(groups[o]) + len(small) <= cfg.band_max]
            if not options:
                continue
            _, target = max(options, key=lambda t: (t[0], -len(groups[t[1]]), min(groups[t[1]])))
            groups[target] |= small
            for p in small:
                home[p] = target
            del groups[gid]
            changed = True
    return _order(groups.values())


def cluster(g: nx.Graph, kb: KnowledgeSource, cfg: PlannerConfig) -> Clusters:
    draft = louvain(g, cfg.seed)
    utils = find_utilities(g, draft, kb, cfg)
    others = g.subgraph(set(g.nodes) - utils)
    isolated = {p for p in others.nodes if others.degree(p) == 0}  # no links except to utilities
    rest = g.subgraph(set(g.nodes) - utils - isolated)
    domain = apply_band(g, louvain(rest, cfg.seed), cfg) if rest.number_of_nodes() else []
    if not utils:
        utilities: list[set[str]] = []
    elif len(utils) < cfg.band_min:
        utilities = [set(utils)]
    else:
        utilities = apply_band(g, louvain(g.subgraph(utils), cfg.seed), cfg)
    return Clusters(domain, utilities, isolated)
