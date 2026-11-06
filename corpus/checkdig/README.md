# CHECKDIG

## Python and Go translations

Hand-written, correct translations of CHECKDIG (decimals are integers scaled by 10^scale or `Decimal`, never binary floating point), following the rules in `corpus/README.md`:

* **Python** - `python/checkdig.py`: class `Checkdig`, `int` fields, one method per paragraph; `PERFORM VARYING` as `while` loops.
* **Go** - `go/checkdig/` (`package main`, `main.go` + `helpers.go`): struct `Checkdig`, exported `int64`/`string` fields and methods. `go.mod` declares module `example.com/checkdig` (no dependencies).

Validation (`python -m tools.corpus_check corpus/checkdig --lang python|go`: 0 differences; `verify --tiers 0,1,2 --mode full`), identical for both languages: T0 PASS, T1 PASS (402 cases, 0 failed, paragraph coverage 1.0, statement 0.86); T2a NOT_APPLICABLE (ACCEPT inside a loop).
