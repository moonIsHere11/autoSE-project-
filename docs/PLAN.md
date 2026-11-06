# Plan (milestone checklist)

Status 6 Nov 2026: scope narrowed to **COBOL → Java** (Python/Go deferred, code kept). Mid-evaluation date: **TBD** (placeholder `<MIDEVAL_DATE>` was not filled in the spec).
Mid-eval cut line: M0–M4; M2 is the minimum demo; if M4 slips, T2a is the honest proof tier.
Each milestone ends with tests green, `make selftest`, RESULTS.md and a PROGRESS.md entry.

## M0 — environment and spikes
- [x] `docker/Dockerfile` pinned: GnuCOBOL 3.2, JDK 17, CBMC/JBMC 6.8.0, OpenJML 21.0.28, Python, z3, CrossHair, Go 1.22.12, libfaketime, tree-sitter grammars
- [x] host dev env: venv, ruff, mypy, pytest, `Makefile`
- [x] S1 cobc build / run / `-E` / trace (+ exact trace env vars) → `docs/spikes/S1.md`
- [x] S2 JBMC on Java-17 harness with `CProver.nondet*` + long-backed decimal → `S2.md`
- [x] S3 OpenJML ESC on toy example → `S3.md`
- [x] S4 `crosshair diffbehavior` toy → `S4.md`
- [x] S5 ProLeap vs hand-written subset parser → `S5.md`
- [x] S6 ACCEPT parsing rules, DISPLAY formats, layout probe → `S6.md`

## M1 — Java T0, reports, corpus
- [x] pydantic report schema, `summary.md` renderer, feedback skeleton, scoring/levels/acceptance
- [x] manifest model + conventions resolver
- [x] sandbox runner (docker, limits, batch runner)
- [x] COBOL front end part 1: preprocess, PIC/data division with probe validation, program structure
- [x] T0a Java build with diagnostics mapped to file:line + excerpts
- [x] T0b tree-sitter checks: data mapping, forbidden representations, completeness, forbidden APIs, integrity, anti-overfitting
- [x] seed corpus (10–15 programs) with correct Java translations — 14 programs
- [x] CLI + API + held-out guard; e2e test T0 on corpus

## M2 — Java T1 (mid-eval minimum)
- [x] cobc build cache, `-ftraceall` variant, coverage parser
- [x] input channels, strategies, encoders, bundle writer, expected-output capture
- [x] differential runner, byte comparison, exclusions (runtime errors, flaky/time)
- [x] decoding to field values, signatures, shrinking, classifier, localisation
- [x] coverage-preserving greedy minimisation
- [x] mutation operators (verifier/mutation, Java/Python/Go) + `make selftest` (tools/selftest.py)

## M3 — cheap breadth
- [ ] Python and Go packs: T0 + T1 — code exists, **deferred** (Java-only scope, 6 Nov); not re-validated
- [x] T2a exhaustive small-domain proofs (all languages)

## M4 — Java T2b
- [x] runtime library `cobolrt` (Java, Python, Go) + RUNTIME_API.md + differential property tests vs GnuCOBOL (10,000 cases, 0 mismatches)
- [ ] OpenJML ESC on the Java runtime core (script broken — LIMITATIONS.md)
- [x] semantics golden suite `tests/semantics/` (25 programs)
- [x] subset parser → IR, interpreter, dataflow
- [x] Java reference emitter, validation gate, JBMC harness, vacuity + mutation sanity, T1u — works; few units eligible (LIMITATIONS.md)

## M5 — Java T3
- [x] contracts from IR (requires/ensures/assignable/88-level predicates/functional post)
- [x] JML insertion + OpenJML ESC; loop-invariant hook (hint file `.verifier/invariants.json`; no automatic PERFORM VARYING invariants yet)

## M6 — wider coverage, integration
- [ ] Python T2b/T3 via CrossHair; optional Go T1.5 fuzzing — deferred
- [ ] integration with teammates' manifests/bundles — not started
- [x] RESULTS.md with self-test numbers (Java)
