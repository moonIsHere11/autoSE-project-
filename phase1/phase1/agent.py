"""Phase 1 main loop.
  analyse (static, no LLM) -> survey agent decides WHAT to migrate (set_plan)
  -> per unit: translate agent loops with Phase 2 feedback until green or budget exhausted."""
import json
from pathlib import Path

from .cobol.repo import Index, analyse_repo, unit_graph_order
from .context import compact
from .llm import GroqClient, LLMError
from .tools import SURVEY_TOOLS, TRANSLATE_TOOLS, ToolBox

SURVEY_SYS = """You are the planning agent of a COBOL-to-{lang} migration harness. Your job: understand the COBOL
codebase and decide which units (sections/paragraphs) to migrate now, and in what order.
Iteration-1 subset that CAN be migrated: numeric PIC fields, MOVE, ADD/SUBTRACT/MULTIPLY/COMPUTE, IF/EVALUATE, PERFORM,
record structures, WORKING-STORAGE. NOT migratable yet: file I/O, REDEFINES, GO TO/ALTER, CICS, SQL.
Prefer migrating whole clusters (modules sharing state) together, lowest-risk leaves first, and skip units whose
hazards are structural (GO TO) or unsupported. Method: read the overview, drill into programs/units with the exploration tools (never read whole files),
save key findings with `notes`, then call `set_plan` with units ordered leaves-first (callees before callers)
and the skipped units with reasons. Use only unit_ids the tools returned. Be efficient: few, targeted calls.
{scope}"""

DRIVER_IFACE = """- ALL COBOL numeric behaviour (decimals, truncation, ROUNDED, sign) must use the runtime library in `{rt}` UNCHANGED.
- Expose the execution interface: a driver reads {{"unit_id","state"}} JSON on stdin and writes {{"unit_id","status","message","state"}} on stdout.
  A driver template is in the project: add your unit to its dispatch table. Values are canonical strings (decimals with exact scale)."""

CHECKER_JAVA = """
Checker conventions (the independent verifier derives everything from these; deviations make units unverifiable):
- One public class per COBOL program, named PascalCase(PROGRAM-ID) (CALC-FEE -> CalcFee), with `public static void main`.
  Running main must reproduce the COBOL program's observable behaviour exactly: stdout bytes, files written, exit code.
- One method per paragraph, named camelCase(paragraph) (CALC-FEE -> calcFee), same control flow (PERFORM = method call).
- One field per data item, camelCase(name). Money/decimals: use the cobolrt runtime (CobolDecimal) or scaled long arithmetic
  with explicit PIC truncation -- NEVER float/double. No clock/network/random, no hard-coded expected outputs, no swallowed exceptions.
- Put the code in `src/main/java/app/<ClassName>.java` (package `app`). Everything you need is in this prompt: do NOT search for
  runtime libraries or templates -- there are none in the project. Plain `long` arithmetic scaled by 10^scale (as the PIC dictates) with
  explicit truncation/sign handling is fine; `cobolrt` is optional and, if you import it, is provided by the checker.
- Reproduce DISPLAY output byte for byte: numerics zero-padded to PIC width, signed fields print a leading +/- as GnuCOBOL does."""

TRANSLATE_SYS = """You are a COBOL-to-{lang} {ver} migration agent translating ONE {granule} at a time.
- The first message contains a context pack (source, field types, semantic HAZARDS with fixes, callee/data dependences).
  Every listed hazard must be handled explicitly in your code. Use search/read_lines/unit_info only for what is missing.
  Consult rules_for / gaps_for for the hazard gap ids.
{conventions}
- Workflow: inspect -> write_file -> build -> fix errors -> submit. Only the checker's report decides correctness.
- On a RED report, read findings/counterexamples and the cited KB refs, fix, resubmit.
- Record decisions (type mappings, naming) with `notes`; older messages get dropped but notes persist. Be concise.

Your notes so far:
{notes}"""


MINIMAL_TOOLS = {"search", "read_lines", "unit_source", "notes", "rules_for", "gaps_for", "list_files", "read_file",
                 "write_file", "build", "submit", "context_pack"}


def toolset(cfg, tools):
    """Small/rate-limited models: ship fewer tool schemas (each costs prompt tokens on every call)."""
    if cfg.get("phase1", {}).get("toolset") == "minimal":
        return [t for t in tools if t["function"]["name"] in MINIMAL_TOOLS]
    return tools


def ensure_analysis(ws, force=False):
    out = ws.root / "phase1"
    out.mkdir(exist_ok=True)
    ix_path = out / "index.json"
    if force or not ix_path.exists():
        data = analyse_repo(ws.root / "source")
        ix_path.write_text(json.dumps(data))
        (out / "architecture.md").write_text(Index(data, ws.root / "source").overview())
    return Index.load(ix_path, ws.root / "source")


def program_plan(ix):
    """Program-granularity plan for the whole-program checker: leaves-first by call layer; skip CICS/SQL programs."""
    keep, skip = [], []
    for ly in ix.d["layers"]:
        for pid in ly["programs"]:
            p = ix.progs[pid]
            bad = sorted(set(p["flags"]) & {"cics", "sql", "alter"})
            (skip if bad else keep).append({"unit_id": pid, "reason": ",".join(bad) or f"{p['loc']} loc, risk {sum(u['risk'] for u in ix.d['units'] if u['program'] == pid)}"})
    return {"units": keep, "skipped": skip}


def collapse_to_programs(ix, plan):
    seen, items = set(), []
    for it in plan["units"]:
        pid = ix.units[it["unit_id"]]["program"] if it["unit_id"] in ix.units else it["unit_id"]
        if pid not in seen and pid in ix.progs:
            seen.add(pid)
            items.append({"unit_id": pid, "reason": it.get("reason", "")})
    return {"units": items, "skipped": plan["skipped"]}


def heuristic_plan(ix):
    """Fallback without an LLM: in-scope units; clusters kept together, leaves first inside each."""
    leaf = {u: i for i, u in enumerate(unit_graph_order(ix.d))}
    cl_rank = {}
    for c in ix.d["clusters"]:
        cl_rank[c["cluster_id"]] = min(leaf[m] for m in c["units"])
    order = sorted(leaf, key=lambda u: (cl_rank.get(ix.units[u].get("cluster"), 0), leaf[u]))
    keep, skip = [], []
    for uid in order:
        u = ix.unit_brief(uid)
        if u["kind"] == "section" or not u["stmt_count"]:
            continue
        (keep if u["in_scope"] else skip).append({"unit_id": uid, "reason": ",".join(u["unsupported"]) or "ok"})
    return {"units": keep, "skipped": skip}


def _small_source(ix, pid, max_lines=220):
    """Small programs fit in context: hand the whole COBOL text over instead of making the model hunt for it."""
    p = ix.progs[pid]
    if p["loc"] > max_lines:
        return "\n\nThe program is large: read it paragraph by paragraph with unit_source / read_lines."
    return "\n\n## Full COBOL source (" + p["file"] + ")\n" + ix.read_lines(p["file"], 1, max_lines, max_lines=max_lines)


class Loop:
    """Generic tool-calling loop with context compaction and pinned notes."""

    def __init__(self, llm, tb, system_fn, tools, ws, unit_id=None, log=print, budget=36000):
        self.llm, self.tb, self.system_fn, self.tools = llm, tb, system_fn, tools
        self.ws, self.unit_id, self.log, self.budget = ws, unit_id, log, budget
        self.keep_last = 5 if budget < 20000 else 8

    def run(self, user_msg, done, max_steps=40):
        msgs = [{"role": "system", "content": self.system_fn()}, {"role": "user", "content": user_msg}]
        nudged, bad_calls = 0, 0
        for _ in range(max_steps):
            msgs[0]["content"] = self.system_fn()  # re-pin latest notes
            saved = compact(msgs, self.budget, self.keep_last)
            if saved:
                self.ws.emit("context_compacted", unit_id=self.unit_id, chars_saved=saved)
            try:
                msg, usage = self.llm.chat(msgs, self.tools)
            except LLMError as e:
                if "HTTP 400" in str(e) and any(k in str(e) for k in ("tool_use_failed", "Parsing failed", "failed_generation")) and bad_calls < 6:  # model emitted malformed tool JSON: tell it, retry
                    bad_calls += 1
                    msgs.append({"role": "user", "content": "Your last tool call was malformed JSON and was rejected. "
                                 "Call the tool again with valid JSON arguments (use {} when there are none)."})
                    self.log(f"  [{self.unit_id or 'survey'}] malformed tool call, retrying ({bad_calls})")
                    continue
                self.log(f"[phase1] LLM error: {e}")
                return f"llm_error: {e}"
            self.ws.emit("llm_usage", unit_id=self.unit_id, model=self.llm.model,
                         tokens_in=usage.get("prompt_tokens"), tokens_out=usage.get("completion_tokens"))
            calls = msg.get("tool_calls") or []
            entry = {"role": "assistant", "content": msg.get("content") or ""}
            if calls:
                entry["tool_calls"] = calls
            msgs.append(entry)
            if not calls:
                self.log(f"  [{self.unit_id or 'survey'}] text reply: {(msg.get('content') or '')[:160]!r}")
                if nudged >= 3:
                    return "gave_up"
                nudged += 1
                msgs.append({"role": "user", "content": "You must act through tool calls. Next steps: write_file the complete "
                             "Java source, then build, then fix errors, then submit. Do not reply with plain text."})
                continue
            for c in calls:
                try:
                    args = json.loads(c["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                out = self.tb.call(c["function"]["name"], args)
                self.log(f"  [{self.unit_id or 'survey'}] {c['function']['name']}({', '.join(f'{k}={str(v)[:30]}' for k, v in args.items())}) -> {out[:80]!r}")
                msgs.append({"role": "tool", "tool_call_id": c["id"], "content": out})
            if done():
                return "done"
        return "max_steps"


def run(ws, wanted=None, max_steps=40, verbose=True, skip_survey=False):
    cfg = ws.config
    log = print if verbose else (lambda *a, **k: None)
    tc = ws.kb("toolchain")
    ws.seed_staging(tc["runtime_dir"])
    ix = ensure_analysis(ws)
    llm = GroqClient(model=cfg.get("phase1", {}).get("model"))
    max_attempts = cfg["budgets"]["attempts_per_unit"]
    scope = f"Only consider these units: {wanted}." if wanted else ""
    gran = cfg.get("phase1", {}).get("granularity", "program")

    # ---- stage A: survey -> plan ----
    plan_path = ws.root / "phase1" / "plan.json"
    if wanted:
        plan = {"units": [{"unit_id": u, "reason": "requested"} for u in wanted], "skipped": []}
    elif plan_path.exists():
        plan = json.loads(plan_path.read_text())
    else:
        tb = ToolBox(ws, ix, tc)
        sys_fn = lambda: SURVEY_SYS.format(lang=tc["language"], scope=scope) + "\n\nNotes:\n" + tb.read_notes()
        res = Loop(llm, tb, sys_fn, SURVEY_TOOLS, ws, log=log, budget=cfg.get('phase1', {}).get('context_budget', 36000)).run(
            "Overview of the repo (call `overview` for the full version):\n" + ix.overview()[:2500]
            + "\nSurvey, then call set_plan.", lambda: tb.plan is not None, max_steps)
        plan = tb.plan
        if plan is None:
            log(f"[phase1] survey ended ({res}) without a plan; using heuristic plan")
            plan = heuristic_plan(ix)
    if gran == "program" and not wanted:
        plan = collapse_to_programs(ix, plan) if plan["units"] and plan["units"][0]["unit_id"] not in ix.progs else plan
        if not plan["units"]:
            plan = program_plan(ix)
    ws.emit("plan_created", units=[u["unit_id"] for u in plan["units"]], skipped=len(plan["skipped"]))
    log(f"[phase1] plan: {[u['unit_id'] for u in plan['units']]}  (skipped {len(plan['skipped'])})")

    # ---- stage B: translate each unit ----
    accepted, failed = [], []
    for item in plan["units"]:
        uid = item["unit_id"]
        state = ws.run_state()["units"].get(uid, {})
        if state.get("status") in ("accepted", "failed"):
            continue
        ws.emit("unit_started", unit_id=uid)
        st = {"attempts": state.get("attempts", 0), "max": max_attempts, "green": False}
        tb = ToolBox(ws, ix, tc, [uid], accepted, st)
        sys_fn = lambda: TRANSLATE_SYS.format(lang=tc["language"], ver=tc["version"], rt=tc["runtime_dir"],
                                              granule="whole COBOL program" if uid in ix.progs else "unit",
                                              conventions=CHECKER_JAVA if tc["language"] == "java" else DRIVER_IFACE.format(rt=tc["runtime_dir"]),
                                              notes=tb.read_notes() or "(none)")
        Loop(llm, tb, sys_fn, toolset(cfg, TRANSLATE_TOOLS), ws, unit_id=uid, log=log, budget=cfg.get('phase1', {}).get('context_budget', 36000)).run(
            f"Translate unit `{uid}` (plan reason: {item.get('reason', '')}). Already accepted: {accepted or 'none'}. "
            f"Required tier: {cfg['gate']['required_tier']}. Build: {' '.join(tc['build_cmd'])}.\n\n"
            + (ix.program_pack(uid, 7000) + _small_source(ix, uid) if uid in ix.progs else ix.context_pack(uid, 5000)),
            lambda: st["green"] or st["attempts"] >= st["max"], max_steps)
        if st["green"]:
            accepted.append(uid)
            log(f"[phase1] {uid} GREEN after {st['attempts']} attempt(s)")
        else:
            failed.append(uid)
            ws.emit("unit_abandoned", unit_id=uid, reason="budget exhausted or agent gave up", attempts=st["attempts"])
            log(f"[phase1] {uid} abandoned after {st['attempts']} attempt(s)")
    return {"accepted": accepted, "failed": failed, "skipped": [s["unit_id"] for s in plan["skipped"]]}
