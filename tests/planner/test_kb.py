"""KB contract types and the fixture estate.  python3 -m unittest tests.planner.test_kb -v"""
import unittest
from pathlib import Path

from planner.kb import Copybook, FixtureKb, JobStep, Program, StoreUse

FIXTURE = Path(__file__).parent / "fixtures" / "estate.json"


class FixtureKbTests(unittest.TestCase):
    def setUp(self):
        self.kb = FixtureKb(FIXTURE)

    def test_fixture_loads(self):
        progs = self.kb.programs()
        self.assertEqual(len(progs), 13)
        self.assertTrue(all(isinstance(p, Program) for p in progs))
        self.assertEqual(self.kb.copybooks()["ABENDRTN"], Copybook("ABENDRTN", "code"))
        self.assertEqual(self.kb.copybooks()["ACCTREC"].kind, "record")
        steps = self.kb.job_steps()
        self.assertEqual([s.order for s in steps], [1, 2, 3, 4])
        self.assertEqual(steps[0], JobStep("NIGHTLY", "STEP010", 1, "TRANVAL", ("TRAN.DAILY",), ("TRAN.VALID",)))
        self.assertTrue(self.kb.source_root().is_dir())
        self.assertIn(StoreUse("TRANPOST", "ACCOUNT", "table", "write"), self.kb.store_uses())
        self.assertTrue(self.kb.kb_version())

    def test_every_program_has_a_source_file(self):
        for p in self.kb.programs():
            self.assertTrue((self.kb.source_root() / p.file).is_file(), p.file)

    def test_units_default_empty(self):
        self.assertEqual(self.kb.units("NOPE"), [])
        self.assertTrue(self.kb.units("ACCTVIEW"))


if __name__ == "__main__":
    unittest.main()
