# Phase 0 · Knowledge Base

## How to call me
```
make venv && make image                                   # once: verifier venv + toolchain image (cobc 3.2)
phase0/bin/phase0 build --workspace W                     # W/source + W/config.yaml -> W/kb (exit 2 if a file fails validation)
phase0/bin/phase0 query <method> [args] --workspace W     # JSON on stdout; drop-in for the stub (PHASE0_CMD)
phase0/bin/phase0 report --workspace W                    # checks kb/docs (views, decision records) against the facts
phase0/bin/phase0 eval --workspace SCRATCH --out phase0/eval --gold phase0/eval/gold [--e2e]
PHASE0_CMD=phase0/bin/phase0 python integration/e2e_scripted.py /tmp/ws   # whole loop with the real KB
```
`phase0/bin/phase0` re-execs under `~/.venvs/cobol-verifier` (`VERIFIER_PY` overrides). Exit codes: 0 ran, 2 bad input or contract violation (unknown ids list the valid ones), 3 internal error.

## Query methods
Contract (agreement 4.1): `list_units`, `get_unit U`, `source_text U`, `get_field F`, `callers U`, `callees U`, `rules_for C1,C2`, `gaps_for T1,T2`, `toolchain`.
Added in 1.1: `writers_of F`, `readers_of F`, `fields_of U`, `hazards_for U`, `coverage`, `context_packet U [BUDGET]` (Phase 1's context-pack sections, built from KB facts).
`rules_for` / `gaps_for` match an id exactly, else a substring of the construct/topic or of a cross-referenced id (`rules_for G-DIVZERO`).

## What it writes (`schema_version` 1.1, additive over 1.0)
| File | Content |
| --- | --- |
| `kb/manifest.json` | `kb_version` (sha256 of kb/ minus the manifest), `source_hash`, toolchain, extractor versions, coverage summary |
| `kb/source/units.json` | program, section and paragraph units: spans, reads/writes (elementary items, group and REDEFINES expanded), performs, perform_thru, goes_to, falls_through_to, exits, calls, hazards, unsupported, provenance |
| `kb/source/data_dictionary.json` | every data item: PIC, usage, semantic type, offset, byte length, OCCURS, REDEFINES, 88-levels, section, provenance |
| `kb/source/call_graph.json` | PERFORM / THRU / GO TO / fall-through / CALL / exit edges with line and resolution |
| `kb/source/data_flow.json` | field mutation table and sequential-file CRUD matrix |
| `kb/source/inventory.json` | every file by content: kind, format, copybooks, calls, JCL steps, parse status |
| `kb/source/coverage.json` | per file: lines attributed / comment / blank, every unattributed line with a reason, unsupported constructs, unresolved calls, parse errors |
| `kb/target/` | toolchain, 21 semantic gaps, 27 mapping rules, `runtime/` (byte copy of `runtimes/java/src/cobolrt`), `driver_template/`, `encoding_fixtures.json` |
| `kb/docs/` | Mermaid views (control graph, data view, JCL batch flow) and recovered decision records |

JSON Schemas for every file: `phase0/schemas/`.

## How it works
Stages run in order, each a function of the previous outputs (`phase0/phase0/stages/`):
A inventory (content classification, COPY/CALL/JCL scans) -> B parse (`cobc -E` + the verifier's lexer, parser and IR; Phase 1's tolerant analyser for rejected files) -> C layout (`verifier.cobol.datadiv`) -> D control flow -> E data flow (IR statements, byte-overlap storage model) -> F hazards (Phase 1's scanner on the strict IR, same gap ids) -> coverage -> docs.
Design decisions: `phase0/docs/adr/`. Working log: `phase0/notes.md`. Requests to other modules: `phase0/TEAM_NOTES.md`.

## Evaluation
`phase0/eval/RESULTS.md` (generated from `metrics.json`): GnuCOBOL listing and probe (E3), `-ftraceall` traces (E2, E4), the verifier's interpreter (E5, model-based), Phase 1 baseline (E7), determinism (E8), contract checks and the e2e loop (E9). Gold annotations for E6: `phase0/eval/gold/ANNOTATION_GUIDE.md`.
