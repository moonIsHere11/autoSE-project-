# Phase 2 · Checker (adapter over the formal verifier in `verifier/`)

## How to call me
```
make venv                                      # once: ~/.venvs/cobol-verifier (pydantic 2, tree-sitter)
make image                                     # once: pinned toolchain image (GnuCOBOL, JBMC, OpenJML)
phase2/bin/phase2 check --workspace W --submission S-0001 [--until build|lint|differential|verification]
python3 integration/demo_workspace.py /tmp/ws divrem [--bug]   # sample workspace + submission (corpus program)
```
`phase2/bin/phase2` re-execs under the verifier venv (`VERIFIER_PY` overrides). Exit codes: 0 ran (red is fine), 2 bad input, 3 internal.

## What the adapter does (`phase2_adapter/`)
1. Reads `submissions/<sid>/submission.json`; **KB version mismatch -> `error` / `infra_error`** (agreement 7).
2. Compares the project's runtime dir with `kb/target/runtime` byte for byte; any diff -> blocker `build_error` (agreement 5).
3. Gives the verifier a copy of the project **without** the runtime dir (the verifier mounts its own verified `cobolrt` jar).
4. Calls `verifier.api.verify(cobol=dirname(source.entry), target=<copy>, lang=java, units=..., tiers=..., previous_report=<last report>)`.
   `gate.required_tier` -> tiers: tested = T0+T1, bounded = +T2, proven = +T3 (`full` mode). `--until` caps the tiers.
   Passing the previous report rotates the random-test seed each attempt and adds a `delta` to the feedback (anti-overfitting).
5. Converts Nan's report to the agreement Report (`convert.py`) and writes `reports/<sid>/report.json` atomically.
   Raw verifier output (report.json, summary.md, feedback/, cases/) stays in `reports/<sid>/artifacts/verifier/`.

## Mapping
| Verifier | Agreement |
|---|---|
| unit evidence T3, T2a, T2b(bound complete) | tier `proven` |
| T2b (bound k) | `bounded` |
| T0+T1 pass | `tested` |
| T0 only / T1 fail | `unchecked` |
| T0 build / static ERROR findings | `build_error` / `lint` (blocker) |
| T1 counterexample (<=3 per unit, from `feedback/*.json`) | `behavior_mismatch` + `counterexample` + `reproduce` |
| T2/T3 FAIL | `verification_failed`; ERROR/TIMEOUT -> `infra_error`/`timeout` warning |
| unit not accepted (e.g. paragraph coverage < 0.8) or tier below required | blocker `verification_unknown` |
| classifier cause (SIGN_LOST, ROUNDING_MISSING, ...) | `kb_refs` gap ids (`G-SIGN`, `G-ROUNDING`, `G-TRUNCATE`...) shared with Phase 1's hazard scanner |
| verifier infra failure (docker, tool crash) | verdict `error` (free retry) |

## Deviations from agreement.md (to agree with the team)
- **Execution interface (4.2) is not used.** The verifier runs the *whole program* (stdin/stdout/files) against GnuCOBOL, so `driver_cmd` is ignored and no unit driver is needed. Unit evidence is per paragraph inside that run.
- **Unit ids:** verifier uses `PROGRAM::PARAGRAPH`; the adapter accepts `PARAGRAPH` (single program), `PROG.PARA`, `PROG::PARA` or a bare program id (= all its paragraphs).
- **Granularity:** because T1 executes the whole program, Phase 1 now submits whole programs (`phase1.granularity: program`, default) instead of single paragraphs; a half-translated program cannot pass differential testing.
- **Runtime library:** the verifier owns `cobolrt` (`runtimes/java`); Phase 0's `kb/target/runtime` should be a copy of it.
- **Conventions** (class `PascalCase(PROGRAM-ID)`, method `camelCase(paragraph)`, field `camelCase`) are in Phase 1's system prompt (`CHECKER_JAVA`).
