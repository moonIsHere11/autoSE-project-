# Runtime library `cobolrt` (Java): API proposal for the generation team

`cobolrt` gives generated Java exact GnuCOBOL 3.2 data semantics, so the model doesn't have to
re-derive truncation, rounding, sign and DISPLAY rules in every program. Using it is **optional**:
the verifier works without it (T0/T1/T2a always apply). Code that uses it, or follows the same
representation conventions, is easier to check with T2b/T3.

*Status (6 Nov 2026):* Java is the priority. Python and Go ports exist (`runtimes/python`,
`runtimes/go`) and are paused, but kept.

## Where it is

* Sources: `runtimes/java/src/cobolrt/*.java`. Built jar: `runtimes/build/java/cobolrt.jar`
  (`make runtimes`; the hashes are in `runtimes/build/BUILD.json`).
* At verification time the jar is mounted read-only at `/opt/cobolrt` and is on the classpath for
  building and running the candidate.

## Main classes

| Class | What it is | Key methods |
|---|---|---|
| `Pic` | Description of a numeric item: digits, scale, signed, usage, sign position | `Pic.parse("S9(5)V99", "COMP-3")` |
| `CobolDecimal` | A numeric elementary item: `long` unscaled value + `Pic` | `of(pic, usage, literal)`, `move(...)`, `add/subtract/multiply/divide(x, Round.*, SizeError.*)` (return `true` on size error), `divideRemainder(...)`, `compute(Dec, mode, size)`, `compareTo`, `accept(line)`, `display()`, `encode()`/`decode()` |
| `PicX` | `PIC X(n) [JUSTIFIED RIGHT]`, fixed-length ISO-8859-1 bytes, initially spaces | `move(...)` (pad/truncate like COBOL), `accept(line)`, `bytes()` |
| `Display` | DISPLAY output byte-identical to GnuCOBOL | `Display.print(System.out, item1, " ", item2)` |
| `Codec` | Record encodings: zoned (overpunch sign), COMP-3, COMP (big-endian), COMP-5 (little-endian) | `encode(u, pic)`, `decode(bytes, item)` |
| `Accept` | ACCEPT from stdin, line rules and EOF behaviour of GnuCOBOL | |
| `Round`, `SizeError`, `Usage` | `int` codes for ROUNDED modes, ON SIZE ERROR phrases, usages | `Round.TRUNCATION`, `Round.ROUNDED`, … |
| `Num`, `Alnum` | Static, JBMC/OpenJML-friendly core on `long` / `byte[]` (no JDK calls, no exceptions, JML-annotated). The verifier's reference emitter uses these. | `Num.truncDigits`, `Num.rescale`, `Num.fits`, `Alnum.move`, `Alnum.compare`, … |

Example: `ADD A TO B ROUNDED ON SIZE ERROR … END-ADD`

```java
if (b.add(a, Round.ROUNDED, SizeError.ON)) { /* ON SIZE ERROR branch: b is unchanged */ }
```

## Semantics (measured against GnuCOBOL 3.2, `-std=default`)

* Stores truncate high-order digits; without ROUNDED, excess decimals are truncated toward zero.
* ROUNDED = nearest, away from zero. The exception is ADD/SUBTRACT into COMP-3, which GnuCOBOL 3.2
  truncates; this is measured behaviour.
* ON SIZE ERROR leaves the target unchanged. Unsigned targets drop the sign.
* DISPLAY: signed items always show `+`/`-`; `V` prints as `.`; COMP-5 prints the raw binary integer.

## Conventions the verifier can check most strongly (T2b/T3)

* Numeric field → `long` (or `int` for ≤ 9 digits) holding value × 10^scale. `BigDecimal`,
  `String` and `double` fields are accepted by T0/T1, but T2b/T3 then report NOT_APPLICABLE.
* Alphanumeric field → `char[]` or `byte[]` of exactly the PIC length. `String` works for T1/T3,
  but JBMC (T2b) can't check it.
* One instance method per paragraph, operating on the object's fields, with no parameters.

## Validation

* **Differential property tests** (`tests/runtimes`): random operation, operands and PICs → a tiny
  COBOL program is generated and run under GnuCOBOL and compared with the library. The last run
  covered 10,000 cases per language, all matching (`out/rt-difftest/summary_22.json`, seed 22).
* **OpenJML ESC on `Num`/`Alnum`** (`runtimes/java/esc/run_esc.sh`): **not working yet**. The
  script copies the sources without their `cobolrt/` package directory, so OpenJML can't resolve
  `Round`/`Usage`. See `LIMITATIONS.md`.
