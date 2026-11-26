"""Phase0Kb: reading Phase 0's kb/ files into the planner's KB contract.  python3 -m unittest tests.planner.test_kb_phase0 -v"""
import unittest
from pathlib import Path

from planner.kb import Copybook, StoreUse
from planner.kb_phase0 import Phase0Kb

WS = Path(__file__).parent / "fixtures" / "phase0_ws"


class Phase0KbTests(unittest.TestCase):
    def setUp(self):
        self.kb = Phase0Kb(WS)
        self.progs = {p.id: p for p in self.kb.programs()}
        self.uses = set(self.kb.store_uses())

    def test_programs_calls_and_identifiers(self):
        self.assertEqual(set(self.progs), {"TRANLOAD", "ACCTONL", "DATEUTL"})
        self.assertEqual(self.progs["TRANLOAD"].calls, ("DATEUTL",))  # dynamic ?WS-PGM dropped
        self.assertIn("LOAD-TRAN", self.progs["TRANLOAD"].identifiers)   # paragraph from a qualified unit id
        self.assertIn("TRAN-AMT", self.progs["TRANLOAD"].identifiers)    # data item
        self.assertEqual(self.progs["TRANLOAD"].file, "TRANLOAD.cbl")

    def test_assign_resolves_through_jcl_step(self):
        self.assertIn(StoreUse("TRANLOAD", "NIGHTLY:&&SORTED", "dataset", "read"), self.uses)

    def test_unresolved_assign_is_private(self):
        self.assertIn(StoreUse("TRANLOAD", "TRANLOAD:LOGFILE", "private", "write"), self.uses)

    def test_gdg_generation_stripped(self):
        self.assertIn(StoreUse("TRANLOAD", "PROD.TRAN.RPT", "dataset", "write"), self.uses)
        self.assertFalse(any("(+1)" in u.store for u in self.uses))

    def test_uses_deduplicated(self):
        uses = self.kb.store_uses()
        self.assertEqual(len(uses), len(set(uses)))

    def test_job_steps(self):
        steps = self.kb.job_steps()
        self.assertEqual([(s.step, s.order, s.program) for s in steps],
                         [("STEP010", 1, "SORT"), ("STEP020", 2, "TRANLOAD"), ("STEP030", 3, None)])
        self.assertEqual(steps[0].reads, ("PROD.TRAN.DAILY",))
        self.assertEqual(steps[0].writes, ("NIGHTLY:&&SORTED",))

    def test_tso_batch_step_has_no_program(self):
        self.assertIsNone(self.kb.job_steps()[2].program)

    def test_tolerant_confidence_and_kind(self):
        self.assertEqual(self.progs["ACCTONL"].confidence, 0.6)
        self.assertEqual(self.progs["ACCTONL"].kind, "online")
        self.assertEqual(self.progs["TRANLOAD"].kind, "batch")
        self.assertEqual(self.progs["DATEUTL"].kind, "subprogram")
        self.assertEqual(self.progs["TRANLOAD"].confidence, 1.0)

    def test_code_copybook_kind(self):
        self.assertEqual(self.kb.copybooks(), {"ACCTREC": Copybook("ACCTREC", "record"),
                                               "ERRPROC": Copybook("ERRPROC", "code")})

    def test_version_root_units(self):
        self.assertEqual(self.kb.kb_version(), "phase0-fixture-1")
        self.assertEqual(self.kb.source_root(), (WS / "source").resolve())
        self.assertEqual({u["unit_id"] for u in self.kb.units("TRANLOAD")}, {"TRANLOAD.LOAD-TRAN", "TRANLOAD.WRITE-RPT"})


if __name__ == "__main__":
    unittest.main()
