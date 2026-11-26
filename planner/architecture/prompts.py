"""Prompts for the architecture review agents. The first line of each task message names the run
('Review module m01 ...', 'Explore program X: ...', 'Global review ...'); events and tests key on it."""
from __future__ import annotations

from collections import Counter

import networkx as nx

from .plan import ArchitecturePlan

PROMPT_VERSION = "arch-review-1"

ROLE = """You are the architecture planner of a COBOL-to-{target} migration. A deterministic draft has already
grouped programs into modules (domain modules, utility modules, isolated programs). You review the parts the draft
was unsure about and give modules names and purposes. The migration keeps each program's logic as it is; you only
decide where programs live, which module owns which data store, and what each module is for."""

RULES = """Rules:
- Use the KB tools first (module_overview, program_facts, program_edges, who_uses, similar_programs, unit_facts).
  Use search_code / read_lines only for what the KB does not hold. explore_program asks a read-only helper one
  focused question about one program; it has a small budget.
- Change the plan only with the edit tools. Every edit needs a short reason and evidence refs that exist:
  program:ID, copybook:NAME, store:ID, job:ID, src:PATH:LINE. An edit whose evidence does not exist is rejected.
- Do not refactor program logic or invent programs, files or tables. Prefer fewer, cohesive modules of 3 to 25
  programs. Leave a program where it is when the evidence is balanced; the reviewer will see it as an open question.
- Finish by calling `finish` with the result asked for in the task."""

EXPLORER = """You answer one question about one COBOL program for an architecture planner, using the KB tools first
and code search only where the KB is silent. Answer in one or two sentences and cite evidence refs
(program:ID, copybook:NAME, store:ID, job:ID, src:PATH:LINE) that support it. Then call `finish`."""


def module_message(plan: ArchitecturePlan, module_id: str) -> str:
    m = plan.module(module_id)
    lines = [f"Review module {m.id} ({m.name}, {m.kind}).",
             "Programs (confidence = share of its links that stay inside this module):"]
    lines += [f"- {a.program}: {a.confidence:.2f}" + (" [tolerant KB facts]" if a.low_kb_confidence else "")
              for a in m.programs]
    questions = [q for q in plan.open_questions if q.subject in {a.program for a in m.programs}
                 and q.kind in ("uncertain_program", "low_kb_confidence")]
    lines.append("Open questions:")
    lines += [f"- {q.kind} {q.subject}: {q.detail}" for q in questions] or ["- none"]
    lines.append("Other modules: " + ", ".join(f"{x.id} {x.name} ({x.kind}, {len(x.programs)})"
                                               for x in plan.modules if x.id != m.id))
    lines.append("Decide for each uncertain program whether it belongs here; move it with evidence if not. "
                 "Then call finish with {name, purpose, evidence}: a short lower-case module name, a one-sentence "
                 "purpose, and refs supporting them.")
    return "\n".join(lines)


def global_message(plan: ArchitecturePlan, g: nx.Graph) -> str:
    home = {a.program: m.id for m in plan.modules for a in m.programs}
    cross = Counter()
    for a, b, d in g.edges(data=True):
        if a in home and b in home and home[a] != home[b]:
            cross[tuple(sorted((home[a], home[b])))] += d["weight"]
    lines = ["Global review of the architecture plan.", "Modules:"]
    lines += [f"- {m.id} {m.name} ({m.kind}, {len(m.programs)} programs): {m.purpose or '(no purpose yet)'}"
              for m in plan.modules]
    lines.append("Strongest links between modules (sum of edge weights):")
    lines += [f"- {a} <-> {b}: {w:.1f}" for (a, b), w in cross.most_common(10)] or ["- none"]
    shared = [s for s in plan.stores if s.shared_write]
    lines.append("Stores written by more than one module:")
    lines += [f"- {s.id}: writers {', '.join(s.writers)}; owner {s.owner}" for s in shared] or ["- none"]
    lines.append("Merge, split or rename modules only where the evidence is clear, and settle ownership of shared "
                 "stores with set_owner. Then call finish with {summary}: what you changed and why.")
    return "\n".join(lines)


def explorer_message(program_id: str, question: str) -> str:
    return f"Explore program {program_id}: {question}"
