# Phase 0 (Knowledge Base) review

Reviewed: branch `origin/phase0` (58 commits by one author, ~11k lines under `phase0/`), against the current `integration` working tree.
Method: read the code, ADRs, notes and committed eval results; built the KB myself for `corpus/payroll` and for a synthetic
enterprise-style probe (`docs/phase0_review_probe/`: a DB2 batch program, a CALLed subprogram, a JCL stream) and grepped the output.

## Verdict

Phase 0 is a **high-quality static analyser for a narrow slice of COBOL** (arithmetic, storage layout, paragraph control flow),
and it is rigorously tested for *that*. It is **not yet a knowledge base**: it holds almost nothing a worker agent cannot
get by reading the source, and it holds nothing about the things you listed (business rules, DB, batch behaviour, external dependencies).
The effort is aimed at what is easy to measure, not at what a migration agent is missing.

Your three concerns are all correct. Evidence follows.

## 0. Context that changes the question: nothing consumes the KB today

- On `integration` the worker agent's tools are `list_files, read_file, read_lines, search, write_file, build, notes, submit`
  (`extras/cobol_java/tools.py`). The only KB reference left in `harness/`, `extras/`, `adapters/` is a `kb_version` string pass-through.
  `docs/HARNESS_PIPELINE.md` lists "knowledge base / hazard hints" as *removed on purpose*, pending ablation.
- Even before that, in the old Phase 1 (`git show origin/integration:phase1/phase1/tools.py`), only `rules_for` and `gaps_for` went through
  `phase0 query`. Every other exploration tool (`unit_info`, `hazards`, `data_flow`, `context_pack`, ...) used Phase 1's *own* analyser index.
  (`toolchain` was also read, by the runner, for the build command.) So 3 of the 9 contract query methods were ever used, and only 2 by the agent.
- Phase 0's own metrics (E1-E11) are all *intrinsic* (is the fact correct?). None measures *utility* (does an agent with the KB
  need fewer attempts, fewer tokens, reach a higher tier?). Nobody can currently say whether any artifact below earns its place.

## 1. Is everything in the KB needed? (artifact by artifact)

Test applied: can a worker agent with `read_file` + `search` get this cheaply and reliably on its own?

| Artifact | Hard for the agent alone? | Verdict |
| --- | --- | --- |
| Byte `offset` / `byte_length`, REDEFINES/OCCURS storage, group expansion | **Yes**, LLMs get overlays wrong; verified against cobc listing + a GnuCOBOL probe (E3, 5,559 comparisons, 0 mismatches) | **Keep.** Best work in Phase 0 |
| Alias-aware reads/writes (INITIALIZE of a group, PERFORM VARYING control item, REDEFINES) | **Yes.** Old Phase 1 analyser had 133 write / 46 read violations on these (E7) | **Keep** |
| `mapping_rules`, `semantic_gaps`, `runtime/`, `driver_template`, `encoding_fixtures`, `toolchain` | **Yes**, target-side knowledge, not in the source. Contract-required | **Keep.** Check the prompt in `extras/cobol_java/prompts.py` doesn't duplicate it divergently |
| Repo-level call graph, callers/callees, reverse indexes (`readers_of`, `writers_of`), copybook resolution, dynamic-CALL resolution | **No at 100 lines, yes at 60k lines** (CardDemo) | **Keep**, but only justified at repo scale. Test there, not on toy programs |
| JCL job/step/DD rows and the step-to-step dataset hand-off (DR-003 in my probe correctly found `SORT` writes `&&SORTED`, next step reads it) | **Yes**, cross-file | **Keep and extend** (section 3) |
| Unit spans, direct `performs`, paragraph list | No, one `search`/`outline` | Redundant at small scale. Cheap, harmless |
| Per-field PIC/usage/digits/scale/signed | No, it is the `WORKING-STORAGE` text, re-encoded | Redundant. Only the offset/aliasing part adds value |
| **Hazards** (`G-OVERFLOW`, `G-TRUNCATE`, ...) | Partly. Reproduces old Phase 1 scanner 1:1 | **Rework.** CardDemo: 1,895 hazard sites, 772 (41%) are `G-FALLTHROUGH` (the normal state of COBOL). The same ~150-char fix hint is repeated per site, and every unguarded `COMPUTE` is "high". For `CALC-DEDUCTIONS` (23 lines) the context packet is 3.5k chars, 4x the source, mostly this. The verifier already decides correctness, so this is signal-to-noise, not safety. No precision number exists for hazards |
| **Decision records** (`kb/docs/decisions/DR-*.md`) | No | **Cut or replace.** They are templates triggered by fact patterns; `Rationale: unknown` in all 85 CardDemo records. DR-001 is a list of PIC clauses. Real value would be rationale mining (comments, change logs), which the code does not attempt |
| **Mermaid views** (`kb/docs/views/`) | Not for agents | Human artifact, duplicates `call_graph.json`/`data_flow.json`. It is hashed into `kb_version`, so a cosmetic change invalidates every downstream pin. Move out of `kb/` |
| `coverage.json` per-line "unattributed" lists | No | This is Phase 0's QA output, not knowledge. Keep a per-program *confidence/parse-status* summary (agents should know a fact is tolerant-quality); move the line lists to eval |
| Provenance on every record | n/a | 16% of `data_dictionary.json`; fine, but repeated per field instead of per span |
| `phase0 eval` harness (`evaluation/`, 2.2k lines vs 2.5k lines of extraction stages), E7 baseline vs Phase 1 analyser | n/a | E7 benchmarks against code that no longer exists on `integration`. E10 (metamorphic) and E3/E4 (real oracles) are worth keeping; E5 is self-labelled circular (shares the front end) |

## 2. Deterministic only vs an exploration agent

The one LLM stage (G, `stages/summaries.py`) is built so it cannot add knowledge:

- Input is the paragraph's own source plus "FACTS" that are the same static facts (reads/writes/performs/hazard ids).
- System prompt: "**do not guess business intent**"; "mention data items and paragraphs ONLY by the names listed under ALLOWED NAMES; never name anything else (no other fields, files, programs...)".
- The entity check then rejects any summary naming something outside the unit's facts. So a summary may not mention a table, a file in another
  program, a business concept, or another unit. It is a paraphrase of facts the unit already has.
- It is off by default, per-paragraph, and E11 measures only hallucination rate (3B/9B local models), not whether summaries help anyone.
- Also: the summary schema is a single `Unit.summary` string. There is nowhere to put a structured finding.

Where an exploration agent *does* beat deterministic extraction (all absent today):

1. **Intent and naming** of a rule or program ("freeze delinquent account"), glossary of field meaning from names/comments.
2. **Linking across artifacts** that have no syntactic edge: JCL `SYSTSIN` `RUN PROGRAM(ACCTUPD)` to the program, ddname to `SELECT ... ASSIGN TO`, DB table to owning module, program to nightly job.
3. **Dead/obsolete code and conflicting duplicates** (the same fee rule coded in 3 programs).
4. **Classifying residue** the parser rejects (the tolerant 59% on CardDemo) instead of dropping to a regex pass.

The pattern that fits your constraints (and already exists in miniature in their entity check): deterministic extractor produces
*candidates with evidence line ranges*; an exploration agent with read-only tools over source + KB proposes structured records;
a verifier rejects any record whose cited lines or named entities do not exist (their ETF check, generalised to structured output).
Keep it a separate build stage with its own cache and a pinned model so `kb_version` stays reproducible.

## 3. What is missing (your point 3), with evidence from the probe

Probe: `docs/phase0_review_probe/` (`ACCTUPD.cbl` uses `EXEC SQL`, an indexed file, `CALL`, 88-levels, thresholds and two commented
business rules; `NIGHTLY.jcl` runs it under `IKJEFT01` with COND, a temp dataset and instream SORT cards).
Build: `phase0/bin/phase0 build --workspace <copy of probe>`.

| Need | What Phase 0 produced | Evidence |
| --- | --- | --- |
| **Embedded SQL / DB schema** | Nothing but `unsupported: ['sql']` on the paragraph. No table, operation, columns, cursor, host-variable mapping, SQLCODE handling, DCLGEN/DDL ingestion | `ACCOUNT_MASTER`, `SQLCODE`, `DCL-BAL` appear nowhere in `kb/`. Inventory only scans `EXEC SQL INCLUDE` for copybook names (`stages/inventory.py`) |
| **Soundness of facts on SQL programs** | `APPLY-TRANS` reads 5 / writes **0**; `WS-DAYS-PAST`, `WS-TIER` (set by `SELECT INTO`) show *no writer* in the data view | A consumer calling `writers_of WS-DAYS-PAST` is told nothing writes it. E5's "0 violations" covers D1+D2 strict programs only |
| **Why SQL programs are degraded** | `cobc -E` rejects raw `EXEC SQL`, so the whole program drops to the tolerant analyser: confidence 0.6, no offsets/layout, empty file-CRUD matrix | `ACCTUPD`: `parse_status: tolerant`, `data_flow.files == []`. On CardDemo **26 of 44 programs (59%)** are tolerant: exactly the DB2/CICS ones |
| **Business rules** | None. No rule records, no constants (`90`, `5000`, `0.015`, `2.50`), no `GOLD` tier, comments `BR-17`/`BR-22` not captured | greps return nothing. Only 88-level names exist as dictionary entries (and none for the tolerant program) |
| **Batch behaviour** | Step/DD rows and dataset hand-off recovered. Missed: `IKJEFT01` + `SYSTSIN RUN PROGRAM(ACCTUPD) PLAN(ACCTPLN)` (the real program and DB2 subsystem), `COND` logic, instream `SORT FIELDS` (a real business transform), PARM, GDG `(+1)`, step order/restart semantics, temp-dataset edge dropped from the flow view | batch_flow view shows `IKJEFT01`, never `ACCTUPD`; `ACCTPLN`, `DB2P`, `COND`, `SORT FIELDS` absent from KB |
| **File to DD to dataset binding** | Program files (`TRANIN`, `XREFVSAM` via `ASSIGN TO`) never linked to JCL DDs; VSAM/indexed access mode and key not recorded | `TRANIN` appears only in inventory JCL rows |
| **External dependencies / interfaces** | Static `CALL` edge only. No parameter contract (`CALL 'DATEUTIL' USING WS-PARM-DATE` to `LK-DATE`), no CICS resources (files, queues, maps, `RETURN`/`LINK` COMMAREA), no MQ/IMS, no environment (`ACCEPT FROM DATE`, `PARM`, SYSIN) as inputs | `LINKAGE` is a bare "unsupported" counter; CardDemo's top unsupported list is `CALL (16)`, `LINKAGE (8)`, indexed files (11) |
| **Error and exit semantics** | Only `RETURN-CODE` writers (DR-003 in PAYROLL). Not `FILE STATUS` use, `SQLCODE` checks, `ABEND`/`STOP RUN` paths | |

Suggested additions, in order of value for a migration agent:

1. **SQL/CICS-aware front end**: a small EXEC-block stripper/precompiler shim in front of `cobc -E` so SQL programs stay on the strict path, plus a parser for the
   statements that yields `{table, op, columns, host_vars, cursor, sqlcode_checked}` per paragraph; fold host-variable reads/writes into `reads/writes`.
   Optional DDL/DCLGEN ingestion for the schema.
2. **Interface/dependency model** (`interfaces.json`): files (ASSIGN-to-DD-to-dataset, org, access, key), DB tables, CALL parameter bindings, CICS resources, env inputs, per program, with the JCL step that supplies each.
3. **JCL depth**: PROC expansion, `PARM`, `COND`/`IF`, in-stream data classification (`SYSTSIN`, `SYSIN`), resolve `IKJEFT01 -> RUN PROGRAM(...)`, job ordering, restartability.
4. **Business-rule candidates** (`rules.json`): every decision point (`IF`/`EVALUATE`) that gates a store, SQL write, file write or `RETURN-CODE`, with literals, 88-names resolved, nearby comment text, evidence lines. Deterministic skeleton first; exploration agent names, groups and de-duplicates them (section 2). Bonus: thresholds (`90`, `5000`) are exactly the boundary seeds the verifier's T1 generator wants.
5. Drop or demote the items marked Cut/Rework in section 1 to make room.

## 4. Problems with the results themselves

- **Headline "0 violations / 100%" is on 38 toy programs** (D1+D2, ~3.2k lines written to exercise semantics). The realistic set (CardDemo, 61k lines) has **no ground truth**: only coverage and hazard counts.
- **"98.7% of lines accounted for" counts tolerant-analyser lines as attributed.** It measures attribution, not correctness. On D3, 59% of programs are tolerant.
- **E6 (the only independent precision check for reads/writes) is still "pending": no gold files exist.** E5's 31% "writes observed changing" is a weak lower bound, and E5 shares the front end with Phase 0 (they say so).
- **E4's check is deliberately permissive** (any earlier performer may justify a transition), also acknowledged.
- The self-comparison (E7) is against the analyser the team removed, so it no longer supports a decision.

## 5. Integration risks on your reorg

- `phase0/phase0/stages/tolerant.py` imports `phase1/` from the repo root. Your working tree deletes `phase1/`, so merging phase0 as-is breaks the tolerant fallback (and the E7 baseline) with `ImportError`.
- ADR-0001: Phase 0 imports `verifier.cobol` internals, a stated deviation from agreement principle 1. `TEAM_NOTES.md` lists real verifier bugs it found (SECTION `end_line`, `datadiv` failing on CardDemo copybooks, `detect_format` on free-format): these are worth fixing regardless.
- `integration/e2e_scripted.py` is modified on both sides (phase0 adds `PHASE0_CMD`); expect a conflict.

## 6. Recommended order of work

1. Decide what the agent will actually query, then add the **ablation switch** (KB tools on/off) so utility can be measured on the corpus plus CardDemo. Everything else is guesswork without it.
2. Fix the SQL/CICS front-end gap (section 3.1); it moves 59% of CardDemo off the degraded path.
3. Add interfaces + JCL depth (3.2, 3.3), then rule candidates with the agent stage (3.4, section 2).
4. Cut/rework section 1 items; move views and per-line coverage out of the hashed `kb/`.
5. Replace E7 with an extrinsic metric (attempts-to-green, tokens, tier reached with vs without KB); get E6 gold done.

## What I did not verify

- I did not build CardDemo (not on disk, not fetched); all D3 numbers are from their committed `metrics.json`/`RESULTS.md`.
- Probe is one synthetic workspace; real DB2 shops precompile before `cobc`, which changes how the SQL gap should be fixed, not whether it exists.
- Stage G was not run (needs Ollama); the conclusion comes from its prompt, config and entity-check code.
- Hazard precision, and the correctness of the 27 rules/21 gaps content, were not assessed.
