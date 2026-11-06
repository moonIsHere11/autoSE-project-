# INVENTORY

## Python and Go translations

Hand-written, correct translations of INVENTORY (decimals are integers scaled by 10^scale or `Decimal`, never binary floating point), following the rules in `corpus/README.md`:

* **Python** - `python/inventory.py`: fixed-length SEQUENTIAL records decoded/encoded byte-exactly (COMP-3 with C/D/F sign nibbles, big-endian COMP, overpunched zoned, SIGN LEADING/TRAILING SEPARATE), including the F nibble a packed MOVE from the unsigned WS-COST leaves in WS-UNIT.
* **Go** - `go/inventory/`: the same codecs on `[]byte`, `encoding/binary` for COMP. `go.mod` declares module `example.com/inventory` (no dependencies).

Validation (`python -m tools.corpus_check corpus/inventory --lang python|go`: 0 differences; `verify --tiers 0,1,2 --mode full`), identical for both languages: T0 PASS, T1 PASS (489 cases, paragraph coverage 0.875, statement 0.92); T2a NOT_APPLICABLE (input file with an unbounded record count): level 1, accepted.
