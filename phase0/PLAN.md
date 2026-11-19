# Phase 0 plan (branch `phase0`, from `integration`)

No dates: milestones run back to back, as fast as possible. Running log of actions and decisions: `phase0/notes.md`.

Package `phase0/` = own `pyproject.toml` (`phase0` pkg, depends on installed `cobol-verifier`), wrapper
`phase0/bin/phase0`, tests in `tests/phase0/`. Makefile `lint`/`typecheck` extended to cover `phase0`.
Read-only libraries: `verifier.cobol.*` (strict, ADR-0001), `phase1.phase1.cobol.*` (tolerant fallback, ADR-0002).
No edits to `verifier/`, `phase1/`, `phase2/`.

| Ms | Files (all under `phase0/phase0/` unless noted) | Done when |
| --- | --- | --- |
| M1 | `schema.py` (pydantic 1.1 models, JSON Schema export to `phase0/schemas/`), `cli.py`, `workspace.py` (config, events), `stages/inventory.py` (A), `catalog/gaps.json`+`rules.json` (curated, cited), `target.py` (toolchain, runtime copy of `runtimes/java/src/cobolrt`, `driver_template/` + encoding fixtures), `manifest.py` (kb_version hash), `query.py` (9 contract methods, teaching errors) | build writes valid manifest/inventory/toolchain/gaps/rules/runtime/driver; `e2e_scripted.py` passes with real `phase0` |
| M2 | `stages/parse.py` (B: `preprocess`+lexer+parser, fallback), `stages/layout.py` (C: `datadiv`), `units.json`, `data_dictionary.json`, `eval/e2_units.py`, `eval/e3_layout.py`, `eval/oracles/o1_probe.py` (generated DISPLAY-LENGTH/offset probe in Docker) | D1+D2 parse; E2/E3 numbers |
| M3 | `stages/control.py` (D), `stages/dataflow.py` (E, alias expansion via `analysis.item_aliases`), `stages/hazards.py` (F, Phase 1 gap ids), `call_graph.json`, `data_flow.json`, `coverage.json`, `eval/o2_trace.py`, `eval/e4_control.py`, `eval/e5_dataflow.py` (O4, labelled model-based), `phase0/eval/gold/TEMPLATE.json`+`ANNOTATION_GUIDE.md` | E4/E5 zero unexplained violations; gold template handed over |
| M4 | `eval/runner.py` (`phase0 eval`, `metrics.json`, `failures.jsonl` with repro cmds), `eval/e1,e6,e7(baseline: `phase1 analyze` mapped),e8,e9`, `eval/render.py` -> `phase0/eval/RESULTS.md` | E1-E9 on D1/D2/D3 (E6 when gold lands) |
| M5 | `report/views.py` (Mermaid call graph, data/CRUD view, CardDemo JCL batch flow), `report/decisions.py` (recovered decision records from fact patterns), `phase0/docs/adr/0001..0006`, `README.md`, `TEAM_NOTES.md` | `phase0 report` output; ADRs cite repo measurements |
| M6 | `stages/summaries.py` (G, cached by input hash, entity check), `eval/e10_metamorphic.py`, `eval/e11_grounding.py`, `query.context_packet` | optional |

**Key choices (details in ADRs)**
- Determinism: sorted keys, stable ordering, no timestamps in `kb/`; `kb_version` = sha256 over sorted (path, bytes) of `kb/` minus manifest.
- Oracles run in `cobol-verifier-toolchain:0.1.0` (cobc 3.2, present locally) via `verifier.cobol.gnucobol`; host has no cobc/java.
- Schema validation = pydantic models of record + exported JSON Schema (no new runtime dep).
- Stage G LLM client: pluggable; testing uses local Ollama models (`qwen3.5:9b-q4_K_M`, `qwen2.5:3b`) via the OpenAI-compatible endpoint, Groq kept as an option. Model choice deferred to you. Off by default, so build stays deterministic.
- Integration: `integration/e2e_scripted.py` hardcodes the stub. Minimal additive edit there: honour an existing `PHASE0_CMD` and run `phase0 build` after `demo_workspace.py` (noted in TEAM_NOTES).
- Every metric in `metrics.json`; `RESULTS.md` is rendered from it, never hand-edited.

**Needs from you**: CardDemo path (none on disk; default = clone to `data/carddemo`, gitignored); gold annotations after M3.
**Risks**: front end rejects CICS/SQL (fallback covers inventory only); `make runtimes` needed for e2e (`cobolrt.jar` absent).
