# TEMPCONV

## Python and Go translations

Hand-written, correct translations of TEMPCONV (decimals are integers scaled by 10^scale or `Decimal`, never binary floating point), following the rules in `corpus/README.md`:

* **Python** - `python/tempconv.py`: every numeric is a `decimal.Decimal` (context precision 200); `div` truncates quotients 38 digits beyond the operands' scale as GnuCOBOL does (`WS-TEMP / 3 * 3` with 1 gives 0.9).
* **Go** - `go/tempconv/`: `int64` scaled values; each COMPUTE is an exact fraction stored with ROUNDED or truncation. The only place the 38-digit truncated quotient is observable (`WS-TEMP / 3 * 3`) is modelled explicitly (`storeBelow`); the comment explains why exact fractions are equivalent elsewhere. `go.mod` declares module `example.com/tempconv` (no dependencies).

Validation (`python -m tools.corpus_check corpus/tempconv --lang python|go`: 0 differences; `verify --tiers 0,1,2 --mode full`), identical for both languages: T0 PASS, T1 PASS (278 cases, coverage 1.0/1.0), T2a PASS (exhaustive, 1,100 inputs): level 2.
