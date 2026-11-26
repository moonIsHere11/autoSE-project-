# ADR-0001: Reuse the verifier's COBOL front end as Phase 0's primary parser

## Context
Phase 0 must describe each program exactly as Phase 2's oracle sees it (task principle 2). If the KB and the checker disagree about a field's length or a paragraph's span, the agent's context contradicts the checker's feedback. The verifier (`verifier/cobol`) already has a `cobc -E` preprocessor with line mapping, a lexer, a parser, a data-layout module and a typed IR. Its layout is checked against GnuCOBOL, and its interpreter is checked by `tools/validate_interp.py`.

## Options considered
1. **Import `verifier.cobol` read-only** through the installed `cobol-verifier` package.
2. **ProLeap**, an ANTLR4 COBOL parser in Java. It adds a JVM dependency, gives a second COBOL semantics (its own PICTURE and layout rules) and does not model GnuCOBOL `-std=default`. A disagreement with the oracle would then be possible by construction.
3. **Extend Phase 1's regex analyser** (`phase1/phase1/cobol/analyzer.py`). It is tolerant but has no data layout (offsets and byte lengths), and its name resolution is by text.

## Decision
Option 1. Phase 0 imports `verifier.cobol` and `verifier.sandbox` as a library and never modifies `verifier/`. This deviates from agreement principle 1 ("no module imports another module's internals"); `phase0/TEAM_NOTES.md` item 1 asks Nandini and Mohit to approve it. If they object, the fallback is to depend on a pinned version of the `cobol-verifier` package, not to copy the code.

## Evidence
- E3 (`phase0/eval/RESULTS.md`): 5,559 attribute comparisons against oracles independent of the parser (the `cobc -ftsymbols` listing, a GnuCOBOL probe program and the corpus manifests). Every attribute matches 100%, with 0 KB-only and 0 listing-only items among 710 fields.
- E2: span starts equal the GnuCOBOL trace line in 18,511 of 18,511 paragraph entries.
- E7: Phase 1's analyser (option 3) states no offsets or byte lengths (0% on both rows) and has 133 write and 46 read soundness violations in E5. Phase 0 has 0 of each.
- Using the same front end exposed a real verifier bug (paragraph `end_line` before a SECTION header, TEAM_NOTES item 5). A second parser would have hidden it rather than fixed it.

## Consequences
- Phase 0 and Phase 2 share bugs in the front end. E3/E2/E4 use independent oracles (O1, O2, O3) so that shared bugs show up; E5 (interpreter) is labelled model-based for this reason (ADR-0005).
- Phase 0 needs the toolchain image for `cobc -E`. Builds are cached under `W/.phase0-cache`.
- Phase 0 works around verifier bugs inside `phase0/`, for example paragraph ends computed from tokens, and records them in TEAM_NOTES.
