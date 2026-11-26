"""The only way the planner agent changes the plan. Every edit needs a reason and evidence refs that exist in
the KB or the source; it is applied to a copy, roles and confidences are recomputed, the result must pass
validate_plan, and only then is it swapped in and journalled. Methods return 'ok: ...' or 'ERROR: ...' text
(tool results the model reads), never raise for a bad request."""
from __future__ import annotations

import copy
import re
from typing import Callable

import networkx as nx

from ..kb import KnowledgeSource
from .config import PlannerConfig
from .draft import confidence, evidence_for, open_questions
from .plan import ArchitecturePlan, Assignment, Edit, Module
from .roles import assign_roles
from .validate import evidence_exists, validate_plan

KEEP_QUESTIONS = {"review_incomplete"}  # added by the review loop, not derived from the plan


class PlanEditor:
    def __init__(self, plan: ArchitecturePlan, kb: KnowledgeSource, g: nx.Graph, cfg: PlannerConfig):
        self.plan, self.kb, self.g, self.cfg = plan, kb, g, cfg

    # ---- machinery ----
    def _apply(self, action: str, args: dict, reason: str, evidence: list[str],
               mutate: Callable[[ArchitecturePlan], str | None]) -> str:
        if not (reason or "").strip():
            return "ERROR: every edit needs a non-empty reason"
        if not evidence:
            return "ERROR: every edit needs evidence refs (program:ID, copybook:NAME, store:ID, job:ID, src:PATH:LINE)"
        missing = [r for r in evidence if not evidence_exists(r, self.kb)]
        if missing:
            return f"ERROR: evidence not found in the KB or source: {', '.join(missing)}"
        new = copy.deepcopy(self.plan)
        problem = mutate(new)
        if problem:
            return f"ERROR: {problem}"
        new.edits.append(Edit(action, args, reason.strip(), list(evidence)))
        self._recompute(new)
        errors = validate_plan(new, self.kb)
        if errors:
            return "ERROR: the edit would break the plan: " + "; ".join(errors[:5])
        self.plan = new
        return f"ok: {action} {args}"

    def _recompute(self, plan: ArchitecturePlan) -> None:
        plan.modules = [m for m in plan.modules if m.programs]
        utilities = {a.program for m in plan.modules if m.kind == "utility" for a in m.programs}
        for m in plan.modules:
            members = {a.program for a in m.programs}
            for a in m.programs:
                a.confidence = round(confidence(self.g, a.program, members, utilities), 4)
                a.evidence = evidence_for(self.g, a.program, members)
        plan.shared_types, plan.shared_code, plan.stores, plan.jobs = assign_roles(self.kb, plan.modules)
        ids = {m.id for m in plan.modules}
        for e in plan.edits:  # explicit ownership decisions outlive role recomputation
            if e.action == "set_owner" and e.args["module"] in ids:
                for s in plan.stores:
                    if s.id == e.args["store"] and s.owner != e.args["module"]:
                        plan.module(s.owner).owned_stores.remove(s.id)
                        plan.module(e.args["module"]).owned_stores.append(s.id)
                        s.owner = e.args["module"]
        kept = [q for q in plan.open_questions if q.kind in KEEP_QUESTIONS]
        plan.open_questions = open_questions(plan, self.kb, self.g, self.cfg) + kept

    @staticmethod
    def _find(plan: ArchitecturePlan, module_id: str) -> Module | None:
        return next((m for m in plan.modules if m.id == module_id), None)

    def _next_id(self, plan: ArchitecturePlan) -> str:
        used = {m.id for m in plan.modules} | {v for e in plan.edits for v in e.args.values() if isinstance(v, str)}
        n = max([int(x[1:]) for x in used if re.fullmatch(r"m\d+", x)] + [0]) + 1
        return f"m{n:02}"

    @staticmethod
    def _take(plan: ArchitecturePlan, program: str) -> Assignment | None:
        for m in plan.modules:
            for a in m.programs:
                if a.program == program:
                    m.programs.remove(a)
                    a.decided_by = "agent"
                    return a
        return None

    # ---- edits (tool handlers) ----
    def move_program(self, program: str, to_module: str, reason: str = "", evidence: list[str] | None = None) -> str:
        def mutate(plan):
            target = self._find(plan, to_module)
            if target is None:
                return f"no module {to_module}"
            if any(a.program == program for a in target.programs):
                return f"{program} is already in {to_module}"
            a = self._take(plan, program)
            if a is None:
                return f"no program {program} in the plan"
            target.programs.append(a)
            target.programs.sort(key=lambda x: x.program)
        return self._apply("move_program", {"program": program, "to_module": to_module}, reason, evidence or [], mutate)

    def merge_modules(self, keep: str, absorb: str, reason: str = "", evidence: list[str] | None = None) -> str:
        def mutate(plan):
            k, a = self._find(plan, keep), self._find(plan, absorb)
            if k is None or a is None or k is a:
                return f"need two different existing modules, got {keep}, {absorb}"
            for x in a.programs:
                x.decided_by = "agent"
            k.programs = sorted(k.programs + a.programs, key=lambda x: x.program)
            a.programs = []
        return self._apply("merge_modules", {"keep": keep, "absorb": absorb}, reason, evidence or [], mutate)

    def split_module(self, module: str, programs: list[str], new_name: str, reason: str = "",
                     evidence: list[str] | None = None) -> str:
        def mutate(plan):
            m = self._find(plan, module)
            if m is None:
                return f"no module {module}"
            members = {a.program for a in m.programs}
            wanted = set(programs or [])
            if not wanted or not wanted <= members:
                return f"programs must be a non-empty subset of {module}: {sorted(members)}"
            if wanted == members:
                return "a split must leave at least one program in the original module"
            if not (new_name or "").strip() or any(x.name == new_name for x in plan.modules):
                return f"new_name must be non-empty and unique, got {new_name!r}"
            moved = [self._take(plan, p) for p in sorted(wanted)]
            plan.modules.append(Module(self._next_id(plan), new_name.strip(), "", m.kind, moved))
        return self._apply("split_module", {"module": module, "programs": sorted(programs or []), "new_name": new_name},
                           reason, evidence or [], mutate)

    def rename_module(self, module: str, name: str, reason: str = "", evidence: list[str] | None = None) -> str:
        def mutate(plan):
            m = self._find(plan, module)
            if m is None:
                return f"no module {module}"
            if not (name or "").strip() or any(x.name == name and x is not m for x in plan.modules):
                return f"name must be non-empty and unique, got {name!r}"
            m.name = name.strip()
        return self._apply("rename_module", {"module": module, "name": name}, reason, evidence or [], mutate)

    def set_module_purpose(self, module: str, purpose: str, reason: str = "", evidence: list[str] | None = None) -> str:
        def mutate(plan):
            m = self._find(plan, module)
            if m is None:
                return f"no module {module}"
            if not (purpose or "").strip():
                return "purpose must be non-empty"
            m.purpose = purpose.strip()
        return self._apply("set_module_purpose", {"module": module, "purpose": purpose}, reason, evidence or [], mutate)

    def mark_utility(self, program: str, reason: str = "", evidence: list[str] | None = None) -> str:
        def mutate(plan):
            util = next((m for m in plan.modules if m.kind == "utility"), None)
            if util is not None and any(a.program == program for a in util.programs):
                return f"{program} is already a utility"
            a = self._take(plan, program)
            if a is None:
                return f"no program {program} in the plan"
            if util is None:
                name = "util" if all(m.name != "util" for m in plan.modules) else "util-2"
                util = Module(self._next_id(plan), name, "", "utility")
                plan.modules.append(util)
            util.programs = sorted(util.programs + [a], key=lambda x: x.program)
        return self._apply("mark_utility", {"program": program}, reason, evidence or [], mutate)

    def set_owner(self, store: str, module: str, reason: str = "", evidence: list[str] | None = None) -> str:
        def mutate(plan):
            if not any(s.id == store for s in plan.stores):
                return f"no store {store} in the plan"
            if self._find(plan, module) is None:
                return f"no module {module}"
        return self._apply("set_owner", {"store": store, "module": module}, reason, evidence or [], mutate)
