"""Program graph and similarity signal.  python3 -m unittest tests.planner.test_graph -v"""
import json
import math
import tempfile
import unittest
from pathlib import Path

from planner.architecture.config import PlannerConfig, Weights
from planner.architecture.features import add_similarity, comment_lines, program_tokens, similarity
from planner.architecture.graph import build_graph
from planner.kb import FixtureKb, Program

FIXTURE = Path(__file__).parent / "fixtures" / "estate.json"


def evidence(g, a, b, kind):
    return [e for e in g.edges[a, b]["evidence"] if e.kind == kind] if g.has_edge(a, b) else []


def fixture_variant(edit):
    """A copy of the estate fixture with `edit(doc)` applied; source_root stays the original."""
    doc = json.loads(FIXTURE.read_text())
    doc["source_root"] = str((FIXTURE.parent / "estate_src").resolve())
    edit(doc)
    d = tempfile.mkdtemp()
    path = Path(d) / "estate.json"
    path.write_text(json.dumps(doc))
    return FixtureKb(path)


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.kb = FixtureKb(FIXTURE)
        self.cfg = PlannerConfig()
        self.g = build_graph(self.kb, self.cfg)

    def test_one_node_per_program(self):
        self.assertEqual(sorted(self.g.nodes), sorted(p.id for p in self.kb.programs()))

    def test_call_edge_weight(self):
        ev = evidence(self.g, "ACCTUPDT", "DATEFMT", "call")
        self.assertEqual([(e.item, e.weight) for e in ev], [("DATEFMT", 3.0)])

    def test_ubiquitous_copybook_adds_nothing(self):
        self.assertFalse([e for _, _, d in self.g.edges(data=True) for e in d["evidence"] if e.item == "COMMHDR"])
        self.assertEqual(self.g.degree("ORPHAN"), 0)

    def test_write_read_idf(self):
        ev = evidence(self.g, "TRANVAL", "TRANPOST", "write_read")
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0].item, "TRAN.VALID")
        self.assertAlmostEqual(ev[0].weight, 2.0 * math.log(13 / 2))

    def test_copybook_and_co_read_and_job(self):
        self.assertAlmostEqual(evidence(self.g, "ACCTVIEW", "ACCTBAT", "copybook")[0].weight, 2.0 * math.log(13 / 4))
        self.assertEqual(evidence(self.g, "ACCTVIEW", "ACCTBAT", "co_read")[0].item, "ACCOUNT")
        self.assertEqual(evidence(self.g, "TRANVAL", "ACCTBAT", "same_job")[0].weight, 0.5)

    def test_edge_weight_is_sum_of_evidence(self):
        for a, b, d in self.g.edges(data=True):
            self.assertAlmostEqual(d["weight"], sum(e.weight for e in d["evidence"]))
            self.assertGreater(d["weight"], 0)

    def test_no_self_loops_or_double_count(self):
        def edit(doc):
            p = next(p for p in doc["programs"] if p["id"] == "ACCTVIEW")
            p["calls"].append("ACCTVIEW")
            p["copybooks"].append("ACCTREC")
        g = build_graph(fixture_variant(edit), self.cfg)
        self.assertFalse(g.has_edge("ACCTVIEW", "ACCTVIEW"))
        self.assertEqual(evidence(g, "ACCTVIEW", "ACCTBAT", "copybook"), evidence(self.g, "ACCTVIEW", "ACCTBAT", "copybook"))

    def test_private_stores_add_no_edges(self):
        def edit(doc):
            doc["store_uses"] += [{"program": "ORPHAN", "store": "ORPHAN:INFILE", "store_kind": "private", "mode": "write"},
                                  {"program": "ACCTBAT", "store": "ORPHAN:INFILE", "store_kind": "private", "mode": "read"}]
        self.assertEqual(build_graph(fixture_variant(edit), self.cfg).degree("ORPHAN"), 0)

    def test_weights_configurable(self):
        g = build_graph(self.kb, PlannerConfig(weights=Weights(call=10.0)))
        self.assertEqual(evidence(g, "ACCTUPDT", "DATEFMT", "call")[0].weight, 10.0)


class SimilarityTests(unittest.TestCase):
    def setUp(self):
        self.kb = FixtureKb(FIXTURE)
        self.cfg = PlannerConfig()

    def test_similarity_groups_vocabulary(self):
        sims = similarity(self.kb, PlannerConfig(similarity_threshold=0.0))
        key = lambda a, b: tuple(sorted((a, b)))  # noqa: E731
        self.assertGreater(sims.get(key("ACCTVIEW", "ACCTUPDT"), 0), sims.get(key("ACCTVIEW", "ORPHAN"), 0))
        above = similarity(self.kb, self.cfg)
        self.assertFalse([p for p in above if "ORPHAN" in p])
        self.assertIn(key("ACCTVIEW", "ACCTUPDT"), above)
        self.assertTrue(all(v >= self.cfg.similarity_threshold for v in above.values()))

    def test_add_similarity_extends_edges(self):
        g = build_graph(self.kb, self.cfg)
        before = g.edges["ACCTVIEW", "ACCTUPDT"]["weight"]
        add_similarity(g, {("ACCTUPDT", "ACCTVIEW"): 0.5}, self.cfg)
        self.assertAlmostEqual(g.edges["ACCTVIEW", "ACCTUPDT"]["weight"], before + 0.5)
        self.assertEqual(evidence(g, "ACCTVIEW", "ACCTUPDT", "similar")[0].weight, 0.5)

    def test_program_tokens(self):
        p = Program("X", "X.cbl", 1, "batch", 1.0, identifiers=("WS-ACCT-BAL", "LK_DATE", "FILLER", "WS-01", "AB"))
        self.assertEqual(program_tokens(p, ["account balance AND the 2024 total"]),
                         ["ACCT", "BAL", "DATE", "ACCOUNT", "BALANCE", "TOTAL"])

    def test_comment_lines_fixed_and_free(self):
        with tempfile.TemporaryDirectory() as d:
            fixed = Path(d) / "F.cbl"
            fixed.write_text("       IDENTIFICATION DIVISION.\n      * ACCOUNT UPDATE\n      / PAGE BREAK\n"
                             "           MOVE A TO B.\n")
            free = Path(d) / "G.cbl"
            free.write_text("IDENTIFICATION DIVISION.\n*> free comment\nMOVE A TO B. *> trailing note\n")
            self.assertEqual(comment_lines(fixed), ["ACCOUNT UPDATE", "PAGE BREAK"])
            self.assertEqual(comment_lines(free), ["free comment", "trailing note"])
            self.assertEqual(comment_lines(Path(d) / "missing.cbl"), [])

    def test_config_from_dict(self):
        cfg = PlannerConfig.from_dict({"weights": {"call": 5}, "band_max": 10, "review": {"pass_steps": 3}})
        self.assertEqual((cfg.weights.call, cfg.weights.copybook, cfg.band_max, cfg.review.pass_steps), (5, 2.0, 10, 3))
        with self.assertRaises(ValueError):
            PlannerConfig.from_dict({"nope": 1})
        with self.assertRaises(ValueError):
            PlannerConfig.from_dict({"weights": {"nope": 1}})


if __name__ == "__main__":
    unittest.main()
