# ADR-0005: Evaluate against oracles, not LLM judges

## Context
The project is graded on whether the KB matches the code. An LLM judge would share the blind spots of an LLM extractor, and its verdicts are not reproducible.

## Options considered
1. LLM-as-judge on sampled facts.
2. Oracles independent of Phase 0's parser: GnuCOBOL at compile time (O1: `-ftsymbols` listing and a generated probe program), GnuCOBOL at run time (O2: `-ftraceall` traces), and human artifacts (O3: hand-written Java translations, manifests, gold annotations). The validated interpreter (O4) is used only as a secondary, model-based oracle.

## Decision
Option 2. O4 shares the front end with Phase 0, so its results (E5) are reported separately, labelled model-based, and never the only evidence for a claim.

## Evidence
- Independent oracles find real errors, but in both directions. In this project they found 4 harness bugs, a verifier bug and 3 Phase 0 improvements (`phase0/notes.md`). The listing's numeric-edited classification, unmodeled PERFORM returns and REDEFINES buffers were harness bugs; paragraph spans, READ write semantics and fall-through for all-branches-leave statements were real issues.
- Results (`phase0/eval/RESULTS.md`): E3 100% on all attributes; E4 0 violations in 18,511 transitions; E5 0 violations in 1,703 checks; E2 recall 100% against traces.
- Syzygy (Shetty et al., LLM4Code 2025) grounds translation in dynamic analysis; O2 does the same for the KB.

## Consequences
- The evaluation needs the toolchain image and takes about 80 s for D1-D3.
- Gold annotations (E6) are human work and arrive later. They are scored the same way once present, together with inter-annotator agreement.
