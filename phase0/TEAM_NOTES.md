# Phase 0: requests and notes for the team

## For Nandini (verifier owner) and Mohit

1. **Phase 0 imports `verifier.cobol` as a library (ADR-0001).** This deviates from agreement principle 1 ("no module imports another module's internals"). Reason: principle 2 of the Phase 0 task, one COBOL semantics for the whole harness: the KB must describe the program exactly as the checker's front end sees it (PIC sizes, paragraph spans). Phase 0 never modifies `verifier/`. If you object, the fallback is to depend on a pinned version of the `cobol-verifier` package, not to copy code. **Please approve or object.**
2. **Dialect.** Phase 2's adapter calls `verifier.api.verify` without a config, so the oracle always uses `-std=default`, whatever `config.yaml: source.dialect` says. Phase 0 does the same (it must match the oracle). Should the adapter pass `source.dialect` through? Until then Phase 0 reports the configured dialect next to the effective one.
3. **Driver template vs T0 lint.** The verifier's T0 lint scans every `.java` file in the project, including Phase 0's driver template. Anything in the template that opens files is a blocker; the template now does no file I/O. Phase 2 currently ignores `driver_cmd` (phase2/README "Deviations"), so the driver is shipped for the contract only.
4. **Encoding fixtures** (`kb/target/encoding_fixtures.json`) decide the agreement section 10 open question (signed zero, COMP-3, OCCURS keys, groups). Phase 2 is the reviewer: please check they match `verifier.inputs.encode`.

## Changes outside phase0/

- `Makefile`: `lint` also checks `phase0`; `typecheck` also runs mypy in `phase0/`.
- `integration/e2e_scripted.py`: honours `PHASE0_CMD` from the environment and runs `phase0 build` first; the default is still the stub.
- Verifier venv: installed `pyyaml` and `types-PyYAML` (imported by Phase 1, the Phase 2 adapter and `integration/`, but missing from the venv).
