"""PromptBuilder and the stdlib schema check.  python3 -m unittest tests.harness.test_prompt -v"""
import unittest

from harness.prompt import PromptBuilder
from harness.schema_check import validate

RESULT = {"type": "object", "required": ["name", "purpose"],
          "properties": {"name": {"type": "string"}, "purpose": {"type": "string"}}}


class PromptBuilderTests(unittest.TestCase):
    def test_sections_order_and_insert(self):
        p = PromptBuilder()
        p.set("a", "A")
        p.set("c", "C")
        p.set("b", "B", after="a")
        p.set("z", "Z", before="a")
        self.assertEqual(p.names(), ["z", "a", "b", "c"])
        self.assertEqual(p.render(), "Z\n\nA\n\nB\n\nC")

    def test_callable_sections_reevaluated(self):
        n = [0]

        def counter():
            n[0] += 1
            return str(n[0])

        p = PromptBuilder()
        p.set("count", counter)
        self.assertEqual(p.render(), "1")
        self.assertEqual(p.render(), "2")

    def test_empty_sections_skipped(self):
        p = PromptBuilder()
        p.set("a", "A")
        p.set("notes", lambda: "")
        p.set("b", "  ")
        p.set("c", "C")
        self.assertEqual(p.render(), "A\n\nC")

    def test_replace_keeps_position(self):
        p = PromptBuilder()
        for k in "abc":
            p.set(k, k.upper())
        p.set("b", "NEW")
        self.assertEqual(p.names(), ["a", "b", "c"])
        self.assertIn("NEW", p.render())
        p.remove("b")
        self.assertEqual(p.names(), ["a", "c"])

    def test_copy_is_independent(self):
        p = PromptBuilder()
        p.set("a", "A")
        q = p.copy()
        q.set("b", "B")
        self.assertEqual(p.names(), ["a"])

    def test_unknown_anchor_raises(self):
        with self.assertRaises(KeyError):
            PromptBuilder().set("a", "A", after="missing")


class SchemaCheckTests(unittest.TestCase):
    def test_required_and_types(self):
        errs = validate({"name": 3}, RESULT)
        self.assertEqual(len(errs), 2)
        self.assertTrue(any("$.purpose" in e for e in errs))
        self.assertTrue(any("$.name" in e and "string" in e for e in errs))

    def test_array_items_and_enum(self):
        schema = {"type": "object", "properties": {
            "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "kind": {"enum": ["domain", "utility"]}}}
        errs = validate({"evidence": ["ok", 4], "kind": "other"}, schema)
        self.assertTrue(any(e.startswith("$.evidence[1]") for e in errs))
        self.assertTrue(any(e.startswith("$.kind") for e in errs))
        self.assertTrue(validate({"evidence": []}, schema))
        self.assertFalse(validate({"evidence": ["x"], "kind": "utility"}, schema))

    def test_integer_is_not_bool_and_number_accepts_int(self):
        self.assertTrue(validate(True, {"type": "integer"}))
        self.assertFalse(validate(3, {"type": "number"}))
        self.assertFalse(validate(None, {"type": "null"}))

    def test_valid_returns_empty(self):
        self.assertEqual(validate({"name": "acct", "purpose": "accounts"}, RESULT), [])
        self.assertEqual(validate({"x": 1}, {"type": "object", "unknownKeyword": True}), [])


if __name__ == "__main__":
    unittest.main()
