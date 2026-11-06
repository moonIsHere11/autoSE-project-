# TAXCALC

## Python and Go translations

Hand-written, correct translations of TAXCALC (decimals are integers scaled by 10^scale or `Decimal`, never binary floating point), following the rules in `corpus/README.md`:

* **Python** - `python/taxcalc.py`: module-level variables and one function per paragraph (`global` state), ints scaled by 10^scale.
* **Go** - `go/` root package (`main.go` at the repository root, so the verifier uses the only main package): package-level `int64` variables and exported functions. `go.mod` declares module `example.com/taxcalc` (no dependencies).

Validation (`python -m tools.corpus_check corpus/taxcalc --lang python|go`: 0 differences; `verify --tiers 0,1,2 --mode full`), identical for both languages: T0 PASS, T1 PASS (265 cases, coverage 1.0/1.0), T2a PASS (exhaustive, 1,000 inputs): level 2.
