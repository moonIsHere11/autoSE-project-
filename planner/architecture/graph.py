"""The program coupling graph: one node per program, weighted edges with the evidence behind each weight.

IDF = log(N / users) damps items everyone uses (common headers, SQLCA): an item used by every program adds 0.
Private stores (an ASSIGN name the KB could not bind to a dataset) add no edges."""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations

import networkx as nx

from ..kb import KnowledgeSource
from .config import PlannerConfig


@dataclass(frozen=True)
class Evidence:
    kind: str      # call | copybook | write_read | co_read | same_job | similar
    other: str     # the other program, from one program's point of view ("" when stored on an edge)
    item: str      # what connects them: callee, copybook, store, job, similarity score
    weight: float


def idf(n: int, users: int) -> float:
    return math.log(n / users) if users else 0.0


def damp(n: int, users: int, cfg: PlannerConfig) -> float:
    """IDF, except in an estate smaller than one module, where 'used by everyone' says nothing."""
    return 1.0 if n < cfg.band_min else idf(n, users)


class _Edges:
    """(pair, kind, item) -> weight, counted once however often a fact repeats."""

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[tuple[str, str], float]] = defaultdict(dict)

    def add(self, a: str, b: str, kind: str, item: str, weight: float) -> None:
        if a == b or weight <= 0:
            return
        self.items[tuple(sorted((a, b)))][(kind, item)] = weight


def build_graph(kb: KnowledgeSource, cfg: PlannerConfig) -> nx.Graph:
    w = cfg.weights
    programs = kb.programs()
    ids = {p.id for p in programs}
    n = len(programs)
    edges = _Edges()

    for p in programs:
        for callee in set(p.calls):
            if callee in ids:
                edges.add(p.id, callee, "call", callee, w.call)

    copy_users: dict[str, set[str]] = defaultdict(set)
    for p in programs:
        for c in p.copybooks:
            copy_users[c].add(p.id)
    for copybook, users in copy_users.items():
        weight = w.copybook * damp(n, len(users), cfg)
        for a, b in combinations(sorted(users), 2):
            edges.add(a, b, "copybook", copybook, weight)

    readers: dict[str, set[str]] = defaultdict(set)
    writers: dict[str, set[str]] = defaultdict(set)
    for u in kb.store_uses():
        if u.store_kind == "private" or u.program not in ids:
            continue
        (writers if u.mode == "write" else readers)[u.store].add(u.program)
    for store in sorted(set(readers) | set(writers)):
        factor = damp(n, len(readers[store] | writers[store]), cfg)
        for wr in sorted(writers[store]):
            for rd in sorted(readers[store]):
                edges.add(wr, rd, "write_read", store, w.write_read * factor)
        for a, b in combinations(sorted(readers[store]), 2):
            if (("write_read", store) not in edges.items.get((a, b), {})):
                edges.add(a, b, "co_read", store, w.co_read * factor)

    jobs: dict[str, set[str]] = defaultdict(set)
    for s in kb.job_steps():
        if s.program in ids:
            jobs[s.job].add(s.program)
    for job, members in jobs.items():
        for a, b in combinations(sorted(members), 2):
            edges.add(a, b, "same_job", job, w.same_job)

    g = nx.Graph()
    g.add_nodes_from(sorted(ids))
    for (a, b), items in sorted(edges.items.items()):
        ev = [Evidence(kind, "", item, weight) for (kind, item), weight in sorted(items.items())]
        g.add_edge(a, b, weight=sum(e.weight for e in ev), evidence=ev)
    return g
