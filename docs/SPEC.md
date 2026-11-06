# Spec: Build the COBOL→X Verification Pipeline ("the verifier")

This is the original build prompt, kept verbatim so contributors and helper agents can read it.
Where it conflicts with other notes, this spec wins. Decisions that interpret it are in
[DECISIONS.md](DECISIONS.md).

- Mid-evaluation date: <MIDEVAL_DATE> (not filled in; see DECISIONS D1)
- Owner: the verification pipeline owner

---

## 1. Context

This is a university project for an Autonomous Software Systems course. The proposal is in `docs/proposal.pdf`: a verification-first agentic harness for code migration. We narrowed it to **COBOL → X**, where X is **Java (priority 1)**, then Python (priority 2), then Go (priority 3). Background notes on a tiered verification stack are in `docs/verification_notes.md`.

The work is split across the team:
- **Corpus & evaluation teammate.** Collects COBOL repos, generates stress-test inputs, records input/output pairs from the original COBOL, and later scores generated code on those held-out pairs.
- **Generation teammates.** Decompose COBOL into a context tree, run the agent that writes X code, and run the repair loop that consumes my feedback.
- **Me (what you are building).** Given a COBOL repo and a generated X repo, decide as rigorously as the available tooling allows whether they behave the same. Report which verification tier each unit reached. When they differ, return machine-readable and LLM-ready feedback built around concrete counterexamples.

**There is no LLM inside the verifier.** It is deterministic tooling. The LLM lives in the generation teammates' loop.

## 2. Non-negotiable principles

1. **The oracle always comes from the COBOL side.** Expected outputs, specifications and contracts come from executing GnuCOBOL or from our validated COBOL semantic model. They never come from the generated code, its comments or its tests.
2. **Statuses are honest.** Every check returns exactly one of `PASS`, `FAIL`, `ERROR` (tool or infrastructure problem), `TIMEOUT`, `NOT_APPLICABLE` (with a reason), or `SKIPPED` (gated by an earlier failure).
   - A tool crash is never a PASS. A missing tool is never a PASS.
   - Only mark PASS after parsing a positive result from the tool's real output.
   - Anything stubbed is labelled `STUB` in the report.
3. **Every PASS records its scope.** Store what was checked, which inputs or bound were used, which oracle, which tool and version, and the exact command line.
4. **Every FAIL has a reproducible counterexample.** Store the input, the expected output, the actual output, and a one-line command that reproduces it.
   - Confirm every symbolic counterexample (from JBMC or CrossHair) by running it concretely. If concrete execution does not reproduce it, report `ERROR` (an encoding or tool issue), not `FAIL`.
5. **Held-out separation.** The verifier's input generation is independent of the evaluation teammate's.
   - The verifier refuses to read the configured held-out evaluation directory. Pointing it there is a hard error.
   - Use rotating seeds per repair iteration, so a model cannot overfit to one fixed input set.
6. **Generated code is untrusted.** Run it in Docker with no network, CPU, memory and wall-clock limits, a read-only source mount and a temporary working directory.
7. **Determinism.** Use seeded RNGs and pinned tool versions. The same inputs give the same report, apart from timings.
8. **Never modify the input repos.** Copy them into a workspace. Contracts and harnesses go into the copy.
9. **Cheapest checks first, with gating.** Do not spend minutes proving something that a 1-second test already refutes.
10. **Never fake progress.** If something proves infeasible, return `NOT_APPLICABLE` with a reason, log it in `docs/LIMITATIONS.md`, and move on.

## 3. Ground-truth semantics

- **GnuCOBOL 3.x is the reference semantics.** Prefer 3.2, and record the exact version.
- Put all `cobc` flags in a single config: dialect `-std=`, binary truncation and similar options. Record that config in every report.
- IBM Enterprise COBOL differences are a documented limitation, not something we handle.
- **In scope:**
  - pure batch computation on WORKING-STORAGE
  - ACCEPT and DISPLAY
  - SEQUENTIAL and LINE SEQUENTIAL files
  - CALL between programs in the same repo (stretch)
- **Out of scope:** programs using `EXEC SQL`, `EXEC CICS`, indexed or relative files, or SORT/MERGE. These get T1+ `NOT_APPLICABLE` with the reason "uses <feature>".

## 4. Interfaces

Write `docs/INTERFACE.md` before writing any tier code. Teammates will read it.

### 4.1 CLI and Python API

```
verify --cobol PATH --target PATH --lang {java,python,go}
       [--manifest PATH] [--mode fast|full] [--units ID,...]
       [--tiers 0,1,2,3] [--seed N] [--previous-report PATH] --out DIR
```

The Python API is `verifier.api.verify(...) -> Report`, with the same parameters.

**Modes:**
- `fast` is for the inner repair loop. Target under about 60 s for a typical program of 300–500 lines. It runs T0, T1 with boundary cases plus a capped random sample, and T2 with a small bound.
- `full` runs everything.

**Exit codes:**
- 0 means every selected unit was accepted.
- 1 means at least one unit was not accepted.
- 2 means a verifier error.

### 4.2 Translation manifest

The generation team produces this file. It is optional: the verifier must still work without it by falling back to naming conventions. In that case, any tier needing information the conventions can't supply becomes `NOT_APPLICABLE` with a reason.

```json
{
  "schema_version": "1.0",
  "language": "java",
  "build": {"command": "mvn -q -DskipTests package", "workdir": "."},
  "programs": [{
    "cobol_program_id": "LOANCALC",
    "cobol_file": "src/LOANCALC.cbl",
    "run": {"command": "java -cp target/classes com.acme.LoanCalc"},
    "files": [{"cobol_select": "CUST-FILE", "path": "CUSTIN.dat"}],
    "class": "com.acme.LoanCalc",
    "units": [{"cobol_paragraph": "CALC-INTEREST", "target_symbol": "calcInterest"}],
    "fields": [{
      "cobol": "WS-INTEREST", "target": "wsInterest",
      "declared": {"kind": "decimal", "digits": 7, "scale": 2, "signed": false, "usage": "DISPLAY"}
    }]
  }]
}
```

**Default conventions:**
- Java: one class per PROGRAM-ID named in PascalCase, fields in camelCase, one method per paragraph in camelCase.
- Python: snake_case.
- Go: exported PascalCase.
- Files: both programs read and write files under the same relative names in their working directory.

Define a pydantic model for the manifest and validate it strictly, with helpful error messages.

### 4.3 Test-case bundle

This format is shared with the evaluation teammate. Propose it to them, so their I/O pairs plug straight into our runner. Their held-out cases still never enter the repair loop.

```
case_<hash>/
  case.json      # stdin, args, env, fake_time, input files list, generator strategy, seed
  stdin.txt
  in/<files>
  expected/      # filled by running GnuCOBOL: stdout, return_code, out/<files>
```

### 4.4 Report

- `report.json` uses a schema-versioned pydantic model.
- `summary.md` is for humans.
- `feedback/<unit_id>.md` and `feedback/<unit_id>.json` are for the agent.

Each unit in `report.json` has this shape:

```json
{
  "id": "LOANCALC::CALC-INTEREST",
  "level": 1,
  "evidence": ["T0", "T1"],
  "accepted": false,
  "score": 1.83,
  "tiers": {
    "T0": {"status": "PASS", "checks": []},
    "T1": {
      "status": "FAIL", "cases_run": 412, "cases_failed": 7, "cases_excluded": 3,
      "coverage": {"paragraph": 0.92, "statement": 0.81, "uncovered": ["ERR-HANDLER"]},
      "failure_signatures": [], "counterexamples": []
    },
    "T2": {"status": "SKIPPED", "reason": "gated by T1 FAIL"},
    "T3": {"status": "SKIPPED", "reason": "gated by T1 FAIL"}
  },
  "toolchain": {}, "config": {}, "repro": []
}
```

The top level also includes a summary: number of units, a histogram of `level`, a histogram of each evidence type, the number accepted, and timings per tier. **The headline metric is the percentage of units reaching each level.** Never report BLEU-style similarity metrics.

## 5. Architecture

Use Python 3.11+, with type hints, ruff, mypy and pytest. Keep modules small. Target-language specifics live in **language packs** behind one interface: one COBOL semantic model plus one pack per target, not pairwise hacks.

```
verifier/
  cli.py  api.py  config.py
  report/      schema.py  render_md.py  feedback.py  scoring.py
  sandbox/     docker_runner.py  limits.py
  cobol/       gnucobol.py (build/run/trace, cached)  preprocess.py (cobc -E)
               datadiv.py (PIC + layout)  parser.py  ir.py  interp.py  dataflow.py
  inputs/      strategies.py  bundle.py  encode.py (bytes<->field values)  shrink.py
  tiers/       t0_build.py  t0_static.py  t1_diff.py  t2_exhaustive.py
               t2_symbolic.py  t3_contracts.py
  langpacks/   base.py  java/  python/  go/
  diagnose/    classifier.py  localize.py
runtimes/      java/  python/  go/        # shared runtime libraries (section 7)
corpus/        seed programs, handwritten translations, generated mutants
tests/         unit/  semantics/ (golden COBOL feature programs)  e2e/
docker/        Dockerfile (pinned versions)
docs/          INTERFACE.md DESIGN.md PLAN.md DECISIONS.md LIMITATIONS.md
               PROGRESS.md RESULTS.md RUNTIME_API.md spikes/
```

The `LangPack` interface provides the following. Any method may return `NOT_APPLICABLE`.
- `build()`
- `run_command()`
- `static_rules()`
- `emit_reference(ir_unit)`
- `make_equivalence_harness(unit, mapping)`
- `run_symbolic(harness, bound)`
- `instrument_contracts(unit, contracts)`
- `check_contracts()`
- `parse_counterexample()`
- `replay_concrete()`

## 6. The tiers

### T0 — Build and static/structural checks

**T0a, build.** Run the pack's build command, capturing compiler diagnostics mapped to file and line. The feedback includes the first N errors with code excerpts.
- Java: `javac`, or the Maven/Gradle command from the manifest.
- Python: `py_compile`, plus `mypy` on the generated package (mypy findings are warnings).
- Go: `go build` and `go vet`.

**T0b, static checks.** Use tree-sitter so one engine serves all three languages. Each finding has a severity of ERROR (fails T0) or WARNING. Implement these checks:

1. **Data-mapping check.** For every COBOL elementary item, compute the true type from its PIC: kind, digits, scale, sign, usage and length. Compare it with the manifest's `declared` type, then best-effort check that the target symbol really has a compatible type in the code. This needs no SMT and catches a large class of bugs early.
2. **Forbidden representations.** Flag `float` or `double` (Java), `float` (Python) and `float32`/`float64` (Go) used for decimal fields. Flag integer types too narrow for the PIC digits.
3. **Completeness.** Every COBOL program and paragraph in scope has a counterpart.
4. **Forbidden APIs.**
   - network access
   - reflection
   - process execution
   - reading the wall clock or RNG, except through an injected source
   - file paths that weren't declared
   - catch-all handlers that swallow errors
5. **Integrity.**
   - dependencies come only from an allowlist
   - no references to verifier, corpus or evaluation paths
   - no reading of `expected/` artefacts
6. **Anti-overfitting.** Numeric or string literals in the new code that match earlier counterexample inputs or outputs, but appear nowhere in the COBOL source, are flagged as ERROR "possible special-casing of a counterexample". The check takes `--previous-report` as input.

### T1 — Differential testing (program-level, oracle = GnuCOBOL)

**Build the COBOL side.**
- Run `cobc -x` with the pinned flags. Cache the result by (hash of the preprocessed source, cobc version, flags).
- Build a second variant with `-ftraceall` for coverage. Look up the exact runtime trace environment variables in the installed version's docs and record them in `docs/spikes`.

**Find the input channels.**
- ACCEPT targets, from stdin.
- Input FD records, from files. LINE SEQUENTIAL versus fixed-length SEQUENTIAL matters here.
- Command-line arguments and environment variables.

**Generate inputs from the DATA DIVISION.** `datadiv.py` must handle:
- 9, X, A, S, V and P characters, and repetition `(n)`
- DISPLAY, COMP, BINARY, COMP-3/PACKED-DECIMAL and COMP-5 usage
- SIGN LEADING/TRAILING [SEPARATE]
- OCCURS (flag DEPENDING ON), REDEFINES, levels 66/77/88, VALUE, FILLER and group items

It must compute byte lengths and offsets. Validate the layout against GnuCOBOL with an auto-generated probe program that DISPLAYs `FUNCTION LENGTH` of every item.

**Generation strategies** (each case records which strategy produced it):
- Per-field boundaries:
  - 0, ±1, max and min for the digit count, all 9s
  - maximum scale digits
  - negative zero for signed fields
  - values one unit past the boundary, where the input path allows (to provoke truncation)
- Values that round differently: …5 cases at the scale boundary, plus their negatives.
- Literal-seeded values. Extract numeric literals from PROCEDURE DIVISION conditions (`IF AMT > 1000` gives 999, 1000, 1001) and use EVALUATE WHEN values and 88-level VALUE sets.
- Alphanumeric values: empty/spaces, full length, overlong where the input path allows, mixed case, digits in alpha fields.
- Files: 0 records, 1 record, many records, and boundary records.
- Pairwise combinations of per-field boundaries across fields, which keeps the count manageable, plus seeded uniform-random cases.

**Input encoding.** Find out by probe how GnuCOBOL interprets ACCEPTed text into numeric fields (for example `123.45`, `-5`, leading spaces), and generate canonical forms. Encode file records byte-exactly: zoned decimal with overpunch sign, packed decimal, binary at the configured endianness.

**Run and compare.**
- Run both sides in the sandbox on the same bundle.
- Compare stdout **bytes**, every output file's **bytes**, and the return code.
- Store stderr but don't compare it.
- No normalisation by default. Any normaliser, such as trailing whitespace, is explicit, opt-in, and reported.

**Exclusions** are counted and reported, never silently dropped:
- Cases where COBOL itself hits a runtime error.
- Non-deterministic programs. Detect CURRENT-DATE, ACCEPT FROM DATE/TIME and RANDOM, run both sides under libfaketime or an injected clock, and run COBOL twice per case. Flaky cases are excluded.

**Coverage.** Measure paragraph and statement coverage from the COBOL trace. Greedily minimise the case set while keeping coverage, and report uncovered paragraphs.

**Analyse failures.**
- Decode differing bytes back into field-level values: show `WS-TOTAL = -123.45`, not raw bytes.
- Group failures by signature: the kind of mismatch plus the output location.
- Shrink each signature's counterexample with delta debugging, moving field values toward 0 and short strings while it still fails.
- Classify each one with `diagnose/classifier.py`, always labelled as "likely":
  - `MISSING_HIGH_ORDER_TRUNCATION`, `ROUNDING_MISSING`, `ROUNDING_MODE`
  - `SIGN_LOST`, `NEGATIVE_ZERO`, `SCALE_OFF_BY_POWER_OF_10`
  - `PADDING_OR_JUSTIFICATION`, `DISPLAY_FORMAT`, `ITERATION_COUNT`
  - `SIZE_ERROR_HANDLING`, `MISSING_OR_EXTRA_OUTPUT`, `ENCODING`
- Localise each failure with `diagnose/localize.py`: use the COBOL trace for the failing case plus data-flow to find the statements that wrote the differing field.

**Status.** T1 PASS means every non-excluded case matched. Coverage is reported as a strength qualifier and is used by the acceptance policy (section 8).

**T1u, unit-level differential testing** (milestone M4). Generate random states in the PIC domain, then run the validated reference (section 6, T2b) and the LLM's mapped method on each one. This localises a program-level failure to a paragraph cheaply.

### T2 — Equivalence beyond sampling

**T2a, exhaustive small-domain proof.** This is language-agnostic, needs no COBOL model, and is the safe mid-eval proof tier.
- It applies when a program's whole input space is finite and below `exhaustive_limit` (default 20,000 cases). Examples: a few small numeric ACCEPTs, or a fixed-size input file with tiny fields.
- Enumerate every input, comparing against GnuCOBOL in batched sandbox runs.
- An all-match result is `PASS` with `method: exhaustive`, which is a proof over the declared domain. Record the domain.

**T2b, bounded symbolic equivalence at unit level.**

1. **COBOL frontend.**
   - Run `cobc -E` to expand COPY books and normalise the source format.
   - Parse a supported subset into a small typed IR. The subset is MOVE, COMPUTE, ADD/SUBTRACT/MULTIPLY/DIVIDE (with ROUNDED, REMAINDER and ON SIZE ERROR), IF, EVALUATE, PERFORM, PERFORM n TIMES, PERFORM UNTIL/VARYING, 88-level conditions and INITIALIZE.
   - Anything outside the subset (GO TO, ALTER, PERFORM THRU at first, STRING/UNSTRING/INSPECT at first, and so on) makes the unit T2-ineligible, with the exact construct named as the reason. Never guess semantics.
   - Time-box a spike comparing ProLeap COBOL parser against a hand-written subset parser. Default to the hand-written parser unless ProLeap is clearly cheaper to integrate.
2. **IR tools.**
   - `interp.py` runs the IR concretely.
   - `dataflow.py` computes read and write sets per paragraph, transitively through PERFORM.
3. **Reference emitter per language pack.** It produces a literal, non-idiomatic translation of the unit that calls the runtime library (section 7).
   - The Java reference must be JBMC-friendly: `long`-based arithmetic, fixed arrays, no collections, no BigDecimal.
   - A unit is T2-eligible only if the encoder can prove that every intermediate result fits in 63 bits given the PIC sizes. Otherwise the result is `NOT_APPLICABLE` with "precision exceeds bound".
4. **Validation gate.** The reference for a program is trusted only if:
   - the IR interpreter matches GnuCOBOL on every T1 case for that program, **and**
   - the emitted reference matches GnuCOBOL on every T1 case for that program.

   A failure here means a bug in our model, never in the LLM code. Report it as `ERROR` and log it.
5. **Product harness.** Built from the manifest or the conventions.
   - Create a nondeterministic value for every input field. In Java use `org.cprover.CProver.nondetLong()` and `CProver.assume(...)`, constrained to the field's PIC domain.
   - Load identical state into the reference and into the LLM object.
   - Call both.
   - Assert equality of **all** mapped fields afterwards, not just the COBOL write set, so extra side effects are caught too.
6. **Run the checker.**
   - Java: `jbmc` with `--unwind k --unwinding-assertions`. If the unwinding assertions also hold, the result is a complete proof for that unit. Record `bound: complete` versus `bound: k`.
   - Python: `crosshair diffbehavior` between the reference and the LLM function, with type hints derived from the PICs. Label the result `method: symbolic_search` (bounded search, not a proof) and never `proof`.
   - Go: `NOT_APPLICABLE`, "no mature model checker". Optionally offer T1.5: native `go test -fuzz` coverage-guided differential fuzzing against the emitted Go reference, reported as testing evidence and never as proof.
7. **Vacuity checks.** Every T2 PASS must pass both of these, or it is downgraded to `ERROR`:
   - **Reachability.** A harness variant with `assert false` after both calls must FAIL. If it doesn't, the assumptions are contradictory.
   - **Mutation sanity.** Apply 3–5 COBOL-semantic mutants (section 9) to the LLM unit. The checker must find counterexamples for most of them. Report the kill rate.
8. **Counterexamples.** Parse the checker trace into field values, replay concretely on both sides (principle 4), shrink, classify, and emit the same feedback format as T1.

### T3 — Contracts (gated only by T1 FAIL; runs even when T2 is NOT_APPLICABLE)

T3 adds value in two places. It covers units that T2 can't reach (ineligible constructs, BigDecimal, too large), and it gives unbounded guarantees where T2 was only bounded.

**Contracts are generated by the verifier from the COBOL side only:**
- `requires`: input fields are within their PIC domain.
- `ensures`: written fields are within their PIC domain and scale.
- `assignable` (the frame): the COBOL write set.
- 88-level conditions as named predicates.
- For loop-free units, the exact functional postcondition computed from the IR.

**Checking:**
- **Java.** Insert JML into a workspace copy of the target and run OpenJML in ESC mode. The runtime library carries its own JML specs, verified once.
- **Python.** Use CrossHair contract checking (icontract or deal). Label it `symbolic_search`.
- **Go.** `NOT_APPLICABLE`; Gobra is a documented stretch goal.

**Loop invariants.**
- Use simple automatic invariants derived from PERFORM VARYING bounds.
- If a proof still needs a missing invariant, report `NOT_APPLICABLE` "needs loop invariant", not FAIL.
- Design a hook so the generation team's LLM can later *propose* invariants. These are checked by the tool and are only hints, never specifications.

## 7. Runtime libraries

This gives the most leverage of anything in the design. It is a proposal to the team, so write `docs/RUNTIME_API.md` for them. The verifier must still work, with fewer tiers, when generated code doesn't use the library.

**Java `cobolrt`:**
- `CobolDecimal`: a `long` unscaled value plus digits, scale and signed. Operations implement COBOL truncation, ROUNDED (default NEAREST-AWAY-FROM-ZERO; check empirically against GnuCOBOL) and size-error detection.
- `PicX`: fixed length, space padding, truncation, JUSTIFIED.
- `display()` formatting byte-identical to GnuCOBOL DISPLAY for every usage and sign form.
- Record codecs for zoned, packed and binary encodings.
- Numeric-edited PICTURE formatting is a stretch goal.
- Keep it JBMC-friendly and annotate it with JML.

**Python and Go equivalents:** a scaled-int implementation in Python and an `int64` implementation in Go.

**Validation:**
- Property-based differential testing. Generate a random operation, operands and PICs, emit a tiny COBOL program, run it under GnuCOBOL, and compare with the library result. Run thousands of cases in CI.
- OpenJML ESC on the Java library.

## 8. Feedback, levels, scoring and acceptance

**Levels:**
- 0: T0 PASS
- 1: T1 PASS
- 2: T2 PASS
- 3: T2 PASS and T3 PASS

Also report the set of `evidence` types, so a unit that has T1 and T3 but T2 `NOT_APPLICABLE` is visible as such.

**Score** (for ranking candidates in rejection sampling): a value in [0, 4].
- +1 for T0 PASS
- + the fraction of T1 cases passing (1.0 if PASS)
- +1 for T2 PASS
- +1 for T3 PASS

The score is for ranking only. It is never the acceptance criterion.

**Acceptance policy** (configurable). A unit is accepted when all of these hold:
- T0 PASS
- T1 PASS with paragraph coverage ≥ `coverage_threshold` (default 0.8)
- no FAIL in T2 or T3; a PASS or a reasoned NOT_APPLICABLE is fine
- the integrity checks are clean

Otherwise the result is `abstain`, with a diagnosis.

**Feedback file** (`feedback/<unit>.md`). Paste-ready for the agent. Default cap of about 1,500 tokens, configurable.
- Header: unit, the tier that failed, and the tiers already passed.
- At most 3 distinct failure signatures, most severe first. For each one:
  - the shrunk counterexample as named field values
  - the expected value (GnuCOBOL) and the actual value (target)
  - the likely cause, explicitly hedged
  - the implicated COBOL statements, quoted with line numbers
  - the field-mapping row
  - the target code location, if known
- For build errors: the compiler messages with code excerpts.
- When `--previous-report` is given: what improved, what regressed, and whether this failure signature repeats (an oscillation signal for the repair loop).
- It never includes held-out evaluation data.

The `feedback/<unit>.json` file holds the same content in structured form.

Also write `docs/REPAIR_LOOP_GUIDE.md` for the generation team. Recommend:
- feed one signature at a time
- include the previous attempt's summary
- cap retries
- stop when the same signature repeats twice
- abstain when the budget is exhausted

## 9. Testing the verifier itself

**Seed corpus** (`corpus/`): 10–15 small COBOL programs. Search for permissively licensed sources such as:
- the NIST COBOL85 suite shipped with GnuCOBOL's sources
- COBOLEval, if available
- the openmainframeproject cobol-programming-course

Add hand-written programs that target the tricky semantics listed below. Write **correct handwritten translations**: Java for all of them, Python and Go for at least 5.

**Semantics golden suite** (`tests/semantics/`): one tiny program per feature, with outputs captured from GnuCOBOL. It must cover:
- MOVE: numeric high-order truncation, alphanumeric right truncation with padding, numeric↔alphanumeric moves, unsigned fields dropping sign
- ROUNDED versus truncation, and intermediate precision in COMPUTE
- ON SIZE ERROR, which leaves the target unchanged
- DIVIDE … REMAINDER
- negative zero
- COMP-3 and COMP truncation
- REDEFINES
- OCCURS, with 1-based subscripts
- PERFORM VARYING boundaries, and fall-through between paragraphs
- EVALUATE, 88-levels, INITIALIZE
- DISPLAY of signed fields
- file status codes

**Mutation operators** (COBOL-semantic, applied to correct translations to plant bugs):
- drop ROUNDED, or use HALF_EVEN instead
- remove truncation, or use a wider field
- drop the sign (abs)
- shift the scale by one place
- off-by-one in a loop bound
- flip a comparison
- pad on the wrong side
- ignore ON SIZE ERROR
- replace a decimal with double
- swap two branches

**`make selftest`** reports the following in `docs/RESULTS.md`:
- **False positives on correct translations.** This must be zero. Any FAIL on a correct translation is a verifier bug.
- **Planted-bug catch rate per tier and overall.** The proposal's target is that ≥90% of planted bugs are caught by accepted proofs.
- Time per tier.
- Percentage of units eligible for T2b and T3.

## 10. Milestones

Do them in order. Each needs its exit criteria met, with tests green, before the next one starts.

- **M0, environment and spikes.** Build a pinned Dockerfile containing GnuCOBOL 3.x, JDK 17, CBMC/JBMC, OpenJML, Python 3.11, z3-solver, crosshair-tool, Go 1.22+, libfaketime and tree-sitter grammars. Then run these time-boxed spikes, at most about 2 hours each, writing `docs/spikes/Sx.md` with findings and a go/no-go:
  - **S1:** `cobc` build, run, `-E` and trace.
  - **S2:** JBMC on a Java 17-compiled harness using `CProver.nondet*` and a `long`-backed decimal class. If JBMC rejects Java 17 class files, find a workaround (for example compiling T2 harnesses with `--release 11` or 8) and note it.
  - **S3:** an OpenJML version that supports Java 17, running ESC on a toy example.
  - **S4:** `crosshair diffbehavior` on a toy example.
  - **S5:** ProLeap versus a hand-written subset parser.
  - **S6:** ACCEPT input parsing rules and layout probes.
- **M1, Java T0, reports and corpus.** T0a and T0b, the report and feedback skeleton, and the seed corpus with Java translations.
- **M2, Java T1 (must-have for mid-eval).** The full T1 as specified, with coverage, shrinking and the classifier. Exit criteria: zero false positives, and most planted bugs caught.
- **M3, cheap breadth.** Python and Go language packs for T0 and T1, plus T2a exhaustive proofs for all languages.
- **M4, Java T2b.** Runtime library, semantics suite, IR, the Java reference emitter, the validation gate, the JBMC harness, vacuity and mutation sanity checks, and T1u.
- **M5, Java T3.** OpenJML contracts.
- **M6, wider coverage and integration.**
  - Python T2b and T3 through CrossHair.
  - Optional Go T1.5 fuzzing.
  - Integration tests using the teammates' real manifests and bundles.
  - The final numbers in `RESULTS.md`.

**Mid-eval cut line.** Target M0–M4. M2 is the minimum demo. If M4 slips, T2a still gives a real proof tier, so present that honestly.

## 11. How to work

1. **Start by doing these things, in this order:**
   1. Read `docs/proposal.pdf` and `docs/verification_notes.md`.
   2. Inspect the environment.
   3. Write `docs/DESIGN.md` (at most about 3 pages) and `docs/PLAN.md` (a milestone checklist).
   4. Write `docs/INTERFACE.md`.
   5. Begin M0.
2. **Work autonomously.** Do not block on questions. Record assumptions and choices in `docs/DECISIONS.md`, one short entry each covering context, decision and alternatives, and continue.
   - **Exception:** if a decision changes `INTERFACE.md` or `RUNTIME_API.md` after the first version, flag it prominently at the top of `PROGRESS.md`, because teammates depend on those documents.
3. **Respect time boxes.** If a tool fights you past its time box, record what failed, fall back as this spec describes, and move on.
4. **Testing and commits.**
   - Every module gets pytest tests.
   - Add an end-to-end test per tier on the seed corpus.
   - Commit after each green step with a clear message.
   - Append to `PROGRESS.md` at the end of each milestone, saying what works, what doesn't, and the next step.
5. **Never weaken a check to make a test pass.** If a correct translation fails, find out whether the bug is in the verifier, the runtime library or the translation, and fix the right one.
6. **When you finish a milestone,** run `make selftest` and update `RESULTS.md` before starting the next one.
