"""Plan model, roles, confidence and the deterministic draft.  python3 -m unittest tests.planner.test_draft -v"""
import json
import unittest
from pathlib import Path

from planner.architecture.config import PlannerConfig
from planner.architecture.draft import make_draft
from planner.architecture.plan import ArchitecturePlan
from planner.kb import FixtureKb
from tests.planner.test_graph import fixture_variant

FIXTURE = Path(__file__).parent / "fixtures" / "estate.json"


class DraftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kb = FixtureKb(FIXTURE)
        cls.plan, cls.g = make_draft(cls.kb, PlannerConfig())

    def mod(self, program):
        return self.plan.module_of(program)

    def questions(self, kind):
        return [q for q in self.plan.open_questions if q.kind == kind]

    def test_draft_modules_and_utilities(self):
        kinds = sorted(m.kind for m in self.plan.modules)
        self.assertEqual(kinds, ["domain", "domain", "domain", "isolated", "utility"])
        self.assertEqual(sorted(self.plan.program_ids()), sorted(p.id for p in self.kb.programs()))
        self.assertEqual(len(self.plan.program_ids()), len(set(self.plan.program_ids())))
        self.assertEqual(self.mod("DATEFMT").kind, "utility")
        self.assertIs(self.mod("DATEFMT"), self.mod("ERRHNDL"))
        self.assertEqual(self.mod("ORPHAN").kind, "isolated")
        self.assertEqual([m.id for m in self.plan.modules], [f"m{i:02}" for i in range(1, 6)])
        names = [m.name for m in self.plan.modules]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(self.mod("DATEFMT").name, "util")
        self.assertTrue(all(m.purpose == "" for m in self.plan.modules))

    def test_shared_types_and_local_types(self):
        tran = self.mod("TRANVAL")
        self.assertIn("TRANREC", tran.local_types)
        shared = {t.copybook: t for t in self.plan.shared_types}
        self.assertNotIn("COMMHDR", shared)
        self.assertFalse(any("COMMHDR" in m.local_types for m in self.plan.modules))
        card_shared = self.mod("CUSTSRCH") is not self.mod("CARDLIST")
        self.assertEqual("CARDREC" in shared, card_shared)
        self.assertIn("ACCTREC", shared)  # CUSTSRCH uses it too and does not sit with the account programs
        self.assertEqual(shared["ACCTREC"].type_name, "Acctrec")
        self.assertEqual(len(shared["ACCTREC"].used_by), 2)

    def test_shared_code_placement(self):
        code = {c.copybook: c for c in self.plan.shared_code}
        self.assertEqual(code["DATECHK"].module, self.mod("TRANVAL").id)
        self.assertEqual(code["ABENDRTN"].module, self.mod("DATEFMT").id)
        self.assertEqual(sorted(code["ABENDRTN"].used_by), ["ACCTBAT", "CARDACT"])

    def test_store_owner_and_shared_write(self):
        stores = {s.id: s for s in self.plan.stores}
        acct = stores["ACCOUNT"]
        self.assertEqual(acct.owner, self.mod("ACCTUPDT").id)
        self.assertTrue(acct.shared_write)
        self.assertEqual(sorted(acct.writers), ["ACCTUPDT", "TRANPOST"])
        self.assertEqual(acct.interface, "AccountRepository")
        self.assertEqual(stores["TRAN.VALID"].interface, "TranValidRepository")
        self.assertFalse(stores["CARD"].shared_write)
        self.assertIn("ACCOUNT", self.mod("ACCTVIEW").owned_stores)
        self.assertTrue(any(q.subject == "ACCOUNT" for q in self.questions("shared_write")))

    def test_depends_on(self):
        self.assertIn(self.mod("DATEFMT").id, self.mod("ACCTUPDT").depends_on)   # calls a utility
        if self.mod("CUSTSRCH") is not self.mod("ACCTVIEW"):  # reads ACCOUNT, owned by the account module
            self.assertIn(self.mod("ACCTVIEW").id, self.mod("CUSTSRCH").depends_on)
        for m in self.plan.modules:
            self.assertNotIn(m.id, m.depends_on)

    def test_custsrch_uncertain(self):
        a = next(a for m in self.plan.modules for a in m.programs if a.program == "CUSTSRCH")
        self.assertLess(a.confidence, 0.6)
        self.assertTrue(any(q.subject == "CUSTSRCH" for q in self.questions("uncertain_program")))
        strong = next(a for m in self.plan.modules for a in m.programs if a.program == "TRANVAL")
        self.assertGreaterEqual(strong.confidence, 0.6)
        self.assertTrue(strong.evidence and len(strong.evidence) <= 3)
        self.assertTrue(all(e.other for e in strong.evidence))
        self.assertTrue(any(q.subject == "ORPHAN" for q in self.questions("isolated")))
        self.assertFalse(any(q.subject in ("DATEFMT", "ERRHNDL") for q in self.questions("uncertain_program")))

    def test_utility_calls_do_not_lower_confidence(self):
        util = {a.program for a in self.mod("DATEFMT").programs}
        members = {a.program for a in self.mod("ACCTUPDT").programs}
        edges = [(o, d["weight"]) for _, o, d in self.g.edges("ACCTUPDT", data=True) if o not in util]
        expected = sum(w for o, w in edges if o in members) / sum(w for _, w in edges)
        got = next(a.confidence for a in self.mod("ACCTUPDT").programs if a.program == "ACCTUPDT")
        self.assertAlmostEqual(got, expected, places=3)
        util_id = self.mod("DATEFMT").id
        self.assertFalse(any(util_id in q.detail for q in self.questions("uncertain_program")))

    def test_job_steps_mapped_to_modules(self):
        (job,) = self.plan.jobs
        self.assertEqual(job.id, "NIGHTLY")
        self.assertEqual([(s["order"], s["program"], s["module"]) for s in job.steps],
                         [(1, "TRANVAL", self.mod("TRANVAL").id), (2, "TRANPOST", self.mod("TRANPOST").id),
                          (3, "TRANRPT", self.mod("TRANRPT").id), (4, "ACCTBAT", self.mod("ACCTBAT").id)])

    def test_inputs_recorded(self):
        self.assertEqual(self.plan.inputs["kb_version"], "fixture-estate-1")
        self.assertEqual(self.plan.inputs["seed"], 7)
        self.assertEqual(self.plan.schema_version, "1.0")

    def test_roundtrip_json(self):
        d = json.loads(json.dumps(self.plan.to_dict()))
        self.assertEqual(ArchitecturePlan.from_dict(d), self.plan)

    def test_deterministic(self):
        self.assertEqual(make_draft(self.kb, PlannerConfig())[0], self.plan)

    def test_tiny_estates(self):
        def keep(ids):
            def edit(doc):
                doc["programs"] = [p for p in doc["programs"] if p["id"] in ids]
                doc["store_uses"] = [u for u in doc["store_uses"] if u["program"] in ids]
                doc["job_steps"] = [s for s in doc["job_steps"] if s["program"] in ids]
            return edit
        for ids in ([], ["ORPHAN"], ["ACCTVIEW", "ACCTUPDT"]):
            plan, _ = make_draft(fixture_variant(keep(ids)), PlannerConfig())
            self.assertEqual(sorted(plan.program_ids()), sorted(ids))
            self.assertEqual(sum(len(m.programs) for m in plan.modules), len(ids))
        plan, _ = make_draft(fixture_variant(keep(["ORPHAN"])), PlannerConfig())
        self.assertTrue(any(q.kind == "missing_kb_fact" for q in plan.open_questions))  # no store uses at all


if __name__ == "__main__":
    unittest.main()
