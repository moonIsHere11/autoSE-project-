"""Planner tools and the agent review (scripted LLM, no network).  python3 -m unittest tests.planner.test_review -v"""
import json
import unittest
from pathlib import Path

from harness.llm import LLMError
from harness.registry import ToolRegistry
from planner.architecture.config import PlannerConfig
from planner.architecture.draft import make_draft
from planner.architecture.edits import PlanEditor
from planner.architecture.review import review
from planner.architecture.tools import register_code_tools, register_edit_tools, register_kb_tools
from planner.kb import FixtureKb
from tests.harness.helpers import call

FIXTURE = Path(__file__).parent / "fixtures" / "estate.json"
EDIT_TOOLS = {"move_program", "merge_modules", "split_module", "rename_module", "set_module_purpose",
              "mark_utility", "set_owner"}


class RoutedLLM:
    """Serves a separate script per agent run, chosen by the run's first user message (routes are substrings).
    When a route's script is used up it finishes with a default result for that kind of run."""
    model = "routed"

    def __init__(self, routes):
        self.routes = {k: list(v) for k, v in routes.items()}
        self.offered, self.results, self.tasks = {}, {}, []

    def route(self, msgs):
        task = msgs[1]["content"]
        for key in self.routes:
            if key in task:
                return key
        if task.startswith("Explore program"):
            return "explore-default"
        if task.startswith("Global review"):
            return "global-default"
        return "module-default"

    def chat(self, msgs, tools):
        key = self.route(msgs)
        if msgs[1]["content"] not in self.tasks:
            self.tasks.append(msgs[1]["content"])
        self.offered.setdefault(key, [t["function"]["name"] for t in tools])
        if msgs[-1]["role"] == "tool":
            self.results.setdefault(key, []).append(msgs[-1]["content"])
        script = self.routes.get(key)
        if script:
            step = script.pop(0)
            if isinstance(step, Exception):
                raise step
            return step, {"prompt_tokens": 1, "completion_tokens": 1}
        if key.startswith("explore") or (key in self.routes and key.startswith("Explore")):
            return call("finish", {"answer": "n/a", "evidence": ["program:ORPHAN"]}, 99), {}
        if "Global" in msgs[1]["content"]:
            return call("finish", {"summary": "ok"}, 98), {}
        mid = msgs[1]["content"].split()[2]
        return call("finish", {"name": f"auto-{mid}", "purpose": "auto", "evidence": ["program:ORPHAN"]}, 97), {}


class FailingLLM:
    model = "down"

    def chat(self, msgs, tools):
        raise LLMError("service unavailable")


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.kb = FixtureKb(FIXTURE)
        self.cfg = PlannerConfig()
        self.plan, self.g = make_draft(self.kb, self.cfg)
        self.card = self.plan.module_of("CARDLIST").id
        self.acct = self.plan.module_of("ACCTVIEW").id

    def run_review(self, routes):
        self.llm = RoutedLLM(routes)
        return review(self.plan, self.g, self.kb, self.llm, self.cfg, log=lambda *a: None)

    def test_module_pass_moves_uncertain_program(self):
        out = self.run_review({
            f"Review module {self.card}": [
                call("explore_program", {"program_id": "CUSTSRCH", "question": "accounts or cards first?"}, 1),
                call("move_program", {"program": "CUSTSRCH", "to_module": self.acct, "reason": "account lookup first",
                                      "evidence": ["store:ACCOUNT", "program:ACCTVIEW"]}, 2),
                call("finish", {"name": "cards", "purpose": "Card lifecycle", "evidence": ["program:CARDLIST"]}, 3)],
            "Explore program CUSTSRCH": [
                call("finish", {"answer": "searches accounts, then cards", "evidence": ["src:CUSTSRCH.cbl:4"]}, 4)]})
        self.assertEqual(out.module_of("CUSTSRCH").id, self.acct)
        self.assertEqual((out.module(self.card).name, out.module(self.card).purpose), ("cards", "Card lifecycle"))
        self.assertIn("move_program", [e.action for e in out.edits])
        self.assertIn("searches accounts", self.llm.results[f"Review module {self.card}"][0])  # explorer answer came back
        self.assertFalse([q for q in out.open_questions if q.kind == "review_incomplete"])
        self.assertFalse([q for q in out.open_questions if q.kind == "uncertain_program" and q.subject == "CUSTSRCH"])

    def test_invalid_evidence_edit_does_not_apply(self):
        out = self.run_review({f"Review module {self.card}": [
            call("move_program", {"program": "CUSTSRCH", "to_module": self.acct, "reason": "r",
                                  "evidence": ["store:NOPE"]}, 1)]})
        self.assertEqual(out.module_of("CUSTSRCH").id, self.card)
        self.assertIn("store:NOPE", self.llm.results[f"Review module {self.card}"][0])
        self.assertNotIn("move_program", [e.action for e in out.edits])

    def test_llm_error_keeps_draft_and_flags(self):
        out = review(self.plan, self.g, self.kb, FailingLLM(), self.cfg, log=lambda *a: None)
        self.assertEqual({m.id: [a.program for a in m.programs] for m in out.modules},
                         {m.id: [a.program for a in m.programs] for m in self.plan.modules})
        incomplete = [q for q in out.open_questions if q.kind == "review_incomplete"]
        self.assertIn("global", [q.subject for q in incomplete])
        self.assertIn(self.card, [q.subject for q in incomplete])
        self.assertTrue(all("llm_error" in q.detail for q in incomplete))
        self.assertTrue([q for q in out.open_questions if q.kind == "uncertain_program"])  # still visible to the reviewer

    def test_review_does_not_mutate_input(self):
        import copy
        before = copy.deepcopy(self.plan)
        review(self.plan, self.g, self.kb, FailingLLM(), self.cfg, log=lambda *a: None)
        self.assertEqual(self.plan, before)

    def test_explorer_limit_enforced(self):
        explore = [call("explore_program", {"program_id": "CUSTSRCH", "question": f"q{i}"}, i) for i in range(6)]
        self.run_review({f"Review module {self.card}": explore})
        results = self.llm.results[f"Review module {self.card}"]
        self.assertIn("call limit 5", results[5])
        self.assertNotIn("call limit", results[4])

    def test_tools_are_read_only_for_explorer(self):
        self.run_review({f"Review module {self.card}": [
            call("explore_program", {"program_id": "CUSTSRCH", "question": "q"}, 1)]})
        explorer = set(self.llm.offered["explore-default"])
        self.assertFalse(explorer & (EDIT_TOOLS | {"explore_program"}))
        self.assertTrue({"program_facts", "search_code", "finish"} <= explorer)
        module_tools = set(self.llm.offered[f"Review module {self.card}"])
        self.assertTrue((EDIT_TOOLS | {"explore_program", "module_overview"}) <= module_tools)

    def test_only_modules_with_questions_get_a_pass(self):
        self.run_review({})
        passes = sorted(t.split()[2] for t in self.llm.tasks if t.startswith("Review module"))
        flagged = sorted({self.plan.module_of(q.subject).id for q in self.plan.open_questions
                          if q.kind in ("uncertain_program", "low_kb_confidence")})
        self.assertEqual(passes, flagged)
        self.assertNotIn(self.plan.module_of("TRANRPT").id, passes)
        self.assertTrue(self.llm.tasks[-1].startswith("Global review"))


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.kb = FixtureKb(FIXTURE)
        plan, g = make_draft(self.kb, PlannerConfig())
        self.ed = PlanEditor(plan, self.kb, g, PlannerConfig())
        self.reg = ToolRegistry(max_out=100000)
        register_kb_tools(self.reg, self.kb, self.ed)
        register_code_tools(self.reg, self.kb)
        register_edit_tools(self.reg, self.ed)

    def test_tool_tags(self):
        tags = {t.name: t.tags for t in self.reg.tools()}
        self.assertEqual(tags["program_facts"], frozenset({"read"}))
        self.assertEqual(tags["search_code"], frozenset({"read"}))
        self.assertTrue(all(tags[n] == frozenset({"plan_edit"}) for n in EDIT_TOOLS))

    def test_kb_tools_read_current_plan(self):
        before = json.loads(self.reg.call("module_overview", {}))
        self.reg.call("rename_module", {"module": before[0]["id"], "name": "renamed", "reason": "r",
                                        "evidence": ["program:CARDLIST"]})
        after = json.loads(self.reg.call("module_overview", {}))
        self.assertEqual(after[0]["name"], "renamed")

    def test_program_facts_edges_and_who_uses(self):
        facts = json.loads(self.reg.call("program_facts", {"program_id": "TRANPOST"}))
        self.assertIn("ACCOUNT", json.dumps(facts["stores"]))
        self.assertEqual(facts["module"], self.ed.plan.module_of("TRANPOST").id)
        edges = json.loads(self.reg.call("program_edges", {"program_id": "TRANPOST"}))
        self.assertIn("TRANVAL", [e["program"] for e in edges])
        uses = json.loads(self.reg.call("who_uses", {"item": "ACCOUNT"}))
        self.assertIn("TRANPOST", uses["writers"])
        self.assertIn("ERROR", self.reg.call("program_facts", {"program_id": "NOPE"}))

    def test_code_tools(self):
        out = self.reg.call("search_code", {"pattern": "PROGRAM-ID\\. CUSTSRCH"})
        self.assertIn("CUSTSRCH.cbl:2:", out)
        self.assertNotIn("CUSTOMER SEARCH", self.reg.call("search_code", {"pattern": "CUSTOMER"}))  # comments skipped
        self.assertIn("ERROR", self.reg.call("search_code", {"pattern": "("}))
        self.assertIn("2|", self.reg.call("read_lines", {"path": "CUSTSRCH.cbl", "start": 1, "end": 3}))
        self.assertIn("ERROR", self.reg.call("read_lines", {"path": "../estate.json", "start": 1, "end": 3}))


if __name__ == "__main__":
    unittest.main()
