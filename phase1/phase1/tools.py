"""Agent tools. Exploration tools read the static-analysis index + COBOL source (read-only);
write tools are confined to staging/; KB tools go through `phase0 query`."""
import json
import subprocess

MAX_OUT = 9500


def clip(s, n=MAX_OUT):
    return s if len(s) <= n else s[:n] + f"\n...[truncated {len(s) - n} chars; narrow your query]"


def J(o):
    return json.dumps(o, separators=(",", ":"))


def _fn(name, desc, props=None, required=()):
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": props or {}, "required": list(required)}}}


S, I = {"type": "string"}, {"type": "integer"}
LST = {"type": "array", "items": S}

EXPLORE = [
    _fn("overview", "Architecture overview of the whole COBOL repo: programs, entry points, "
        "migration layers (leaves first), call graph, shared copybooks, unsupported-construct prevalence."),
    _fn("list_programs", "Page through programs (id, file, loc, flags).", {"offset": I, "limit": I}),
    _fn("program_info", "One program: description, files, copybooks, calls, flags, and its units.",
        {"program_id": S}, ["program_id"]),
    _fn("outline", "Units (sections/paragraphs) of a source file with line ranges and what they PERFORM.",
        {"file": S}, ["file"]),
    _fn("search", "Regex search over COBOL source (comments skipped). Use for names, literals, verbs.",
        {"pattern": S, "glob": {"type": "string", "description": "e.g. '*.cbl'"},
         "context": {"type": "integer", "description": "lines of context"}, "max_results": I}, ["pattern"]),
    _fn("read_lines", "Read a line range of a source file (max 200 lines).",
        {"file": S, "start": I, "end": I}, ["file", "start", "end"]),
    _fn("unit_info", "Structured facts for a unit: span, reads, writes, performs, callers, calls, "
        "fall-through, unsupported constructs, in_scope flag.", {"unit_id": S}, ["unit_id"]),
    _fn("unit_source", "COBOL source text of a unit.", {"unit_id": S}, ["unit_id"]),
    _fn("unit_fields", "Data dictionary entries (PIC, usage, decimal digits/scale/sign) for fields a unit reads/writes.",
        {"unit_id": S}, ["unit_id"]),
    _fn("data_flow", "Which units read/write a field name (impact analysis).", {"field": S}, ["field"]),
    _fn("context_pack", "ONE call that returns everything needed to translate a unit: source, field type table, "
        "semantic hazards with fixes, callee summaries, data producers/consumers, module mates. Budgeted.",
        {"unit_id": S, "budget": I}, ["unit_id"]),
    _fn("program_pack", "Program-level context: structure, paragraph order, risk, top hazards.",
        {"program_id": S, "budget": I}, ["program_id"]),
    _fn("hazards", "Static semantic-hazard scan for a unit (truncation, overflow, rounding, sign, group MOVE, GO TO...).",
        {"unit_id": S}, ["unit_id"]),
    _fn("clusters", "Candidate modules: units that share state/calls (optionally for one program), ranked by risk.",
        {"program": S}),
    _fn("notes", "Persistent scratchpad that stays in your context even when old messages are dropped. "
        "Write decisions, field-type choices, naming conventions. Omit `append` to read.",
        {"append": S}),
]
KB = [
    _fn("rules_for", "Mapping rules (required target patterns) for COBOL constructs.", {"constructs": LST}, ["constructs"]),
    _fn("gaps_for", "Semantic gaps COBOL vs target (truncation, rounding, sign...).", {"topics": LST}, ["topics"]),
]
FILES = [
    _fn("list_files", "List files in the staging project."),
    _fn("read_file", "Read a staging project file.", {"path": S}, ["path"]),
    _fn("write_file", "Create/overwrite a staging project file.", {"path": S, "content": S}, ["path", "content"]),
    _fn("build", "Run the toolchain build in staging."),
    _fn("submit", "Snapshot staging and have the independent checker verify it; returns the report.",
        {"driver_cmd": {"type": "array", "items": S, "description": "optional; how to run the program from project root"},
         "notes": S}),
]
PLAN = [_fn("set_plan", "Finish the survey: ordered units to migrate now (leaves first) and units skipped with reasons.",
            {"units": {"type": "array", "items": {"type": "object", "properties": {"unit_id": S, "reason": S}}},
             "skipped": {"type": "array", "items": {"type": "object", "properties": {"unit_id": S, "reason": S}}}},
            ["units"])]

SURVEY_TOOLS = EXPLORE + KB + PLAN
TRANSLATE_TOOLS = EXPLORE + KB + FILES


class ToolBox:
    def __init__(self, ws, index, toolchain=None, unit_ids=(), regression_ids=(), st=None):
        self.ws, self.ix, self.tc = ws, index, toolchain or {}
        self.unit_ids, self.regression_ids = list(unit_ids), list(regression_ids)
        self.st = st or {"attempts": 0, "max": 5, "green": False}
        self.notes_path = ws.root / "phase1" / "notes.md"
        self.plan = None

    def call(self, name, args):
        fn = getattr(self, "t_" + name, None)
        if fn is None:
            return f"ERROR: unknown tool {name}"
        uid = args.get("unit_id")
        if uid in self.ix.progs and name in ("context_pack", "unit_info", "unit_source", "unit_fields", "hazards"):
            ids = [u["unit_id"] for u in self.ix.d["units"] if u["program"] == uid]
            return (f"ERROR: '{uid}' is a PROGRAM, not a unit. Use program_pack('{uid}') for the whole program, "
                    f"or pass one of its unit ids: {ids[:25]}")
        try:
            import inspect
            ok = inspect.signature(fn).parameters
            return clip(str(fn(**{k: v for k, v in args.items() if k in ok})))  # ignore stray args from small models
        except TypeError as e:
            return f"ERROR: bad arguments: {e}"
        except Exception as e:
            return f"ERROR: {type(e).__name__}: {e}"

    # --- exploration ---
    def t_overview(self): return self.ix.overview()
    def t_list_programs(self, offset=0, limit=30): return J(self.ix.list_programs(offset, limit))
    def t_program_info(self, program_id): return J(self.ix.program(program_id.upper()))
    def t_outline(self, file): return J(self.ix.outline(file))
    def t_search(self, pattern, glob="*", context=0, max_results=25):
        return self.ix.search(pattern, glob, context, min(max_results, 60))
    def t_read_lines(self, file, start, end): return self.ix.read_lines(file, start, end)
    def t_unit_info(self, unit_id): return J(self.ix.unit_brief(unit_id))
    def t_unit_source(self, unit_id): return self.ix.unit_source(unit_id)
    def t_context_pack(self, unit_id, budget=6000): return self.ix.context_pack(unit_id, min(budget, 9000))
    def t_program_pack(self, program_id, budget=7000): return self.ix.program_pack(program_id.upper(), min(budget, 9000))
    def t_hazards(self, unit_id): return J(self.ix.hazards(unit_id))
    def t_clusters(self, program=None): return J(self.ix.clusters(program))
    def t_unit_fields(self, unit_id): return J(self.ix.fields_of(unit_id))
    def t_data_flow(self, field): return J(self.ix.data_flow(field))

    def t_notes(self, append=None):
        self.notes_path.parent.mkdir(exist_ok=True)
        if append:
            with open(self.notes_path, "a") as f:
                f.write(append.strip() + "\n")
            return "noted"
        return self.read_notes() or "(empty)"

    def read_notes(self, limit=3000):
        t = self.notes_path.read_text() if self.notes_path.exists() else ""
        return t[-limit:]

    # --- KB ---
    def t_rules_for(self, constructs): return J(self.ws.kb("rules_for", ",".join(constructs)))
    def t_gaps_for(self, topics): return J(self.ws.kb("gaps_for", ",".join(topics)))

    # --- plan ---
    def t_set_plan(self, units, skipped=()):
        known = self.ix.units
        bad = [u["unit_id"] for u in units if u["unit_id"] not in known]
        if bad:
            return f"ERROR: unknown unit ids {bad[:5]}; use ids from unit_info/outline"
        self.plan = {"units": units, "skipped": list(skipped)}
        p = self.ws.root / "phase1" / "plan.json"
        p.parent.mkdir(exist_ok=True)
        p.write_text(json.dumps(self.plan, indent=1))
        return f"plan saved: {len(units)} units, {len(skipped)} skipped"

    # --- files ---
    def _path(self, rel):
        p = (self.ws.staging / rel).resolve()
        if not str(p).startswith(str(self.ws.staging.resolve())):
            raise ValueError("path escapes staging/")
        return p

    def t_list_files(self):
        b = self.ws.staging
        return "\n".join(sorted(str(p.relative_to(b)) for p in b.rglob("*") if p.is_file()))

    def t_read_file(self, path):
        p = self._path(path)
        if not p.exists():  # fall back to the read-only COBOL source tree
            src = (self.ws.root / "source" / path).resolve()
            if src.exists() and str(src).startswith(str((self.ws.root / "source").resolve())):
                return src.read_text(errors="replace")
        return p.read_text()

    def t_write_file(self, path, content):
        rt = (self.tc.get("runtime_dir") or "").strip("/")
        if rt and (path.strip("/") + "/").startswith(rt + "/"):
            return "ERROR: the runtime library is read-only; use it unchanged."
        p = self._path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"wrote {len(content)} chars to {path}"

    def t_build(self):
        r = subprocess.run(self.tc["build_cmd"], cwd=self.ws.staging, capture_output=True, text=True, timeout=300)
        out = (r.stdout + r.stderr).strip()
        return f"exit={r.returncode}\n{out}" if out else f"exit={r.returncode} (ok)"

    def t_submit(self, driver_cmd=None, notes=None):
        driver_cmd = driver_cmd or ["java", "-cp", "."]
        if self.st["attempts"] >= self.st["max"]:
            return "ERROR: attempt budget exhausted."
        self.st["attempts"] += 1
        retries = self.ws.config["budgets"].get("check_retries_on_error", 2)
        for _ in range(1 + retries):
            sid = self.ws.submit(self.unit_ids, self.regression_ids, driver_cmd, self.st["attempts"], notes)
            report, err = self.ws.check(sid)
            if report is None:
                report = {"verdict": "error", "summary": err, "findings": [], "units": []}
            if report["verdict"] != "error":
                break
        self.st["last_report"], self.st["sid"] = report, sid
        self.st["green"] = report["verdict"] == "green"
        return format_report(sid, report) + f"\nAttempts left for this unit: {self.st['max'] - self.st['attempts']}"


def format_report(sid, rep):
    lines = [f"Submission {sid}: verdict={rep['verdict'].upper()}", rep.get("summary", "")]
    for f in rep.get("findings", []):
        if f.get("severity") == "info":
            continue
        loc = f.get("location")
        lines.append(f"- [{f['severity']}/{f['category']}] {f['message']}" + (f" ({loc['file']}:{loc['line']})" if loc else ""))
        if f.get("kb_refs"):
            lines.append(f"  relevant KB: {', '.join(f['kb_refs'])}")
        ce = f.get("counterexample")
        if ce:
            lines.append(f"  counterexample: inputs={ce['inputs']} expected={ce['expected']} actual={ce['actual']}")
        if f.get("reproduce"):
            lines.append(f"  reproduce: {f['reproduce']}")
    return "\n".join(lines)
