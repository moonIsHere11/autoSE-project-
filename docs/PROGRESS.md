# Progress

> **Interface notice:** no change to `INTERFACE.md` (v1.0) or to the conventions in `RUNTIME_API.md`
> in this round. Scope was narrowed to **COBOL → Java** on 6 Nov 2026; the Python/Go code is kept but
> not re-validated (DECISIONS D16).

## 6 Nov 2026: Java pipeline end to end (M4/M5 for Java)

**What works (measured, see RESULTS.md):**
* All four tiers run end to end on Java: T0 (build + static), T1 (differential vs GnuCOBOL),
  T2 (T2a exhaustive, T2b JBMC with T1u and vacuity checks), T3 (OpenJML contracts).
* 14-program corpus, 101 paragraphs: **0 false positives**. Every program passes T0 and T1.
  18 paragraphs reach level 2 or 3.
* T2b validation gate implemented (it was a stub): the COBOL model is checked against GnuCOBOL on all
  T1 cases, and the emitted reference against the model on random states (D17).
* First real T2b proofs (complete, vacuity-checked): DIVREM and INVENTORY `SET-RETURN`, PAYROLL
  `SPLIT-HOURS`. An e2e test shows T2b catching a bug T1 cannot see.
* T3 fixed: String fields in frames, and the OpenJML `isSameType DEFERRED` crash worked around (D18).
  T3 now passes on 7 programs.
* Bugs fixed on the way:
  * field aliases in the T2b harness gave a false FAIL (D19);
  * PAYROLL translation didn't drop the sign on an unsigned store (D20);
  * non-deterministic T1u seed;
  * a misleading vacuity message;
  * self-test crashed on an empty corpus folder.
* ruff and mypy clean; 93 fast tests plus Docker/e2e tests green (3 new e2e tests for T2b/T3).
* Docs: STATUS.md (plain language), RESULTS.md, LIMITATIONS.md, RUNTIME_API.md, DECISIONS D16–D20,
  PLAN.md ticks.

**What doesn't work / isn't done (details in LIMITATIONS.md):**
* Planted-bug catch rate is **71%** (target ≥ 90%). The weak spot is `double` used inside arithmetic
  expressions (T0 only checks field types).
* T2b applies to only 7/101 paragraphs (I/O, division, `String`/`BigDecimal`, REDEFINES …). Four
  MERGE2 units hit the 3 GB JBMC memory cap.
* T3: 3 PAYROLL units TIMEOUT; INVENTORY `VALIDATE-RECORD` ERROR (infeasible precondition, not
  diagnosed). There are no automatic PERFORM VARYING loop invariants, only the hint hook.
* OpenJML proof of the runtime library: script broken, not run.
* Not started: integration with the teammates' manifests/bundles (M6); spike S7 write-up.
* Python and Go: deferred.

**Next steps:**
1. T0 rule for `double`/`float` arithmetic on decimal fields (would target the main group of survivors).
2. Review the 12 surviving mutants for equivalence.
3. Raise the JBMC memory cap and re-run MERGE2.
4. Diagnose the INVENTORY T3 infeasibility.
5. Integrate the teammates' manifests and bundles.
