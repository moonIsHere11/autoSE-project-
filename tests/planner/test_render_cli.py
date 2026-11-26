"""Layout, review document and CLI.  python3 -m unittest tests.planner.test_render_cli -v"""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from harness.llm import LLMError
from planner.architecture.config import PlannerConfig
from planner.architecture.draft import make_draft
from planner.architecture.plan import ArchitecturePlan, Assignment, Module
from planner.architecture.render import layout, package_name, render_markdown
from planner.architecture.validate import validate_plan
from planner.cli import main
from planner.kb import FixtureKb

FIXTURE = Path(__file__).parent / "fixtures" / "estate.json"
SECTIONS = ["# Architecture plan", "## Modules", "## Shared types", "## Shared code", "## Data stores", "## Jobs",
            "## Changes made by the planner agent", "## Open questions"]


class DownLLM:
    """Configured via config.yaml in the CLI test; every call fails, so the review keeps the draft."""
    model = "down"

    def __init__(self, **kw):
        self.kw = kw

    def chat(self, msgs, tools):
        raise LLMError("no network in tests")


def workspace(cfg: str) -> Path:
    w = Path(tempfile.mkdtemp())
    (w / "config.yaml").write_text(cfg)
    return w


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class RenderTests(unittest.TestCase):
    def test_package_name(self):
        self.assertEqual(package_name("Card-Lifecycle 2"), "card_lifecycle_2")
        self.assertEqual(package_name("9lives"), "m_9lives")

    def test_layout_per_target(self):
        plan = ArchitecturePlan(modules=[Module("m01", "account", "", "domain", [Assignment("A", 1.0)])])
        self.assertEqual(layout(plan, "java")["m01"], "src/main/java/app/account/")
        self.assertEqual(layout(plan, "python")["m01"], "app/account/")
        self.assertEqual(layout(plan, "go")["m01"], "internal/account/")
        self.assertEqual(layout(plan, "java", root="com_acme")["shared-types"], "src/main/java/com_acme/shared/types/")
        self.assertEqual(layout(plan, "go")["jobs"], "internal/jobs/")
        with self.assertRaises(ValueError):
            layout(plan, "cobol")

    def test_markdown_sections_in_order(self):
        plan, _ = make_draft(FixtureKb(FIXTURE), PlannerConfig())
        md = render_markdown(plan)
        positions = [md.index(s + "\n") for s in SECTIONS]
        self.assertEqual(positions, sorted(positions))
        for m in plan.modules:
            self.assertIn(f"### {m.name}", md)
        self.assertIn("CUSTSRCH", md[md.index("## Open questions"):])
        self.assertIn("AccountRepository", md)


class CliTests(unittest.TestCase):
    def test_cli_no_agent_on_fixture(self):
        w = workspace("target: {language: python}\n")
        code, out, err = run(["architecture", "--workspace", str(w), "--no-agent", "--fixture", str(FIXTURE)])
        self.assertEqual(code, 0, err)
        plan = ArchitecturePlan.from_dict(json.loads((w / "plan" / "architecture.json").read_text()))
        self.assertEqual(validate_plan(plan, FixtureKb(FIXTURE)), [])
        self.assertTrue(plan.layout["m01"].startswith("app/"))  # python, from config.yaml
        self.assertTrue((w / "plan" / "architecture.md").read_text().startswith("# Architecture plan"))
        summary = json.loads(out.strip().splitlines()[-1])
        self.assertEqual(summary["modules"], len(plan.modules))
        self.assertEqual(summary["edits"], 0)

    def test_cli_target_flag_overrides_config(self):
        w = workspace("target: {language: python}\n")
        run(["architecture", "--workspace", str(w), "--no-agent", "--fixture", str(FIXTURE), "--target", "go"])
        plan = json.loads((w / "plan" / "architecture.json").read_text())
        self.assertTrue(plan["layout"]["m01"].startswith("internal/"))

    def test_cli_agent_uses_configured_llm(self):
        w = workspace("harness: {llm: {adapter: 'tests.planner.test_render_cli:DownLLM', model: x}}\n")
        code, out, err = run(["architecture", "--workspace", str(w), "--fixture", str(FIXTURE)])
        self.assertEqual(code, 0, err)
        plan = json.loads((w / "plan" / "architecture.json").read_text())
        self.assertIn("review_incomplete", [q["kind"] for q in plan["open_questions"]])
        self.assertEqual(plan["inputs"]["review"]["model"], "down")

    def test_cli_bad_target_exit_2(self):
        w = workspace("{}\n")
        code, _, err = run(["architecture", "--workspace", str(w), "--no-agent", "--fixture", str(FIXTURE),
                            "--target", "cobol"])
        self.assertEqual(code, 2)
        self.assertIn("cobol", err)

    def test_cli_missing_kb_exit_2(self):
        w = workspace("{}\n")
        code, _, err = run(["architecture", "--workspace", str(w), "--no-agent"])
        self.assertEqual(code, 2)
        self.assertIn("kb", err.lower())

    def test_cli_bad_config_exit_2(self):
        w = workspace("planner: {architecture: {nope: 1}}\n")
        code, _, err = run(["architecture", "--workspace", str(w), "--no-agent", "--fixture", str(FIXTURE)])
        self.assertEqual(code, 2)
        self.assertIn("nope", err)


if __name__ == "__main__":
    unittest.main()
