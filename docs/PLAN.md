# Plan (milestone checklist)

Mid-evaluation date: **TBD** (placeholder `<MIDEVAL_DATE>` was not filled in the spec).
Mid-eval cut line: M0–M4; M2 is the minimum demo; if M4 slips, T2a is the honest proof tier.
Each milestone ends with tests green, `make selftest`, RESULTS.md and a PROGRESS.md entry.

## M0 — environment and spikes
- [ ] `docker/Dockerfile` pinned: GnuCOBOL 3.2, JDK 17, CBMC/JBMC 6.8.0, OpenJML 21.0.28, Python, z3, CrossHair, Go 1.22.12, libfaketime, tree-sitter grammars
- [ ] host dev env: venv, ruff, mypy, pytest, `Makefile`
- [ ] S1 cobc build / run / `-E` / trace (+ exact trace env vars) → `docs/spikes/S1.md`
- [ ] S2 JBMC on Java-17 harness with `CProver.nondet*` + long-backed decimal → `S2.md`
- [ ] S3 OpenJML ESC on toy example → `S3.md`
- [ ] S4 `crosshair diffbehavior` toy → `S4.md`
- [ ] S5 ProLeap vs hand-written subset parser → `S5.md`
- [ ] S6 ACCEPT parsing rules, DISPLAY formats, layout probe → `S6.md`

## M1 — Java T0, reports, corpus
- [ ] pydantic report schema, `summary.md` renderer, feedback skeleton, scoring/levels/acceptance
- [ ] manifest model + conventions resolver
- [ ] sandbox runner (docker, limits, batch runner)
- [ ] COBOL front end part 1: preprocess, PIC/data division with probe validation, program structure
- [ ] T0a Java build with diagnostics mapped to file:line + excerpts
- [ ] T0b tree-sitter checks: data mapping, forbidden representations, completeness, forbidden APIs, integrity, anti-overfitting
- [ ] seed corpus (10–15 programs) with correct Java translations
- [ ] CLI + API + held-out guard; e2e test T0 on corpus

## M2 — Java T1 (mid-eval minimum)
- [ ] cobc build cache, `-ftraceall` variant, coverage parser
- [ ] input channels, strategies, encoders, bundle writer, expected-output capture
- [ ] differential runner, byte comparison, exclusions (runtime errors, flaky/time)
- [ ] decoding to field values, signatures, shrinking, classifier, localisation
- [ ] coverage-preserving greedy minimisation
- [ ] mutation operators + `make selftest` (0 false positives, catch rate)

## M3 — cheap breadth
- [ ] Python and Go packs: T0 + T1
- [ ] T2a exhaustive small-domain proofs (all languages)

## M4 — Java T2b
- [ ] runtime library `cobolrt` (Java, Python, Go) + RUNTIME_API.md + differential property tests vs GnuCOBOL
- [ ] semantics golden suite `tests/semantics/`
- [ ] subset parser → IR, interpreter, dataflow
- [ ] Java reference emitter, validation gate, JBMC harness, vacuity + mutation sanity, T1u

## M5 — Java T3
- [ ] contracts from IR (requires/ensures/assignable/88-level predicates/functional post)
- [ ] JML insertion + OpenJML ESC; loop-invariant hook

## M6 — wider coverage, integration
- [ ] Python T2b/T3 via CrossHair; optional Go T1.5 fuzzing
- [ ] integration with teammates' manifests/bundles; final RESULTS.md
