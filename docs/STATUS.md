# COBOL → Java verifier: status in plain words

*Last updated: 6 Nov 2026. Scope: Java only. The Python and Go code is kept but paused.*

## What the verifier does (one line)

You give it a COBOL program and a Java program that claims to do the same thing. It tells you
whether they really behave the same, and how strong that evidence is. When they differ, it shows
an exact input that proves it.

It does **not** translate anything. Real COBOL (GnuCOBOL 3.2) is always the judge, never the Java.

## The plan, step by step: did we do it?

| # | Planned check | In simple words | Status |
|---|---|---|---|
| 1 | **T0 – build + code checks** | Does the Java compile? Does it avoid bad things (e.g. `double` for money, network, clock, hard-coded answers)? | ✅ Done. Works on all 14 test programs. |
| 2 | **T1 – side-by-side testing** | Run COBOL and Java on hundreds of generated inputs and compare every output byte. | ✅ Done. 0 false alarms on all 14 correct Java programs (265–408 inputs each, every paragraph exercised). |
| 3 | **T2a – try every input** | If a program has a small number of possible inputs, try all of them. That is a real proof. | ✅ Done. Proves 3 of the 14 programs completely (DIVREM, TAXCALC, TEMPCONV). |
| 4 | **T2b – math proof per paragraph (JBMC)** | A tool mathematically checks one COBOL paragraph against its Java method for *all* values. | ⚠️ Works, but only on a few paragraphs. Fully proven so far: `SET-RETURN` in DIVREM and INVENTORY. Most paragraphs can't use it (see "limits"). |
| 5 | **Validation gate for T2b** | Before trusting our own COBOL model, check it reproduces real COBOL. | ✅ Done today (it was a stub before). |
| 6 | **T1u – per-paragraph random testing** | Throw random values at one paragraph on both sides. | ✅ Works (runs wherever T2b can run). |
| 7 | **T3 – contracts (OpenJML)** | Write rules from the COBOL (value ranges, which fields may change, exact result) and prove the Java method obeys them. | ⚠️ Works on suitable paragraphs (e.g. TAXCALC `COMPUTE-TAX` passes). Two bugs fixed today (String fields, OpenJML crash). |
| 8 | **Runtime library (`cobolrt`)** | A Java helper library that does COBOL math exactly. | ✅ Written and matches real COBOL on 10,000 random cases. ❌ Its own formal proof run is not working yet. |
| 9 | **COBOL rule tests** | 25 tiny COBOL programs pinning down tricky rules (rounding, truncation, signs, …). | ✅ Done. |
| 10 | **Reports + feedback for the fixing AI** | `report.json`, `summary.md`, per-paragraph feedback with the failing input. | ✅ Done. |
| 11 | **Self-test with planted bugs** | Insert known bugs into correct Java and count how many we catch. | ⏳ Running now; numbers go into `RESULTS.md`. |
| 12 | Python and Go | Same checks for other languages. | ⏸️ Paused on purpose (code kept). |

## What we can guarantee

* **T1 PASS:** on every one of the hundreds of generated inputs, the Java output is
  byte-for-byte identical to real COBOL. This is strong testing, **not** a proof for every input.
* **T2a PASS:** identical on **every possible input** in the declared input range. This is a proof.
* **T2b PASS:** for that paragraph, identical for **all** field values. It is a mathematical proof,
  and we also check that the proof isn't empty and that it catches planted bugs.
* **T3 PASS:** the Java method provably obeys the rules taken from the COBOL.
* **Every FAIL** comes with a concrete input you can re-run. A tool crash or a missing tool is
  **never** reported as PASS. Anything unfinished is labelled STUB or NOT_APPLICABLE with a reason.

## What we cannot guarantee (limits)

* Programs that use SQL, CICS, indexed files or SORT are out of scope and are marked as such.
* We copy GnuCOBOL's behaviour, not IBM mainframe COBOL's.
* The math proofs (T2b) can't handle most paragraphs:
  * paragraphs that read or print (about half of all paragraphs);
  * multiplication or division by a variable (the tool runs for more than 15 minutes with no answer);
  * Java that stores text as `String` or numbers as `BigDecimal`.

  These paragraphs still get T1 testing and, where possible, T2a and T3.
* T1 is testing, not proof: a bug that shows up only on inputs we never generated could slip through.

## What is left

1. Finish the final corpus run and the planted-bug self-test, then publish the numbers (`RESULTS.md`).
2. Investigate 4 empty `*-EXIT` paragraphs in MERGE2 that T2b reports as ERROR. That is the safety
   check refusing an unconvincing proof, so it is never a wrong PASS.
3. Get the runtime library's own formal proof working.
4. Later: Python and Go, and plugging in the teammates' real manifests and test bundles.
