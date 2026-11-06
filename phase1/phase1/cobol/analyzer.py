"""Static analysis of one COBOL program: data dictionary, units (sections/paragraphs),
reads/writes, PERFORM/CALL/GO TO graph, unsupported-construct flags."""
import re

NAME = r"[A-Za-z0-9][A-Za-z0-9-]*"
NOT_PARAGRAPHS = {"EXIT", "GOBACK", "CONTINUE", "ELSE", "NEXT", "STOP", "END-EXEC", "DIVISION"}
VERBS = ("MOVE ADD SUBTRACT MULTIPLY DIVIDE COMPUTE IF ELSE EVALUATE WHEN PERFORM CALL GO READ WRITE "
         "REWRITE DELETE OPEN CLOSE START ACCEPT DISPLAY STRING UNSTRING INSPECT INITIALIZE SET STOP "
         "GOBACK EXIT CONTINUE SEARCH RETURN SORT MERGE RELEASE CANCEL ALTER").split()
FILE_VERBS = {"OPEN", "CLOSE", "READ", "WRITE", "REWRITE", "DELETE", "START", "RETURN", "SORT", "MERGE"}
HARD_UNSUPPORTED = {"file_io", "cics", "sql", "goto", "alter", "redefines"}
TERMINAL = {"GOBACK", "STOP"}


# ---------------- data division ----------------
def pic_type(pic, usage, has_children):
    if has_children or pic is None:
        return {"kind": "group", "digits": None, "scale": None, "signed": None, "length": None}
    p = pic.upper().replace(" ", "")
    exp = re.sub(r"(.)\((\d+)\)", lambda m: m.group(1) * int(m.group(2)), p)
    if re.fullmatch(r"S?[9]*(V9*)?", exp.replace("P", "")) and "9" in exp:
        body = exp.lstrip("S")
        ip, _, fp = body.partition("V")
        return {"kind": "decimal", "digits": len(ip) + len(fp), "scale": len(fp),
                "signed": exp.startswith("S"), "length": None}
    if re.fullmatch(r"[XA]+", exp):
        return {"kind": "alphanumeric", "digits": None, "scale": None, "signed": None, "length": len(exp)}
    # edited / other numeric-edited pictures
    return {"kind": "alphanumeric", "digits": None, "scale": None, "signed": None,
            "length": len(exp), "edited": True}


def parse_data(lines):
    """lines: data-division Line objects. -> (fields, conditions{name: parent_id})"""
    fields, conds, stack = [], {}, []
    stmt, first = "", None
    for ln in lines:
        stmt = (stmt + " " + ln.text.strip()).strip()
        first = first or ln
        if not stmt.endswith("."):
            continue
        s, f = stmt[:-1].strip(), first
        stmt, first = "", None
        m = re.match(rf"(\d{{1,2}})\s+({NAME})?\s*(.*)$", s, re.I | re.S)
        if not m:
            continue
        level, name, rest = int(m.group(1)), (m.group(2) or "FILLER").upper(), m.group(3)
        if name in ("PIC", "PICTURE", "VALUE", "OCCURS", "REDEFINES", "USAGE", "COMP"):  # unnamed item
            rest, name = name + " " + rest, "FILLER"
        if level == 88:
            if stack:
                conds[name] = stack[-1]["field_id"]
            continue
        if level == 66:
            continue
        while stack and (stack[-1]["level"] >= level or level in (1, 77)):
            stack.pop()
        parent = stack[-1]["field_id"] if stack else None
        fid = f"{parent}.{name}" if parent else name
        pic = re.search(r"\bPIC(?:TURE)?\s+(?:IS\s+)?(\S+)", rest, re.I)
        usage = re.search(r"\b(?:USAGE\s+(?:IS\s+)?)?(COMP-[1-5]|COMP|COMPUTATIONAL(?:-[1-5])?|BINARY|PACKED-DECIMAL|INDEX|POINTER)\b",
                          rest, re.I)
        occ = re.search(r"\bOCCURS\s+(\d+)", rest, re.I)
        val = re.search(r"\bVALUES?\s+(?:IS\s+|ARE\s+)?('[^']*'|\"[^\"]*\"|\S+)", rest, re.I)
        redef = re.search(r"\bREDEFINES\s+(" + NAME + ")", rest, re.I)
        fld = {"field_id": fid, "name": name, "level": level, "parent": parent,
               "pic": pic.group(1).rstrip(".") if pic else None,
               "usage": usage.group(1).upper() if usage else "DISPLAY",
               "occurs": int(occ.group(1)) if occ else None,
               "initial_value": val.group(1) if val else None,
               "redefines": redef.group(1).upper() if redef else None,
               "span": {"file": f.file, "start_line": f.no, "end_line": ln.no}}
        fld["_group"] = pic is None
        fields.append(fld)
        stack.append(fld)
    for fl in fields:
        has_child = any(c["parent"] == fl["field_id"] for c in fields) if fl["_group"] else False
        fl["semantic_type"] = pic_type(fl["pic"], fl["usage"], fl["_group"] or has_child)
        del fl["_group"]
    return fields, conds


# ---------------- procedure division ----------------
def _tokens(text):
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9-]*|=", text.upper())


def split_statements(text):
    """Split flattened, literal-stripped text into (VERB, [tokens]) statements."""
    toks, out, cur = _tokens(text), [], None
    for t in toks:
        if t in VERBS and not (cur and cur[0] in ("GO",) and t == "GO"):
            if t == "STOP" or t != "ELSE":
                cur = [t, []]
                out.append(cur)
                continue
            cur = None
        if cur is not None:
            cur[1].append(t)
    return out


class Resolver:
    def __init__(self, fields, conds):
        self.by_name = {}
        for f in fields:
            if f["name"] != "FILLER":
                self.by_name.setdefault(f["name"], []).append(f["field_id"])
        self.conds = conds
        self.f = {f["field_id"]: f for f in fields}

    def look(self, tok):
        if tok in self.by_name:
            return self.by_name[tok]
        if tok in self.conds:
            return [self.conds[tok]]
        return []


def analyse_statements(stmts, res):
    reads, writes = set(), set()
    for verb, toks in stmts:
        def ids(ts):
            return [i for t in ts for i in res.look(t)]
        if verb == "MOVE" and "TO" in toks:
            k = toks.index("TO")
            reads.update(ids(toks[:k]))
            writes.update(ids(toks[k + 1:]))
        elif verb in ("ADD", "SUBTRACT", "MULTIPLY", "DIVIDE"):
            tgt_kw = {"ADD": "TO", "SUBTRACT": "FROM", "MULTIPLY": "BY", "DIVIDE": "INTO"}[verb]
            if "GIVING" in toks:
                k = toks.index("GIVING")
                reads.update(ids(toks[:k]))
                writes.update(ids(toks[k + 1:]))
            elif tgt_kw in toks:
                k = toks.index(tgt_kw)
                reads.update(ids(toks[:k]))
                writes.update(ids(toks[k + 1:]))
                reads.update(ids(toks[k + 1:]))
            else:
                reads.update(ids(toks))
        elif verb == "COMPUTE" and "=" in toks:
            k = toks.index("=")
            writes.update(ids(toks[:k]))
            reads.update(ids(toks[k + 1:]))
        elif verb in ("READ", "ACCEPT", "INITIALIZE") or (verb == "SET" and "TO" in toks):
            if verb == "SET":
                k = toks.index("TO")
                writes.update(ids(toks[:k]))
                reads.update(ids(toks[k + 1:]))
            elif "INTO" in toks:
                k = toks.index("INTO")
                reads.update(ids(toks[:k]))
                writes.update(ids(toks[k + 1:k + 2]))
            else:
                (reads if verb == "READ" else writes).update(ids(toks))
        elif verb in ("STRING", "UNSTRING") and "INTO" in toks:
            k = toks.index("INTO")
            reads.update(ids(toks[:k]))
            writes.update(ids(toks[k + 1:]))
        elif verb == "INSPECT":
            reads.update(ids(toks))
            writes.update(ids(toks[:1]))
        else:
            reads.update(ids(toks))
    return reads, writes


# ---------------- semantic hazards (COBOL behaviours a naive translation gets wrong) ----------------
SEV_W = {"high": 3, "medium": 2, "low": 1}


def _ty(f):
    return f["semantic_type"] if f else None


def _idig(t):
    return (t["digits"] or 0) - (t["scale"] or 0)


def find_hazards(stmts, res, lines):
    """Static scan for silent-semantics hazards. Each hazard names the KB gap that explains it."""
    out, seen = [], set()

    def one(tok):
        ids = res.look(tok)
        return res.f[ids[0]] if len(set(ids)) == 1 else None

    def where(verb, tok):
        for l in lines:
            u = l.text.upper()
            if verb in u and tok in u:
                return l
        for l in lines:
            if tok in l.text.upper():
                return l
        return lines[0] if lines else None

    def add(gap, sev, msg, verb, tok, fields=()):
        key = (gap, msg)
        if key in seen:
            return
        seen.add(key)
        l = where(verb, tok)
        out.append({"gap_id": gap, "severity": sev, "message": msg, "fields": list(fields),
                    "file": l.file if l else None, "line": l.no if l else None})

    for verb, toks in stmts:
        if verb == "MOVE" and "TO" in toks:
            k = toks.index("TO")
            src, tgts = toks[:k], [t for t in toks[k + 1:] if t != "ROUNDED"]
            if len(src) != 1:
                continue
            s_tok = src[0]
            sf = one(s_tok)
            for tn in tgts:
                tf = one(tn)
                if not tf:
                    continue
                st, tt = _ty(sf), _ty(tf)
                if sf is None and s_tok.isdigit() and tt["kind"] == "decimal":
                    if len(s_tok) > _idig(tt):
                        add("G-TRUNCATE", "high", f"literal {s_tok} has more integer digits than {tf['name']} PIC {tf['pic']}: high-order digits are dropped", verb, tn, [tf["name"]])
                    continue
                if not st:
                    continue
                if st["kind"] == "group" and tt["kind"] == "group":
                    add("G-GROUPMOVE", "medium", f"group MOVE {sf['name']} -> {tf['name']} copies raw bytes, not field by field", verb, tn, [sf["name"], tf["name"]])
                elif st["kind"] == "decimal" and tt["kind"] == "decimal":
                    if _idig(st) > _idig(tt):
                        add("G-TRUNCATE", "high", f"MOVE {sf['name']} (PIC {sf['pic']}) -> {tf['name']} (PIC {tf['pic']}): high-order digits silently truncated", verb, tn, [sf["name"], tf["name"]])
                    if (st["scale"] or 0) > (tt["scale"] or 0):
                        add("G-TRUNCATE", "medium", f"MOVE {sf['name']} -> {tf['name']}: {st['scale']} -> {tt['scale']} decimals, fraction truncated not rounded", verb, tn, [sf["name"], tf["name"]])
                    if st["signed"] and not tt["signed"]:
                        add("G-SIGN", "high", f"MOVE {sf['name']} (signed) -> {tf['name']} (unsigned): sign is lost, magnitude stored", verb, tn, [sf["name"], tf["name"]])
                elif {st["kind"], tt["kind"]} == {"decimal", "alphanumeric"}:
                    add("G-NUMALPHA", "medium", f"MOVE between numeric {sf['name'] if st['kind']=='decimal' else tf['name']} and alphanumeric field: implicit conversion/padding rules apply", verb, tn, [sf["name"], tf["name"]])
                elif st["kind"] == "alphanumeric" and tt["kind"] == "alphanumeric" and (st["length"] or 0) > (tt["length"] or 0):
                    add("G-TRUNCATE", "medium", f"MOVE {sf['name']} (X({st['length']})) -> {tf['name']} (X({tt['length']})): right-truncated", verb, tn, [sf["name"], tf["name"]])
        elif verb in ("ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "COMPUTE"):
            if verb == "COMPUTE":
                tg = toks[:toks.index("=")] if "=" in toks else []
            else:
                kw = {"ADD": "TO", "SUBTRACT": "FROM", "MULTIPLY": "BY", "DIVIDE": "INTO"}[verb]
                if "GIVING" in toks:
                    tg = toks[toks.index("GIVING") + 1:]
                elif kw in toks:
                    tg = toks[toks.index(kw) + 1:]
                else:
                    tg = []
            sized = "SIZE" in toks
            rounded = "ROUNDED" in toks
            for tn in tg:
                tf = one(tn)
                if not tf or _ty(tf)["kind"] != "decimal":
                    continue
                t = _ty(tf)
                if not sized:
                    add("G-OVERFLOW", "high" if verb in ("MULTIPLY", "COMPUTE") else "medium",
                        f"{verb} into {tf['name']} PIC {tf['pic']} ({t['digits']} digits) without ON SIZE ERROR: overflow is silently truncated (BigDecimal would keep all digits)", verb, tn, [tf["name"]])
                if rounded:
                    add("G-ROUNDING", "medium", f"{verb} ... {tf['name']} ROUNDED: COBOL rounds half away from zero; Java defaults (HALF_EVEN / truncation) differ", verb, tn, [tf["name"]])
                elif verb in ("COMPUTE", "DIVIDE", "MULTIPLY"):
                    add("G-TRUNCATE", "medium", f"{verb} into {tf['name']} ({t['scale']} decimals) without ROUNDED: extra decimals truncated, not rounded", verb, tn, [tf["name"]])
            if verb == "DIVIDE" and not sized:
                add("G-DIVZERO", "medium", "DIVIDE without ON SIZE ERROR: divide-by-zero leaves target unchanged in COBOL (Java throws)", verb, toks[0] if toks else "", [])
    return out


def paragraph_facts(name, lines, res, para_names):
    raw = " ".join(l.text.strip() for l in lines)
    flags, calls, performs, gotos, cics_verbs = set(), [], [], [], []
    # EXEC blocks first (they hide verbs like READ/WRITE from the COBOL scan)
    extra_r, extra_w = set(), set()
    for blk in re.findall(r"EXEC\s+(CICS|SQL)\b(.*?)END-EXEC", raw, re.I | re.S):
        kind, body = blk[0].upper(), blk[1].upper()
        if kind == "SQL":
            flags.add("sql")
            for h in re.findall(r":([A-Z0-9-]+)", body):
                extra_r.update(res.look(h))
            continue
        flags.add("cics")
        v = re.match(r"\s*([A-Z]+)", body)
        cics_verbs.append(v.group(1) if v else "?")
        for opt, q, arg in re.findall(r"([A-Z]+)\s*\(\s*(['\"]?)([A-Z0-9-]+)['\"]?\s*\)", body):
            if opt == "PROGRAM":
                calls.append({"target": arg, "dynamic": not q})
            elif not q:
                (extra_w if opt in ("INTO", "SET") else extra_r).update(res.look(arg))
    raw = re.sub(r"EXEC\s+(CICS|SQL)\b.*?END-EXEC", " ", raw, flags=re.I | re.S)
    for m in re.finditer(r"\bCALL\s+(?:'([^']+)'|\"([^\"]+)\"|(" + NAME + "))", raw, re.I):
        t = m.group(1) or m.group(2)
        calls.append({"target": t.upper() if t else m.group(3).upper(), "dynamic": not t})
        flags.add("call")
    text = re.sub(r"'[^']*'|\"[^\"]*\"", " ", raw)
    stmts = split_statements(text)
    for verb, toks in stmts:
        if verb == "PERFORM" and toks:
            t0 = toks[0]
            nxt = toks[1] if len(toks) > 1 else ""
            if t0 not in ("UNTIL", "VARYING", "WITH", "TEST", "FOREVER") and nxt != "TIMES" and t0 in para_names:
                end = None
                if nxt in ("THRU", "THROUGH") and len(toks) > 2:
                    end = toks[2]
                performs.append((t0, end))
        elif verb == "GO" and "TO" in toks:
            gotos.append(toks[toks.index("TO") + 1] if len(toks) > toks.index("TO") + 1 else "?")
            flags.add("goto")
        elif verb == "ALTER":
            flags.add("alter")
        elif verb in FILE_VERBS:
            flags.add("file_io")
        elif verb in ("STRING", "UNSTRING", "INSPECT"):
            flags.add("string_ops")
        elif verb in ("DISPLAY", "ACCEPT"):
            flags.add("console_io")
    lit_moves = [(v.upper(), l.upper()) for l, v in re.findall(r"MOVE\s+'([^']+)'\s+TO\s+(" + NAME + ")", re.sub(r"\s+", " ", " ".join(l.text for l in lines)), re.I)]
    reads, writes = analyse_statements(stmts, res)
    reads |= extra_r
    writes |= extra_w
    last = stmts[-1][0] if stmts else None
    terminal = last in TERMINAL or (last == "EXIT" and stmts and "PROGRAM" in stmts[-1][1]) or \
        (last == "GO" and not re.search(r"\bIF\b", text.upper().split("GO")[-2][-60:] if "GO" in text.upper() else "")) \
        or (last == "RETURN" and "cics" in flags) or any(v in ("RETURN", "XCTL") for v in cics_verbs[-1:])
    return {"reads": sorted(reads), "writes": sorted(writes), "performs": performs, "gotos": gotos,
            "calls": calls, "lit_moves": lit_moves, "hazards": find_hazards(stmts, res, lines), "flags": flags, "cics_verbs": cics_verbs, "terminal": bool(terminal),
            "stmt_count": len(stmts)}


def split_paragraphs(proc_lines):
    """-> list of dicts {name, kind, lines}. Statements before the first header go to __START__."""
    paras, cur, at_start = [], {"name": "__START__", "kind": "paragraph", "lines": []}, True
    for ln in proc_lines:
        t = ln.text
        m = re.fullmatch(rf"\s*({NAME})(\s+SECTION(?:\s+\d+)?)?\s*\.\s*", t, re.I)
        indent = len(t) - len(t.lstrip())
        if m and at_start and m.group(1).upper() not in NOT_PARAGRAPHS \
                and not m.group(1).upper().startswith("END-") and indent <= 4:
            if cur["lines"] or cur["name"] != "__START__":
                paras.append(cur)
            cur = {"name": m.group(1).upper(), "kind": "section" if m.group(2) else "paragraph",
                   "lines": [ln]}
            at_start = True
            continue
        cur["lines"].append(ln)
        at_start = t.rstrip().endswith(".")
    paras.append(cur)
    return paras


def analyse_program(lines, header_comments, copybooks_used):
    """lines: expanded Line list for ONE program."""
    div, sect = None, None
    buckets = {"ident": [], "env": [], "data": [], "proc": []}
    program_id, proc_using = None, None
    for ln in lines:
        m = re.match(r"\s*(IDENTIFICATION|ID|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION\b(.*)", ln.text, re.I)
        if m:
            div = {"IDENTIFICATION": "ident", "ID": "ident", "ENVIRONMENT": "env",
                   "DATA": "data", "PROCEDURE": "proc"}[m.group(1).upper()]
            if div == "proc":
                proc_using = m.group(2).strip(" .") or None
            buckets[div].append(ln) if div != "proc" else None
            continue
        if div:
            buckets[div].append(ln)
    for ln in buckets["ident"]:
        m = re.search(r"PROGRAM-ID\.?\s+(" + NAME + ")", ln.text, re.I)
        if m:
            program_id = m.group(1).upper()
    files = []
    env_text = " ".join(l.text.strip() for l in buckets["env"])
    for m in re.finditer(r"SELECT\s+(?:OPTIONAL\s+)?(" + NAME + r")\s+ASSIGN\s+(?:TO\s+)?(\S+)(.*?)(?=SELECT\s|$)", env_text, re.I):
        org = re.search(r"ORGANIZATION\s+(?:IS\s+)?(\w+)", m.group(3), re.I)
        files.append({"name": m.group(1).upper(), "assign": m.group(2).strip(". "),
                      "organization": org.group(1).upper() if org else "SEQUENTIAL"})
    fields, conds = parse_data(buckets["data"])
    res = Resolver(fields, conds)
    paras = split_paragraphs(buckets["proc"])
    names = {p["name"] for p in paras}
    facts = {p["name"]: paragraph_facts(p["name"], p["lines"], res, names) for p in paras}
    order = [p["name"] for p in paras]
    units, sect_of = [], {}
    cur_sec = None
    for p in paras:
        if p["kind"] == "section":
            cur_sec = p["name"]
        sect_of[p["name"]] = cur_sec
    for i, p in enumerate(paras):
        f = facts[p["name"]]
        perf = []
        for a, b in f["performs"]:
            if b and b in order and a in order:
                perf += order[order.index(a):order.index(b) + 1]
            else:
                perf.append(a)
        nxt = order[i + 1] if i + 1 < len(order) and not f["terminal"] and p["kind"] == "paragraph" else None
        ls = p["lines"]
        units.append({
            "unit_id": p["name"], "kind": p["kind"], "program": program_id,
            "span": {"file": ls[0].file if ls else "", "start_line": ls[0].no if ls else 0,
                     "end_line": ls[-1].no if ls else 0},
            "reads": f["reads"], "writes": f["writes"], "performs": list(dict.fromkeys(perf)),
            "calls": [list(t) for t in dict.fromkeys((c["target"], c["dynamic"]) for c in f["calls"])],
            "gotos": f["gotos"], "falls_through_to": nxt, "section": sect_of[p["name"]],
            "unsupported": sorted(f["flags"] & (HARD_UNSUPPORTED | {"string_ops", "call", "console_io"})),
            "loc": len(ls), "stmt_count": f["stmt_count"], "summary": None,
            "hazards": list(f["hazards"]),
        })
        uh, tail = units[-1]["hazards"], (ls[-1] if ls else None)
        sp = units[-1]["span"]
        if f["gotos"]:
            uh.append({"gap_id": "G-GOTO", "severity": "high", "message": "GO TO " + ",".join(f["gotos"][:3]) + ": unstructured control flow, cannot map to a function cleanly", "fields": [], "file": sp["file"], "line": sp["start_line"]})
        if nxt:
            uh.append({"gap_id": "G-FALLTHROUGH", "severity": "low", "message": f"control falls through into {nxt}: translating alone changes behaviour unless the caller PERFORMs THRU", "fields": [], "file": sp["file"], "line": sp["end_line"]})
        packed = sorted({res.f[i]["name"] for i in f["reads"] + f["writes"] if res.f[i]["usage"] in ("COMP-3", "PACKED-DECIMAL", "COMP", "BINARY", "COMPUTATIONAL")})
        if packed:
            uh.append({"gap_id": "G-PACKED", "severity": "low", "message": "binary/packed (COMP/COMP-3) fields: " + ",".join(packed[:4]) + " - same value semantics, different byte layout", "fields": packed[:6], "file": sp["file"], "line": sp["start_line"]})
    # a SECTION owns the paragraphs that follow it
    by_id = {u["unit_id"]: u for u in units}
    for u in units:
        if u["kind"] == "section":
            for c in units:
                if c["kind"] == "paragraph" and c["section"] == u["unit_id"]:
                    u["hazards"] += [h for h in c["hazards"] if h not in u["hazards"]]
                    for k in ("reads", "writes", "performs", "calls", "unsupported"):
                        u[k] = sorted(set(u[k]) | set(c[k])) if k != "calls" else u[k] + [x for x in c[k] if x not in u[k]]
                    u["performs"] = [x for x in u["performs"] if x != u["unit_id"]]
    for u in units:
        u["risk"] = sum(SEV_W[h["severity"]] for h in u["hazards"])
    redef = {f["name"] for f in fields if f["redefines"]}
    if redef:
        for u in units:
            touched = {x.split(".")[-1] for x in u["reads"] + u["writes"]}
            if touched & (redef | {f["redefines"] for f in fields if f["redefines"]}):
                u["unsupported"] = sorted(set(u["unsupported"]) | {"redefines"})
    desc = next((h for h in header_comments if re.search(r"FUNCTION|PURPOSE|DESCRIPTION", h, re.I)), None)
    proc_lines = buckets["proc"]
    var_lits = {}
    for f in facts.values():
        for v, lit in f["lit_moves"]:
            var_lits.setdefault(v, [])
            if lit not in var_lits[v]:
                var_lits[v].append(lit)
    prog = {"program_id": program_id, "description": desc, "copybooks": sorted(set(copybooks_used)),
            "files": files, "using": proc_using,
            "flags": sorted({fl for u in units for fl in u["unsupported"]}),
            "cics_verbs": sorted({v for f in facts.values() for v in f["cics_verbs"]}),
            "var_literals": var_lits,
            "unit_count": len(units), "field_count": len(fields),
            "proc_lines": len(proc_lines)}
    return prog, units, fields
