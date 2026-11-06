# DIVREM

## Python and Go translations

Hand-written, correct translations of DIVREM (decimals are integers scaled by 10^scale or `Decimal`, never binary floating point), following the rules in `corpus/README.md`:

* **Python** - `python/calc/divrem.py` in package `calc` (run as `python3 -m calc.divrem`), helpers in `calc/cobolsem.py`. Python's `//`/`%` floor, so `tdiv`/`tmod` reproduce COBOL truncation toward zero and the dividend-signed remainder.
* **Go** - `go/divrem/`: struct `Divrem`; Go's `/` and `%` already truncate toward zero. `go.mod` declares module `example.com/divrem` (no dependencies).

Validation (`python -m tools.corpus_check corpus/divrem --lang python|go`: 0 differences; `verify --tiers 0,1,2 --mode full`), identical for both languages: T0 PASS, T1 PASS (229 cases, coverage 1.0/1.0), T2a PASS (exhaustive, 1,100 inputs): level 2.
