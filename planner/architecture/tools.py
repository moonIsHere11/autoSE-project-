"""Planner agent tools. KB tools (tag `read`) are the primary source; code tools (tag `read`) are simple searches;
edit tools (tag `plan_edit`) are the only way to change the plan. Tools read editor.plan at call time."""
from __future__ import annotations

import json
import re

from harness.registry import I, LIST_S, S, ToolRegistry, obj

from ..kb import KnowledgeSource
from .edits import PlanEditor

READ, EDIT = ("read",), ("plan_edit",)
TEXT_EXTS = {".cbl", ".cob", ".cobol", ".cpy", ".copy", ".jcl", ".prc", ".proc", ".bms", ".txt", ""}


def _j(x) -> str:
    return json.dumps(x, separators=(",", ":"), default=str)


def register_kb_tools(reg: ToolRegistry, kb: KnowledgeSource, editor: PlanEditor) -> None:
    progs = {p.id: p for p in kb.programs()}

    def module_id(program: str) -> str | None:
        try:
            return editor.plan.module_of(program).id
        except KeyError:
            return None

    @reg.tool("module_overview", "Current modules: id, name, kind, purpose, programs with confidence, owned stores, "
                                 "dependencies.", tags=READ)
    def module_overview():
        return _j([{"id": m.id, "name": m.name, "kind": m.kind, "purpose": m.purpose,
                    "programs": {a.program: a.confidence for a in m.programs}, "owned_stores": m.owned_stores,
                    "depends_on": m.depends_on} for m in editor.plan.modules])

    @reg.tool("program_facts", "KB facts for one program: kind, copybooks, calls, stores read/written, job steps, "
                               "KB confidence, current module.", obj(["program_id"], program_id=S), tags=READ)
    def program_facts(program_id):
        p = progs.get(program_id)
        if p is None:
            return f"ERROR: unknown program {program_id!r}; known: {sorted(progs)[:40]}"
        return _j({"id": p.id, "file": p.file, "kind": p.kind, "kb_confidence": p.confidence, "loc": p.loc,
                   "copybooks": p.copybooks, "calls": p.calls, "module": module_id(p.id),
                   "stores": [{"store": u.store, "kind": u.store_kind, "mode": u.mode}
                              for u in kb.store_uses() if u.program == p.id],
                   "job_steps": [f"{s.job}.{s.step} (#{s.order})" for s in kb.job_steps() if s.program == p.id]})

    @reg.tool("program_edges", "Who a program is linked to in the program graph, strongest first, with the "
                               "evidence (call, copybook, write_read, co_read, same_job, similar).",
              obj(["program_id"], program_id=S), tags=READ)
    def program_edges(program_id):
        if program_id not in editor.g:
            return f"ERROR: unknown program {program_id!r}"
        rows = sorted(editor.g.edges(program_id, data=True), key=lambda e: -e[2]["weight"])
        return _j([{"program": other, "module": module_id(other), "weight": round(d["weight"], 2),
                    "evidence": [f"{e.kind}:{e.item}" for e in d["evidence"]]} for _, other, d in rows[:15]])

    @reg.tool("who_uses", "Users of a copybook, readers/writers of a dataset or table, or callers/callees of a "
                          "program.", obj(["item"], item=S), tags=READ)
    def who_uses(item):
        out: dict = {}
        users = sorted(p.id for p in progs.values() if item in p.copybooks)
        if users:
            out["copybook_users"] = users
        uses = [u for u in kb.store_uses() if u.store == item]
        if uses:
            out["readers"] = sorted({u.program for u in uses if u.mode == "read"})
            out["writers"] = sorted({u.program for u in uses if u.mode == "write"})
        if item in progs:
            out["callers"] = sorted(p.id for p in progs.values() if item in p.calls)
            out["callees"] = list(progs[item].calls)
        return _j(out) if out else f"ERROR: {item!r} is not a known copybook, store or program"

    @reg.tool("similar_programs", "Programs with similar vocabulary and I/O, most similar first.",
              obj(["program_id"], program_id=S, limit=I), tags=READ)
    def similar_programs(program_id, limit=5):
        if program_id not in editor.g:
            return f"ERROR: unknown program {program_id!r}"
        rows = []
        for _, other, d in editor.g.edges(program_id, data=True):
            for e in d["evidence"]:
                if e.kind == "similar":
                    rows.append((float(e.item), other))
        rows.sort(key=lambda r: (-r[0], r[1]))
        return _j([{"program": o, "module": module_id(o), "similarity": s} for s, o in rows[: max(1, min(limit, 20))]])

    @reg.tool("unit_facts", "Paragraphs/sections of a program from the KB (calls, performs).",
              obj(["program_id"], program_id=S), tags=READ)
    def unit_facts(program_id):
        units = kb.units(program_id)
        if not units and program_id not in progs:
            return f"ERROR: unknown program {program_id!r}"
        return _j([{k: u.get(k) for k in ("unit_id", "kind", "calls", "performs") if u.get(k) is not None}
                   for u in units[:60]])


def register_code_tools(reg: ToolRegistry, kb: KnowledgeSource) -> None:
    root = kb.source_root().resolve()

    def files():
        return [p for p in sorted(root.rglob("*")) if p.is_file() and p.suffix.lower() in TEXT_EXTS]

    @reg.tool("search_code", "Regex search over the COBOL source tree (comment lines skipped); returns path:line: text.",
              obj(["pattern"], pattern=S, max_results=I), tags=READ)
    def search_code(pattern, max_results=25):
        try:
            rx = re.compile(pattern, re.I)
        except re.error as e:
            return f"ERROR: bad regex: {e}"
        cap, out = max(1, min(int(max_results), 60)), []
        for p in files():
            for n, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
                if len(line) > 6 and line[6] in "*/":
                    continue
                if rx.search(line):
                    out.append(f"{p.relative_to(root)}:{n}: {line.strip()}")
                    if len(out) >= cap:
                        return "\n".join(out) + "\n[stopped; refine the pattern]"
        return "\n".join(out) or "no matches"

    @reg.tool("read_lines", "Read a line range (at most 120 lines) of a source file, numbered.",
              obj(["path", "start", "end"], path=S, start=I, end=I), tags=READ)
    def read_lines(path, start, end):
        target = (root / path).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            return f"ERROR: no file {path!r} under the source tree"
        lines = target.read_text(errors="replace").splitlines()
        start, end = max(1, int(start)), min(int(end), len(lines), max(1, int(start)) + 119)
        return "\n".join(f"{i:>5}| {lines[i - 1].rstrip()}" for i in range(start, end + 1)) or "(empty range)"


def register_edit_tools(reg: ToolRegistry, editor: PlanEditor) -> None:
    why = {"reason": S, "evidence": LIST_S}
    req = ["reason", "evidence"]
    reg.tool("move_program", "Move a program to another module.",
             obj(["program", "to_module"] + req, program=S, to_module=S, **why), tags=EDIT)(editor.move_program)
    reg.tool("merge_modules", "Merge module `absorb` into module `keep`.",
             obj(["keep", "absorb"] + req, keep=S, absorb=S, **why), tags=EDIT)(editor.merge_modules)
    reg.tool("split_module", "Move `programs` out of `module` into a new module called `new_name`.",
             obj(["module", "programs", "new_name"] + req, module=S, programs=LIST_S, new_name=S, **why),
             tags=EDIT)(editor.split_module)
    reg.tool("rename_module", "Rename a module (short, lower-case, unique).",
             obj(["module", "name"] + req, module=S, name=S, **why), tags=EDIT)(editor.rename_module)
    reg.tool("set_module_purpose", "Set a module's one-sentence purpose.",
             obj(["module", "purpose"] + req, module=S, purpose=S, **why), tags=EDIT)(editor.set_module_purpose)
    reg.tool("mark_utility", "Move a program into the shared utility module.",
             obj(["program"] + req, program=S, **why), tags=EDIT)(editor.mark_utility)
    reg.tool("set_owner", "Make a module the owner of a data store (it gets the store's data-access interface).",
             obj(["store", "module"] + req, store=S, module=S, **why), tags=EDIT)(editor.set_owner)
