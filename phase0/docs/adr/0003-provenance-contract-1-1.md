# ADR-0003: Additive provenance on every fact (contract 1.1)

## Context
Agreement section 10 proposes `unsupported: list[str]` on `Unit` as a minor version bump, and asks that contract changes be additive. Phase 0 must record where every fact came from, which extractor produced it and how sure we are (principle 4).

## Options considered
1. A separate provenance file keyed by fact id.
2. Optional fields on the existing records (`provenance`, `unsupported`, `confidence` inside provenance) plus new optional fields (`perform_thru`, `goes_to`, `exits`, `hazards`, `offset`, `byte_length`, `redefines`, `condition_names`, `section`, ...).

## Decision
Option 2, `schema_version` "1.1". Every new field is optional with a default, so a 1.0 consumer that ignores unknown keys is unaffected. Pydantic models (`phase0/phase0/schema.py`) are the schema of record; JSON Schemas are exported to `phase0/schemas/` for other modules. New files (`call_graph.json`, `data_flow.json`, `inventory.json`, `coverage.json`, `encoding_fixtures.json`, `docs/`) are additive too.

## Evidence
- E9: all 39 evaluation KBs validate; the exported JSON Schemas match the models (`exported_json_schemas_current`).
- E9: `integration/e2e_scripted.py` passes with the real Phase 0. Phase 1 and Phase 2, written against 1.0, read 1.1 unchanged (RED on the planted bug, then GREEN).
- A separate file (option 1) would need a join on unstable ids. The phase 1 tolerant facts in D3 already differ in unit naming (`(MAIN)` vs `__START__`).

## Consequences
- Confidence is a float: strict 1.0, strict with syntax fallback 0.8, tolerant 0.6. Coverage can sum it.
- Field ids use Phase 1's convention (`PROG.` prefix only for multi-program workspaces), so ids can collide with the dotted path for nested items. Readers must split on the first `.` only when `program` is set.
