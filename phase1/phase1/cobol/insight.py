"""Higher-level structure on top of the static facts:
 - data-coupling clustering of units into candidate modules (Mono2Micro / Service-Cutter style:
   units that call each other or share written state belong together);
 - subsystem clustering of programs (calls + shared copybooks);
 - dependency-aware context packs (bottom-up callee context + data producers/consumers, AlphaTrans /
   CodePlan / RepoGraph style) so the agent gets what it needs in one budgeted read."""
import math
from collections import Counter, defaultdict


def label_propagation(nodes, edges, iters=25):
    """Deterministic weighted label propagation. edges: {(a,b): w}."""
    adj = defaultdict(dict)
    for (a, b), w in edges.items():
        if a != b:
            adj[a][b] = adj[a].get(b, 0) + w
            adj[b][a] = adj[b].get(a, 0) + w
    lab = {n: n for n in nodes}
    order = sorted(nodes)
    for _ in range(iters):
        changed = False
        for n in order:
            if not adj[n]:
                continue
            score = Counter()
            for m, w in adj[n].items():
                score[lab[m]] += w
            best = max(score.items(), key=lambda kv: (kv[1], -hash_key(kv[0])))[0]
            if best != lab[n] and score[best] > score[lab[n]]:
                lab[n] = best
                changed = True
        if not changed:
            break
    return lab


def hash_key(s):
    return sum(ord(c) * (i + 1) for i, c in enumerate(s)) % 100003


def cluster_units(units, fields):
    """Annotates each unit with `cluster` (id) and returns cluster descriptions."""
    by_prog = defaultdict(list)
    for u in units:
        by_prog[u["program"]].append(u)
    fby = defaultdict(dict)
    for f in fields:
        fby[f["program"]][f["field_id"]] = f
    clusters = []
    for prog, us in by_prog.items():
        ids = {u["unit_id"] for u in us}
        touch = defaultdict(list)
        for u in us:
            for fid in set(u["reads"]) | set(u["writes"]):
                touch[fid].append(u["unit_id"])
        edges = defaultdict(float)
        for u in us:
            for c in u["performs"]:
                if c in ids:
                    edges[(u["unit_id"], c)] += 2
        n = len(us)
        for fid, who in touch.items():
            if len(who) < 2 or len(who) > max(4, 0.3 * n):  # skip globals (status flags, counters)
                continue
            w = 1 / math.log(1 + len(who))
            wr = [x for x in who if fid in next(u for u in us if u["unit_id"] == x)["writes"]]
            if not wr:
                continue
            for a in wr:
                for b in who:
                    if a != b:
                        edges[(a, b)] += w
        lab = label_propagation(sorted(ids), edges)
        groups = defaultdict(list)
        for uid, l in lab.items():
            groups[l].append(uid)
        for i, (_, members) in enumerate(sorted(groups.items(), key=lambda kv: -len(kv[1]))):
            cid = f"{prog}#{i}"
            roots = Counter()
            for u in us:
                if u["unit_id"] in members:
                    for fid in set(u["reads"]) | set(u["writes"]):
                        roots[fid.split(".")[0]] += 1
            label = ", ".join(r for r, _ in roots.most_common(2)) or "control"
            clusters.append({"cluster_id": cid, "program": prog, "units": sorted(members), "label": label,
                             "loc": sum(u["loc"] for u in us if u["unit_id"] in members),
                             "risk": sum(u["risk"] for u in us if u["unit_id"] in members)})
            for u in us:
                if u["unit_id"] in members:
                    u["cluster"] = cid
    return clusters


def cluster_programs(programs, call_graph, copybook_users):
    pids = [p["program_id"] for p in programs]
    edges = defaultdict(float)
    for a, bs in call_graph.items():
        for b in bs:
            edges[(a, b)] += 3
    for cb, users in copybook_users.items():
        if 2 <= len(users) <= max(3, 0.5 * len(pids)):
            for i, a in enumerate(users):
                for b in users[i + 1:]:
                    edges[(a, b)] += 1 / math.log(1 + len(users))
    lab = label_propagation(pids, edges)
    groups = defaultdict(list)
    for p, l in lab.items():
        groups[l].append(p)
    out = []
    for i, (_, members) in enumerate(sorted(groups.items(), key=lambda kv: -len(kv[1]))):
        cbs = Counter(c for p in programs if p["program_id"] in members for c in p["copybooks"]
                      if len(copybook_users.get(c, ())) < len(pids) * 0.5)
        out.append({"subsystem_id": f"SS{i}", "programs": sorted(members),
                    "label": ", ".join(c for c, _ in cbs.most_common(2)) or members[0]})
        for p in programs:
            if p["program_id"] in members:
                p["subsystem"] = f"SS{i}"
    return out


GAP_FIX = {"G-TRUNCATE": "emulate PIC width with the runtime library's decimal type (truncate, do not round)",
           "G-OVERFLOW": "check result against PIC digits; COBOL drops high-order digits when no SIZE ERROR",
           "G-ROUNDING": "use ROUNDED = half away from zero, not HALF_EVEN",
           "G-SIGN": "unsigned target stores magnitude", "G-NUMALPHA": "format numerics to exact PIC width, zero-padded",
           "G-GROUPMOVE": "group MOVE = byte-wise string copy of the record", "G-GOTO": "needs control-flow restructuring",
           "G-FALLTHROUGH": "translate the whole PERFORM THRU range together", "G-PACKED": "use runtime decimal; ignore byte layout unless REDEFINES",
           "G-DIVZERO": "guard divisor == 0 and leave target unchanged"}


def context_pack(ix, uid, budget=6000):
    """Priority-ordered, budgeted context for translating one unit."""
    u = ix.units[uid]
    parts, used = [], 0

    def add(title, body, share):
        nonlocal used
        cap = int(budget * share)
        if len(body) > cap:
            body = body[:cap].rsplit("\n", 1)[0] + "\n...[truncated; use read_lines/search for more]"
        if body.strip():
            parts.append(f"## {title}\n{body}")
            used += len(body)

    add("Unit source", ix.unit_source(uid, 120), 0.40)
    fl = ix.fields_of(uid)
    add("Fields (type table)", "\n".join(
        f"{f['rw']:2} {f['field_id']}  PIC {f['pic'] or '(group)'} {f['usage']}  "
        f"{f['type']['kind']}" + (f"({f['type']['digits']},{f['type']['scale']},{'S' if f['type']['signed'] else 'U'})" if f['type']['kind'] == 'decimal' else (f"[{f['type']['length']}]" if f['type']['length'] else ""))
        for f in fl[:40]), 0.20)
    if u["hazards"]:
        add("Semantic hazards to handle (static scan)", "\n".join(
            f"- [{h['severity']}] {h['gap_id']} line {h['line']}: {h['message']}  => {GAP_FIX.get(h['gap_id'], '')}"
            for h in sorted(u["hazards"], key=lambda h: -{"high": 3, "medium": 2, "low": 1}[h["severity"]])[:12]), 0.22)
    callees = [ix.units[c] for c in u["performs"] if c in ix.units]
    if callees:
        add("Callees (already migrated first - bottom-up)", "\n".join(
            f"- {c['unit_id']}: reads {len(c['reads'])} writes {len(c['writes'])} fields, risk {c['risk']}, "
            f"{'in_scope' if not c['unsupported'] else 'unsupported:' + ','.join(c['unsupported'])}" for c in callees[:10]), 0.06)
    prod = Counter()
    cons = Counter()
    mine_r, mine_w = set(u["reads"]), set(u["writes"])
    for o in ix.d["units"]:
        if o["unit_id"] == uid or o["program"] != u["program"]:
            continue
        a = len(mine_r & set(o["writes"]))
        b = len(mine_w & set(o["reads"]))
        if a:
            prod[o["unit_id"]] = a
        if b:
            cons[o["unit_id"]] = b
    if prod or cons:
        add("Data dependences (who feeds me / who consumes me)",
            "feeds me: " + ", ".join(f"{k}({v})" for k, v in prod.most_common(5)) +
            "\nconsumes my output: " + ", ".join(f"{k}({v})" for k, v in cons.most_common(5)), 0.06)
    cl = u.get("cluster")
    if cl:
        mates = [m for m in next(c for c in ix.d["clusters"] if c["cluster_id"] == cl)["units"] if m != uid]
        add("Module (cluster) mates - share state, keep conventions consistent", ", ".join(mates[:12]), 0.06)
    return "\n\n".join(parts)


def program_pack(ix, pid, budget=7000):
    """Program-level context: structure, unit order (leaves first) with risk, hazards of the riskiest units."""
    p = ix.progs[pid]
    us = [u for u in ix.d["units"] if u["program"] == pid]
    order = [u["unit_id"] for u in sorted(us, key=lambda u: u["span"]["start_line"])]
    L = [f"## Program {pid} ({p['file']}, {p['loc']} loc, {len(us)} units)", p.get("description") or "",
         f"files: {', '.join(f['name'] + '=' + f['assign'] for f in p['files']) or 'none'}; "
         f"copybooks: {', '.join(p['copybooks']) or 'none'}; constructs: {', '.join(p['flags']) or 'clean'}",
         "", "## Paragraphs in source order (translate each as one method; keep control flow identical)"]
    for u in us:
        L.append(f"- {u['unit_id'].split('.')[-1]}: lines {u['span']['start_line']}-{u['span']['end_line']}, "
                 f"performs {[x.split('.')[-1] for x in u['performs']][:5]}, risk {u['risk']}, "
                 f"{'/'.join(u['unsupported']) or 'ok'}")
    L.append("")
    L.append("## Top semantic hazards (handle each explicitly)")
    hz = sorted(((h, u) for u in us for h in u["hazards"] if h["severity"] != "low"),
                key=lambda x: -{"high": 3, "medium": 2}[x[0]["severity"]])[:14]
    for h, u in hz:
        L.append(f"- [{h['severity']}] {h['gap_id']} {u['unit_id'].split('.')[-1]} line {h['line']}: {h['message']} => {GAP_FIX.get(h['gap_id'], '')}")
    text = "\n".join(L)
    return text if len(text) <= budget else text[:budget] + "\n...[truncated; use outline/context_pack]"
