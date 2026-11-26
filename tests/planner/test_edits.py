"""Plan validator and evidence-checked edits.  python3 -m unittest tests.planner.test_edits -v"""
import copy
import unittest
from pathlib import Path

from planner.architecture.config import PlannerConfig
from planner.architecture.draft import make_draft
from planner.architecture.edits import PlanEditor
from planner.architecture.validate import evidence_exists, validate_plan
from planner.kb import FixtureKb

FIXTURE = Path(__file__).parent / "fixtures" / "estate.json"


class EditTests(unittest.TestCase):
    def setUp(self):
        self.kb = FixtureKb(FIXTURE)
        plan, g = make_draft(self.kb, PlannerConfig())
        self.ed = PlanEditor(plan, self.kb, g, PlannerConfig())

    def mid(self, program):
        return self.ed.plan.module_of(program).id

    def test_draft_is_valid(self):
        self.assertEqual(validate_plan(self.ed.plan, self.kb), [])

    def test_move_with_evidence(self):
        acct = self.mid("ACCTVIEW")
        out = self.ed.move_program("CUSTSRCH", acct, reason="customer search reads accounts first",
                                   evidence=["store:ACCOUNT", "program:ACCTVIEW", "copybook:ACCTREC"])
        self.assertTrue(out.startswith("ok"), out)
        a = next(a for a in self.ed.plan.module(acct).programs if a.program == "CUSTSRCH")
        self.assertEqual(a.decided_by, "agent")
        self.assertEqual(len(self.ed.plan.edits), 1)
        self.assertEqual(self.ed.plan.edits[0].action, "move_program")
        self.assertNotIn("ACCTREC", [t.copybook for t in self.ed.plan.shared_types])  # roles recomputed
        self.assertFalse(any(q.kind == "uncertain_program" and q.subject == "CUSTSRCH" for q in self.ed.plan.open_questions))
        self.assertEqual(validate_plan(self.ed.plan, self.kb), [])

    def test_missing_evidence_rejected(self):
        before = copy.deepcopy(self.ed.plan)
        out = self.ed.move_program("CUSTSRCH", self.mid("ACCTVIEW"), reason="r", evidence=["store:NOPE"])
        self.assertTrue(out.startswith("ERROR"))
        self.assertIn("store:NOPE", out)
        self.assertEqual(self.ed.plan, before)

    def test_empty_reason_or_evidence_rejected(self):
        self.assertTrue(self.ed.rename_module(self.mid("TRANVAL"), "postings", reason=" ", evidence=["program:TRANVAL"])
                        .startswith("ERROR"))
        self.assertTrue(self.ed.rename_module(self.mid("TRANVAL"), "postings", reason="r", evidence=[]).startswith("ERROR"))

    def test_moving_last_program_removes_module(self):
        orphan = self.mid("ORPHAN")
        out = self.ed.move_program("ORPHAN", self.mid("TRANVAL"), reason="batch housekeeping", evidence=["job:NIGHTLY"])
        self.assertTrue(out.startswith("ok"), out)
        self.assertNotIn(orphan, [m.id for m in self.ed.plan.modules])

    def test_merge_and_split_keep_invariants(self):
        card, acct = self.mid("CARDLIST"), self.mid("ACCTVIEW")
        self.assertTrue(self.ed.merge_modules(card, acct, reason="one customer domain",
                                              evidence=["program:CUSTSRCH"]).startswith("ok"))
        self.assertEqual(self.mid("ACCTVIEW"), card)
        self.assertEqual(validate_plan(self.ed.plan, self.kb), [])
        out = self.ed.split_module(card, ["ACCTVIEW", "ACCTUPDT", "ACCTBAT"], "accounts", reason="account lifecycle",
                                   evidence=["store:ACCOUNT"])
        self.assertTrue(out.startswith("ok"), out)
        new = self.ed.plan.module_of("ACCTVIEW")
        self.assertNotEqual(new.id, card)
        self.assertEqual(new.name, "accounts")
        self.assertNotIn(new.id, [m.id for m in self.ed.plan.modules if m.id != new.id])
        self.assertEqual(validate_plan(self.ed.plan, self.kb), [])
        self.assertTrue(self.ed.split_module(card, ["NOPE"], "x", reason="r", evidence=["program:CARDLIST"])
                        .startswith("ERROR"))
        whole = [a.program for a in self.ed.plan.module(card).programs]
        self.assertTrue(self.ed.split_module(card, whole, "x", reason="r", evidence=["program:CARDLIST"])
                        .startswith("ERROR"))  # a split must leave something behind

    def test_rename_unique(self):
        self.assertTrue(self.ed.rename_module(self.mid("TRANVAL"), "card", reason="r", evidence=["program:TRANVAL"])
                        .startswith("ERROR"))
        self.assertTrue(self.ed.rename_module(self.mid("TRANVAL"), "transactions", reason="r",
                                              evidence=["program:TRANVAL"]).startswith("ok"))
        self.assertEqual(self.ed.plan.module_of("TRANVAL").name, "transactions")

    def test_set_purpose(self):
        self.assertTrue(self.ed.set_module_purpose(self.mid("TRANVAL"), "Validate, post and report transactions",
                                                   reason="r", evidence=["job:NIGHTLY"]).startswith("ok"))
        self.assertIn("post", self.ed.plan.module_of("TRANPOST").purpose)

    def test_set_owner_survives_recompute(self):
        tran = self.mid("TRANPOST")
        self.assertTrue(self.ed.set_owner("ACCOUNT", tran, reason="posting is the system of record",
                                          evidence=["store:ACCOUNT", "program:TRANPOST"]).startswith("ok"))
        self.ed.rename_module(tran, "tx", reason="r", evidence=["program:TRANPOST"])  # any later edit recomputes roles
        acct = next(s for s in self.ed.plan.stores if s.id == "ACCOUNT")
        self.assertEqual(acct.owner, tran)
        self.assertIn("ACCOUNT", self.ed.plan.module(tran).owned_stores)
        self.assertNotIn("ACCOUNT", self.ed.plan.module_of("ACCTVIEW").owned_stores)

    def test_set_owner_unknown_module_rejected(self):
        self.assertTrue(self.ed.set_owner("ACCOUNT", "m99", reason="r", evidence=["store:ACCOUNT"]).startswith("ERROR"))
        self.assertTrue(self.ed.set_owner("NOPE", self.mid("ACCTVIEW"), reason="r", evidence=["program:ACCTVIEW"])
                        .startswith("ERROR"))

    def test_mark_utility(self):
        out = self.ed.mark_utility("CUSTSRCH", reason="search used everywhere", evidence=["program:CUSTSRCH"])
        self.assertTrue(out.startswith("ok"), out)
        self.assertEqual(self.ed.plan.module_of("CUSTSRCH").kind, "utility")

    def test_src_ref_line_checked(self):
        self.assertTrue(evidence_exists("src:ACCTVIEW.cbl:3", self.kb))
        self.assertFalse(evidence_exists("src:ACCTVIEW.cbl:999", self.kb))
        self.assertFalse(evidence_exists("src:ACCTVIEW.cbl:0", self.kb))
        self.assertFalse(evidence_exists("src:../estate.json:1", self.kb))  # outside the source tree
        self.assertFalse(evidence_exists("src:NOPE.cbl:1", self.kb))
        self.assertTrue(evidence_exists("job:NIGHTLY", self.kb))
        self.assertTrue(evidence_exists("copybook:ABENDRTN", self.kb))
        self.assertFalse(evidence_exists("module:m01", self.kb))

    def test_validator_catches_broken_plans(self):
        plan = copy.deepcopy(self.ed.plan)
        plan.modules[0].programs.append(copy.deepcopy(plan.modules[1].programs[0]))
        plan.stores[0].owner = "m99"
        errors = validate_plan(plan, self.kb)
        self.assertTrue(any("more than one module" in e for e in errors))
        self.assertTrue(any("m99" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
