# Agent loop template + Phase 2 architecture planner: design

Date: 2026-11-26. Status: approved 2026-11-26.

## 1. Intent

Two pieces, built in this order:

1. **One standard agent loop class** that every agent in the harness uses (builders/translators, planners,
   explorers, later reviewers). Every aspect of the loop can be changed through methods: system prompt,
   privileges, tools offered, stop conditions, budgets, context handling, recovery. Tool definition and
   maintenance stay in a separate registry, not in the loop.
2. **Phase 2, part 1: architecture planning.** An agent, built on that loop, turns a COBOL estate described by
   the KB into a target architecture for Java, Python or Go: which modules exist, which programs go in each,
   which copybooks become shared types, which data stores sit behind which interfaces, how JCL jobs map to an
   orchestration layer, and which programs are shared utilities. Part 2 (migration order: topological sort,
   chunking) consumes this plan and is out of scope here, but the plan must give it what it needs.

Why: the current harness migrates programs one by one, alphabetically, with no plan. At scale, the team needs a
reviewed architecture before translation starts, and every agent type needs the same loop so behaviour,
logging and limits are consistent.

## 2. Goals, non-goals, anti-goals

Goals
- A loop class configurable without subclassing for the common cases, and with clear override points for the rest.
- An architecture plan that is machine-readable (for part 2 and the translators) and human-reviewable (every
  grouping has a reason and evidence).
- Planner works at estate scale (hundreds to thousands of programs): LLM effort grows with the number of
  *uncertain* programs, not the total.
- Runs with no network in tests (scripted LLM, fixture KB).

Non-goals
- Large-scale refactoring. Program logic is not redesigned; paragraphs stay methods/functions inside the
  program's unit. (User: "avoid large scale refactors, that is a different problem".)
- The human review and "developer uploads own architecture" flow (later; the plan format must allow it).
- Verification of the redesigned code (deferred by the user).
- Migration ordering (part 2).
- Fixing Phase 0's KB gaps (separate work; this design states what it needs from the KB).

Anti-goals (failure even if it "works")
- Naive mapping: one module per program or per copybook.
- Groupings with no traceable evidence, or an LLM inventing programs, files or tables.
- Precomputed LLM summaries stored for every program as the grouping signal (user: not robust at scale).
- A loop whose privileges can be bypassed by the model (e.g. calling a tool it was not offered).

## 3. Constraints and current state

- `harness/` (uncommitted reorg on `integration`): `AgentLoop` (loop.py), `ToolRegistry` (registry.py),
  `ContextManager`/`Scratchpad` (context.py), `EventLog`, `LLM` protocol with `GroqLLM`, `Runner`, `Profile`.
  15 stdlib unit tests pass. The new loop must keep `Runner` working and these tests' behaviour.
- Harness core stays stdlib + PyYAML. The planner package may use `networkx` (installed for system python3).
- Only one LLM adapter exists (Groq, OpenAI-compatible message format). The loop keeps that message format.
- The KB (Phase 0, branch `origin/phase0`, not merged) has: programs, units, CALL edges, copybooks per file,
  JCL steps/DDs, per-program file CRUD (strict programs only), data dictionary. It lacks: DB tables per
  program, JCL program binding through IKJEFT01/SYSTSIN, ASSIGN-to-DD binding, CICS resources. The planner
  reads the KB through an adapter and degrades gracefully when facts are missing (fewer edges, lower confidence).
- Phase 0 imports `phase1/`, which the reorg deletes; the planner must not depend on Phase 0's code, only on
  its output files.

## 4. Approaches considered

Planner (chosen in conversation: C, hybrid, with the user's refinement)
- A. Deterministic coupling graph + clustering, LLM only names/explains. Scalable, reproducible, evidence for
  free; groups by shared data, misses "does the same thing".
- B. Exploration agent first (per-program summaries, bottom-up). Captures function; non-deterministic, context
  pressure at scale, weak evidence. User rejected stored summaries at every level as not robust.
- **C (chosen). Hybrid.** Deterministic graph + deterministic similarity features give a draft with evidence and
  a confidence per program. A planner agent then reviews only the uncertain parts, exploring source on demand
  through a read-only explorer sub-agent, and edits the plan through validated tools. Nothing the agent reads is
  stored as a summary; what it concludes is stored as the rationale of a plan decision.

Loop
- **(i) Chosen: evolve the existing `AgentLoop` into a configurable `Agent`** (spec + policy + hooks + prompt
  sections), keeping the registry separate and a thin `AgentLoop` shim for `Runner`.
- (ii) Class hierarchy per agent type (BuilderAgent, PlannerAgent...). Rejected: behaviour spread across
  subclasses, harder to mix capabilities.
- (iii) Adopt an external agent framework. Rejected: provider coupling, heavier dependencies, the current loop
  already handles the hard parts (malformed tool JSON, nudges, compaction).

## 5. Part A: the agent loop template

### 5.1 Pieces and ownership

| Piece | File | Owns |
|---|---|---|
| `ToolRegistry` (existing, extended) | `harness/registry.py` | tool definitions: name, description, JSON schema, handler, **tags** (`read`, `write`, `exec`, `network`, `plan_edit`, `finish`, ...). Dispatch, arg filtering, error-to-text, clipping. No knowledge of agents. |
| `ToolPolicy` (new) | `harness/policy.py` | privileges: allow/deny by tool name or tag, per-tool call limits, "ask" tools routed to an approval callback, optional per-tool argument guards (e.g. path must be under `staging/`). Returns allow / deny(reason) / ask. |
| `PromptBuilder` (new) | `harness/prompt.py` | the system prompt as ordered named sections; each section is a string or a zero-arg callable re-evaluated every turn (e.g. notes, budget left). |
| `AgentSpec` (new) | `harness/agent.py` | plain data describing one agent: name, prompt sections, policy, max_steps, max_tokens (optional), context settings, recovery limits, stop conditions, finish schema. Copyable (`spec.copy(**changes)`) so a base template can be specialised. |
| `Agent` (new) | `harness/agent.py` | the loop. Holds an LLM, a registry, a spec, an event log, hooks. |
| `AgentLoop` (shim) | `harness/loop.py` | old constructor and `run(system_fn, user_msg, done, max_steps) -> str` implemented on `Agent`, so `Runner` and existing tests keep working. |

### 5.2 Agent API (shape, not final signatures)

```python
agent = Agent(llm, registry, spec, events=ev, log=print)
agent.set_system_prompt("...")            # replace all sections with one
agent.add_prompt_section("notes", lambda: pad.read(), after="role")
agent.remove_prompt_section("notes")
agent.set_policy(ToolPolicy(allow_tags={"read"}, deny={"write_file"}, limits={"submit": 5}))
agent.allow_tools("search", "read_lines"); agent.deny_tools("build")
agent.set_budget(max_steps=40, max_tokens=200_000)
agent.add_stop_condition("green", lambda state: state.data.get("green"))
agent.set_context(ContextManager(budget=9000))
agent.on("before_tool", hook)  # also: before_model, after_model, after_tool, on_text_reply, on_stop
agent.expect_result(schema)               # adds the built-in `finish` tool with this argument schema
result = agent.run("task message", state=None)   # -> AgentResult
tool = agent.as_tool("explore_program", "...", input_schema, make_message)  # sub-agent exposed as a tool
```

`AgentResult`: `stop_reason` (`finished` | stop-condition name | `max_steps` | `max_tokens` | `gave_up` |
`llm_error: ...`), `output` (validated `finish` arguments, or None), `steps`, `usage` (tokens in/out),
`messages` (final transcript), `state` (the per-run mutable dict tools and hooks share).

### 5.3 Loop behaviour (one turn)

1. Rebuild the system prompt from sections; context manager elides old output if over budget (existing logic).
2. Offer tool schemas = registry tools the policy allows (the model never sees denied tools).
3. Call the LLM. Recoverable error -> corrective user message, retry (existing). Unrecoverable -> stop.
4. Text-only reply -> nudge, or `gave_up` after N (existing; configurable message and N).
5. For each tool call: policy check again at dispatch (a call to a tool not offered is refused with a message,
   never executed) -> `before_tool` hooks (may veto or rewrite args) -> registry dispatch -> `after_tool` hooks
   (may rewrite output) -> tool message appended. `ask` tools call the approval callback (default: deny).
6. `finish` called with valid arguments -> stop with `output`. Invalid arguments -> error text back to the model.
7. Stop conditions checked after each turn; budgets checked before each model call.
8. Every step emits events (`llm_usage`, `tool_called` with allowed/denied, `context_compacted`, `agent_stopped`).

### 5.4 Sub-agents

`Agent.as_tool(...)` wraps a configured agent (typically read-only) as a tool another agent can call. Each call
runs a fresh child `Agent` (fresh messages, own budget, events labelled `parent/child`) and returns its
`output` (or a short failure text). This is how the planner explores source on demand.

## 6. Part B: architecture planner (Phase 2, part 1)

Package `planner/architecture/` (new; `planner/ordering/` later for part 2). CLI:
`bin/planner architecture --workspace W [--target java|python|go] [--no-agent]`.
`--no-agent` produces the deterministic draft only (no LLM).

### 6.1 Input: the KB contract (`planner/kb.py`)

A `KnowledgeSource` protocol returns plain records; `Phase0Kb` reads Phase 0's `kb/` files; `FixtureKb` reads a
JSON fixture for tests. Facts used (each optional except programs):

| Fact | From Phase 0 today | Missing today |
|---|---|---|
| programs (id, file, loc, kind batch/online/subprogram, parse confidence) | inventory, units, coverage | kind batch/online (infer: CICS -> online, LINKAGE+USING -> subprogram) |
| CALL / LINK / XCTL edges | call_graph | parameter bindings |
| copybooks per program | inventory | record copybook vs code copybook (inventory subkind has it) |
| file/dataset use per program (read/write) | data_flow CRUD (strict only) + JCL DDs | ASSIGN-to-DD binding |
| DB tables per program (read/write) | none | needs SQL extraction |
| JCL jobs: steps, programs, datasets, order | inventory jcl_steps | IKJEFT01 RUN PROGRAM binding, PROC expansion |
| identifiers and comments per program | source + units/data dictionary | none |

`docs/phase2/KB_CONTRACT.md` lists these for the KB team, marking which ones change the plan most.

**KB first (user requirement, at approval): the planner primarily uses the KB; simple searches on the
codebase are fine.** It does not extract facts from source (user: make assumptions about what the KB phase
will provide and pass them on). Source access is limited to: a regex `search_code` (file:line: text, capped),
bounded `read_lines`, and a comment-line scan for the similarity signal. No parsing of source in the planner. DB tables, ASSIGN-to-DD binding and
IKJEFT01 program binding are assumed to come from the KB per `KB_CONTRACT.md`; the fixture KB has them.

**Store identity.** A store is identified by its dataset name (DSN, GDG base without generation, temp
`&&X` qualified by job) or DB table name. A program-level file (`ASSIGN` name) is resolved to a dataset when
the KB binds it, or, in the `Phase0Kb` adapter, by joining the program's `ASSIGN` names with the DD names of
the JCL step that runs that program (a join over KB data only). An `ASSIGN` name that cannot be resolved stays
a program-private store `PROGRAM:ASSIGN` and adds no edges, so generic ddnames like `INFILE` never merge
unrelated programs.

Consequence stated plainly: on today's Phase 0 KB, the 59% of CardDemo programs parsed by the tolerant
analyser contribute few edges and land in the "uncertain" set. Plan quality on real estates depends on the
KB contract being met.

### 6.2 Deterministic draft (`graph.py`, `features.py`, `cluster.py`, `roles.py`)

1. **Program graph.** Undirected weighted graph over programs. Edge weights (defaults, configurable):
   CALL/LINK/XCTL 3.0; shared record copybook 2.0 x IDF; same dataset or table written by one and read by the
   other 2.0 x IDF; both read the same dataset/table 1.0 x IDF; same JCL job 0.5. IDF = log(N / users) so a
   copybook or file used by everyone (common headers, SQLCA) contributes almost nothing.
2. **Similarity signal ("does the same thing"), no LLM.** Per program: a TF-IDF vector of identifier tokens
   taken from the KB (program, paragraph and data item names; split on `-`, drop prefixes like `WS`, `LK`,
   numbers) plus comment words from a simple comment-line scan; and an I/O signature from the KB (set of
   record types, datasets, tables, CRUD verbs). Cosine similarity above a threshold adds an edge
   (weight 1.0 x similarity). Keeps "similar programs on different data" close.
3. **Utilities first.** Programs called by programs in >= 3 (configurable) different draft communities, or
   with fan-in >= 5 and no file/DB writes, are taken out and assigned to a `shared-utilities` module.
4. **Cluster** the rest with Louvain (networkx, fixed seed). Isolated programs get their own module only if
   they have no similarity edge; otherwise they join their most similar program's module.
4b. **Size post-pass.** Target module size is a configurable band (default 3 to 25 programs). A community
   above the band is re-clustered on its own subgraph at a higher Louvain resolution until its parts fit or
   stop changing; a community below it (1 to 2 programs) merges into the neighbouring module it shares the
   most edge weight with, unless it has none (then it stays, flagged for review). Utilities are clustered
   the same way among themselves by the similarity signal, giving several `util-*` modules
   (e.g. dates, error handling, DB access) instead of one dump; a single `shared-utilities` module only when
   there are fewer than the band minimum.
5. **Roles.** Record copybooks used by one module -> module-local types; by >= 2 modules -> `shared-types`.
   Procedure (code) copybooks become `shared_code` entries: placed in the single module that uses them, or in
   the closest `util-*` module when several modules do; they add graph edges with the same weight as record
   copybooks. Translators implement them once at that location and call them, rather than inlining copies.
   Each dataset/table -> one data-access interface owned by the module that writes it; several writing modules
   -> owner = most writes, others flagged `shared_write` for review. Each JCL job -> one orchestration entry
   (job id, ordered steps, program entry points, datasets passed between steps).
6. **Confidence per program** = share of its edge weight inside its module (0..1), plus a flag when its KB
   facts are tolerant/low-confidence. Programs below a threshold (default 0.6) or flagged are "uncertain".
7. **Evidence**: every assignment keeps the top edges that justify it (kind, other program, shared item).

### 6.3 Agent review (`agent.py`, `tools.py`)

The planner agent is an `Agent` with:
- **KB read tools** (tag `read`, the primary tools): `module_overview`, `program_facts`, `program_edges`,
  `who_uses` (copybook, dataset, table), `similar_programs`, `unit_facts`.
- **Code search tools** (tag `read`, secondary): `search_code` (regex, capped results) and `read_lines`
  (bounded range). The system prompt tells the agent to answer from the KB first and search code only for
  what the KB does not hold.
- **Explorer sub-agent** `explore_program(program_id, question)`: read-only `Agent` with the same KB read
  tools and code search tools,
  returns a structured finding `{answer, evidence: [file:line]}`. Used only for uncertain programs.
- **Plan-edit tools** (tag `plan_edit`), each validated deterministically before applying: `move_program`,
  `merge_modules`, `split_module`, `rename_module`, `set_module_purpose`, `mark_utility`,
  `set_owner(store, module)`. Every edit requires `reason` and `evidence` (list of fact refs or file:line); an
  evidence ref that does not exist in the KB or source is rejected. Edits go to an edit journal.
- **Work plan:** (1) per-module pass: for each module with uncertain programs, one bounded agent run reviews
  only those programs and names/describes the module; (2) one global pass over the module-level graph
  (modules as nodes, cross-module edges, shared-write stores, utilities) to merge/split/rename and settle
  ownership; (3) `finish`.
- Budgets: max steps per pass, max explorer calls per pass, total token cap; when exhausted, remaining
  uncertain programs keep their draft assignment and are listed as open questions.

### 6.4 Output (`plan.py`, `render.py`)

`W/plan/architecture.json` (versioned schema, validated):
- `modules[]`: id, name, purpose, programs[] (with confidence, evidence, decided_by draft|agent), local_types[],
  owned_stores[], depends_on[] (modules it calls or reads from)
- `shared_types[]` (copybook -> type name, used_by modules), `shared_code[]` (procedure copybook -> location
  module, used_by programs), `stores[]` (dataset/table, kind, owner,
  readers, writers, interface name, shared_write flag), `jobs[]` (orchestration entries), `utilities` module
- `layout`: target language package/directory per module (rendered deterministically for java/python/go)
- `edits[]`: the agent's edit journal (what changed from the draft, why, evidence)
- `open_questions[]`: uncertain programs left as drafted, shared writes, missing KB facts that reduced confidence
- `inputs`: kb_version / source hash, config, seed, model, prompt version

`W/plan/architecture.md`: the human review document rendered from the JSON (module table, per-module purpose
and programs with reasons, shared types, data ownership, jobs, open questions, what the agent changed). The
later human-review flow reads/writes the JSON; an uploaded architecture must validate against the same schema.

Invariants checked by `validate.py` (also run after every edit): every program in exactly one module; every
store has one owner; shared types used by >= 2 modules; no empty modules; evidence refs exist.

Part 2 needs from this plan: module membership, inter-module dependencies, store ownership and job order.
All are present.

## 7. Testing

- Loop: scripted LLM (existing pattern) for policy denial at offer and dispatch time, `ask` approval, tool call
  limits, hooks veto/rewrite, prompt sections refreshed per turn, `finish` schema validation, stop conditions,
  token budget, sub-agent as tool. Existing 15 tests keep passing through the shim.
- Planner: fixture KB of a small estate (about 15 programs: account, card, transaction groups, two utilities,
  one ambiguous program, one batch job chain, one ubiquitous copybook, one table written by two modules).
  Assert the draft clusters, utilities, shared types, ownership, confidence ordering. Agent pass with a scripted
  LLM: valid edits applied, invalid evidence rejected, budget exhaustion produces open questions. Renderer
  snapshot for java/python/go layouts. `Phase0Kb` adapter tested on a small KB built by Phase 0's format.
- No network, no Docker.

Definition of done for this iteration: all of the above pass; `bin/planner architecture --no-agent` runs on a
KB built by Phase 0 for `docs/phase0_review_probe/` and on the fixture; the agent pass runs end to end on the
fixture with a scripted LLM. A real-LLM run on a real estate (CardDemo) waits for the KB contract facts and an
LLM provider with enough quota; it is not required now.

## 8. Decided in conversation

- Hybrid planner (C); modules = several programs that belong together / do similar work; program logic stays
  intact; shared copybooks -> shared types; I/O behind per-store interfaces; JCL -> thin orchestration;
  shared utilities module.
- Plan is reviewed by a human later (elicitation); a rejected plan is replaced by a developer-supplied
  architecture artifact (not built now).
- Verification of redesigned code is out of scope for now.
- No precomputed per-program LLM summaries as a grouping signal.
- Assumptions about upstream KB facts are written down for the KB team.
- The planner uses the KB primarily; simple code searches (regex search, bounded line reads) are allowed.
- Work happens on branch `phase2`, created from the current state and merged with `origin/phase0`.

## 9. My calls (correct any)

- Plan is language-neutral; Java/Python/Go only affect the rendered `layout`.
- Loop core stays stdlib; planner may use networkx.
- New code in `harness/` (loop pieces) and `planner/architecture/` (planner); `bin/planner` entry point.
- `Runner` migrates to `Agent` via the `AgentLoop` shim; no behaviour change for the translator.
- Default weights/thresholds as in 6.2, all in config under `planner.architecture`.
- Approval callback for `ask` tools defaults to deny (no human in the loop yet).
- Planner reads no facts from source beyond identifiers/comments; missing facts are the KB's job (6.1).
- Stores keyed by dataset/table; unresolved `ASSIGN` names stay program-private (6.1).
- Module size band 3 to 25 with split/merge post-pass; utilities split into several `util-*` modules (6.2).
- Procedure copybooks become `shared_code`, implemented once and called (6.2).
- Done = fixture + probe runs, no real-estate LLM run yet (7).
- Nothing is committed: `integration` has your uncommitted reorg, so I leave commits to you.

## 10. Left to the builder

Exact method signatures, file split inside the packages, the TF-IDF tokeniser details, fixture contents,
event field names beyond those listed, markdown layout of the review doc.
