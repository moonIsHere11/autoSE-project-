# What Phase 2 (architecture planning) needs from the KB

Audience: the KB team. The planner (`planner/`, branch `phase2`) reads the KB only through the records below
(`planner/kb.py`). Today it reads Phase 0's `kb/` files through `planner/kb_phase0.py`. If the KB adds a file,
only that adapter changes.

## The records

| Record | Fields | Used for |
| --- | --- | --- |
| `Program` | id, file, loc, kind (`batch`, `online`, `subprogram`), confidence (1.0 strict parse, lower if heuristic), copybooks, calls, identifiers (paragraph and data item names) | graph nodes, CALL edges, copybook edges, vocabulary similarity, utility detection, "low KB confidence" flags |
| `Copybook` | name, kind (`record` = data layout, `code` = shared procedure text) | shared types vs shared code |
| `StoreUse` | program, store (dataset name, table name, or `PROGRAM:ASSIGN` when unresolved), store_kind (`dataset`, `table`, `private`), mode (`read`, `write`) | data-coupling edges (the strongest signal after CALL), data ownership, repository interfaces |
| `JobStep` | job, step, order, program (or none), datasets read, datasets written | same-job edges, the jobs/orchestration layer, step-to-step data hand-offs |
| units | per program: unit records (id, kind, calls, performs) | shown to the planner agent on request |

## What Phase 0 gives today, and what is missing (most important first)

Measured on the review probe (`docs/phase0_review_probe/`, a DB2 batch program, a subprogram, a JCL job). The
planner's output there is one module, no data stores, and three `missing_kb_fact` / `low_kb_confidence`
questions. Each item below names what the planner does without it.

1. **DB tables per program, with read/write** (`EXEC SQL` SELECT/INSERT/UPDATE/DELETE, cursors, the table each
   touches). Phase 0 marks the paragraph `unsupported: sql` and records nothing else.
   *Without it:* no table stores, so no data ownership or table-based grouping for DB2 programs. These are
   usually the core business programs.
2. **Program file -> dataset binding.** Phase 0 records a program's files by `ASSIGN` name, and JCL DDs per
   step. The planner joins the two when the step runs the program by name (`EXEC PGM=X`). Missing: programs run
   through `IKJEFT01`/`IKJEFT1B` (`RUN PROGRAM(X)` in SYSTSIN, i.e. every DB2 batch program), PROC expansion, and
   symbolic parameters.
   *Without it:* the step shows "program unknown" (`missing_kb_fact`), and the program's files stay
   program-private, adding no edges.
3. **Facts for SQL/CICS programs from the strict parser.** `cobc -E` rejects raw `EXEC SQL`/`EXEC CICS`, so these
   programs fall back to the tolerant analyser (confidence 0.6, no file CRUD). On CardDemo that is 26 of 44
   programs. A precompiler shim that blanks the EXEC blocks before `cobc -E` would keep them on the strict path.
   *Without it:* the programs are flagged `low_kb_confidence` and sent to the planner agent for review, so LLM cost
   grows with the size of the estate.
4. **Program kind.** The planner infers it: `online` if a unit mentions CICS, `subprogram` if called and not run
   by JCL, else `batch`. An explicit kind from the KB (CICS transaction, batch main, called routine) would
   replace the guess.
5. **Copybook kind.** Phase 0's inventory `subkind` (`procedure` vs `data`/`sql`) is used as is; it is already
   adequate.

Lower priority but useful: CICS resources per program (files, queues, maps, `LINK`/`XCTL` targets with COMMAREA),
MQ queues, and `CALL ... USING` parameter bindings. These would become more store kinds and better edges.

## Not needed by the planner

Per-field byte offsets, hazards, decision records, Mermaid views and per-line coverage are not read by the
planner. They may matter to the translators or the verifier, but not to architecture planning.
