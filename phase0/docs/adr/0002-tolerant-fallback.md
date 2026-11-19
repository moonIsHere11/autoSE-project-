# ADR-0002: Fall back to Phase 1's tolerant analyser for files the strict front end rejects

## Context
The strict front end rejects a file when `cobc -E` fails (missing IBM-supplied copybooks such as DFHAID, DFHBMSCA or CMQ*) or when the parser throws. Principle 3 forbids dropping such files: every line must be accounted for, and out-of-scope programs must still be inventoried.

## Options considered
1. Mark rejected programs `failed` and record nothing about them.
2. Write stub copybooks for the IBM ones. This invents data layouts we cannot verify.
3. Run Phase 1's regex analyser on the rejected file and tag every fact it produces.

## Decision
Option 3. Facts from the fallback carry `provenance.extractor = "tolerant"` and confidence 0.6. Field types still come from `verifier.cobol.datadiv.parse_pic` (the same PICTURE semantics), but there are no layout facts. Coverage counts these facts separately (`facts_by_extractor`, parse status `tolerant`). Only the known failure modes of the regex analyser are caught; anything else propagates.

## Evidence
- CardDemo (D3): 44 programs, 18 strict and 26 tolerant, 0 failed. Every tolerant program is a CICS/IMS/MQ/DB2 program whose rejection names the missing IBM copybook or SQL syntax (`coverage.json` `rejected_files`).
- Before the structural attribution for tolerant files, D3 had 5,621 unattributed lines; afterwards 510 of 39,670, all with a reason (`phase0/notes.md`, "CardDemo fixes").

## Consequences
- Phase 1 and Phase 2 can tell strict facts from tolerant ones and trust them accordingly. Phase 2 does not verify these programs anyway: they are out of scope for translation.
- Tolerant facts have Phase 1's known blind spots (E7: group INITIALIZE, VARYING control items, REDEFINES), so they must not feed Phase 2.
