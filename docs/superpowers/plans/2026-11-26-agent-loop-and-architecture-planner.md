# Agent Loop Template + Architecture Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One configurable `Agent` loop class for every agent in the harness, and a Phase 2 architecture planner built on it that turns the KB into a reviewed, evidence-backed module plan.

**Architecture:** `harness/` gains `ToolPolicy` (privileges), `PromptBuilder` (sectioned system prompt) and `Agent` (the loop, with hooks, stop conditions, budgets, structured `finish`, sub-agents as tools); the registry stays separate and the old `AgentLoop` becomes a shim. `planner/` reads the KB through a `KnowledgeSource` adapter, builds a deterministic draft (program graph, similarity, Louvain clustering, roles, confidence), lets a planner `Agent` review only uncertain programs through validated edit tools, and writes `plan/architecture.json` + `.md`.

**Tech Stack:** Python 3.12 (system `python3`), stdlib `unittest`, PyYAML; networkx 3.6.1 in `planner/` only.

**Spec:** `docs/superpowers/specs/2026-11-26-agent-loop-and-architecture-planner-design.md`

## Global Constraints

- Branch `phase2`. One commit per task; message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push.
- `harness/` stays stdlib + PyYAML. Only `planner/` may import `networkx`.
- Tests: stdlib `unittest`, no network, no Docker. Run with `python3 -m unittest discover -s tests/harness -t .` and `python3 -m unittest discover -s tests/planner -t .`. The existing 15 harness tests must keep passing after every task.
- LLM message format stays OpenAI-compatible: `llm.chat(messages, tools) -> (message, usage)`, usage keys `prompt_tokens`, `completion_tokens`; `LLMError(recoverable=...)` from `harness.llm`.
- "KB first": the planner reads facts only from the KB. Source access is limited to regex search (capped), bounded line reads, and a comment-line scan. No source parsing in `planner/`.
- Defaults (all overridable under `planner.architecture` in `config.yaml`): CALL/LINK/XCTL edge 3.0; shared record or code copybook 2.0 x IDF; writer->reader of the same dataset/table 2.0 x IDF; both read the same dataset/table 1.0 x IDF; same JCL job 0.5; similarity edge 1.0 x similarity; IDF = `log(N / users)` (N = number of programs); similarity threshold 0.35; utilities = called from >= 3 draft communities, or fan-in >= 5 with no writes; module size band 3..25; confidence threshold 0.6; low KB confidence = program confidence < 0.8; Louvain seed 7.
- `ask`-type tools are denied unless an approval callback says yes (default: deny).
- Plan schema version `"1.0"`.

## Review Focus

- An estate with 0, 1 or 2 programs: draft still produces a valid plan (one module, flagged), never crashes. Test in Task 9.
- A program with no edges and no similarity: gets its own module flagged `isolated` for review, is not silently merged. Test in Task 8.
- Self-calls and duplicate facts in the KB (A CALLs A, the same copybook listed twice): no self-loop edges, weights not double-counted. Test in Task 7.
- LLM error or a review pass that never calls `finish`: the draft plan (plus any edits already applied) is still written, with a `review_incomplete` open question. Test in Task 11.
- Generic or unresolvable file names: `&&TEMP` datasets are qualified by job, GDG generations are stripped, unresolved `ASSIGN` names stay program-private and add no edges. Test in Task 6.

---

### Task 1: Tool tags and ToolPolicy (privileges)

**Files:**
- Modify: `harness/registry.py` (add tags, `get`, `remove`, `replace`, `tools`)
- Create: `harness/policy.py`
- Test: `tests/harness/test_policy.py`

**Interfaces:**
- Produces:
  - `Tool(name, description, parameters, handler, tags: frozenset[str] = frozenset())`
  - `ToolRegistry.add(tool)`, `.tool(name, description, parameters=None, tags=())` decorator, `.get(name) -> Tool | None`, `.remove(name) -> None`, `.replace(tool) -> None`, `.tools() -> list[Tool]`, existing `.call(name, args) -> str` and `.schemas(allow)` unchanged.
  - `PolicyDecision(action: Literal["allow", "deny", "ask"], reason: str = "")`
  - `ToolPolicy(allow: set[str] | None = None, allow_tags: set[str] | None = None, deny: set[str] = set(), deny_tags: set[str] = set(), ask: set[str] = set(), limits: dict[str, int] = {}, guards: dict[str, Callable[[dict], str | None]] = {})` with `.offered(tool: Tool) -> bool`, `.check(tool: Tool, args: dict, counts: dict[str, int]) -> PolicyDecision`, `.copy(**changes) -> ToolPolicy`.
- Semantics: if both `allow` and `allow_tags` are None every tool is offered; otherwise a tool is offered when its name is in `allow` or a tag is in `allow_tags`. `deny`/`deny_tags` always win. `check` = deny if not offered; deny `"call limit N reached for X"` when `counts[name] >= limits[name]`; deny with the guard's message when a guard returns a string; `ask` when name in `ask`; else allow.

- [ ] **Step 1: Write failing tests** `PolicyTests`: `test_default_offers_everything`, `test_allow_by_name_or_tag` (tool tagged `read` offered with `allow_tags={"read"}`, untagged tool not), `test_deny_wins_over_allow` (`deny_tags={"write"}` hides a tool also in `allow`), `test_limit_denies_after_n` (`limits={"submit": 2}`, counts 2 -> `deny`, reason contains `"call limit 2"`), `test_guard_message_denies` (guard returns `"path escapes staging/"` -> deny with that reason), `test_ask_tools` (-> `action == "ask"`), `test_copy_is_independent`. Registry: `test_tags_get_remove_replace`.
- [ ] **Step 2: Run** `python3 -m unittest tests.harness.test_policy -v`. Expected: FAIL (ImportError `harness.policy`).
- [ ] **Step 3: Implement** the registry additions and `harness/policy.py` per the Interfaces block. `copy` deep-copies the sets/dicts.
- [ ] **Step 4: Run** `python3 -m unittest discover -s tests/harness -t .`. Expected: all pass (15 old + new).
- [ ] **Step 5: Commit** `feat(harness): tool tags and ToolPolicy privileges`.

### Task 2: PromptBuilder and a minimal JSON-schema validator

**Files:**
- Create: `harness/prompt.py`, `harness/schema_check.py`
- Test: `tests/harness/test_prompt.py`

**Interfaces:**
- Produces:
  - `PromptBuilder()` with `.set(name: str, content: str | Callable[[], str], *, before: str | None = None, after: str | None = None) -> None` (replaces in place if `name` exists; otherwise inserts at the position given, else appends), `.remove(name) -> None`, `.names() -> list[str]`, `.render() -> str` (evaluates callables now, skips empty sections, joins with `"\n\n"`), `.copy() -> PromptBuilder`.
  - `validate(instance, schema: dict) -> list[str]`: supports `type` (object, array, string, integer, number, boolean, null), `required`, `properties`, `items`, `enum`, `minItems`. Returns human-readable errors with a JSON-pointer-ish path (`"$.evidence[0]: expected string"`); empty list = valid. Unknown keywords are ignored.

- [ ] **Step 1: Write failing tests**: `test_sections_order_and_insert` (set a, c, then b `after="a"` -> names `["a","b","c"]`), `test_callable_sections_reevaluated` (counter callable renders `"1"` then `"2"`), `test_empty_sections_skipped`, `test_replace_keeps_position`; validator: `test_required_and_types` (`{"name": 3}` against `{type: object, required: [name, purpose], properties: {name: {type: string}}}` -> two errors, one mentions `$.purpose`), `test_array_items_and_enum`, `test_valid_returns_empty`.
- [ ] **Step 2: Run** `python3 -m unittest tests.harness.test_prompt -v`. Expected: FAIL (ImportError).
- [ ] **Step 3: Implement** both modules.
- [ ] **Step 4: Run** the harness suite. Expected: all pass.
- [ ] **Step 5: Commit** `feat(harness): PromptBuilder and stdlib schema check`.

### Task 3: Agent loop core

**Files:**
- Create: `harness/agent.py`
- Modify: `harness/__init__.py` (export `Agent`, `AgentSpec`, `AgentResult`, `ToolPolicy`, `PromptBuilder`)
- Test: `tests/harness/test_agent.py` (reuse `ScriptedLLM` and `call()` helpers; move them to `tests/harness/helpers.py` and import them from `test_core.py` too)

**Interfaces:**
- Consumes: Task 1 (`ToolRegistry`, `Tool`, `ToolPolicy`), Task 2 (`PromptBuilder`, `validate`), existing `ContextManager`, `EventLog`, `LLMError`.
- Produces:
  - `AgentSpec(name: str, prompt: PromptBuilder, policy: ToolPolicy = ToolPolicy(), max_steps: int = 40, max_tokens: int | None = None, context_budget: int = 36000, keep_last: int | None = None, max_malformed: int = 6, max_nudges: int = 3, nudge: str = NUDGE, result_schema: dict | None = None, finish_tool: str = "finish")` with `.copy(**changes) -> AgentSpec` (copies prompt and policy).
  - `AgentResult(stop_reason: str, output: dict | None, steps: int, usage: dict[str, int], messages: list[dict], state: dict)`; `usage` keys `tokens_in`, `tokens_out`.
  - `Agent(llm, registry: ToolRegistry, spec: AgentSpec, *, events: EventLog | None = None, log: Callable = lambda *a: None, approve: Callable[[str, dict], bool] | None = None)`
  - Methods: `set_system_prompt(text: str)`, `add_prompt_section(name, content, *, before=None, after=None)`, `remove_prompt_section(name)`, `set_policy(policy: ToolPolicy)`, `allow_tools(*names)` (removes from deny; adds to `allow` when `allow` is a set), `deny_tools(*names)`, `set_budget(max_steps: int | None = None, max_tokens: int | None = None)`, `set_context(manager: ContextManager)`, `add_stop_condition(name: str, fn: Callable[[dict], bool])`, `on(event: str, hook: Callable)`, `expect_result(schema: dict)`, `offered_tools() -> list[str]`, `run(message: str, state: dict | None = None) -> AgentResult`.
  - Hook events and return contracts: `before_model(messages, state)`; `after_model(message, state)`; `before_tool(name, args, state) -> None | dict | str` (dict = replacement args, str = veto, used as the tool result); `after_tool(name, args, output, state) -> None | str` (str = replacement output); `on_text_reply(text, state)`; `on_stop(result)`.
  - Stop reasons: `"finished"`, a stop-condition name, `"max_steps"`, `"max_tokens"`, `"gave_up"`, `"llm_error: <msg>"`.
  - Events (when `events` given, `unit_id=spec.name`): `llm_usage`, `tool_called` (`tool`, `decision`), `context_compacted`, `agent_stopped` (`reason`, `steps`).
- Behaviour per turn is spec section 5.3. `finish` is owned by the agent (not the shared registry): offered only when `result_schema` is set, always allowed, arguments checked with `validate`; errors go back to the model as `"ERROR: invalid result: ..."`. A call to a tool not offered returns `"ERROR: tool X is not available to this agent"` and is never dispatched. Policy counts are per run. Token budget is checked before each model call against `tokens_in + tokens_out`.

- [ ] **Step 1: Write failing tests** (`AgentTests`): `test_finish_returns_validated_output` (bad args then good -> `stop_reason == "finished"`, `output == {...}`, first finish result contains `"invalid result"`), `test_denied_tool_not_offered_and_refused` (schemas passed to `llm.chat` lack the denied tool; a scripted call to it returns the refusal and the handler is not run), `test_ask_uses_approval_callback` (no callback -> refused; `approve=lambda n, a: True` -> runs), `test_call_limit`, `test_before_tool_veto_and_rewrite`, `test_after_tool_rewrites_output`, `test_prompt_sections_refreshed_each_turn`, `test_stop_condition_name_is_reason`, `test_max_tokens_stops_before_call` (usage 60+60 per call, `max_tokens=100` -> one call, reason `"max_tokens"`), `test_gave_up_and_llm_error` (reuse existing scenarios), `test_events_written` (`tool_called` and `agent_stopped` lines in events file).
- [ ] **Step 2: Run** `python3 -m unittest tests.harness.test_agent -v`. Expected: FAIL (ImportError `harness.agent`).
- [ ] **Step 3: Implement** `harness/agent.py`. Reuse the malformed-JSON / nudge / compaction logic from `harness/loop.py` (move shared constants `NUDGE`, `MALFORMED` into `agent.py`).
- [ ] **Step 4: Run** the harness suite. Expected: all pass.
- [ ] **Step 5: Commit** `feat(harness): configurable Agent loop`.

### Task 4: Sub-agents as tools, AgentLoop shim

**Files:**
- Modify: `harness/agent.py` (add `as_tool`), `harness/loop.py` (shim), `harness/README.md` (document Agent, ToolPolicy, PromptBuilder, sub-agents; 1 short section)
- Test: `tests/harness/test_agent.py` (add `SubAgentTests`); existing `tests/harness/test_core.py` untouched except helper import

**Interfaces:**
- Produces:
  - `Agent.as_tool(name: str, description: str, parameters: dict, make_message: Callable[..., str], *, spec: AgentSpec | None = None, tags: Iterable[str] = ("agent",)) -> Tool`. The handler runs a fresh child `Agent(self.llm, self.registry, spec or self.spec.copy(name=f"{self.spec.name}/{name}"), events=self.events, approve=self.approve)` on `make_message(**kwargs)` and returns `json.dumps(result.output)` when the child finished, else `"sub-agent stopped: <reason>"`. Child token usage is added to the parent's running usage and counts against the parent's `max_tokens`.
  - `AgentLoop(llm, registry, context, events, *, allow=None, label=None, log=print, max_malformed=6, max_nudges=3, nudge=NUDGE)` and `.run(system_fn, user_msg, done, max_steps=40) -> str`: builds an `AgentSpec` with one prompt section `"system"` = `system_fn`, `ToolPolicy(allow=allow)`, `set_context(context)`, `add_stop_condition("done", lambda s: done())`, returns `result.stop_reason`.

- [ ] **Step 1: Write failing tests**: `test_subagent_tool_returns_child_output` (child spec with `result_schema`, scripted LLM serves parent call -> child finish -> parent finish; parent output includes child JSON), `test_subagent_usage_rolls_up`, `test_subagent_failure_text` (child hits `max_steps`).
- [ ] **Step 2: Run** `python3 -m unittest tests.harness.test_agent -v`. Expected: new tests FAIL.
- [ ] **Step 3: Implement** `as_tool` and rewrite `harness/loop.py` as the shim.
- [ ] **Step 4: Run** the harness suite. Expected: all pass, including the 4 original `LoopTests` and 2 `RunnerTests` through the shim.
- [ ] **Step 5: Commit** `feat(harness): sub-agents as tools; AgentLoop runs on Agent`.

### Task 5: KB types, KnowledgeSource, FixtureKb and the fixture estate

**Files:**
- Create: `planner/__init__.py`, `planner/kb.py`, `tests/planner/__init__.py`, `tests/planner/fixtures/estate.json`, `tests/planner/fixtures/estate_src/<PROGRAM>.cbl` (one per program, 3-8 lines, mostly comments)
- Test: `tests/planner/test_kb.py`

**Interfaces:**
- Produces (frozen dataclasses in `planner/kb.py`):
  - `Program(id: str, file: str, loc: int, kind: str, confidence: float, copybooks: tuple[str, ...], calls: tuple[str, ...], identifiers: tuple[str, ...])`; `kind` in `batch | online | subprogram`.
  - `Copybook(name: str, kind: str)`; `kind` in `record | code`.
  - `StoreUse(program: str, store: str, store_kind: str, mode: str)`; `store_kind` in `dataset | table | private`; `mode` in `read | write`.
  - `JobStep(job: str, step: str, order: int, program: str | None, reads: tuple[str, ...], writes: tuple[str, ...])`.
  - `class KnowledgeSource(Protocol)`: `programs() -> list[Program]`, `copybooks() -> dict[str, Copybook]`, `store_uses() -> list[StoreUse]`, `job_steps() -> list[JobStep]`, `units(program_id: str) -> list[dict]`, `source_root() -> Path`, `kb_version() -> str`.
  - `FixtureKb(path: Path)` reads one JSON file with keys `kb_version`, `source_root` (relative to the JSON file), `programs`, `copybooks`, `store_uses`, `job_steps`, `units` (program id -> list).
- Fixture estate (13 programs), so later tasks can assert groupings:
  - account: `ACCTVIEW` (online, reads table `ACCOUNT`, calls `ERRHNDL`), `ACCTUPDT` (online, writes `ACCOUNT`, calls `DATEFMT`, `ERRHNDL`), `ACCTBAT` (batch, reads `ACCOUNT`, writes dataset `ACCT.EXTRACT`, code copybook `ABENDRTN`); all use record copybook `ACCTREC`.
  - card: `CARDLIST` (reads `CARD`, calls `ERRHNDL`), `CARDUPDT` (writes `CARD`, calls `DATEFMT`, `ERRHNDL`), `CARDACT` (writes `CARD`, calls `DATEFMT`, code copybook `ABENDRTN`); all use `CARDREC`.
  - tran: `TRANVAL` (reads `TRAN.DAILY`, writes `TRAN.VALID`, calls `DATEFMT`, code copybook `DATECHK`), `TRANPOST` (reads `TRAN.VALID`, writes table `TRANSACT` and table `ACCOUNT`, calls `DATEFMT`, `ERRHNDL`, code copybook `DATECHK`), `TRANRPT` (reads `TRANSACT`, writes `TRAN.REPORT`); all use `TRANREC`.
  - utilities: `DATEFMT`, `ERRHNDL` (subprogram, no store writes).
  - `CUSTSRCH` (online): reads `ACCOUNT` and `CARD`, uses `ACCTREC` and `CARDREC`, no calls (ambiguous).
  - `ORPHAN` (batch): no copybooks, calls, stores or shared vocabulary (isolated).
  - every program uses record copybook `COMMHDR` (ubiquitous; IDF 0).
  - job `NIGHTLY`: steps 1 `TRANVAL`, 2 `TRANPOST`, 3 `TRANRPT`, 4 `ACCTBAT` with matching reads/writes.
  - identifiers: domain words (`ACCT-BAL`, `CARD-NUM`, `TRAN-AMT`, ...) per group; comments in `estate_src` repeat the group's domain words; `ORPHAN` uses unrelated words.

- [ ] **Step 1: Write failing tests**: `test_fixture_loads` (13 programs, `copybooks()["ABENDRTN"].kind == "code"`, 4 job steps ordered 1..4, `source_root()` exists), `test_units_default_empty` (unknown program -> `[]`).
- [ ] **Step 2: Run** `python3 -m unittest discover -s tests/planner -t .`. Expected: FAIL (ImportError).
- [ ] **Step 3: Implement** `planner/kb.py` and write the fixture files.
- [ ] **Step 4: Run** the planner suite. Expected: pass.
- [ ] **Step 5: Commit** `feat(planner): KB contract types and fixture estate`.

### Task 6: Phase0Kb adapter

**Files:**
- Create: `planner/kb_phase0.py`, `tests/planner/fixtures/phase0_ws/kb/manifest.json`, `.../kb/source/{inventory,units,call_graph,data_flow,data_dictionary}.json`, `.../source/` (2 programs + 1 JCL)
- Test: `tests/planner/test_kb_phase0.py`

**Interfaces:**
- Consumes: Task 5 types.
- Produces: `Phase0Kb(workspace: Path)` implementing `KnowledgeSource`. Reads files that are either a list or `{"<key>": [...]}` (`units`, `fields`, `edges`, `files`).
- Mapping rules:
  - programs from `inventory.files` with `kind == "program"`; `confidence` = max unit `provenance.confidence` for that program (default 1.0); `identifiers` = paragraph names from `units.json` + item names from `data_dictionary.json` for that program; `calls` from `call_graph` edges with `kind == "call"` (dst, dynamic `?X` dropped); `kind`: `online` if any unit's `unsupported` contains a string with `cics` (case-insensitive), else `subprogram` if some other program calls it and no JCL step runs it, else `batch`.
  - copybooks: inventory `kind == "copybook"`; `subkind == "procedure"` -> `code`, else `record`; name = file stem upper-cased.
  - job steps from inventory `jcl_steps` rows in order: an `exec` row starts a step (`program` = row `program`, `None` for `IKJEFT01`/`IKJEFT1A`/`IKJEFT1B` or a `proc` row); `dd` rows add `dsn` to `writes` when DISP's first token is `NEW` or `MOD`, else `reads`.
  - dataset ids: strip GDG generation (`PROD.X(+1)` -> `PROD.X`); temp `&&T` -> `<JOB>:&&T`.
  - store uses: each `data_flow.files` row: mode `write` if any unit has C/U/D, `read` if any has R (both possible). Resolve `assign` through the step that runs `program` (DD name == assign) -> dataset; unresolved -> store `<PROGRAM>:<ASSIGN>` with kind `private`. Plus, for each step with a program, its DD datasets as uses (covers tolerant programs without CRUD). Deduplicate `(program, store, mode)`.
  - `kb_version` from `kb/manifest.json`; `source_root` = `<workspace>/source`.

- [ ] **Step 1: Write failing tests**: `test_assign_resolves_through_jcl_step` (`TRANIN` -> `NIGHTLY:&&SORTED`), `test_unresolved_assign_is_private`, `test_gdg_generation_stripped`, `test_tso_batch_step_has_no_program`, `test_tolerant_confidence_and_kind` (tolerant program confidence 0.6; `cics` unsupported -> `online`), `test_code_copybook_kind`.
- [ ] **Step 2: Run** `python3 -m unittest tests.planner.test_kb_phase0 -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `planner/kb_phase0.py`. Write the fixture KB by hand in Phase 0's shapes (see `phase0/phase0/schema.py`: `FileCrud`, `InventoryEntry`, `Unit`).
- [ ] **Step 4: Run** the planner suite. Expected: pass.
- [ ] **Step 5: Commit** `feat(planner): Phase 0 KB adapter`.

### Task 7: Program graph and similarity signal

**Files:**
- Create: `planner/architecture/__init__.py`, `planner/architecture/config.py`, `planner/architecture/graph.py`, `planner/architecture/features.py`
- Test: `tests/planner/test_graph.py`

**Interfaces:**
- Consumes: Task 5.
- Produces:
  - `Weights(call=3.0, copybook=2.0, write_read=2.0, co_read=1.0, same_job=0.5, similar=1.0)`; `PlannerConfig(weights=Weights(), similarity_threshold=0.35, util_min_communities=3, util_min_fan_in=5, band_min=3, band_max=25, confidence_threshold=0.6, low_kb_confidence=0.8, seed=7, root_package="app", review=ReviewBudget())`; `ReviewBudget(pass_steps=25, explorer_calls=5, explorer_steps=15, max_tokens=None)`; `PlannerConfig.from_dict(d: dict) -> PlannerConfig` (unknown keys -> `ValueError`).
  - `Evidence(kind: str, other: str, item: str, weight: float)`; kinds `call`, `copybook`, `write_read`, `co_read`, `same_job`, `similar`.
  - `build_graph(kb: KnowledgeSource, cfg: PlannerConfig) -> nx.Graph`: one node per program; edge attrs `weight: float`, `evidence: list[Evidence]`; no self-loops; per (pair, kind, item) counted once; weight 0 edges not added.
  - `comment_lines(path: Path) -> list[str]` (fixed format: column 7 `*` or `/`; free: text after `*>`).
  - `program_tokens(program: Program, comments: list[str]) -> list[str]`: split identifiers on `-`/`_`, upper-case, drop `WS`, `LK`, `FILLER`, pure numbers, tokens shorter than 3.
  - `similarity(kb, cfg) -> dict[tuple[str, str], float]`: `0.5 * cosine(tf-idf of tokens) + 0.5 * jaccard(io signature)` where io signature = set of (store, mode) plus record copybooks with IDF > 0; only pairs >= threshold.
  - `add_similarity(g, sims, cfg) -> None` adds/extends edges with kind `similar`.

- [ ] **Step 1: Write failing tests**: `test_call_edge_weight` (ACCTUPDT-DATEFMT carries `call` 3.0), `test_ubiquitous_copybook_adds_nothing` (no `COMMHDR` evidence anywhere), `test_write_read_idf` (TRANVAL-TRANPOST via `TRAN.VALID`, weight `2.0 * log(13/2)`), `test_no_self_loops_or_double_count` (fixture copy with `CALL ACCTVIEW` from ACCTVIEW and `ACCTREC` listed twice -> no self-loop, copybook weight unchanged), `test_similarity_groups_vocabulary` (sim(ACCTVIEW, ACCTUPDT) > sim(ACCTVIEW, ORPHAN); ORPHAN has no pair above threshold), `test_comment_lines_fixed_and_free`.
- [ ] **Step 2: Run** `python3 -m unittest tests.planner.test_graph -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the three modules.
- [ ] **Step 4: Run** the planner suite. Expected: pass.
- [ ] **Step 5: Commit** `feat(planner): program graph and similarity signal`.

### Task 8: Clustering, utilities and size band

**Files:**
- Create: `planner/architecture/cluster.py`
- Test: `tests/planner/test_cluster.py`

**Interfaces:**
- Consumes: Task 7 (`build_graph`, `similarity`, `PlannerConfig`).
- Produces:
  - `louvain(g: nx.Graph, seed: int, resolution: float = 1.0) -> list[set[str]]` (wraps `nx.community.louvain_communities(g, weight="weight", seed=seed, resolution=resolution)`, sorted by (-size, min id)).
  - `find_utilities(g, communities, kb, cfg) -> set[str]`: callers of a program span >= `util_min_communities` communities, or (fan-in >= `util_min_fan_in` and no `write` store use).
  - `apply_band(g, communities, cfg) -> list[set[str]]`: split oversized (re-run `louvain` on the subgraph at resolution x1.5, up to 5 tries, stop when parts fit or the split stops changing); merge undersized into the neighbour community with the largest cross weight; a community with no cross weight stays.
  - `cluster(g, kb, cfg) -> Clusters` where `Clusters(domain: list[set[str]], utilities: list[set[str]], isolated: set[str])`. Order: louvain on full graph -> utilities removed -> louvain on the rest -> isolated programs (no edges at all) pulled out -> `apply_band`. Utilities: if fewer than `band_min`, one group; else louvain on the utilities' similarity subgraph.

- [ ] **Step 1: Write failing tests**: `test_fixture_groups` (communities contain {ACCTVIEW, ACCTUPDT, ACCTBAT}, {CARDLIST, CARDUPDT, CARDACT}, {TRANVAL, TRANPOST, TRANRPT} as subsets of three different domain clusters), `test_utilities_detected` (`{"DATEFMT", "ERRHNDL"}` single utility group), `test_isolated_program_stays_alone` (`ORPHAN` in `isolated`, in no domain cluster), `test_oversized_split` (synthetic graph: two 15-node cliques joined by one weak edge, band_max 25 -> 2 clusters), `test_undersized_merged` (2-node community with a heavy edge into a 5-node one is merged), `test_deterministic` (two runs equal).
- [ ] **Step 2: Run** `python3 -m unittest tests.planner.test_cluster -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `cluster.py`. If the fixture groups do not separate, strengthen the fixture's domain vocabulary/edges (Task 5 files), not the algorithm defaults.
- [ ] **Step 4: Run** the planner suite. Expected: pass.
- [ ] **Step 5: Commit** `feat(planner): clustering with utilities and size band`.

### Task 9: Plan model, roles, confidence and the draft

**Files:**
- Create: `planner/architecture/plan.py`, `planner/architecture/roles.py`, `planner/architecture/draft.py`
- Test: `tests/planner/test_draft.py`

**Interfaces:**
- Consumes: Tasks 5, 7, 8.
- Produces (`plan.py`, dataclasses with `to_dict()` / `from_dict()`, `SCHEMA_VERSION = "1.0"`):
  - `Assignment(program: str, confidence: float, evidence: list[Evidence], decided_by: str = "draft", low_kb_confidence: bool = False)`
  - `Module(id: str, name: str, purpose: str, kind: str, programs: list[Assignment], local_types: list[str], owned_stores: list[str], depends_on: list[str])`; `kind` in `domain | utility | isolated`.
  - `SharedType(copybook: str, type_name: str, used_by: list[str])`; `SharedCode(copybook: str, module: str, used_by: list[str])`
  - `Store(id: str, kind: str, owner: str, readers: list[str], writers: list[str], interface: str, shared_write: bool)`
  - `Job(id: str, steps: list[dict])` (each step: `step`, `order`, `program`, `module`, `reads`, `writes`)
  - `Edit(action: str, args: dict, reason: str, evidence: list[str])`; `OpenQuestion(kind: str, subject: str, detail: str)`
  - `ArchitecturePlan(schema_version, modules, shared_types, shared_code, stores, jobs, layout: dict, edits, open_questions, inputs: dict)`; helpers `module_of(program) -> Module`, `program_ids() -> list[str]`.
  - `roles.assign_roles(kb, modules: list[Module]) -> tuple[list[SharedType], list[SharedCode], list[Store], list[Job]]` and fills each module's `local_types`, `owned_stores`, `depends_on`. Rules from spec 6.2 step 5: record copybooks with IDF > 0 used by 1 module -> local, >= 2 -> `SharedType` (type name = PascalCase of copybook); code copybooks -> `SharedCode` in the single using module, else in the utility module that the users call most (first utility module if none); store owner = module with most writer programs (ties: lowest module id), `shared_write` when writers span > 1 module, `interface` = PascalCase(store last qualifier) + `Repository`; `depends_on` = modules this module calls or reads stores owned by.
  - `confidence(g, program, members: set[str]) -> float` = intra weight / total weight (0.0 when no edges).
  - `draft.make_draft(kb, cfg) -> tuple[ArchitecturePlan, nx.Graph]`: modules `m01, m02, ...` ordered by (-size, min program); domain name = top TF-IDF token of members lower-cased (unique, suffix `-2`); utility modules `util` or `util-<token>`; isolated `kind == "isolated"`; `purpose == ""`; evidence = top 3 in-module edges by weight; open questions: `uncertain_program` (confidence < threshold), `low_kb_confidence`, `isolated`, `shared_write`, `missing_kb_fact` (no store uses at all in the KB, or job steps without a program); `inputs = {kb_version, seed, config}`.

- [ ] **Step 1: Write failing tests**: `test_draft_modules_and_utilities` (3 domain modules + 1 utility module + `ORPHAN` isolated; every program in exactly one module), `test_shared_types_and_local_types` (`TRANREC` in the tran module's `local_types`; `COMMHDR` appears in no `SharedType` and no `local_types`; `CARDREC` is a `SharedType` exactly when `CUSTSRCH`'s module differs from the card module), `test_shared_code_placement` (`DATECHK` in tran module; `ABENDRTN` used by account and card -> placed in the utility module), `test_store_owner_and_shared_write` (`ACCOUNT` owned by account module, `shared_write` true because `TRANPOST` writes it), `test_custsrch_uncertain` (confidence < 0.6 and an `uncertain_program` question), `test_job_steps_mapped_to_modules`, `test_roundtrip_json` (`from_dict(to_dict())` equal), `test_tiny_estates` (0, 1, 2 programs -> valid plan, no exception).
- [ ] **Step 2: Run** `python3 -m unittest tests.planner.test_draft -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `plan.py`, `roles.py`, `draft.py`.
- [ ] **Step 4: Run** the planner suite. Expected: pass.
- [ ] **Step 5: Commit** `feat(planner): deterministic architecture draft`.

### Task 10: Plan validator and edit operations

**Files:**
- Create: `planner/architecture/validate.py`, `planner/architecture/edits.py`
- Test: `tests/planner/test_edits.py`

**Interfaces:**
- Consumes: Task 9.
- Produces:
  - `evidence_exists(ref: str, kb) -> bool` for refs `program:ID`, `copybook:NAME`, `store:ID`, `job:ID`, `src:PATH:LINE` (file under `kb.source_root()`, line within range).
  - `validate_plan(plan, kb) -> list[str]`: every KB program in exactly one module; no unknown programs; no empty modules; every store has an owner that exists; every `SharedType.used_by` has >= 2 modules; every `Edit` evidence ref exists.
  - `PlanEditor(plan: ArchitecturePlan, kb, g: nx.Graph, cfg)` with methods returning `str` (`"ok: ..."` or `"ERROR: ..."`), each taking `reason: str, evidence: list[str]` last: `move_program(program, to_module, ...)`, `merge_modules(keep, absorb, ...)`, `split_module(module, programs: list[str], new_name, ...)`, `rename_module(module, name, ...)`, `set_module_purpose(module, purpose, ...)`, `mark_utility(program, ...)`, `set_owner(store, module, ...)`. Each: rejects empty `reason`, empty `evidence` or any missing ref (naming the bad ref); applies to a copy; recomputes roles and confidences (`decided_by = "agent"` for moved programs); rejects if `validate_plan` fails; on success swaps in the copy and appends an `Edit`.

- [ ] **Step 1: Write failing tests**: `test_move_with_evidence` (move `CUSTSRCH` to card module with `["store:CARD", "program:CARDLIST"]` -> ok, `decided_by == "agent"`, one `Edit`), `test_missing_evidence_rejected` (`"store:NOPE"` -> `"ERROR"` naming it, plan unchanged), `test_empty_reason_rejected`, `test_merge_and_split_keep_invariants`, `test_rename_unique`, `test_set_owner_unknown_module_rejected`, `test_src_ref_line_checked`.
- [ ] **Step 2: Run** `python3 -m unittest tests.planner.test_edits -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `validate.py`, `edits.py`.
- [ ] **Step 4: Run** the planner suite. Expected: pass.
- [ ] **Step 5: Commit** `feat(planner): plan validator and evidence-checked edits`.

### Task 11: Planner tools and the agent review

**Files:**
- Create: `planner/architecture/tools.py`, `planner/architecture/prompts.py`, `planner/architecture/review.py`
- Test: `tests/planner/test_review.py`

**Interfaces:**
- Consumes: Tasks 3-4 (`Agent`, `AgentSpec`, `ToolPolicy`, `PromptBuilder`, `as_tool`), Tasks 9-10.
- Produces:
  - `register_kb_tools(reg: ToolRegistry, kb, editor: PlanEditor) -> None` (tag `read`; tools read `editor.plan` and `editor.g` at call time, because edits swap in a new plan): `module_overview()`, `program_facts(program_id)`, `program_edges(program_id)`, `who_uses(item)` (copybook, store or program), `similar_programs(program_id, limit=5)`, `unit_facts(program_id)`.
  - `register_code_tools(reg, kb) -> None` (tag `read`): `search_code(pattern, max_results=25)` (cap 60, skips comment lines, returns `path:line: text`), `read_lines(path, start, end)` (max 120 lines).
  - `register_edit_tools(reg, editor: PlanEditor) -> None` (tag `plan_edit`), one tool per `PlanEditor` method with the same argument names.
  - `review(plan, g, kb, llm, cfg: PlannerConfig, *, events=None, log=print) -> ArchitecturePlan`:
    1. explorer: spec `planner/explorer`, policy `allow_tags={"read"}`, `max_steps=cfg.review.explorer_steps`, result schema `{answer: string, evidence: array of string}` (required both). Each pass agent adds it to the shared registry with `reg.replace(pass_agent.as_tool("explore_program", ..., {program_id, question}, make_message, spec=explorer_spec))`, so the explorer never sees `plan_edit` or `agent` tools.
    2. per-module pass for each module with an `uncertain_program`/`low_kb_confidence` question: spec `planner/module/<id>`, policy `allow_tags={"read", "plan_edit", "agent"}`, `limits={"explore_program": cfg.review.explorer_calls}`, `max_steps=cfg.review.pass_steps`, result schema `{name: string, purpose: string, evidence: array of string}`; on finish apply `rename_module` and `set_module_purpose` with reason `"module review"` and the returned evidence.
    3. global pass: spec `planner/global`, same tools, first message = module-level summary (modules, sizes, cross-module edge weights, shared writes, utilities), result schema `{summary: string}`.
    4. afterwards: drop open questions resolved by edits; for any pass that did not finish add `OpenQuestion("review_incomplete", <module or "global">, <stop_reason>)`; programs still below threshold with `decided_by == "draft"` keep their `uncertain_program` question.
  - `prompts.py`: `ROLE`, `RULES` (KB first; search code only for what the KB lacks; every edit needs reason + evidence refs in the listed formats; do not refactor program logic; prefer fewer, cohesive modules within the size band), `module_message(plan, module_id) -> str`, `global_message(plan, g) -> str`.

- [ ] **Step 1: Write failing tests** (scripted LLM from `tests/harness/helpers.py`): `test_module_pass_moves_uncertain_program` (script: `explore_program` -> explorer finishes with evidence -> `move_program CUSTSRCH` with valid refs -> finish name/purpose; plan has `CUSTSRCH` in card module and that module's `purpose` set), `test_invalid_evidence_edit_does_not_apply`, `test_llm_error_keeps_draft_and_flags` (LLMError non-recoverable -> plan programs unchanged, `review_incomplete` present), `test_explorer_limit_enforced` (6th `explore_program` call refused), `test_tools_are_read_only_for_explorer` (explorer offered tools have no `plan_edit` names).
- [ ] **Step 2: Run** `python3 -m unittest tests.planner.test_review -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the three modules.
- [ ] **Step 4: Run** both suites. Expected: pass.
- [ ] **Step 5: Commit** `feat(planner): agent review of uncertain programs`.

### Task 12: Layout, review document, CLI

**Files:**
- Create: `planner/architecture/render.py`, `planner/cli.py`, `bin/planner`
- Test: `tests/planner/test_render_cli.py`

**Interfaces:**
- Consumes: Tasks 5, 6, 9, 11.
- Produces:
  - `package_name(text: str) -> str` (lower-case, non `[a-z0-9]` -> `_`, leading digit prefixed `m_`).
  - `layout(plan, target: str, root: str = "app") -> dict[str, str]` (module id or `shared-types`/`jobs` -> path): java `src/main/java/<root>/<pkg>/`, python `<root>/<pkg>/`, go `internal/<pkg>/`; shared types at `<...>/shared/types/`, jobs at `<...>/jobs/`. Unknown target -> `ValueError`.
  - `render_markdown(plan) -> str` with sections in order: `# Architecture plan`, `## Modules` (table: id, name, kind, programs, owned stores), one `### <name>` per module (purpose, programs with confidence and top evidence, local types), `## Shared types`, `## Shared code`, `## Data stores` (owner, readers, writers, shared-write flag), `## Jobs`, `## Changes made by the planner agent` (edit journal), `## Open questions`.
  - `planner/cli.py main(argv) -> int`: `planner architecture --workspace W [--target java|python|go] [--no-agent] [--fixture PATH]`. KB = `FixtureKb(PATH)` when given, else `Phase0Kb(W)`. Config from `W/config.yaml` key `planner.architecture` (missing -> defaults). LLM from `harness.llm` adapter spec via `harness.registry.load_adapter` (default `harness.llm.groq:GroqLLM`) only when the agent runs. Writes `W/plan/architecture.json` (with `layout` filled) and `W/plan/architecture.md`; prints a one-line JSON summary (`modules`, `open_questions`, `edits`). Exit 0 ok, 2 bad input (missing KB files, invalid config, unknown target), 3 internal error.
  - `bin/planner`: same pattern as `bin/harness` (`PYTHONPATH` = repo root, `python3 -m planner.cli`).

- [ ] **Step 1: Write failing tests**: `test_layout_per_target` (java path for module `account` == `src/main/java/app/account/`; python `app/account/`; go `internal/account/`), `test_markdown_sections_in_order`, `test_cli_no_agent_on_fixture` (temp workspace with `config.yaml` targeting python; `main(["architecture", "--workspace", W, "--no-agent", "--fixture", FIX, "--target", "python"])` -> 0, both files exist, JSON validates with `validate_plan`), `test_cli_bad_target_exit_2`, `test_cli_missing_kb_exit_2`.
- [ ] **Step 2: Run** `python3 -m unittest tests.planner.test_render_cli -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `render.py`, `cli.py`, `bin/planner` (`chmod +x`).
- [ ] **Step 4: Run** both suites. Expected: pass. Then `bin/planner architecture --workspace $(mktemp -d) --no-agent --fixture tests/planner/fixtures/estate.json` after writing a minimal `config.yaml` there. Expected: exit 0, summary JSON printed.
- [ ] **Step 5: Commit** `feat(planner): layout, review document and CLI`.

### Task 13: KB contract document and the probe run

**Files:**
- Create: `docs/phase2/KB_CONTRACT.md`, `planner/README.md`
- Modify: `docs/superpowers/specs/2026-11-26-agent-loop-and-architecture-planner-design.md` only if a decision changed during implementation (note it under section 9)

**Interfaces:**
- Consumes: Tasks 5, 6, 12.

- [ ] **Step 1: Write `docs/phase2/KB_CONTRACT.md`**: the `KnowledgeSource` records (Task 5) as the contract; per fact, what Phase 0 provides today (Task 6 mapping) and what is missing, ranked by effect on the plan: (1) DB tables per program with read/write, (2) program file -> dataset binding including IKJEFT01 `RUN PROGRAM` and PROCs, (3) facts for SQL/CICS programs on the strict path, (4) program kind (online/batch/subprogram), (5) code vs record copybook. Name the planner behaviour when each is missing (fewer edges, `missing_kb_fact`, more uncertain programs).
- [ ] **Step 2: Write `planner/README.md`**: how to call it, inputs, outputs, config keys with defaults (copy from Global Constraints).
- [ ] **Step 3: Probe run.** Build the probe KB: `W=$(mktemp -d) && cp -r docs/phase0_review_probe/* $W && phase0/bin/phase0 build --workspace $W`, then `bin/planner architecture --workspace $W --no-agent --target java`. Expected: exit 0 and a plan covering `ACCTUPD`, `DATEUTIL`, with `missing_kb_fact` questions. If `phase0 build` fails with `ModuleNotFoundError: phase1` (tolerant fallback), this step depends on Task 14; record the outcome in `planner/README.md` under "Known limitations" either way.
- [ ] **Step 4: Run** both suites one last time. Expected: all pass.
- [ ] **Step 5: Commit** `docs(planner): KB contract and planner README`.

### Task 14 (needs your approval before starting): restore Phase 0's tolerant fallback

Phase 0's `stages/tolerant.py` imports `phase1.cobol` from the deleted `phase1/` tree, so `phase0 build` crashes on any SQL/CICS program (verified on `ACCTUPD`). This changes Phase 0's code, which belongs to another team.

**Files:**
- Create: `phase0/phase0/tolerant_analyser/{__init__,analyzer,repo,source}.py` copied from `git show e9b42c4:phase1/phase1/cobol/<file>.py`
- Modify: `phase0/phase0/stages/tolerant.py` (`_phase1()` imports from `phase0.tolerant_analyser`)

- [ ] **Step 1:** Run `phase0/bin/phase0 build` on a copy of `docs/phase0_review_probe`. Expected: FAIL with `ModuleNotFoundError: No module named 'phase1'`.
- [ ] **Step 2:** Copy the four files, fix their intra-package imports, point `_phase1()` at the new package.
- [ ] **Step 3:** Re-run the build. Expected: exit 0; `ACCTUPD` has `parse_status: tolerant` in `kb/source/inventory.json`.
- [ ] **Step 4:** Commit `fix(phase0): vendor the tolerant analyser removed with phase1/`, then redo Task 13 Step 3.
