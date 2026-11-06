# Seed corpus

Small COBOL programs that exercise tricky semantics, each with **correct** hand-written
translations. The verifier's self-test (`make selftest`) requires **zero** FAILs on these
translations and plants COBOL-semantic mutants into them to measure the bug-catch rate.

## Layout

```
corpus/<name>/
  README.md            what the program does and which COBOL semantics it targets
  cobol/<PROG>.cbl     fixed-format COBOL, compiles with the pinned GnuCOBOL 3.2 (-std=default)
  java/src/main/java/corpus/<Class>.java     (+ helper classes in the same package if needed)
  python/<prog>.py     (some programs; milestone M3)
  go/...               (some programs; milestone M3)
  manifest.java.json   optional translation manifest (docs/INTERFACE.md section 2)
  check_cases.json     hand-picked differential cases for tools/corpus_check.py
```

## Java translation rules (keep T0 clean)

* One public class per PROGRAM-ID, named PascalCase of the PROGRAM-ID split on `-`
  (`LOANCALC` → `Loancalc`, `LOAN-CALC` → `LoanCalc`), package `corpus`, with
  `public static void main(String[] args)`.
* Every WORKING-STORAGE / FILE SECTION elementary item that the program uses → a **non-private
  instance field** named camelCase of the COBOL name (`WS-TOTAL` → `wsTotal`).
* One **non-private instance method per paragraph**, camelCase (`CALC-INTEREST` → `calcInterest`).
  Reproduce the COBOL control flow exactly: PERFORM → call; fall-through from one paragraph into the
  next where COBOL falls through; STOP RUN ends the program.
* Numbers: `long` holding the value scaled by 10^scale (preferred; JBMC-friendly), or
  `java.math.BigDecimal` (allowed; use it in a few programs for diversity). Never `float`/`double`.
  `int` only for ≤ 9 digits.
* Alphanumerics: `String` kept at exactly the PIC length (space padded), or `char[]`/`byte[]`.
* stdin: `new BufferedReader(new InputStreamReader(System.in, StandardCharsets.ISO_8859_1))`.
  stdout: write bytes exactly (`\n` line endings, ISO-8859-1), flush before exit.
  Exit code: `System.exit(returnCode)` (RETURN-CODE; 0 by default).
* Files: open exactly the names in the COBOL `ASSIGN` clause, relative to the working directory.
* Forbidden (T0 ERRORs): wall clock / RNG / reflection / process execution / network; any file name
  not declared by the COBOL program; `catch (Exception|Throwable|RuntimeException e)` that does not
  rethrow or exit; imports outside `java.*`.

## Semantics a correct translation must reproduce (GnuCOBOL 3.2, `-std=default`)

Read `docs/spikes/S6.md` (measured behaviour). The verifier's input generator emits:

* **ACCEPT into numeric DISPLAY fields:** canonical texts `[-]digits[.digits]`, plus *overlong*
  texts (longer than the field). GnuCOBOL takes the **first byte-length characters** of the line,
  then de-edits (sign, digits, one decimal point), aligns on the decimal point, truncates excess
  decimals and high-order digits. `-99999` into `S9(5)` → −9999; `123.45` into `9(3)V99` → 123.40.
  **COMP / COMP-3:** the whole line is de-edited then moved (high-order truncation to the PIC).
  **COMP-5:** not truncated to the PIC; wraps at the binary width.
* **ACCEPT into `X(n)`:** first n characters, space padded. Inputs include empty lines, spaces,
  mixed case, digits, and overlong text (printable ASCII only).
* **EOF:** stdin may have fewer lines than ACCEPTs (and also extra lines). Check what GnuCOBOL does
  on EOF for your fields and reproduce it.
* **DISPLAY:** unsigned numeric → digits; signed → leading `+`/`-` always; `V` → decimal point
  inserted; `SIGN TRAILING SEPARATE` → sign after the digits; COMP-3/COMP display like DISPLAY
  numerics of the same PIC; COMP-5 shows as many digits as the binary capacity (`S9(4) COMP-5` →
  5 digits); groups → raw bytes.
* **Arithmetic:** ROUNDED = half away from zero; without ROUNDED truncate toward zero; results never
  negative zero; high-order truncation without ON SIZE ERROR; with ON SIZE ERROR the target is left
  **unchanged** and the error branch runs; DIVIDE by zero without ON SIZE ERROR leaves the target
  unchanged and continues; MOVE to an unsigned field drops the sign. COMPUTE intermediate results are
  exact (do not round intermediates).
* **Files:** LINE SEQUENTIAL WRITE trims trailing spaces and appends `\n`; READ pads short lines with
  spaces and **splits** lines longer than the record into several records; a last line without `\n`
  is read normally. Fixed SEQUENTIAL records are concatenated with no delimiter; zoned negative =
  ASCII overpunch (last digit byte `0x70 + d`), COMP-3 sign nibble C/D/F, COMP big-endian, COMP-5
  little-endian.

## Validating a translation

```
python -m tools.corpus_check corpus/<name> --lang java
```

builds both sides in the sandbox, runs every case in `check_cases.json` and prints byte-level
differences. The COBOL output is the oracle: when they differ, fix the translation, never the cases.
Each program has ≥ 25 cases covering boundaries (max/min/zero/negative/overlong/`…5` rounding/empty
input/0, 1 and many records/EOF).
