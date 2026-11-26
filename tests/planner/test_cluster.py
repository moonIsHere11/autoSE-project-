"""Clustering, utilities and the module size band.  python3 -m unittest tests.planner.test_cluster -v"""
import unittest
from itertools import combinations
from pathlib import Path

import networkx as nx

from planner.architecture.cluster import Clusters, apply_band, cluster, louvain
from planner.architecture.config import PlannerConfig
from planner.architecture.features import add_similarity, similarity
from planner.architecture.graph import build_graph
from planner.kb import FixtureKb

FIXTURE = Path(__file__).parent / "fixtures" / "estate.json"
ACCT, CARD, TRAN = {"ACCTVIEW", "ACCTUPDT", "ACCTBAT"}, {"CARDLIST", "CARDUPDT", "CARDACT"}, {"TRANVAL", "TRANPOST", "TRANRPT"}


def fixture_clusters(cfg=None):
    cfg = cfg or PlannerConfig()
    kb = FixtureKb(FIXTURE)
    g = build_graph(kb, cfg)
    add_similarity(g, similarity(kb, cfg), cfg)
    return cluster(g, kb, cfg)


def clique(nodes, weight):
    g = nx.Graph()
    for a, b in combinations(nodes, 2):
        g.add_edge(a, b, weight=weight, evidence=[])
    return g


class ClusterTests(unittest.TestCase):
    def setUp(self):
        self.c = fixture_clusters()

    def test_fixture_groups(self):
        homes = []
        for group in (ACCT, CARD, TRAN):
            owners = [i for i, d in enumerate(self.c.domain) if group <= d]
            self.assertEqual(len(owners), 1, f"{group} not in exactly one domain cluster: {self.c.domain}")
            homes.append(owners[0])
        self.assertEqual(len(set(homes)), 3)

    def test_utilities_detected(self):
        self.assertEqual(self.c.utilities, [{"DATEFMT", "ERRHNDL"}])
        self.assertFalse(any({"DATEFMT", "ERRHNDL"} & d for d in self.c.domain))

    def test_isolated_program_stays_alone(self):
        self.assertEqual(self.c.isolated, {"ORPHAN"})
        self.assertFalse(any("ORPHAN" in d for d in self.c.domain))

    def test_every_program_exactly_once(self):
        everything = [p for d in self.c.domain for p in d] + [p for u in self.c.utilities for p in u] + list(self.c.isolated)
        self.assertEqual(len(everything), 13)
        self.assertEqual(len(set(everything)), 13)

    def test_oversized_split(self):
        a, b = [f"A{i:02}" for i in range(15)], [f"B{i:02}" for i in range(15)]
        g = nx.compose(clique(a, 5.0), clique(b, 5.0))
        g.add_edge("A00", "B00", weight=0.1, evidence=[])
        parts = apply_band(g, [set(a) | set(b)], PlannerConfig(band_max=25))
        self.assertEqual(sorted(map(sorted, parts)), [sorted(a), sorted(b)])

    def test_undersized_merged(self):
        big, small = [f"M{i}" for i in range(5)], ["S0", "S1"]
        g = nx.compose(clique(big, 1.0), clique(small, 1.0))
        g.add_edge("S0", "M0", weight=9.0, evidence=[])
        g.add_node("LONE")
        parts = apply_band(g, [set(big), set(small), {"LONE"}], PlannerConfig())
        self.assertIn(set(big) | set(small), parts)
        self.assertIn({"LONE"}, parts)  # no cross weight: stays, for review

    def test_merge_never_exceeds_band(self):
        big, small = [f"M{i}" for i in range(5)], ["S0", "S1"]
        g = nx.compose(clique(big, 1.0), clique(small, 1.0))
        g.add_edge("S0", "M0", weight=9.0, evidence=[])
        parts = apply_band(g, [set(big), set(small)], PlannerConfig(band_max=6))
        self.assertEqual(len(parts), 2)

    def test_deterministic(self):
        self.assertEqual(fixture_clusters(), self.c)
        self.assertIsInstance(self.c, Clusters)

    def test_louvain_sorted(self):
        g = nx.compose(clique(["A", "B", "C"], 1.0), clique(["X", "Y"], 1.0))
        self.assertEqual(louvain(g, 7), [{"A", "B", "C"}, {"X", "Y"}])


if __name__ == "__main__":
    unittest.main()
