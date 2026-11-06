# GRADES

## Python and Go translations

Hand-written, correct translations of GRADES (decimals are integers scaled by 10^scale or `Decimal`, never binary floating point), following the rules in `corpus/README.md`:

* **Python** - `python/grades.py`: a `@dataclass` whose fields are the record and WORKING-STORAGE items; OCCURS tables are `list[int]`; LINE SEQUENTIAL READ (padding, splitting of overlong lines) and WRITE (trailing spaces trimmed) reproduced byte for byte.
* **Go** - `go/grades/`: struct `Grades` with `[4]int64` / `[5]int64` tables; same file semantics. `go.mod` declares module `example.com/grades` (no dependencies).

Validation (`python -m tools.corpus_check corpus/grades --lang python|go`: 0 differences; `verify --tiers 0,1,2 --mode full`), identical for both languages: T0 PASS, T1 PASS (434 cases, paragraph coverage 1.0, statement 0.98); T2a NOT_APPLICABLE (input file with an unbounded record count): level 1, accepted.
