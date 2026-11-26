"""Roles derived from module membership: shared vs local types, where shared code lives, who owns each data
store, which modules depend on which, and how JCL jobs map onto modules. Recomputed after every plan edit."""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from ..kb import KnowledgeSource
from .plan import Job, Module, SharedCode, SharedType, Store


def pascal(name: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[^A-Za-z0-9]+", name) if part)


def assign_roles(kb: KnowledgeSource, modules: list[Module]) -> tuple[list[SharedType], list[SharedCode], list[Store], list[Job]]:
    home = {a.program: m for m in modules for a in m.programs}
    programs = [p for p in kb.programs() if p.id in home]
    kinds = {name: cb.kind for name, cb in kb.copybooks().items()}
    for m in modules:
        m.local_types, m.owned_stores, m.depends_on = [], [], []

    users: dict[str, set[str]] = defaultdict(set)
    for p in programs:
        for c in p.copybooks:
            users[c].add(p.id)
    shared_types, shared_code = [], []
    utility_modules = [m for m in modules if m.kind == "utility"]
    for copybook in sorted(users):
        progs = users[copybook]
        mods = sorted({home[p].id for p in progs})
        if kinds.get(copybook, "record") == "code":
            if len(mods) == 1:
                where = mods[0]
            elif utility_modules:
                calls = Counter(home[c].id for p in programs if p.id in progs for c in p.calls
                                if c in home and home[c].kind == "utility")
                where = max(utility_modules, key=lambda m: (calls.get(m.id, 0), [-ord(ch) for ch in m.id])).id
            else:
                where = mods[0]
            shared_code.append(SharedCode(copybook, where, sorted(progs)))
        else:  # a record layout: local to one module, shared type when several modules use it
            if len(mods) == 1:
                next(m for m in modules if m.id == mods[0]).local_types.append(copybook)
            else:
                shared_types.append(SharedType(copybook, pascal(copybook), mods))

    readers: dict[str, set[str]] = defaultdict(set)
    writers: dict[str, set[str]] = defaultdict(set)
    store_kind: dict[str, str] = {}
    for u in kb.store_uses():
        if u.program in home:
            (writers if u.mode == "write" else readers)[u.store].add(u.program)
            store_kind.setdefault(u.store, u.store_kind)
    stores = []
    for sid in sorted(store_kind):
        voters = writers[sid] or readers[sid]
        counts = Counter(home[p].id for p in voters)
        owner = min(counts, key=lambda mid: (-counts[mid], mid))
        stores.append(Store(sid, store_kind[sid], owner, sorted(readers[sid]), sorted(writers[sid]),
                            pascal(sid) + "Repository", len({home[p].id for p in writers[sid]}) > 1))
        next(m for m in modules if m.id == owner).owned_stores.append(sid)

    owner_of = {s.id: s.owner for s in stores}
    deps: dict[str, set[str]] = defaultdict(set)
    for p in programs:
        mine = home[p.id].id
        deps[mine] |= {home[c].id for c in p.calls if c in home}
        deps[mine] |= {owner_of[s] for s, who in readers.items() if p.id in who and s in owner_of}
    for m in modules:
        m.depends_on = sorted(deps[m.id] - {m.id})

    steps_by_job: dict[str, list[dict]] = defaultdict(list)
    for s in kb.job_steps():
        steps_by_job[s.job].append({"step": s.step, "order": s.order, "program": s.program,
                                    "module": home[s.program].id if s.program in home else None,
                                    "reads": list(s.reads), "writes": list(s.writes)})
    jobs = [Job(job, sorted(steps, key=lambda x: x["order"])) for job, steps in sorted(steps_by_job.items())]
    return shared_types, shared_code, stores, jobs
