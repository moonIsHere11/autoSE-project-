# Verifier design (COBOL → Java / Python / Go)

Owner: Nandini (verification pipeline). Spec: the "Build the COBOL→X Verification Pipeline" prompt.
Interfaces for teammates: [INTERFACE.md](INTERFACE.md). Plan: [PLAN.md](PLAN.md). Choices: [DECISIONS.md](DECISIONS.md).

## 1. What the verifier decides

Input: a COBOL repo, a generated target repo, an optional translation manifest.
Output: for every **unit** (a COBOL paragraph mapped to a target symbol), the strongest verification
tier it reached, with evidence, and — when it fails — reproducible counterexamples formatted as
machine-readable and LLM-ready feedback. The verifier contains **no LLM**; it is deterministic tooling.

Two invariants drive everything:

* **Oracle from the COBOL side only.** Expected behaviour comes from running GnuCOBOL 3.2 (pinned) or
  from our COBOL semantic model *after* that model has been validated against GnuCOBOL. Nothing the
  generated code says about itself (comments, tests, asserts) is ever used as a specification.
* **Honest statuses.** `PASS` only after parsing a positive result from a tool's real output.
  Crashes → `ERROR`; missing tools → `ERROR`/`NOT_APPLICABLE` with reason; stubs are labelled `STUB`.
  Every `PASS` records its scope (inputs/bound, oracle, tool+version, exact command). Every `FAIL`
  carries a concretely replayed counterexample; a symbolic counterexample that does not replay is
  `ERROR`, not `FAIL`.

## 2. Execution model

```
host (Linux/WSL, Python ≥3.11)                     docker image cobol-verifier-toolchain (pinned)
┌──────────────────────────────────┐   docker run  ┌─────────────────────────────────────────────┐
│ verifier (orchestrator, no LLM)  │──────────────▶│ GnuCOBOL 3.2 · JDK 17 · JBMC · OpenJML · Go  │
│  - parses COBOL, generates cases │  --network    │ CrossHair/z3 · libfaketime · batch_runner.py │
│  - tree-sitter static checks     │  none, caps,  │ runs as uid 10001, read-only rootfs, tmpfs   │
│  - compares bytes, shrinks,      │  ro src mount │ /tmp, per-case wall-clock + RLIMIT_FSIZE     │
│    classifies, writes reports    │◀──────────────│ writes results to one rw /out mount          │
└──────────────────────────────────┘               └─────────────────────────────────────────────┘
```

* One pinned image is both toolchain and sandbox. The orchestrator never executes COBOL or target
  code on the host.
* **Batching**: one `docker run` executes a whole batch of cases (`sandbox/batch_runner.py`, mounted
  read-only), with a fresh per-case working directory, per-case timeout, and bounded parallelism.
  This keeps `fast` mode near the 60 s budget despite JVM start-up cost.
* **Workspace copies**: both input repos are copied into `<out>/workspace/{cobol,target}`; builds,
  injected contracts and harnesses only ever touch the copies (principle 8).
* **Caching**: COBOL builds are cached by `sha256(cobc -E output) + cobc version + flags`;
  GnuCOBOL expected outputs are cached by `(binary hash, case id)`.

## 3. Pipeline and gating

```
           ┌─────────── T0a build ──┐   FAIL ⇒ everything below SKIPPED
 inputs ──▶│ T0b static (tree-sitter)│   ERROR finding ⇒ T0 FAIL
           └──────────┬─────────────┘
                      ▼
            T1 differential (program level, oracle = GnuCOBOL run)
              boundary + literal-seeded + pairwise + seeded random cases
              compare stdout bytes, every output file's bytes, return code
              FAIL ⇒ decode → group by signature → shrink → classify → localise
                      │ PASS (or FAIL: T2/T3 SKIPPED "gated by T1 FAIL")
          ┌───────────┴───────────────┐
          ▼                           ▼
   T2a exhaustive (finite domain)   T2b bounded symbolic, per paragraph
   = proof over declared domain     COBOL IR → validated reference → harness → JBMC / CrossHair
          │                           vacuity: reachability + mutant kill-rate
          └───────────┬───────────────┘
                      ▼
            T3 contracts from the COBOL side (JML/OpenJML ESC, CrossHair contracts)
```

Cheapest first: a 1-second T1 refutation prevents minutes of model checking. T3 is gated only by
T1 FAIL (it runs even when T2 is `NOT_APPLICABLE`, which is exactly where it adds most value).

## 4. Units, levels, acceptance

* A **unit** is `PROGRAM-ID::PARAGRAPH` (statements before the first paragraph form `PROGRAM::(MAIN)`).
  Program-level tiers (T0a, T1, T2a) are computed once per program and attached to each of its units
  with `scope: "program"`; unit-level tiers (T1u, T2b, T3) are per paragraph.
* Levels: 0 = T0 PASS; 1 = +T1 PASS; 2 = +T2 PASS; 3 = +T3 PASS; −1 = not even T0.
  `evidence` lists every tier that passed (e.g. `T0,T1,T3` when T2 was `NOT_APPLICABLE`).
* Score ∈ [0,4] for ranking candidates only. Acceptance (configurable): T0 PASS ∧ T1 PASS ∧
  paragraph coverage ≥ 0.8 ∧ no FAIL/ERROR/TIMEOUT in selected T2/T3 ∧ integrity clean.
  Otherwise **abstain** with a diagnosis. Headline metric: % of units at each level.

## 5. COBOL side

* `cobol/gnucobol.py` — build/run/trace via the image; all `cobc` flags in one `CobolConfig`
  (default `-std=default`, fixed format, binary truncation on), recorded in every report.
* `cobol/preprocess.py` — `cobc -E` expands COPY books and normalises the format; we keep a line map
  back to the original files for feedback.
* `cobol/datadiv.py` — PIC parser (9 X A S V P, `(n)`), usages DISPLAY/COMP/BINARY/COMP-3/COMP-5,
  SIGN LEADING/TRAILING [SEPARATE], OCCURS (DEPENDING ON flagged), REDEFINES, 66/77/88, VALUE,
  FILLER, groups; computes byte lengths/offsets and is **validated against GnuCOBOL** with an
  auto-generated probe that DISPLAYs `FUNCTION LENGTH` of every item.
* `cobol/parser.py` → `cobol/ir.py` — hand-written subset parser (decision pending spike S5);
  unsupported constructs are named, never guessed (unit becomes T2-ineligible with that reason).
* `cobol/interp.py`, `cobol/dataflow.py` — concrete IR interpreter and per-paragraph read/write sets
  (transitive through PERFORM). The interpreter and the emitted references must reproduce GnuCOBOL on
  every T1 case before they are trusted (**validation gate**); a mismatch is our bug → `ERROR`.

## 6. Inputs (`inputs/`)

* Channels discovered from the source: ACCEPT targets (stdin lines, in textual order, with extra
  lines for loops), input FDs (LINE SEQUENTIAL vs fixed SEQUENTIAL), `ACCEPT … FROM COMMAND-LINE /
  ARGUMENT-VALUE / ENVIRONMENT`.
* Strategies (each case records its strategy and seed): per-field boundaries, rounding (`…5`) cases,
  literal-seeded values from conditions / EVALUATE / 88-levels, alphanumeric edge cases, file
  cardinalities 0/1/many/boundary, pairwise combinations, seeded uniform random.
* Every case is stored as a **test-case bundle** (INTERFACE §3) plus a structured *input model*
  (field → value) that enables field-level decoding and delta-debugging shrinking.
* `encode.py` maps values to bytes exactly as GnuCOBOL expects (ACCEPT text forms found by probe;
  zoned with overpunch, packed, binary at the configured byte order).
* Seeds rotate per repair iteration (`effective_seed = H(seed, iteration)`) so the random part of
  the input set changes every iteration; boundary cases are deterministic.
* **Held-out guard**: configured evaluation directories are never read. Pointing any argument at
  them is a hard error (exit 2).

## 7. Target side: language packs

`langpacks/base.py` defines `LangPack` (build, run_command, static_rules, emit_reference,
make_equivalence_harness, run_symbolic, instrument_contracts, check_contracts,
parse_counterexample, replay_concrete); any method may return `NOT_APPLICABLE`. Java is the
priority pack; Python and Go reuse the same COBOL model and differ only in the pack.
Runtime libraries (`runtimes/{java,python,go}`, see RUNTIME_API.md) give generated code exact COBOL
decimal/alphanumeric semantics, and give T2/T3 a reference implementation that is JBMC-friendly
(`long`-backed, no BigDecimal) and JML-annotated. The verifier still works (with fewer tiers) when
generated code does not use them.

## 8. Diagnosis and feedback

* Differing bytes are decoded to field values: output-file records via their FD layout; stdout
  lines via the k-th executed DISPLAY in the COBOL trace and that statement's operand layout.
* Failures are grouped by signature (mismatch kind + output location), shrunk by delta debugging
  (batched rounds), classified (`diagnose/classifier.py`, always "likely …") and localised
  (`diagnose/localize.py`: trace of the failing case ∩ statements writing the differing field).
* `feedback/<unit>.md` (≈1,500-token cap, ≤3 signatures, most severe first) and
  `feedback/<unit>.json`. With `--previous-report`: improved / regressed / repeated signature.
* Anti-overfitting: literals in the new code that match earlier counterexamples but are absent
  from the COBOL source are a T0 ERROR.

## 9. Self-test

`corpus/` (10–15 programs, correct handwritten Java for all, Python/Go for ≥5),
`tests/semantics/` (one tiny program per COBOL feature, outputs captured from GnuCOBOL), and
COBOL-semantic mutation operators. `make selftest` reports false positives on correct translations
(must be 0), planted-bug catch rate per tier, time per tier, and T2b/T3 eligibility in RESULTS.md.

## 10. Main risks and fallbacks

| Risk | Fallback |
|---|---|
| JBMC rejects Java 17 class files | compile harness + reference with `--release 11`/`8` (spike S2) |
| OpenJML cannot handle the runtime library | T3 Java `NOT_APPLICABLE` with reason; T2 unaffected |
| IR/reference disagrees with GnuCOBOL | unit T2 `ERROR` "reference not validated"; fix the model, never the oracle |
| 63-bit overflow in intermediates | T2b `NOT_APPLICABLE` "precision exceeds bound"; T3 / T1 still apply |
| JVM start-up makes T1 slow | batched, parallel in-container runner; fast-mode case cap |
| ACCEPT loops make stdin length unknowable statically | extra-line variants + literal-seeded terminators; recorded in LIMITATIONS |
