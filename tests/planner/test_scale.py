"""Scale: the draft must stay usable at estate size (spec: hundreds to thousands of programs).
python3 -m unittest tests.planner.test_scale -v"""
import math
import time
import unittest
from collections import Counter
from itertools import combinations
from pathlib import Path

from planner.architecture.config import PlannerConfig
from planner.architecture.features import comment_lines, program_tokens, similarity
from planner.architecture.graph import idf
from planner.kb import FixtureKb
from planner.kb_phase0 import Phase0Kb
from tests.planner.synthetic import estate_kb, phase0_workspace

FIXTURE = Path(__file__).parent / "fixtures" / "estate.json"


def brute_force_similarity(kb, cfg):
    """The definition, pair by pair (spec 6.2 step 2), as a reference for the fast implementation."""
    programs = kb.programs()
    n = len(programs)
    docs = {p.id: Counter(program_tokens(p, comment_lines(kb.source_root() / p.file))) for p in programs}
    df = Counter(t for c in docs.values() for t in c)
    vec = {pid: {t: (k / sum(c.values())) * idf(n, df[t]) for t, k in c.items()} for pid, c in docs.items() if c}
    users = Counter(c for p in programs for c in set(p.copybooks))
    records = {k for k, v in kb.copybooks().items() if v.kind == "record"}
    sig = {p.id: set() for p in programs}
    for u in kb.store_uses():
        if u.store_kind != "private" and u.program in sig:
            sig[u.program].add(("store", u.store, u.mode))
    for p in programs:
        sig[p.id] |= {("record", c) for c in p.copybooks if c in records and idf(n, users[c]) > 0}

    def cos(a, b):
        dot = sum(v * b.get(k, 0.0) for k, v in a.items())
        na, nb = math.sqrt(sum(v * v for v in a.values())), math.sqrt(sum(v * v for v in b.values()))
        return dot / (na * nb) if na and nb else 0.0

    out = {}
    for a, b in combinations(sorted(sig), 2):
        jac = len(sig[a] & sig[b]) / len(sig[a] | sig[b]) if sig[a] | sig[b] else 0.0
        s = 0.5 * cos(vec.get(a, {}), vec.get(b, {})) + 0.5 * jac
        if s >= cfg.similarity_threshold and s > 0:
            out[(a, b)] = s
    return out


class ScaleTests(unittest.TestCase):
    def assert_same(self, fast, slow):
        self.assertEqual(set(fast), set(slow))
        for k in slow:
            self.assertAlmostEqual(fast[k], slow[k], places=9)

    def test_similarity_matches_definition(self):
        kb = FixtureKb(FIXTURE)
        for threshold in (0.0, 0.35):
            cfg = PlannerConfig(similarity_threshold=threshold)
            self.assert_same(similarity(kb, cfg), brute_force_similarity(kb, cfg))
        small = estate_kb(120, idents=40)
        self.assert_same(similarity(small, PlannerConfig()), brute_force_similarity(small, PlannerConfig()))

    def test_similarity_scales(self):
        kb = estate_kb(600)
        t = time.monotonic()
        similarity(kb, PlannerConfig())
        self.assertLess(time.monotonic() - t, 3.0)  # pair-by-pair Python took ~12 s here

    def test_draft_scales(self):
        from planner.architecture.draft import make_draft
        kb = estate_kb(2000)
        t = time.monotonic()
        plan, _ = make_draft(kb, PlannerConfig())
        self.assertLess(time.monotonic() - t, 20.0)  # ~11 s now; the old size-band merge loop took ~33 s
        self.assertEqual(len(plan.program_ids()), 2000)

    def test_phase0kb_scales(self):
        w = phase0_workspace(1000)
        t = time.monotonic()
        kb = Phase0Kb(w)
        self.assertLess(time.monotonic() - t, 1.5)  # per-program rescans took ~4.5 s here
        self.assertEqual(len(kb.programs()), 1000)
        self.assertEqual(len(kb.programs()[0].identifiers), 70)
        self.assertEqual(len(kb.store_uses()), len(set(kb.store_uses())))


if __name__ == "__main__":
    unittest.main()
