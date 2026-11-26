"""Plan invariants and evidence references. Evidence refs the agent may cite:
program:ID  copybook:NAME  store:ID  job:ID  src:PATH:LINE (PATH relative to the KB's source root)."""
from __future__ import annotations

from collections import Counter

from ..kb import KnowledgeSource
from .plan import ArchitecturePlan

REF_KINDS = ("program", "copybook", "store", "job", "src")


def evidence_exists(ref: str, kb: KnowledgeSource) -> bool:
    kind, _, rest = ref.partition(":")
    if not rest:
        return False
    if kind == "program":
        return any(p.id == rest for p in kb.programs())
    if kind == "copybook":
        return rest in kb.copybooks() or any(rest in p.copybooks for p in kb.programs())
    if kind == "store":
        return any(u.store == rest for u in kb.store_uses())
    if kind == "job":
        return any(s.job == rest for s in kb.job_steps())
    if kind == "src":
        path, _, line = rest.rpartition(":")
        if not path or not line.isdigit():
            return False
        root = kb.source_root().resolve()
        target = (root / path).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            return False
        return 1 <= int(line) <= len(target.read_text(errors="replace").splitlines())
    return False


def validate_plan(plan: ArchitecturePlan, kb: KnowledgeSource) -> list[str]:
    errors = []
    known = {p.id for p in kb.programs()}
    counts = Counter(plan.program_ids())
    for prog, n in sorted(counts.items()):
        if n > 1:
            errors.append(f"program {prog} is in more than one module")
        if prog not in known:
            errors.append(f"unknown program {prog} (not in the KB)")
    for prog in sorted(known - set(counts)):
        errors.append(f"program {prog} is in no module")
    ids = [m.id for m in plan.modules]
    names = [m.name for m in plan.modules]
    for dup in sorted({x for x in ids if ids.count(x) > 1}):
        errors.append(f"module id {dup} is used twice")
    for dup in sorted({x for x in names if names.count(x) > 1}):
        errors.append(f"module name {dup} is used twice")
    for m in plan.modules:
        if not m.programs:
            errors.append(f"module {m.id} has no programs")
    for s in plan.stores:
        if s.owner not in ids:
            errors.append(f"store {s.id} is owned by unknown module {s.owner}")
    for t in plan.shared_types:
        if len(set(t.used_by)) < 2:
            errors.append(f"shared type {t.copybook} is used by fewer than 2 modules")
    for e in plan.edits:
        for ref in e.evidence:
            if not evidence_exists(ref, kb):
                errors.append(f"edit {e.action}: evidence {ref} does not exist")
    return errors
