# Phase 0 working notes

Running log: what was done, and why. Newest entries at the bottom.

## Setup

- Repo had only `origin/integration`; created local `integration` tracking it, then branched `phase0` from it.
- Read `agreement.md` (contracts 4.1-4.6, 5, 7, 9, 10), the Phase 0 stub, `demo_workspace.py`, `e2e_scripted.py`.
- Environment facts that shape the design:
  - venv `~/.venvs/cobol-verifier` runs Python 3.14 with `cobol-verifier` installed editable; ruff targets py311, so code stays 3.11-compatible.
  - Host has no `cobc`, no `java`. Docker image `cobol-verifier-toolchain:0.1.0` exists, so every GnuCOBOL oracle (O1, O2) runs through the verifier's container helpers.
  - `jsonschema` not installed. Decision: pydantic models are the schema of record; export JSON Schema files from them for other modules. Avoids a new dependency.
  - Ollama installed with `qwen3.5:9b-q4_K_M`, `qwen2.5:3b`, `qwen35-9b-a2`; server not running. Only stage G needs it.
  - CardDemo not on disk.
  - `runtimes/build/java/cobolrt.jar` missing (needed by the e2e script); built by `make runtimes`.
- Phase 2's adapter (`check_runtime_unchanged`) compares the project's `runtime_dir` with `kb/target/runtime/` byte for byte, so `kb/target/runtime/` must be the same tree Phase 1 seeds into staging.
- Gap ids referenced elsewhere (grep): Phase 1 analyzer uses G-TRUNCATE, G-GROUPMOVE, G-SIGN, G-NUMALPHA, G-OVERFLOW, G-ROUNDING, G-DIVZERO, G-GOTO, G-FALLTHROUGH, G-PACKED; Phase 2 `CAUSE_TO_GAP` uses G-SIGN, G-TRUNCATE, G-OVERFLOW, G-ROUNDING, G-NUMALPHA; `G-STORAGE` appears in docs. A naive `G-[A-Z]*` grep also hits COBOL names (e.g. `...G-HOURS`); the closure check must use word boundaries.

## Decisions

- User: no milestone dates, go as fast as possible; commits under the user's name only, short messages; fix anything found wrong while testing; keep this file.
