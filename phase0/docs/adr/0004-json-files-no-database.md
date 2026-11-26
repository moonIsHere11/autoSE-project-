# ADR-0004: JSON files plus the query CLI, with no database

## Context
The agreement fixes the KB as files under `kb/` and `phase0 query` as the interface. The KB is built once per run and is read-only afterwards. Modules may be written in any language.

## Options considered
1. JSON files only, with an in-memory index built at query time.
2. SQLite or a graph database next to the files.
3. A vector store over source text for retrieval.

## Decision
Option 1. `kb_version` is a sha256 over the sorted (path, sha256) pairs of `kb/` minus `manifest.json`. The query service loads the JSON lazily (`functools.cached_property`) per call.

## Evidence
- E8: two builds of every D1, D2 and D3 workspace give the same `kb_version`. A database file would make byte-identity depend on the storage engine's page layout.
- Size: the largest KB (CardDemo, 61,802 source lines) builds in about 2 s. The query CLI answers from JSON in well under a second, so an index service is not needed at this scale.
- CodexGraph (Liu et al., NAACL 2025) argues for structured code-graph access over similarity retrieval. `call_graph.json` and `data_flow.json` provide the structure without a separate store, and `context_packet` assembles from those facts (ADR-0006 scope).

## Consequences
- Any language can read the KB with a JSON parser; nothing else needs installing.
- Queries that need joins (`writers_of`, `fields_of`) scan lists. This is fine at the tested size and would need an index above roughly 10^5 units.
