# Verifier interfaces (v1.0)

Audience: the corpus/evaluation teammate and the generation/repair-loop teammates.
Owner: Nandini. **Any change to this file after v1.0 is announced at the top of `docs/PROGRESS.md`.**

Contents: 1. CLI / Python API · 2. Translation manifest · 3. Test-case bundle · 4. Report ·
5. Feedback files · 6. Held-out separation and seeds · 7. How target programs are run.

---

## 1. CLI and Python API

```
verify --cobol PATH --target PATH --lang {java,python,go}
       [--manifest PATH] [--mode fast|full] [--units ID,...]
       [--tiers 0,1,2,3] [--seed N] [--previous-report PATH] --out DIR
       [--config PATH]                       # optional TOML, see verifier/config.py
verify repro --case DIR --report PATH        # re-run one counterexample on both sides
```

```python
from verifier.api import verify
report = verify(cobol="path/to/cobol", target="path/to/java", lang="java",
                manifest=None, mode="fast", units=None, tiers=None, seed=0,
                previous_report=None, out="out/run1")
report.summary.accepted          # pydantic model, same content as report.json
```

| Mode | What runs | Budget |
|---|---|---|
| `fast` (inner repair loop) | T0; T1 with all boundary/literal cases + capped random sample (default cap 150 cases); T2 with a small bound (`unwind=4`, exhaustive limit 2,000) | ≈60 s for a 300–500-line program |
| `full` | all selected tiers, full case budget, larger bounds, T3, mutation sanity | minutes |

`--tiers` selects tiers; tiers not selected are reported `SKIPPED` with reason `"not selected"` and
are **not** considered by the acceptance policy (the report records which tiers were considered).

`--units` takes unit ids (`PROGRAM::PARAGRAPH`) or program ids (`PROGRAM`, meaning all its units).

**Exit codes:** `0` every selected unit accepted · `1` at least one unit not accepted (abstain) ·
`2` verifier error (bad arguments, invalid manifest, held-out path, Docker/toolchain unavailable).

Requirements: Linux or WSL2, Python ≥ 3.11, Docker; `make image` builds the pinned toolchain image.

---

## 2. Translation manifest (`--manifest`, optional)

Produced by the generation team. Validated strictly (pydantic, unknown keys rejected, helpful
errors). Without a manifest the verifier falls back to the naming conventions below; any tier that
needs information the conventions cannot supply becomes `NOT_APPLICABLE` with a reason.

```json
{
  "schema_version": "1.0",
  "language": "java",
  "build": {"command": "mvn -q -o -DskipTests package", "workdir": "."},
  "programs": [{
    "cobol_program_id": "LOANCALC",
    "cobol_file": "src/LOANCALC.cbl",
    "run": {"command": "java -cp $TARGET_ROOT/target/classes com.acme.LoanCalc"},
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

Field notes:

* `language` must equal `--lang`.
* `build.command` runs inside the sandbox **with no network**, cwd = `build.workdir` relative to the
  target repo copy. Maven builds must work offline (`-o`); the image pre-populates nothing beyond the
  JDK. If omitted, the language default is used (Java: `javac` on every `*.java` outside
  `src/test`; Python: `py_compile` + `mypy`; Go: `go build ./... && go vet ./...`).
* `run.command` is executed by `sh -c` with **cwd = a fresh per-test-case working directory** (where
  the program's data files live). `$TARGET_ROOT` is the built, read-only target repo and
  `$COBOLRT` is the runtime-library directory. For convenience, relative paths in the command that
  exist in the target repo (including `-cp`/`-classpath` entries) are rewritten to absolute paths
  under `$TARGET_ROOT`; the rewritten command is recorded in the report.
* `files[].path` is the file name the program uses in its working directory. Default: the name in
  the COBOL `ASSIGN` clause.
* `units[]`: `cobol_paragraph` → `target_symbol` (method / function name; Java: method of `class`).
* `fields[].declared.kind` ∈ `decimal` (numeric with scale, incl. integers: scale 0), `alnum`,
  `alpha`, `group`, `binary`; `usage` ∈ `DISPLAY`, `COMP`, `BINARY`, `COMP-3`, `PACKED-DECIMAL`,
  `COMP-5`. `digits` counts integer + fraction digits (e.g. `PIC 9(5)V99` → digits 7, scale 2);
  for `alnum`/`alpha` use `"length": n` instead of digits/scale.
* Optional `fields[].target_type` lets you state the target type explicitly (e.g. `"CobolDecimal"`,
  `"long"`, `"BigDecimal"`, `"String"`); otherwise the verifier reads it from the code.

**Default conventions (no manifest, or partial manifest):**

| | Program | Paragraph | Field |
|---|---|---|---|
| Java | class `PascalCase(PROGRAM-ID)` with `main`, any package | method `camelCase(paragraph)` | field `camelCase(item)` |
| Python | module `snake_case(PROGRAM-ID).py`, run as `python3 -m` | function `snake_case` | attribute `snake_case` |
| Go | package dir `snake_case(PROGRAM-ID)` with `main`, built to one binary | exported `PascalCase` | exported `PascalCase` |

Case conversion splits COBOL names on `-` (`WS-INTEREST` → `wsInterest` / `ws_interest` / `WsInterest`).
Files: both programs read/write files under the same relative names in their working directory.

---

## 3. Test-case bundle (shared with the evaluation teammate)

```
case_<hash>/
  case.json      # see below
  stdin.txt      # exact bytes fed to stdin (may be empty)
  in/<files>     # exact bytes of every input file, placed in the working directory before the run
  expected/      # filled by running GnuCOBOL (never by the target):
    stdout       #   exact stdout bytes
    stderr       #   stored, never compared
    return_code  #   decimal text
    out/<files>  #   every file present in the working directory after the run
    meta.json    #   cobc version, flags, binary sha256, runtime env, duration, excluded?/why
```

`case.json`:

```json
{
  "schema_version": "1.0",
  "id": "case_3f9a0c12d4e5b6a7",
  "program": "LOANCALC",
  "args": [],
  "env": {},
  "fake_time": "2024-01-15T10:30:00",
  "stdin": "stdin.txt",
  "files_in": [{"name": "CUSTIN.dat", "sha256": "…"}],
  "generator": {"strategy": "boundary:WS-AMT=max", "seed": 1234, "tool": "verifier 0.1.0"},
  "model": {"stdin": [{"field": "WS-AMT", "value": "99999.99"}], "files": {}}
}
```

* `id` = `case_` + first 16 hex digits of sha256 over (program, stdin bytes, args, env, fake_time,
  input file names+bytes). Identical inputs ⇒ identical id, from any producer.
* `model` is optional (the verifier's own cases have it; it enables field-level decoding and
  shrinking). Hand-made or evaluation cases may omit it.
* `fake_time` (optional) freezes the wall clock for both sides (libfaketime + the runtime
  library's injected clock, see §7).
* Comparison: stdout bytes, every file in `expected/out/` (and no extra files on the target side),
  return code. stderr is never compared. No normalisation unless explicitly enabled; enabled
  normalisers are listed in the report.
* The evaluation teammate can run the same runner on held-out bundles; the verifier itself never
  reads them (§6).

---

## 4. Report (`<out>/report.json`, pydantic, `schema_version: "1.0"`)

```json
{
  "schema_version": "1.0",
  "verifier_version": "0.1.0",
  "run": {"cobol": "…", "target": "…", "lang": "java", "mode": "fast", "tiers": [0,1,2],
          "seed": 0, "iteration": 1, "effective_seed": 81726354, "previous_report": null,
          "argv": ["verify", "…"]},
  "toolchain": {"image": "cobol-verifier-toolchain:0.1.0@sha256:…", "gnucobol": "cobc (GnuCOBOL) 3.2.0", "…": "…"},
  "config": {"cobc_flags": ["-x", "-std=default"], "runtime_env": {}, "normalisers": [],
             "acceptance": {"coverage_threshold": 0.8}, "limits": {"case_timeout_s": 10}},
  "programs": [{"id": "LOANCALC", "tiers": {"T0": {}, "T1": {}, "T2": {}}, "out_of_scope": null}],
  "units": [{
    "id": "LOANCALC::CALC-INTEREST",
    "program": "LOANCALC",
    "level": 1,
    "evidence": ["T0", "T1"],
    "accepted": false,
    "acceptance": {"tiers_considered": ["T0","T1","T2","T3"], "reasons": ["T3 FAIL"]},
    "score": 2.0,
    "tiers": {
      "T0": {"status": "PASS", "checks": []},
      "T1": {"status": "PASS", "scope": {"level": "program"}, "cases_run": 412, "cases_failed": 0,
             "cases_excluded": 3, "coverage": {"paragraph": 0.92, "statement": 0.81,
             "uncovered": ["ERR-HANDLER"]}, "failure_signatures": [], "counterexamples": []},
      "T2": {"status": "NOT_APPLICABLE", "reason": "uses STRING (outside the T2b subset)"},
      "T3": {"status": "FAIL", "counterexamples": ["…"]}
    },
    "repro": ["verify repro --case out/run1/cases/case_… --report out/run1/report.json"]
  }],
  "summary": {"units": 12, "accepted": 7, "level_histogram": {"-1": 1, "0": 2, "1": 5, "2": 3, "3": 1},
              "pct_units_at_least_level": {"0": 91.7, "1": 75.0, "2": 33.3, "3": 8.3},
              "evidence_histogram": {"T0": 11, "T1": 9, "T2a": 2, "T2b": 2, "T3": 1},
              "tier_timings_s": {"T0": 3.1, "T1": 21.4, "T2": 30.2, "T3": 0.0},
              "stubs": []}
}
```

Every tier result has: `status` ∈ `PASS | FAIL | ERROR | TIMEOUT | NOT_APPLICABLE | SKIPPED`,
`reason` (required unless PASS/FAIL), `stub` (true ⇒ rendered as `STUB`), `method`
(`build`, `static`, `differential_testing`, `exhaustive`, `bmc`, `symbolic_search`, `esc`),
`scope` (what was checked, inputs/bound, oracle, tool + version, exact command), `duration_s`.

* **Levels:** −1 none; 0 = T0 PASS; 1 = T0+T1 PASS; 2 = … + T2 PASS; 3 = … + T3 PASS.
* **Evidence:** every tier that passed: `T0`, `T1`, `T1u`, `T2a` (exhaustive), `T2b` (bounded
  symbolic; `bound: complete` or `bound: k`), `T3`.
* **Score** ∈ [0, 4] = T0 + fraction of T1 cases passing + T2 + T3. Ranking only, never acceptance.
* **Acceptance** (default policy): T0 PASS; T1 PASS with paragraph coverage ≥ 0.8; T2/T3 (if
  selected) PASS or NOT_APPLICABLE; integrity checks clean. Otherwise `accepted: false` with reasons.
* Program-level tiers (T0a build, T1, T2a) appear once under `programs[]` and are copied into each
  unit with `scope.level = "program"`.
* Never any BLEU-style similarity metric.

`<out>/summary.md` is the human view. `<out>/cases/` holds every generated bundle with
`expected/` and the target's `actual/` outputs.

---

## 5. Feedback files (for the repair loop)

`<out>/feedback/<unit_id>.md` — paste-ready, ≈1,500 tokens max (configurable), unit id with `::`
replaced by `__`. `<out>/feedback/<unit_id>.json` — the same content, structured:

```json
{
  "unit": "LOANCALC::CALC-INTEREST",
  "failed_tier": "T1", "passed_tiers": ["T0"],
  "signatures": [{
    "signature": "VALUE_MISMATCH stdout:L57 WS-TOTAL",
    "severity": 1,
    "counterexample": {"inputs": {"WS-AMT": "-123.45"}, "expected": {"WS-TOTAL": "-123.45"},
                       "actual": {"WS-TOTAL": "123.45"}, "case": "cases/case_…"},
    "likely_cause": {"label": "SIGN_LOST", "text": "likely: the sign of WS-TOTAL is dropped"},
    "cobol_statements": [{"file": "src/LOANCALC.cbl", "line": 57, "text": "COMPUTE WS-TOTAL = …"}],
    "field_mapping": {"cobol": "WS-TOTAL", "pic": "S9(5)V99", "target": "wsTotal", "declared": {}},
    "target_location": {"file": "src/main/java/com/acme/LoanCalc.java", "line": 88},
    "repro": "verify repro --case … --report …",
    "repeats_previous": false
  }],
  "build_errors": [],
  "delta": {"improved": [], "regressed": [], "repeated_signatures": []}
}
```

At most 3 signatures, most severe first. Causes are always hedged ("likely"). Never contains
held-out evaluation data. See `docs/REPAIR_LOOP_GUIDE.md` for how to use it.

---

## 6. Held-out separation and seeds

* Configure held-out directories with `VERIFIER_HELDOUT_DIRS` (path-separated) or `heldout_dirs` in
  the config. If `--cobol`, `--target`, `--manifest`, `--out` or `--previous-report` resolves inside
  one, the verifier exits with code 2 before reading anything. Generated code referring to those
  paths is a T0 integrity ERROR.
* The verifier's input generation is independent of the evaluation teammate's. Its random part
  uses `effective_seed = H(seed, iteration)`, where `iteration` = previous report's iteration + 1,
  so every repair iteration sees fresh random inputs; boundary and literal-seeded cases are
  deterministic (they derive from the COBOL source).

---

## 7. How programs are run (both sides)

* Inside the pinned image, as uid 10001, `--network none`, CPU/memory/pids caps, read-only root
  filesystem and source mount, tmpfs working directory, per-case wall-clock timeout (default 10 s)
  and file-size limit.
* Time: if a program reads the clock (CURRENT-DATE, ACCEPT FROM DATE/TIME, RANDOM), both sides run
  under libfaketime frozen at the case's `fake_time` (default `2024-01-15T10:30:00`), and the
  environment variable `COBOL_VERIFIER_FAKE_TIME` carries the same ISO timestamp for runtime
  libraries that inject a clock. COBOL is run twice per case; disagreeing runs are excluded as
  flaky (counted and reported).
* Environment: `LANG=C.UTF-8`, `TZ=UTC`, plus the case's `env`. GnuCOBOL runtime settings are in the
  report's `config.runtime_env`.
