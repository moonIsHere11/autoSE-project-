# planner: Phase 2, migration planning

Part 1 is architecture planning: from the KB to a reviewed, evidence-backed module plan for the target language.
(Part 2, the migration order, will live in `planner/ordering/` and consume this plan.)

## How to call me
```
bin/planner architecture --workspace W                 # KB from W/kb/ (phase0 build), agent review on
bin/planner architecture --workspace W --no-agent      # deterministic draft only, no LLM
bin/planner architecture --workspace W --fixture F     # KB from a FixtureKb JSON (tests, hand-made estates)
                         [--target java|python|go]     # default: config.yaml target.language, else java
python3 -m unittest discover -s tests/planner -t .     # tests (no LLM, no Docker; needs networkx, numpy, scipy)
```
Writes `W/plan/architecture.json` (schema 1.0, `planner/architecture/plan.py`) and `W/plan/architecture.md` (the
document a human reviews). Prints `{"plan", "modules", "open_questions", "edits"}`. Exit codes: 0 ok, 2 bad input
(missing KB, invalid config, unknown target), 3 internal error.

## How it works
1. **KB** (`kb.py`, `kb_phase0.py`): programs, copybooks, data-store uses and JCL job steps; see
   `docs/phase2/KB_CONTRACT.md`. The planner reads facts only from the KB. Its only source access is a regex
   search, bounded line reads, and a comment-line scan.
2. **Draft** (`architecture/graph.py`, `features.py`, `cluster.py`, `roles.py`, `draft.py`), deterministic:
   - **Graph:** weighted program graph from CALLs, shared copybooks, data written by one program and read by
     another, data both read, and the same JCL job. Items are scaled by IDF, so things everyone uses add nothing.
   - **Similarity:** a "does similar work" edge from identifier and comment vocabulary plus the I/O signature.
   - **Clusters:** Louvain clustering (fixed seed). Utilities are pulled out first; isolated programs get their
     own module. Then a size band applies: groups over 25 are split, groups under 3 merged.
   - **Roles:** shared vs local types, shared code, data-store owners and repository interfaces, the jobs layer.
   - **Confidence:** the share of a program's links inside its module. Links to utilities don't count.
3. **Review** (`architecture/review.py`, `tools.py`, `edits.py`):
   - **Who runs:** a planner `Agent` (harness template) runs one pass per module holding programs below the
     confidence threshold or with tolerant KB facts, then one global pass.
   - **Tools:** KB tools first, code search second, and `explore_program`, a read-only sub-agent.
   - **Edits:** the plan changes only through edit tools that need a reason and evidence refs (`program:ID`,
     `copybook:NAME`, `store:ID`, `job:ID`, `src:PATH:LINE`) that exist. Each edit is checked against the plan
     invariants and recorded in `edits`.
   - **Failures:** if the LLM fails or a pass runs out of budget, the draft and the edits made so far still go
     out, with a `review_incomplete` question.

## Config (`config.yaml`, all optional)
```yaml
target:  {language: java}
harness: {llm: {adapter: harness.llm.groq:GroqLLM, model: openai/gpt-oss-20b}}   # used only with the agent
planner:
  architecture:
    weights: {call: 3.0, copybook: 2.0, write_read: 2.0, co_read: 1.0, same_job: 0.5, similar: 1.0}
    similarity_threshold: 0.35
    util_min_communities: 3        # a program called from >= 3 draft groups is a utility
    util_min_fan_in: 5             # ... or called by >= 5 programs and writes no data
    band_min: 3
    band_max: 25                   # module size band
    confidence_threshold: 0.6      # below this, the program goes to the agent and to open questions
    low_kb_confidence: 0.8         # KB facts below this confidence (tolerant parse) are flagged
    seed: 7
    root_package: app
    review: {pass_steps: 25, explorer_calls: 5, explorer_steps: 15, max_tokens: null,   # max_tokens: per pass
             total_tokens: 500000}     # whole review; when spent, remaining passes are skipped and flagged
```

## Open question kinds
`uncertain_program` (low share of links inside its module), `low_kb_confidence` (tolerant KB facts), `isolated`
(no links except to utilities), `undersized_module` / `oversized_module` (outside the size band and could not be
merged/split), `shared_write` (a store written by several modules), `missing_kb_fact`, `review_incomplete`
(a review pass that failed, ran out of budget, or whose result could not be applied).

## Scale
Draft time on synthetic estates: about 3.5 s for 1,000 programs and 11 s for 2,000 (similarity uses sparse
matrices; the size-band merge reads only the small groups' edges). `tests/planner/test_scale.py` guards this.

## Known limitations
- **Estate tested on:** only the 13-program fixture and the review probe. On a real estate, plan quality depends
  on the KB facts listed in `docs/phase2/KB_CONTRACT.md` (DB tables, IKJEFT01 binding, strict facts for SQL/CICS
  programs).
- **Probe KB:** the probe run used a KB built by Phase 0 before the `phase1/` deletion. On this branch,
  `phase0 build` crashes on programs that need its tolerant fallback (it imports the removed `phase1/`).
- **LLM:** the agent review has only run against scripted LLMs. A real-LLM run needs a model with reliable tool
  calling and enough quota.
- **Human review:** the review flow (accept, or replace with an uploaded architecture) is not built. An uploaded
  plan must validate with `planner.architecture.validate.validate_plan`.
