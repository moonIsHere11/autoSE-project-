"""Agent review of the draft: one bounded pass per module with uncertain programs, then one global pass.
Every agent is a harness Agent; the explorer is a read-only sub-agent exposed as `explore_program`.
Whatever happens (LLM down, budget spent, no finish), the result is a valid plan: the draft plus the edits
that passed validation, with `review_incomplete` questions for passes that did not finish."""
from __future__ import annotations

import copy
from typing import Callable

import networkx as nx

from harness.agent import Agent, AgentSpec
from harness.events import EventLog
from harness.policy import ToolPolicy
from harness.prompt import PromptBuilder
from harness.registry import S, ToolRegistry, obj

from ..kb import KnowledgeSource
from . import prompts
from .config import PlannerConfig
from .draft import open_questions
from .edits import PlanEditor
from .plan import ArchitecturePlan, OpenQuestion
from .tools import register_code_tools, register_edit_tools, register_kb_tools

EVIDENCE = {"type": "array", "items": {"type": "string"}, "minItems": 1}
EXPLORER_RESULT = {"type": "object", "required": ["answer", "evidence"],
                   "properties": {"answer": {"type": "string"}, "evidence": EVIDENCE}}
MODULE_RESULT = {"type": "object", "required": ["name", "purpose", "evidence"],
                 "properties": {"name": {"type": "string"}, "purpose": {"type": "string"}, "evidence": EVIDENCE}}
GLOBAL_RESULT = {"type": "object", "required": ["summary"], "properties": {"summary": {"type": "string"}}}
REVIEW_KINDS = ("uncertain_program", "low_kb_confidence")


def _prompt(*sections: tuple[str, str]) -> PromptBuilder:
    p = PromptBuilder()
    for name, text in sections:
        p.set(name, text)
    return p


def review(plan: ArchitecturePlan, g: nx.Graph, kb: KnowledgeSource, llm, cfg: PlannerConfig, *,
           target: str = "Java", events: EventLog | None = None, log: Callable = print) -> ArchitecturePlan:
    editor = PlanEditor(copy.deepcopy(plan), kb, g, cfg)  # the caller's draft stays untouched
    reg = ToolRegistry(max_out=8000)
    register_kb_tools(reg, kb, editor)
    register_code_tools(reg, kb)
    register_edit_tools(reg, editor)
    role = prompts.ROLE.format(target=target)
    budget = cfg.review
    explorer_spec = AgentSpec("planner/explorer", _prompt(("role", prompts.EXPLORER)),
                              ToolPolicy(allow_tags={"read"}), max_steps=budget.explorer_steps,
                              result_schema=EXPLORER_RESULT)
    incomplete: list[OpenQuestion] = []

    def run_pass(name: str, message: str, schema: dict) -> tuple[str, dict | None]:
        spec = AgentSpec(name, _prompt(("role", role), ("rules", prompts.RULES)),
                         ToolPolicy(allow_tags={"read", "plan_edit", "agent"},
                                    limits={"explore_program": budget.explorer_calls}),
                         max_steps=budget.pass_steps, max_tokens=budget.max_tokens, result_schema=schema)
        agent = Agent(llm, reg, spec, events=events, log=log)
        reg.replace(agent.as_tool("explore_program", "Ask a read-only helper one question about one program.",
                                  obj(["program_id", "question"], program_id=S, question=S),
                                  prompts.explorer_message, spec=explorer_spec))
        result = agent.run(message)
        return result.stop_reason, result.output

    flagged = sorted({editor.plan.module_of(q.subject).id for q in editor.plan.open_questions
                      if q.kind in REVIEW_KINDS})
    for module_id in flagged:
        if module_id not in {m.id for m in editor.plan.modules}:
            continue  # merged away by an earlier pass
        reason, out = run_pass(f"planner/module/{module_id}", prompts.module_message(editor.plan, module_id),
                               MODULE_RESULT)
        if out is None:
            incomplete.append(OpenQuestion("review_incomplete", module_id, reason))
            continue
        if module_id in {m.id for m in editor.plan.modules}:
            for msg in (editor.rename_module(module_id, out["name"], "module review", out["evidence"]),
                        editor.set_module_purpose(module_id, out["purpose"], "module review", out["evidence"])):
                if msg.startswith("ERROR"):
                    incomplete.append(OpenQuestion("review_incomplete", module_id, f"finish not applied: {msg}"))

    reason, out = run_pass("planner/global", prompts.global_message(editor.plan, g), GLOBAL_RESULT)
    if out is None:
        incomplete.append(OpenQuestion("review_incomplete", "global", reason))

    final = editor.plan
    final.open_questions = open_questions(final, kb, g, cfg) + incomplete
    final.inputs = {**final.inputs, "review": {"model": getattr(llm, "model", "?"), "prompt_version": prompts.PROMPT_VERSION}}
    return final
