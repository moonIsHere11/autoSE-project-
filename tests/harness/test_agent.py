"""The configurable Agent loop.  python3 -m unittest tests.harness.test_agent -v"""
import json
import tempfile
import unittest
from pathlib import Path

from harness.agent import Agent, AgentSpec
from harness.events import EventLog
from harness.llm import LLMError
from harness.policy import ToolPolicy
from harness.prompt import PromptBuilder
from harness.registry import S, ToolRegistry, obj
from tests.harness.helpers import ScriptedLLM, call, text

RESULT = {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}


def prompt(text_="sys"):
    p = PromptBuilder()
    p.set("role", text_)
    return p


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.hits = []
        self.reg = ToolRegistry()
        self.reg.tool("ping", "p", obj(), tags=("read",))(lambda: self.hits.append("ping") or "pong")
        self.reg.tool("write", "w", obj(["path"], path=S), tags=("write",))(
            lambda path: self.hits.append(path) or f"wrote {path}")

    def agent(self, steps, usage=None, events=None, **spec_kw):
        self.llm = ScriptedLLM(steps, usage)
        return Agent(self.llm, self.reg, AgentSpec("t", prompt(), **spec_kw), events=events)

    def test_finish_returns_validated_output(self):
        a = self.agent([call("finish", {"name": 3}, 1), call("finish", {"name": "acct"}, 2)], result_schema=RESULT)
        r = a.run("go")
        self.assertEqual((r.stop_reason, r.output, r.steps), ("finished", {"name": "acct"}, 2))
        self.assertIn("invalid result", self.llm.seen[1]["content"])
        self.assertIn("finish", self.llm.offered[0])

    def test_no_finish_tool_without_schema(self):
        a = self.agent([call("ping", {}, 1)], max_steps=1)
        self.assertEqual(a.run("go").stop_reason, "max_steps")
        self.assertNotIn("finish", self.llm.offered[0])

    def test_denied_tool_not_offered_and_refused(self):
        a = self.agent([call("write", {"path": "x"}, 1), call("ping", {}, 2)], max_steps=2,
                       policy=ToolPolicy(deny_tags={"write"}))
        r = a.run("go")
        self.assertEqual(self.llm.offered[0], ["ping"])
        self.assertIn("not available to this agent", self.llm.seen[1]["content"])
        self.assertEqual(self.hits, ["ping"])
        self.assertEqual(r.stop_reason, "max_steps")

    def test_ask_uses_approval_callback(self):
        a = self.agent([call("write", {"path": "x"}, 1)], max_steps=1, policy=ToolPolicy(ask={"write"}))
        a.run("go")
        self.assertEqual(self.hits, [])
        self.llm = ScriptedLLM([call("write", {"path": "y"}, 1)])
        b = Agent(self.llm, self.reg, AgentSpec("t", prompt(), max_steps=1, policy=ToolPolicy(ask={"write"})),
                  approve=lambda name, args: name == "write")
        b.run("go")
        self.assertEqual(self.hits, ["y"])

    def test_call_limit(self):
        a = self.agent([call("ping", {}, i) for i in range(3)], max_steps=3, policy=ToolPolicy(limits={"ping": 2}))
        r = a.run("go")
        self.assertEqual(self.hits, ["ping", "ping"])
        self.assertIn("call limit 2", r.messages[-1]["content"])

    def test_before_tool_veto_and_rewrite(self):
        a = self.agent([call("write", {"path": "a"}, 1), call("write", {"path": "secret"}, 2)], max_steps=2)
        a.on("before_tool", lambda name, args, state: {"path": "b"} if args.get("path") == "a" else None)
        a.on("before_tool", lambda name, args, state: "vetoed" if args.get("path") == "secret" else None)
        r = a.run("go")
        self.assertEqual(self.hits, ["b"])
        self.assertEqual(r.messages[-1]["content"], "vetoed")

    def test_after_tool_rewrites_output(self):
        a = self.agent([call("ping", {}, 1)], max_steps=1)
        a.on("after_tool", lambda name, args, out, state: out.upper())
        self.assertEqual(a.run("go").messages[-1]["content"], "PONG")

    def test_prompt_sections_refreshed_each_turn(self):
        seen, n = [], [0]

        def capture(msgs):
            seen.append(msgs[0]["content"])
            return call("ping", {}, len(seen))

        a = self.agent([capture, capture], max_steps=2)
        a.add_prompt_section("live", lambda: (n.__setitem__(0, n[0] + 1), f"turn {n[0]}")[1])
        a.run("go")
        self.assertEqual(seen, ["sys\n\nturn 1", "sys\n\nturn 2"])
        a.set_system_prompt("only")
        self.assertEqual(a.spec.prompt.render(), "only")

    def test_stop_condition_name_is_reason(self):
        a = self.agent([call("ping", {}, i) for i in range(5)])
        a.add_stop_condition("enough", lambda state: len(self.hits) >= 2)
        r = a.run("go", state={"k": 1})
        self.assertEqual((r.stop_reason, r.steps, r.state["k"]), ("enough", 2, 1))

    def test_max_tokens_stops_before_call(self):
        a = self.agent([call("ping", {}, i) for i in range(3)],
                       usage={"prompt_tokens": 60, "completion_tokens": 60}, max_tokens=100)
        r = a.run("go")
        self.assertEqual((r.stop_reason, self.llm.i), ("max_tokens", 1))
        self.assertEqual(r.usage, {"tokens_in": 60, "tokens_out": 60})

    def test_gave_up_and_llm_error(self):
        self.assertEqual(self.agent([text("hmm")] * 3, max_nudges=2).run("go").stop_reason, "gave_up")
        r = self.agent([LLMError("bad json", recoverable=True), LLMError("rate limit")]).run("go")
        self.assertTrue(r.stop_reason.startswith("llm_error: rate limit"))

    def test_allow_deny_tools_and_budget_setters(self):
        a = self.agent([call("ping", {}, 1)], policy=ToolPolicy(allow={"ping"}))
        self.assertEqual(a.offered_tools(), ["ping"])
        a.allow_tools("write")
        self.assertEqual(a.offered_tools(), ["ping", "write"])
        a.deny_tools("ping")
        self.assertEqual(a.offered_tools(), ["write"])
        a.set_budget(max_steps=1)
        self.assertEqual(a.spec.max_steps, 1)

    def test_events_written(self):
        with tempfile.TemporaryDirectory() as d:
            ev = EventLog(Path(d) / "e.jsonl", "R")
            self.agent([call("ping", {}, 1)], events=ev, max_steps=1).run("go")
            kinds = [json.loads(line)["kind"] for line in (Path(d) / "e.jsonl").read_text().splitlines()]
            self.assertEqual(kinds, ["llm_usage", "tool_called", "agent_stopped"])

    def test_stop_hook_sees_result(self):
        got = []
        a = self.agent([call("ping", {}, 1)], max_steps=1)
        a.on("on_stop", got.append)
        a.run("go")
        self.assertEqual(got[0].stop_reason, "max_steps")

    def test_spec_copy_is_independent(self):
        s = AgentSpec("a", prompt(), policy=ToolPolicy(allow={"x"}))
        t = s.copy(name="b")
        t.prompt.set("extra", "E")
        t.policy.allow.add("y")
        self.assertEqual((s.name, s.prompt.names(), s.policy.allow), ("a", ["role"], {"x"}))


ANSWER = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}}
ASK = obj(["question"], question=S)


class SubAgentTests(unittest.TestCase):
    def setUp(self):
        self.reg = ToolRegistry()
        self.reg.tool("ping", "p", obj(), tags=("read",))(lambda: "pong")

    def parent(self, steps, usage=None, child_spec=None, **spec_kw):
        self.llm = ScriptedLLM(steps, usage)
        parent = Agent(self.llm, self.reg, AgentSpec("planner", prompt(), result_schema=RESULT, **spec_kw))
        child = child_spec or AgentSpec("explorer", prompt("explore"), result_schema=ANSWER,
                                        policy=ToolPolicy(allow_tags={"read"}))
        tool = parent.as_tool("explore", "ask the explorer", ASK, lambda question: f"Q: {question}", spec=child)
        self.reg.replace(tool)
        return parent

    def test_subagent_tool_returns_child_output(self):
        p = self.parent([call("explore", {"question": "who writes CARD?"}, 1),
                         call("finish", {"answer": "CARDUPDT"}, 2),
                         call("finish", {"name": "card"}, 3)])
        r = p.run("plan")
        self.assertEqual(r.output, {"name": "card"})
        self.assertEqual(self.llm.seen[1]["content"], "Q: who writes CARD?")    # the child's task message
        self.assertEqual(json.loads(self.llm.seen[2]["content"]), {"answer": "CARDUPDT"})  # back in the parent
        self.assertEqual(self.llm.offered[1], ["ping", "finish"])  # child: read tools only, not `explore`
        self.assertEqual(self.reg.get("explore").tags, frozenset({"agent"}))

    def test_subagent_ignores_stray_arguments(self):
        p = self.parent([call("explore", {"question": "q", "junk": 1}, 1), call("finish", {"answer": "a"}, 2),
                         call("finish", {"name": "n"}, 3)])
        p.run("plan")
        self.assertEqual(self.llm.seen[1]["content"], "Q: q")

    def test_subagent_usage_rolls_up(self):
        p = self.parent([call("explore", {"question": "q"}, 1), call("finish", {"answer": "a"}, 2),
                         call("finish", {"name": "n"}, 3)], usage={"prompt_tokens": 10, "completion_tokens": 5})
        self.assertEqual(p.run("plan").usage, {"tokens_in": 30, "tokens_out": 15})

    def test_subagent_usage_counts_against_parent_budget(self):
        p = self.parent([call("explore", {"question": "q"}, 1), call("finish", {"answer": "a"}, 2),
                         call("finish", {"name": "n"}, 3)], usage={"prompt_tokens": 10, "completion_tokens": 5},
                        max_tokens=30)  # parent's own call is 15 tokens; only the child's 15 reach the budget
        self.assertEqual(p.run("plan").stop_reason, "max_tokens")

    def test_subagent_failure_text(self):
        child = AgentSpec("explorer", prompt(), result_schema=ANSWER, max_steps=1)
        p = self.parent([call("explore", {"question": "q"}, 1), call("ping", {}, 2),
                         call("finish", {"name": "n"}, 3)], child_spec=child)
        p.run("plan")
        self.assertEqual(self.llm.seen[2]["content"], "sub-agent stopped: max_steps")


if __name__ == "__main__":
    unittest.main()
