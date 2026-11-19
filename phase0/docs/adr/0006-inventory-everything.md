# ADR-0006: Inventory everything and analyse deeply only what is in scope

## Context
The translation scope is batch programs with WORKING-STORAGE, ACCEPT/DISPLAY and sequential files. CardDemo also contains CICS, IMS, DB2, MQ, BMS maps, JCL, data files and documentation. Principle 3 forbids silent drops.

## Options considered
1. Analyse only in-scope programs and ignore the rest.
2. Inventory every file by content and analyse every program as deeply as the strict front end allows, marking out-of-scope constructs per unit (`unsupported`).

## Decision
Option 2. Stage A classifies every file by content (program, copybook data/procedure/sql, JCL job/proc, BMS, binary, other) and scans COPY/CALL/JCL references. Units list their out-of-scope constructs (EXEC CICS/SQL/DLI, SORT/MERGE, indexed/relative files, ALTER, IR-unsupported statements). Coverage lists every unattributed line with a reason.

## Evidence
- D1/D2: 3,256 lines, 0 unattributed. D3: 358 files inventoried, 44 programs analysed (18 strict, 26 tolerant), 510 unattributed lines of 39,670, every one with a reason; the most frequent unsupported constructs are CALL (16 programs) and indexed files (11).
- The JCL scan gives the batch-flow view and 3+ recovered "dataset handed between steps" decision records; ignoring JCL would lose them.

## Consequences
- Phase 1 can see why a unit is skipped (`unsupported`) instead of guessing; Phase 2 can skip the same units.
- The inventory's content rules are heuristics. The README/`.dcl` misclassification found on CardDemo was fixed, and other repositories may need more rules.
