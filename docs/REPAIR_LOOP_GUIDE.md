# Repair-loop guide (for the generation team)

Audience: whoever drives the LLM that writes and repairs the target code. The verifier is
deterministic tooling with no LLM inside. This guide explains how to turn its output into the next
prompt and when to stop. Formats are in [INTERFACE.md](INTERFACE.md) §4–§5.

## 1. The loop

```
attempt 1:  generate → verify --mode fast --out runs/<unit>/it1
attempt k:  repair   → verify --mode fast --previous-report runs/<unit>/it{k-1}/report.json --out runs/<unit>/itk
final:      verify --mode full (all tiers) on the best candidate
```

* Use `--mode fast` inside the loop. It runs T0, T1 with boundary cases plus a capped random
  sample, and T2 with a small bound, in about a minute. Use `--mode full` once, on the final
  candidate.
* **Always pass `--previous-report`.** It does three things:
  1. The verifier rotates the seed of its random cases (`effective_seed = H(seed, iteration)`), so
     the model cannot overfit to a fixed input set.
  2. The anti-overfitting check (T0b) flags literals that copy an earlier counterexample.
  3. The feedback gains a `delta` section showing what improved, what regressed and which
     signatures repeat.
* Exit code `0` means every selected unit was accepted, `1` means at least one abstained, and `2`
  means a verifier/infrastructure error. On `2`, do **not** blame the model: fix the setup.

## 2. What to put in the repair prompt

Use `feedback/<PROGRAM>__<PARAGRAPH>.md`. It is paste-ready and capped at about 1,500 tokens.

1. **One failure signature at a time.** The file lists up to three signatures, most severe first.
   Give the model the first one only. Several simultaneous fixes tend to break things that already
   worked.
2. **Include the previous attempt's summary.** Give a short note on what was changed last time and
   which tiers already passed (`passed_tiers` in the JSON), so the model does not undo them.
3. **Keep the counterexample concrete.** Use the shrunk input values, expected (GnuCOBOL) vs actual
   (target), the quoted COBOL statements with line numbers, and the field-mapping row
   (`WS-TOTAL  PIC S9(5)V99 → wsTotal : long`).
4. **The "likely cause" is a hint, not a fact.** Pass it along as "the verifier suspects …". It is
   produced by a deterministic classifier and is always hedged.
5. For **build errors** (T0a), give the compiler messages with the code excerpts and nothing else.
6. For **static findings** (T0b ERROR), give the finding and its rule: forbidden float for a
   decimal, forbidden API, undeclared file path, swallowed exception, or anti-overfitting literal.
   These are fixed by changing the approach, not by tweaking values.

Never give the model the verifier's test cases wholesale, and never give it anything from the
evaluation team's held-out set. The verifier refuses to read held-out directories, and its feedback
never contains held-out data. Keep it that way on your side too.

## 3. When to stop

| Situation | Action |
|---|---|
| Unit `accepted: true` | Stop; keep the candidate. |
| The same signature appears in `delta.repeated_signatures` **twice in a row** | Stop repairing that signature: the model is oscillating. Either try a fresh generation (rejection sampling, ranked by `score`) or abstain. |
| A fix makes a previously passing tier fail (`delta.regressed` non-empty) | Revert to the previous candidate and re-prompt with both the old and the new signature. |
| Retry budget exhausted (recommended: **5 repairs per unit**, 3 fresh generations) | **Abstain**: report the unit as not migrated, with the last feedback as the diagnosis. |
| `ERROR`/`TIMEOUT` statuses (infrastructure) | Not the model's fault. Re-run once, then report to the verifier owner. |

Abstaining is a valid outcome. The point of the harness is to accept only verified code.

## 4. Ranking candidates

`score` ∈ [0, 4]: +1 for T0 PASS, plus the fraction of T1 cases passing, +1 for T2 PASS, +1 for T3
PASS. Use it to pick the best of several samples. **Acceptance is never decided by score**: it
uses the policy in the report (T0 PASS, T1 PASS with paragraph coverage ≥ 0.8, no FAIL/ERROR in
T2/T3, integrity clean).

## 5. Making the verifier's job easier (and getting higher levels)

* Ask the model to use the **runtime library** (`cobolrt`, see [RUNTIME_API.md](RUNTIME_API.md))
  for COBOL numerics and PIC X fields. Unit-level proofs (T2b with JBMC, T3 with OpenJML) work
  only on `long`-backed decimals and `char[]` alphanumerics. `BigDecimal`/`String` code still gets
  T0+T1, but T2b becomes `NOT_APPLICABLE`.
* Keep the naming conventions (or emit a manifest): one class per PROGRAM-ID, one method per
  paragraph, one field per data item. Unit-level tiers need the mapping.
* Keep I/O (ACCEPT/DISPLAY/READ/WRITE) out of computational paragraphs, as in the COBOL source.
  Pure paragraphs are the ones that can be proved.
* Never read the clock or a random generator directly, and never open files other than the ones
  in the COBOL `ASSIGN` clauses (T0 ERROR).
