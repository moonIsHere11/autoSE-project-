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
- Installed `pyyaml` + `types-PyYAML` into the verifier venv: Phase 1, Phase 2's adapter and `demo_workspace.py` import `yaml`, but neither the venv nor system Python had it. Baseline before any Phase 0 code: `make lint typecheck test` green (93 tests); `integration/e2e_scripted.py` with the stub: RED then GREEN in 9 s.

## M1: skeleton, contract, inventory

- Layout: `phase0/phase0/` package, `phase0/bin/phase0` wrapper (same pattern as `phase2/bin/phase2`: re-exec under the verifier venv with the repo root on `PYTHONPATH`). Separate `phase0/pyproject.toml` only for mypy (`mypy_path = ".."` so the editable `verifier` install resolves); ruff uses the root config. Makefile `lint` and `typecheck` now include phase0.
- Schemas (`schema.py`): pydantic models with `extra="forbid"` for everything Phase 0 writes; 1.1 additions are optional with defaults, so 1.0 readers are unaffected. `Field` is `Field_` in Python only (name clash with pydantic). Confidence is a float in [0, 1] (strict = 1.0, tolerant lower) so coverage can sum it.
- Determinism (`jsonio.py`): sorted keys, indent 1, trailing newline, atomic writes. `kb_version` = sha256 over sorted (relative path, file sha256) of kb/ minus `manifest.json`. No timestamps under kb/; build timings go to the event log and `.phase0-cache/last_build.json`.
- `kb/` is written to `kb.building/`, validated, then renamed over `kb/` (agreement 5: rebuilt as a whole). A validation failure raises `ContractError` (exit 2) and leaves the old kb/ untouched.
- Tool config: Phase 0 uses `VerifierConfig()` defaults, because Phase 2's adapter calls `verifier.api.verify` without a config, so `-std=default` regardless of `config.yaml`'s `dialect`. Recorded the mismatch risk (config says `ibm` in the agreement example) for TEAM_NOTES.
- Inventory (stage A): classification by content (JCL cards, BMS macros, PROGRAM-ID + PROCEDURE DIVISION in the code area, level-number lines for copybooks), never by extension. Pattern scans for COPY / SQL INCLUDE, CALL (static `'X'`, dynamic `?ITEM`), CICS LINK/XCTL, JCL EXEC/DD with continuation cards.
- Catalogue: 21 gaps, 27 rules, each with a `source` citing a spike section, corpus README section or a semantics program with recorded GnuCOBOL output. Verified the VARYING claim (control item ends at 4) against `tests/semantics/expected/VARYING/stdout`; softened the OCCURS bounds claim to "depends on compile flags" because I could not verify it from recorded output. `G-STORAGE` appears in no code (a naive grep hit `WORKING-STORAGE`), but the task lists it, so it exists (WORKING-STORAGE lifetime/initial values). Rule examples were first written with invented runtime calls; replaced them with the real `cobolrt` signatures (grepped from the sources).
- Runtime: `kb/target/runtime/` = byte copy of `runtimes/java/src/cobolrt/*.java`, because Phase 1 copies it to `<project>/cobolrt` and Phase 2 runs `filecmp.dircmp(kb/target/runtime, project/cobolrt)`. Test does the same comparison.
- Driver template (`app.Driver`, `app.Canon`, `app.Json`): java.* only, no catch-all catch (T0 forbids it); a unit signals a COBOL runtime error with `Canon.UnitError`. Compiles and runs in the toolchain image.
- **Bug found by e2e, fixed:** first e2e with the real Phase 0 stayed RED: the verifier's T0 lint scans every Java file in the project and flagged `EncodingCheck.java` (in the driver template) for opening `fixtures/encoding.json`. Moved the fixtures to `kb/target/encoding_fixtures.json` and the checker to `phase0/eval/java/`; added a test that the template does no file I/O. `test_cmd` is now build + a driver smoke run.
- Encoding decisions (open question in agreement 10, owned by Phase 0): canonical decimal = exact `max(scale,0)` decimals, no `+`; negative zero only as `-0.0` when stored by ACCEPT `-0` (matches `verifier.inputs.encode`'s explicit `-0`); COMP-3/COMP-5 use the same text as DISPLAY; OCCURS keys `ID(i,j)` 1-based, outermost first; groups as raw ISO-8859-1 bytes. Fixtures are checked against `verifier.inputs.encode.canonical_text` in a test.
- `integration/e2e_scripted.py`: minimal additive change: if `PHASE0_CMD` is set, run `<PHASE0_CMD> build` after the demo workspace and use it; default stays the stub. Result with the real Phase 0: RED (planted G-TRUNCATE bug) then GREEN.
- Query: the nine contract methods + `writers_of`, `readers_of`, `fields_of`, `hazards_for`, `coverage`. `rules_for`/`gaps_for` match the id exactly, then a substring of the construct/topic or of the cross-referenced ids (so `rules_for G-DIVZERO` returns the rules handling that gap). Unknown ids list the valid ids and difflib's closest matches.
- House rules enforced by tests (ruff cannot): no conditional expressions, no `except Exception`/bare except in phase0 code.
