# Phase 1 · Translator (bare bones)

## How to call me
```
export GROQ_API_KEY=...            # Groq inference
export PHASE0_CMD=phase0 PHASE2_CMD=phase2   # how to invoke the other modules (defaults shown)
phase1/bin/phase1 run --workspace W [--units CALC-FEE,READ-INPUT] [--max-steps 40]
```
Optional in `config.yaml`: `phase1: {model: llama-3.3-70b-versatile}` (or env `PHASE1_MODEL`).

## What it does
`agent.run`: query KB for units -> order leaves-first -> per unit, a Groq tool-calling loop
(KB tools, read/write staging files, build, `submit`). `submit` snapshots `staging/` into
`submissions/S-NNNN/`, runs `phase2 check`, and returns the report (findings, counterexamples,
kb_refs) to the agent. Green ends the unit; budget exhaustion emits `unit_abandoned`.
Events emitted: `unit_started`, `submission_created`, `unit_abandoned`, `llm_usage`.

## Not yet (later)
Checkpointing/resume, task decomposition, sub-agents, context compaction, `--stub` mode,
contract-schema validation of submissions, `kb_gap_reported`.

## Codebase understanding (no LLM needed)
`phase1 analyze --workspace W` statically analyses `W/source/` (fixed/free format, COPY + REPLACING expansion)
and writes `W/phase1/index.json` + `architecture.md`: programs, units (paragraph/section), data dictionary,
reads/writes per unit, PERFORM/CALL graph (CICS XCTL/LINK and `MOVE 'X' TO VAR` dynamic calls resolved),
migration layers (leaves first), shared copybooks, and unsupported-construct flags
(file_io, cics, sql, goto, alter, redefines, ...). Multi-program repos get ids like `PROG.PARA`.
`phase1 tool --workspace W <tool> '<json args>'` calls any exploration tool directly.

## Agent flow
1. **Survey** agent: overview -> drill down with `program_info/outline/search/read_lines/unit_*` -> `set_plan`
   (units to migrate leaves-first + skipped with reasons) -> `phase1/plan.json`. Falls back to a heuristic plan.
2. **Translate** agent per unit: explore, write staging files, build, `submit`, iterate on Phase 2 reports.
3. **Context**: tool output clipped; old tool results elided past a char budget (pairing kept valid);
   `notes` scratchpad (`phase1/notes.md`) is re-pinned in the system prompt every turn.

## Beyond the call graph (novel parts)
| Feature | What it does | Idea it builds on |
|---|---|---|
| **Semantic-hazard scanner** (`hazards`) | Static scan for COBOL behaviours a naive translation silently gets wrong: high-order truncation on narrowing MOVE, ADD/MULTIPLY/COMPUTE overflow without ON SIZE ERROR, ROUNDED vs Java rounding, sign loss, group MOVE, num<->alpha MOVE, GO TO, fall-through, COMP-3. Each hazard carries a KB gap id (`G-TRUNCATE`...), line number and fix hint; per-unit risk score. | Bug taxonomy of LLM code translation: Pan et al., "Lost in Translation" (ICSE'24) |
| **Module clustering** (`clusters`) | Label propagation over PERFORM edges + shared *written* fields (IDF-weighted so globals like status flags are ignored) -> candidate modules; programs clustered into subsystems via calls + shared copybooks. Migration plan keeps a module together. | Mono2Micro (FSE'21), Service Cutter (2016) |
| **Context packs** (`context_pack`) | One budgeted read per unit: source, typed field table, hazards + fixes, callee summaries (bottom-up), data producers/consumers (data-dependence slice), module mates. Auto-injected into the translate prompt. | AlphaTrans (FSE'25) bottom-up repo translation, CodePlan, RepoGraph |
| **Atlas report** | `phase1 report --workspace W` -> `W/phase1/atlas.html`: interactive program/unit graphs, hazard breakdown, plan. | - |
