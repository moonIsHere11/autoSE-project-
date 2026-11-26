"""Harness core, adapters and profile tests. Stdlib only:  python3 -m unittest discover -s tests/harness -t ."""
import json
import stat
import tempfile
import textwrap
import unittest
from pathlib import Path

from adapters.verifiers.contract import ContractVerifier
from extras.cobol_java import Profile
from harness.context import ContextManager, Scratchpad, elide, size
from harness.events import EventLog
from harness.llm import LLMError
from harness.loop import AgentLoop
from harness.registry import S, ToolRegistry, load_adapter, obj
from harness.runner import Runner
from harness.types import Candidate, Verdict
from harness.workspace import Workspace


def call(name, args, i=0):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


class ScriptedLLM:
    model = "scripted"

    def __init__(self, steps):
        self.steps, self.i, self.seen = list(steps), 0, []

    def chat(self, msgs, tools):
        self.seen.append(msgs[-1])
        step = self.steps[self.i]
        self.i += 1
        if isinstance(step, Exception):
            raise step
        return (step(msgs) if callable(step) else step), {}


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.reg = ToolRegistry(max_out=50)

        @self.reg.tool("echo", "echo", obj(["text"], text=S))
        def echo(text):
            return text

        @self.reg.tool("boom", "fails")
        def boom():
            raise RuntimeError("nope")

    def test_dispatch_filters_stray_args_and_clips(self):
        self.assertEqual(self.reg.call("echo", {"text": "hi", "junk": 1}), "hi")
        self.assertIn("truncated", self.reg.call("echo", {"text": "x" * 200}))

    def test_errors_become_text(self):
        self.assertTrue(self.reg.call("boom", {}).startswith("ERROR: RuntimeError"))
        self.assertIn("unknown tool", self.reg.call("nope", {}))
        self.assertIn("bad arguments", self.reg.call("echo", {}))

    def test_allow_list_and_duplicates(self):
        self.assertEqual([s["function"]["name"] for s in self.reg.schemas({"echo"})], ["echo"])
        with self.assertRaises(ValueError):
            self.reg.tool("echo", "again")(lambda: 1)

    def test_load_adapter(self):
        self.assertIsInstance(load_adapter("harness.registry:ToolRegistry", max_out=3), ToolRegistry)
        with self.assertRaises(ValueError):
            load_adapter("no_colon")


class ContextTests(unittest.TestCase):
    def history(self, n=20):
        m = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
        for i in range(n):
            m.append({"role": "assistant", "content": "", "tool_calls": [
                {"id": f"c{i}", "type": "function", "function": {"name": "read_file", "arguments": json.dumps({"p": "x" * 400})}}]})
            m.append({"role": "tool", "tool_call_id": f"c{i}", "content": "y" * 3000})
        return m

    def test_elides_old_keeps_recent_and_pairing(self):
        m = self.history()
        before = size(m)
        saved = elide(m, 36000, 8)
        self.assertGreater(saved, 0)
        self.assertEqual(size(m), before - saved)
        self.assertEqual(len(m[-1]["content"]), 3000)  # recent results untouched
        ids = {c["id"] for x in m for c in x.get("tool_calls", [])}
        self.assertEqual(ids, {x["tool_call_id"] for x in m if x["role"] == "tool"})
        json.loads(m[2]["tool_calls"][0]["function"]["arguments"])  # still valid JSON

    def test_under_budget_is_noop(self):
        self.assertEqual(ContextManager(budget=10**9).prepare(self.history(2)), 0)

    def test_scratchpad_persists_and_limits(self):
        with tempfile.TemporaryDirectory() as d:
            pad = Scratchpad(Path(d) / "n" / "t.md", limit=10)
            pad.append("a" * 50)
            self.assertEqual(len(pad.read()), 10)  # only the tail is pinned
            self.assertTrue(pad.read().endswith("a\n"))


class LoopTests(unittest.TestCase):
    def make(self, steps, **kw):
        d = tempfile.mkdtemp()
        reg = ToolRegistry()
        hits = []
        reg.tool("ping", "p", obj())(lambda: hits.append(1) or "pong")
        loop = AgentLoop(ScriptedLLM(steps), reg, ContextManager(), EventLog(Path(d) / "e.jsonl", "R"),
                         label="t", log=lambda *a: None, **kw)
        return loop, hits, Path(d) / "e.jsonl"

    def test_runs_tools_until_done(self):
        loop, hits, ev = self.make([call("ping", {}, 1), call("ping", {}, 2)])
        self.assertEqual(loop.run(lambda: "sys", "go", lambda: len(hits) == 2), "done")
        self.assertIn("llm_usage", ev.read_text())

    def test_recovers_from_malformed_output_then_gives_up_on_text(self):
        loop, hits, _ = self.make([LLMError("bad json", recoverable=True), call("ping", {}, 1)])
        self.assertEqual(loop.run(lambda: "s", "go", lambda: bool(hits)), "done")
        loop2, _, _ = self.make([{"role": "assistant", "content": "blah"}] * 5, max_nudges=2)
        self.assertEqual(loop2.run(lambda: "s", "go", lambda: False), "gave_up")

    def test_unrecoverable_llm_error_stops(self):
        loop, _, _ = self.make([LLMError("rate limit")])
        self.assertTrue(loop.run(lambda: "s", "go", lambda: False).startswith("llm_error"))

    def test_pinned_system_prompt_is_refreshed_each_turn(self):
        notes = ["v1"]
        seen = []
        loop, hits, _ = self.make([lambda m: (seen.append(m[0]["content"]), call("ping", {}, 1))[1],
                                   lambda m: (seen.append(m[0]["content"]), call("ping", {}, 2))[1]])
        loop.run(lambda: notes.append("v2") or notes[-1], "go", lambda: len(hits) == 2)
        self.assertEqual(seen, ["v2", "v2"])


class FakeVerifier:
    def __init__(self, verdicts):
        self.verdicts, self.cands = list(verdicts), []

    def verify(self, c: Candidate) -> Verdict:
        self.cands.append(c)
        return self.verdicts.pop(0)


COBOL = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLO.
       PROCEDURE DIVISION.
           DISPLAY "HI".
           STOP RUN.
"""


def workspace(tmp: Path) -> Workspace:
    (tmp / "source").mkdir()
    (tmp / "source" / "HELLO.cbl").write_text(COBOL)
    (tmp / "source" / "COPYB.cpy").write_text("       01 X PIC 9.\n")
    (tmp / "config.yaml").write_text(json.dumps({"target": {"language": "java", "version": "21", "build_cmd": ["true"]},
                                                 "gate": {"required_tier": "tested"}, "budgets": {"attempts_per_unit": 3}}))
    return Workspace(tmp)


class ProfileTests(unittest.TestCase):
    def test_tasks_are_programs_not_copybooks(self):
        with tempfile.TemporaryDirectory() as d:
            ws = workspace(Path(d))
            tasks = Profile().tasks(ws)
            self.assertEqual([t.id for t in tasks], ["HELLO"])
            self.assertEqual(tasks[0].scope, ["HELLO"])
            self.assertEqual(Profile().tasks(ws, ["NOPE"]), [])


class RunnerTests(unittest.TestCase):
    def run_flow(self, verdicts, steps_after_red=None):
        d = tempfile.mkdtemp()
        ws = workspace(Path(d))
        red_seen = []

        def after_submit(msgs):
            red_seen.append(msgs[-1]["content"])
            return call("write_file", {"path": "src/Hello.java", "content": "class Hello{}"}, 9)

        steps = [call("write_file", {"path": "src/Hello.java", "content": "bug"}, 1), call("build", {}, 2),
                 call("submit", {}, 3), after_submit, call("submit", {}, 4)]
        ver = FakeVerifier(verdicts)
        res = Runner(ws, ScriptedLLM(steps * 1), ver, Profile(), log=lambda *a: None).run(["HELLO"], max_steps=10)
        return ws, res, ver, red_seen

    def test_red_feedback_reaches_the_model_then_green(self):
        red = Verdict("red", "1 blocker", [{"severity": "blocker", "category": "behavior_mismatch", "message": "WS-X wrong",
                                            "counterexample": {"inputs": {"A": "1"}, "expected": {"B": "2"}, "actual": {"B": "3"}},
                                            "location": None, "kb_refs": ["G-TRUNCATE"], "reproduce": "verify repro"}])
        ws, res, ver, seen = self.run_flow([red, Verdict("green", "ok")])
        self.assertEqual(res, {"accepted": ["HELLO"], "failed": []})
        self.assertIn("verdict=RED", seen[0])
        self.assertIn("counterexample: inputs={'A': '1'}", seen[0])
        self.assertEqual([c.attempt for c in ver.cands], [1, 2])
        sub = json.loads((ws.root / "submissions" / "S-0002" / "submission.json").read_text())
        self.assertEqual(sub["scope"]["unit_ids"], ["HELLO"])
        self.assertTrue((ws.root / "submissions" / "S-0002" / "project" / "src" / "Hello.java").exists())
        kinds = [json.loads(l)["kind"] for l in (ws.run_dir / "events.jsonl").read_text().splitlines()]
        self.assertIn("submission_created", kinds)

    def test_verifier_error_is_a_free_retry(self):
        ws, res, ver, _ = self.run_flow([Verdict("error", "docker down"), Verdict("green", "ok")])
        self.assertEqual(res["accepted"], ["HELLO"])
        self.assertEqual({c.attempt for c in ver.cands}, {1})  # both checks were attempt 1


class ContractVerifierTests(unittest.TestCase):
    def test_reads_report_written_by_any_checker(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            script = d / "checker"
            script.write_text(textwrap.dedent("""\
                #!/usr/bin/env python3
                import json, sys, pathlib
                a = sys.argv; w = pathlib.Path(a[a.index("--workspace") + 1]); s = a[a.index("--submission") + 1]
                (w / "reports" / s).mkdir(parents=True)
                (w / "reports" / s / "report.json").write_text(json.dumps({"verdict": "red", "summary": "x", "findings": [{"message": "m"}], "units": []}))
                """))
            script.chmod(script.stat().st_mode | stat.S_IEXEC)
            v = ContractVerifier([str(script)]).verify(Candidate(d, "S-0001", "T", ["T"], [], 1, "tested"))
            self.assertEqual((v.status, v.summary, len(v.findings)), ("red", "x", 1))
            bad = ContractVerifier(["false"]).verify(Candidate(d, "S-0002", "T", ["T"], [], 1, "tested"))
            self.assertEqual(bad.status, "error")


if __name__ == "__main__":
    unittest.main()
