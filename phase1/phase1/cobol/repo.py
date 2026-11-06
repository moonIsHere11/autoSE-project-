"""Repo-level analysis: programs, call graph, layers, copybook usage, architecture overview.
Also the query helpers (search/read/outline/refs) the agent's tools sit on."""
import json
import re
from collections import defaultdict
from pathlib import Path

from .analyzer import HARD_UNSUPPORTED, analyse_program
from .insight import cluster_programs, cluster_units, context_pack, program_pack
from .source import COBOL_EXTS, CopyResolver, load_file


def split_programs(lines):
    idx = [i for i, l in enumerate(lines) if re.match(r"\s*(IDENTIFICATION|ID)\s+DIVISION", l.text, re.I)]
    if len(idx) <= 1:
        return [lines]
    return [lines[a:b] for a, b in zip(idx, idx[1:] + [len(lines)])]


def tarjan(graph):
    idx, low, st, on, out, n = {}, {}, [], set(), [], [0]

    def go(v):
        idx[v] = low[v] = n[0]; n[0] += 1; st.append(v); on.add(v)
        for w in graph.get(v, ()):
            if w not in idx:
                go(w); low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], idx[w])
        if low[v] == idx[v]:
            comp = []
            while True:
                w = st.pop(); on.discard(w); comp.append(w)
                if w == v:
                    break
            out.append(sorted(comp))
    for v in list(graph):
        if v not in idx:
            go(v)
    return out  # reverse topological: callees (leaves) first


def analyse_repo(root):
    root = Path(root)
    cr = CopyResolver(root)
    programs, units, fields, copybook_files = [], [], [], []
    for p in sorted(root.rglob("*")):
        if not (p.is_file() and p.suffix.lower() in COBOL_EXTS):
            continue
        rel = str(p.relative_to(root))
        lines, header = load_file(p, rel)
        if not any(re.match(r"\s*PROCEDURE\s+DIVISION", l.text, re.I) for l in lines):
            copybook_files.append(rel)
            continue
        for chunk in split_programs(lines):
            used = []
            exp = cr.expand(chunk, used=used)
            prog, us, fs = analyse_program(exp, header, used)
            prog["file"] = rel
            prog["loc"] = len(chunk)
            prog["program_id"] = prog["program_id"] or p.stem.upper()
            for u in us:
                u["program"] = prog["program_id"]
            for f in fs:
                f["program"] = prog["program_id"]
            programs.append(prog); units.extend(us); fields.extend(fs)

    multi = len(programs) > 1
    q = (lambda prog, name: f"{prog}.{name}") if multi else (lambda prog, name: name)
    for u in units:
        base = u["program"]
        u["unit_id"] = q(base, u["unit_id"])
        u["performs"] = [q(base, x) for x in u["performs"]]
        u["falls_through_to"] = q(base, u["falls_through_to"]) if u["falls_through_to"] else None
        u["section"] = q(base, u["section"]) if u["section"] else None
    pids = {p["program_id"] for p in programs}
    pby = {p["program_id"]: p for p in programs}
    fields_by_prog = defaultdict(list)
    for f in fields:
        fields_by_prog[f["program"]].append(f)
    for u in units:  # resolve call targets: literals, or variables set by MOVE 'X' TO VAR
        lits = dict(pby[u["program"]]["var_literals"])
        for f in fields_by_prog.get(u["program"], ()):
            iv = (f["initial_value"] or "").strip("'\"")
            if f["initial_value"] and f["initial_value"][0] in "'\"" and iv.upper() in pby:
                lits.setdefault(f["name"], []).append(iv.upper())
        res = []
        for t, dyn in u["calls"]:
            res += (lits.get(t, []) if dyn else [t]) or ([f"?{t}"] if dyn else [])
        u["calls"] = list(dict.fromkeys(res))
    for p in programs:
        p["calls"] = sorted({t for u in units if u["program"] == p["program_id"] for t in u["calls"]})
    # program call graph (only edges to programs inside the repo)
    cg = {p["program_id"]: sorted(set(t for t in p["calls"] if t in pids and t != p["program_id"]))
          for p in programs}
    called = {t for ts in cg.values() for t in ts}
    for p in programs:
        p["external_calls"] = [t for t in p["calls"] if t not in pids]
        p["entry"] = p["program_id"] not in called
    sccs = tarjan(cg)
    comp_of = {p: i for i, c in enumerate(sccs) for p in c}
    depth = {}
    for i, c in enumerate(sccs):  # callees come first
        deps = [depth[comp_of[t]] for p in c for t in cg[p] if comp_of[t] != i]
        depth[i] = 1 + max(deps) if deps else 0
    lv = defaultdict(list)
    for i, c in enumerate(sccs):
        lv[depth[i]] += c
    layers = [{"layer": k, "programs": sorted(v),
               "cyclic": any(len(c) > 1 and set(c) <= set(v) for c in sccs)} for k, v in sorted(lv.items())]
    cb_users = defaultdict(list)
    for p in programs:
        for c in p["copybooks"]:
            cb_users[c].append(p["program_id"])
    clusters = cluster_units(units, fields)
    subsystems = cluster_programs(programs, cg, dict(cb_users))
    return {"root": str(root), "clusters": clusters, "subsystems": subsystems, "programs": programs, "units": units, "fields": fields,
            "program_call_graph": cg, "layers": layers, "copybook_users": dict(cb_users),
            "unresolved_copybooks": sorted(cr.unresolved), "copybook_files": copybook_files,
            "qualified_ids": multi}


def unit_graph_order(index, only_supported=False):
    """Leaves-first order of units (callees before callers), SCC-safe."""
    by = {u["unit_id"]: u for u in index["units"]}
    g = {u: [x for x in by[u]["performs"] if x in by] for u in by}
    order = [x for comp in tarjan(g) for x in comp]
    order = [u for u in order if by[u]["kind"] != "section" or True]
    return order


def architecture_md(index, max_programs=40):
    ps, us = index["programs"], index["units"]
    L = [f"# Architecture overview ({len(ps)} programs, {len(us)} units, "
         f"{sum(p['loc'] for p in ps)} lines)", ""]
    ent = [p["program_id"] for p in ps if p["entry"]]
    L.append(f"Entry programs (not called by another program): {', '.join(ent[:15])}"
             + (f" ... +{len(ent) - 15} more" if len(ent) > 15 else ""))
    flags = defaultdict(int)
    for p in ps:
        for f in p["flags"]:
            flags[f] += 1
    L.append("Construct prevalence (programs using it): " +
             ", ".join(f"{k}={v}" for k, v in sorted(flags.items(), key=lambda x: -x[1])))
    L.append("")
    L.append("## Migration layers (leaves first; migrate in this order)")
    for ly in index["layers"][:50]:
        pr = ly["programs"]
        L.append(f"- L{ly['layer']}{' (contains call cycles)' if ly['cyclic'] else ''} [{len(pr)}]: "
                 + ", ".join(pr[:12]) + (" ..." if len(pr) > 12 else ""))
    L.append("")
    L.append("## Programs")
    L.append("| program | file | loc | units | flags | calls | description |")
    L.append("|---|---|---|---|---|---|---|")
    for p in sorted(ps, key=lambda p: -p["loc"])[:max_programs]:
        L.append(f"| {p['program_id']} | {p['file']} | {p['loc']} | {p['unit_count']} | "
                 f"{','.join(p['flags']) or '-'} | {','.join(p['calls'][:4]) or '-'} | "
                 f"{(p['description'] or '')[:60]} |")
    if len(ps) > max_programs:
        L.append(f"... {len(ps) - max_programs} more (use list_programs)")
    edges = [(a, b) for a, bs in index["program_call_graph"].items() for b in bs][:60]
    if edges:
        L += ["", "## Call graph (mermaid)", "```mermaid", "graph TD"]
        L += [f"  {a} --> {b}" for a, b in edges] + ["```"]
    L += ["", "## Subsystems (programs coupled by calls + shared copybooks)"]
    for ss in index["subsystems"][:12]:
        L.append(f"- {ss['subsystem_id']} [{len(ss['programs'])}] via {ss['label']}: " + ", ".join(ss["programs"][:8]))
    hz = defaultdict(int)
    for u in index["units"]:
        for h in u["hazards"]:
            if h["severity"] != "low":
                hz[h["gap_id"]] += 1
    L += ["", "## Semantic hazards found (medium/high, count of sites)", ", ".join(f"{k}={v}" for k, v in sorted(hz.items(), key=lambda x: -x[1]))]
    risky = sorted(index["units"], key=lambda u: -u["risk"])[:5]
    L += ["Riskiest units: " + ", ".join(f"{u['unit_id']}({u['risk']})" for u in risky)]
    top = sorted(index["copybook_users"].items(), key=lambda x: -len(x[1]))[:10]
    if top:
        L += ["", "## Most shared copybooks", *[f"- {c}: used by {len(u)} programs" for c, u in top]]
    if index["unresolved_copybooks"]:
        L += ["", "Unresolved copybooks (system/missing): " + ", ".join(index["unresolved_copybooks"][:20])]
    return "\n".join(L)


# ---------------- query helpers used by tools ----------------
class Index:
    def __init__(self, data, source_root):
        self.d, self.root = data, Path(source_root)
        self.units = {u["unit_id"]: u for u in data["units"]}
        self.progs = {p["program_id"]: p for p in data["programs"]}

    @classmethod
    def load(cls, path, source_root):
        return cls(json.loads(Path(path).read_text()), source_root)

    def context_pack(self, uid, budget=6000):
        return context_pack(self, uid, budget)

    def program_pack(self, pid, budget=7000):
        return program_pack(self, pid, budget)

    def hazards(self, uid):
        return self.units[uid]["hazards"]

    def clusters(self, program=None, limit=25):
        cs = [c for c in self.d["clusters"] if not program or c["program"] == program.upper()]
        return [{k: c[k] for k in ("cluster_id", "label", "loc", "risk")} | {"units": c["units"][:8], "n": len(c["units"])}
                for c in sorted(cs, key=lambda c: -c["risk"])[:limit]]

    def overview(self):
        return architecture_md(self.d)

    def list_programs(self, offset=0, limit=30):
        ps = self.d["programs"][offset:offset + limit]
        return [{k: p[k] for k in ("program_id", "file", "loc", "unit_count", "flags", "entry")} for p in ps]

    def program(self, pid):
        p = dict(self.progs[pid])
        p.pop("var_literals", None)
        p["units"] = [{"unit_id": u["unit_id"], "kind": u["kind"], "loc": u["loc"],
                       "unsupported": u["unsupported"]} for u in self.d["units"] if u["program"] == pid]
        return p

    def unit_brief(self, uid):
        u = dict(self.units[uid])
        callers = [x["unit_id"] for x in self.d["units"] if uid in x["performs"]]
        u["callers"] = callers
        u["in_scope"] = not (set(u["unsupported"]) & HARD_UNSUPPORTED)
        return u

    def unit_source(self, uid, max_lines=250):
        u = self.units[uid]
        return self.read_lines(u["span"]["file"], u["span"]["start_line"],
                               min(u["span"]["end_line"], u["span"]["start_line"] + max_lines - 1))

    def fields_of(self, uid):
        u = self.units[uid]
        ids = set(u["reads"]) | set(u["writes"])
        fs = [f for f in self.d["fields"] if f["program"] == u["program"] and f["field_id"] in ids]
        return [{"field_id": f["field_id"], "pic": f["pic"], "usage": f["usage"],
                 "type": f["semantic_type"], "init": f["initial_value"],
                 "rw": ("r" if f["field_id"] in u["reads"] else "") + ("w" if f["field_id"] in u["writes"] else "")}
                for f in fs]

    def data_flow(self, name, limit=40):
        name = name.upper()
        hits = []
        for u in self.d["units"]:
            r = [x for x in u["reads"] if x.split(".")[-1] == name or x == name]
            w = [x for x in u["writes"] if x.split(".")[-1] == name or x == name]
            if r or w:
                hits.append({"unit_id": u["unit_id"], "reads": bool(r), "writes": bool(w)})
        return hits[:limit]

    def read_lines(self, file, start, end, max_lines=200):
        p = (self.root / file).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError("path outside source/")
        lines = p.read_text(errors="replace").splitlines()
        end = min(end, start + max_lines - 1, len(lines))
        return "\n".join(f"{i:>5}| {lines[i - 1].rstrip()}" for i in range(max(start, 1), end + 1)) + \
            (f"\n[file has {len(lines)} lines]" if end < len(lines) else "")

    def search(self, pattern, glob="*", context=0, max_results=25, ignore_case=True):
        rx = re.compile(pattern, re.I if ignore_case else 0)
        out, files = [], 0
        for p in sorted(self.root.rglob(glob)):
            if not (p.is_file() and p.suffix.lower() in COBOL_EXTS | {".jcl", ".txt", ".md"}):
                continue
            ls = p.read_text(errors="replace").splitlines()
            for i, l in enumerate(ls):
                if rx.search(l) and not (len(l) > 6 and l[6] in "*/"):
                    rel = p.relative_to(self.root)
                    blk = [f"{rel}:{j + 1}: {ls[j].strip()}" for j in range(max(0, i - context), min(len(ls), i + context + 1))]
                    out.append("\n".join(blk))
                    if len(out) >= max_results:
                        return "\n".join(out) + f"\n[stopped at {max_results} results; refine the pattern]"
        return "\n".join(out) or "no matches"

    def outline(self, file):
        return [{"unit_id": u["unit_id"], "kind": u["kind"], "lines": f"{u['span']['start_line']}-{u['span']['end_line']}",
                 "performs": u["performs"][:6], "unsupported": u["unsupported"]}
                for u in self.d["units"] if u["span"]["file"] == file]
