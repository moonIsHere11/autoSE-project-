"""ToolPolicy (privileges) and registry tags.  python3 -m unittest tests.harness.test_policy -v"""
import unittest

from harness.policy import PolicyDecision, ToolPolicy
from harness.registry import Tool, ToolRegistry, obj


def tool(name, *tags):
    return Tool(name, name, obj(), lambda: name, frozenset(tags))


READ = tool("read_file", "read")
WRITE = tool("write_file", "write")
PLAIN = tool("notes")


class PolicyTests(unittest.TestCase):
    def test_default_offers_everything(self):
        p = ToolPolicy()
        self.assertTrue(all(p.offered(t) for t in (READ, WRITE, PLAIN)))
        self.assertEqual(p.check(WRITE, {}, {}), PolicyDecision("allow"))

    def test_allow_by_name_or_tag(self):
        p = ToolPolicy(allow={"notes"}, allow_tags={"read"})
        self.assertTrue(p.offered(READ))
        self.assertTrue(p.offered(PLAIN))
        self.assertFalse(p.offered(WRITE))
        self.assertFalse(ToolPolicy(allow_tags={"read"}).offered(PLAIN))

    def test_deny_wins_over_allow(self):
        p = ToolPolicy(allow={"write_file", "read_file"}, deny_tags={"write"})
        self.assertFalse(p.offered(WRITE))
        self.assertTrue(p.offered(READ))
        self.assertFalse(ToolPolicy(deny={"read_file"}).offered(READ))
        self.assertEqual(p.check(WRITE, {}, {}).action, "deny")

    def test_limit_denies_after_n(self):
        submit = tool("submit")
        p = ToolPolicy(limits={"submit": 2})
        self.assertEqual(p.check(submit, {}, {"submit": 1}).action, "allow")
        d = p.check(submit, {}, {"submit": 2})
        self.assertEqual(d.action, "deny")
        self.assertIn("call limit 2", d.reason)

    def test_guard_message_denies(self):
        p = ToolPolicy(guards={"write_file": lambda a: "path escapes staging/" if ".." in a.get("path", "") else None})
        self.assertEqual(p.check(WRITE, {"path": "src/A.java"}, {}).action, "allow")
        self.assertEqual(p.check(WRITE, {"path": "../x"}, {}), PolicyDecision("deny", "path escapes staging/"))

    def test_ask_tools(self):
        self.assertEqual(ToolPolicy(ask={"write_file"}).check(WRITE, {}, {}).action, "ask")

    def test_copy_is_independent(self):
        p = ToolPolicy(allow={"a"}, deny={"b"}, limits={"c": 1})
        q = p.copy(ask={"x"})
        q.allow.add("z")
        q.deny.add("y")
        q.limits["c"] = 9
        self.assertEqual((p.allow, p.deny, p.limits, p.ask), ({"a"}, {"b"}, {"c": 1}, set()))
        self.assertEqual(q.ask, {"x"})


class RegistryTagTests(unittest.TestCase):
    def test_tags_get_remove_replace(self):
        reg = ToolRegistry()

        @reg.tool("echo", "echo", obj(), tags=("read",))
        def echo():
            return "one"

        self.assertEqual(reg.get("echo").tags, frozenset({"read"}))
        self.assertIsNone(reg.get("nope"))
        reg.replace(Tool("echo", "echo2", obj(), lambda: "two", frozenset({"write"})))
        self.assertEqual(reg.call("echo", {}), "two")
        self.assertEqual([t.name for t in reg.tools()], ["echo"])
        reg.remove("echo")
        self.assertEqual(reg.tools(), [])
        with self.assertRaises(KeyError):
            reg.remove("echo")


if __name__ == "__main__":
    unittest.main()
