"""Rendering: the target-language package layout (the only language-specific part of the plan) and the
markdown review document for the human reviewer."""
from __future__ import annotations

import re

from .plan import ArchitecturePlan

RESERVED_PACKAGES = {"jobs", "shared"}  # used by the jobs layer and shared types
TARGETS = {"java": "src/main/java/{root}/{pkg}/", "python": "{root}/{pkg}/", "go": "internal/{pkg}/"}


def package_name(text: str) -> str:
    name = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "module"
    return f"m_{name}" if name[0].isdigit() else name


def layout(plan: ArchitecturePlan, target: str, root: str = "app") -> dict[str, str]:
    if target not in TARGETS:
        raise ValueError(f"unknown target {target!r}; one of {sorted(TARGETS)}")
    pattern = TARGETS[target]
    root = package_name(root)
    out = {m.id: pattern.format(root=root, pkg=package_name(m.name)) for m in plan.modules}
    out["shared-types"] = pattern.format(root=root, pkg="shared/types")
    out["jobs"] = pattern.format(root=root, pkg="jobs")
    return out


def _cell(x) -> str:
    return str(x).replace("|", "\\|").replace("\n", " ")


def render_markdown(plan: ArchitecturePlan) -> str:
    name = {m.id: m.name for m in plan.modules}
    L = ["# Architecture plan", "",
         f"Schema {plan.schema_version}; KB {plan.inputs.get('kb_version', '?')}. "
         f"{len(plan.modules)} modules, {len(plan.program_ids())} programs, {len(plan.open_questions)} open questions.", ""]
    L += ["## Modules", "", "| id | name | kind | programs | owned stores |", "| --- | --- | --- | --- | --- |"]
    L += [f"| {m.id} | {_cell(m.name)} | {m.kind} | {len(m.programs)} | {_cell(', '.join(m.owned_stores) or '-')} |"
          for m in plan.modules]
    for m in plan.modules:
        L += ["", f"### {m.name}", "", f"`{m.id}` ({m.kind}) at `{plan.layout.get(m.id, '?')}`. "
              f"Purpose: {m.purpose or '(not set)'}", ""]
        for a in m.programs:
            ev = "; ".join(f"{e.kind} {e.item} with {e.other}" for e in a.evidence) or "no links inside the module"
            flags = (" (placed by the planner agent)" if a.decided_by == "agent" else "") + \
                    (" (tolerant KB facts)" if a.low_kb_confidence else "")
            L.append(f"- **{a.program}** confidence {a.confidence:.2f}{flags}: {ev}")
        L.append(f"- Local types: {', '.join(m.local_types) or 'none'}. "
                 f"Depends on: {', '.join(f'{d} ({name.get(d, d)})' for d in m.depends_on) or 'nothing'}.")
    L += ["", "## Shared types", ""]
    L += [f"- `{t.type_name}` from copybook {t.copybook}, used by {', '.join(t.used_by)}" for t in plan.shared_types] \
        or ["- none"]
    L += ["", "## Shared code", ""]
    L += [f"- {c.copybook}: implemented once in {c.module} ({name.get(c.module, '?')}), used by {', '.join(c.used_by)}"
          for c in plan.shared_code] or ["- none"]
    L += ["", "## Data stores", "", "| store | kind | owner | interface | readers | writers | shared write |",
          "| --- | --- | --- | --- | --- | --- | --- |"]
    L += [f"| {_cell(s.id)} | {s.kind} | {s.owner} ({_cell(name.get(s.owner, '?'))}) | {s.interface} | "
          f"{_cell(', '.join(s.readers) or '-')} | {_cell(', '.join(s.writers) or '-')} | {'yes' if s.shared_write else 'no'} |"
          for s in plan.stores]
    L += ["", "## Jobs", ""]
    for j in plan.jobs:
        L.append(f"- **{j.id}**: " + " -> ".join(
            f"{s['step']} {s['program'] or '?'} [{s['module'] or '-'}]" for s in j.steps))
    if not plan.jobs:
        L.append("- none")
    L += ["", "## Changes made by the planner agent", ""]
    L += [f"- {e.action} {e.args}: {e.reason} (evidence: {', '.join(e.evidence)})" for e in plan.edits] or ["- none"]
    L += ["", "## Open questions", ""]
    L += [f"- **{q.kind}** {q.subject}: {q.detail}" for q in plan.open_questions] or ["- none"]
    return "\n".join(L) + "\n"
