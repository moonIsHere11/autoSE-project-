# COBOL Migration Harness: System Design & Integration Plan

Nov 6, 2026 · @Mohit

## 1. Purpose and design principles

The harness migrates COBOL programs to a target language (Java, Python or Go) and decides whether the result is correct using tests and formal verification. It is built as three modules that meet only through the contracts in this document, so each of us can implement our module any way we like and the pipeline still runs.

**Iteration 1 scope**

- **In:** a COBOL subset: numeric PIC fields, MOVE, ADD/SUBTRACT/MULTIPLY/COMPUTE (with ROUNDED and truncation), IF/EVALUATE, PERFORM, record structures, WORKING-STORAGE.
- **Out (future work):** file I/O, REDEFINES, GO TO/ALTER, CICS/DB2, EBCDIC.
- **Target:** one target language at a time, chosen per run in a config file.

**Design principles**

1. **Contracts, not code.** Modules exchange JSON files and directories with fixed schemas. No module imports another module's internals.
2. **Language-agnostic interface.** Every module exposes a command-line entry point and a file layout. Each of us can write ours in any language, and our agents can drive any of the three.
3. **Checkers decide truth.** Phase 1 never declares a unit correct. Only a Phase 2 verdict can.
4. **Everything is a versioned, immutable artifact.** Knowledge base, candidates and reports carry ids and versions, so any run can be replayed or resumed.
5. **Stub first.** Each module ships a stub of its contract on day one so the others are never blocked.

**Glossary**

| Term | Meaning |
| --- | --- |
| Phase 0 / KB | The knowledge module: facts about the COBOL source, the target language and the semantic gap between them |
| Phase 1 / Translator | The agent module: plans the migration and writes target code |
| Phase 2 / Checker | The verification module: compiles, tests, verifies and returns feedback |
| Unit | The smallest piece migrated and checked together (a paragraph or section of COBOL, mapped to a function or method) |
| Candidate | One proposed target-language implementation of one or more units |
| Workspace | The shared directory tree where all artifacts live (section 5) |
| Verdict | Phase 2's overall result for a candidate: `green`, `red` or `error` |

## 2. System overview

Phase 0 builds knowledge once; then Phase 1 and Phase 2 trade submissions and reports until each unit is green. The modules never call each other's internals, only read and write files in the shared workspace.

&#91;embedded content: architecture · 3 modules, 1 shared knowledge base\]

Phase 0 writes the knowledge base (highlighted) and nothing else. Phase 1 and Phase 2 only read it. The one direct hand-off between Phase 1 and Phase 2 is a submission going one way and a report coming back.

**End-to-end flow**

1. `phase0 build` reads `source/` and `config.yaml` and writes `kb/`.
2. Phase 1 queries the KB, plans the units, and writes target code into `staging/`.
3. Phase 1 calls `submit`, which snapshots `staging/` into `submissions/<sid>/`.
4. `phase2 check` builds and runs the snapshot against the COBOL oracle, then writes `reports/<sid>/report.json`.
5. A red report sends Phase 1 back to step 2 with concrete findings. A green report accepts the unit.
6. When every unit is accepted, the runner promotes the project to `accepted/` and writes the run summary.

## 3. Module responsibilities

Each module owns exactly one question: Phase 0 answers "what is true?", Phase 1 answers "what should the code be?", and Phase 2 answers "is it right?".

|  | Phase 0 · Knowledge | Phase 1 · Translator | Phase 2 · Checker |
| --- | --- | --- | --- |
| Question it answers | What is true about the COBOL, the target language, and the gap between them? | What should the target code look like, and how do we get there? | Is this code correct, and if not, why? |
| Consumes | COBOL source and copybooks; target language and version from `config.yaml` | The whole KB; Phase 2 reports | Submissions; the KB (data dictionary, unit spans, runtime library, toolchain) |
| Produces | The KB: source facts, mapping rules, semantic gaps, toolchain info, runtime library | Submissions: a code snapshot plus `submission.json` | Reports: verdict, per-unit tier, findings with counterexamples |
| Must not | Write target code for units or judge correctness | Declare its own code correct; edit the KB or reports | Edit candidate code or decide how to fix it (hints are allowed) |
| Entry points | `phase0 build`, `phase0 query` | `phase1 run` | `phase2 check` |

**Freedom inside each module**

- **Phase 0:** parser choice, how facts are extracted (AST tooling, LLM summaries, docs retrieval), and whether the KB also has an index or vector store. Only the contract files and query commands are fixed.
- **Phase 1:** one agent or several, planning strategy, prompts, context assembly, unit batching, and the editing tools the agent gets.
- **Phase 2:** which verifier (Dafny, CBMC/Kani, Z3), how test inputs are generated, how the COBOL oracle is built (GnuCOBOL wrappers), and how feedback is phrased.

One rule applies everywhere: a module may add extra files under its own directories, but it may not change a contract schema without a version bump (section 10).

## 4. Shared contracts

Six contracts define every hand-off between modules. Each is a JSON file (or one JSON object per line) with a `schema_version`. The Python types below are the reference shape; any language can implement them from the JSON. Imports are omitted for brevity.

| # | Contract | From → to | Where it lives |
| --- | --- | --- | --- |
| 1 | Knowledge base files | Phase 0 → 1, 2 | `kb/manifest.json`, `kb/source/*.json`, `kb/target/*` |
| 2 | KB query commands | Phase 0 → 1, 2 | `phase0 query ...` (returns the same JSON as the files) |
| 3 | Execution interface | Phase 1 → 2 | the `driver_cmd` of a submission |
| 4 | Submission | Phase 1 → 2 | `submissions/<sid>/submission.json` |
| 5 | Report | Phase 2 → 1 | `reports/<sid>/report.json` |
| 6 | Events | all → run record | `runs/<run_id>/events.jsonl` |

### 4.1 Knowledge base files and queries (contracts 1 and 2)

The KB has a source side (facts about the COBOL) and a target side (the target language, the semantic gaps, and a runtime library).

```python
@dataclass
class Toolchain:                  # kb/target/toolchain.json
    language: str                 # 'java'
    version: str                  # '21'
    file_ext: str                 # '.java'
    build_cmd: list[str]          # run from the project root
    test_cmd: list[str]
    lint_cmd: list[str] | None
    runtime_dir: str              # where kb/target/runtime/ is copied inside the project

@dataclass
class KbManifest:                 # kb/manifest.json
    schema_version: str           # '1.0'
    kb_version: str               # content hash of everything under kb/
    source_hash: str              # hash of source/ at build time
    target: Toolchain

@dataclass
class SourceSpan:
    file: str
    start_line: int
    end_line: int

@dataclass
class Unit:                       # kb/source/units.json (a list of these)
    unit_id: str                  # stable, e.g. 'CALC-FEE'; 'PROGRAM' = the whole program
    kind: Literal['program', 'section', 'paragraph']
    span: SourceSpan
    reads: list[str]              # field_ids
    writes: list[str]             # field_ids
    performs: list[str]           # unit_ids reached by PERFORM
    calls: list[str]              # external programs reached by CALL
    falls_through_to: str | None  # next paragraph if control falls through
    summary: str | None           # optional LLM summary, grounded in the facts above

@dataclass
class SemanticType:
    kind: Literal['decimal', 'alphanumeric', 'group']
    digits: int | None
    scale: int | None
    signed: bool | None
    length: int | None

@dataclass
class Field:                      # kb/source/data_dictionary.json (a list of these)
    field_id: str                 # fully qualified, e.g. 'WS-ORDER.WS-TOTAL'
    level: int
    parent: str | None
    pic: str | None               # 'S9(5)V99'
    usage: str                    # 'DISPLAY', 'COMP-3', ...
    semantic_type: SemanticType
    occurs: int | None
    initial_value: str | None

@dataclass
class Rule:                       # kb/target/mapping_rules.json (a list of these)
    rule_id: str                  # 'R-EVALUATE'
    cobol_construct: str          # 'EVALUATE'
    required_pattern: str         # what the target code must do
    example_cobol: str
    example_target: str

@dataclass
class Gap:                        # kb/target/semantic_gaps.json (a list of these)
    gap_id: str                   # 'G-TRUNCATE'
    topic: str                    # 'decimal overflow'
    cobol_behavior: str
    target_default: str           # what the target language does if you do nothing
    required_handling: str
    rule_ids: list[str]
```

`kb_version` changes whenever any KB file changes, so every downstream artifact can state which knowledge it was built on. The query interface returns exactly the types above:

```python
class KnowledgeBase(Protocol):    # CLI: phase0 query <method-name> [args] --workspace W  (JSON on stdout)
    def list_units(self) -> list[Unit]: ...
    def get_unit(self, unit_id: str) -> Unit: ...
    def source_text(self, unit_id: str) -> str: ...
    def get_field(self, field_id: str) -> Field: ...
    def callers(self, unit_id: str) -> list[str]: ...
    def callees(self, unit_id: str) -> list[str]: ...
    def rules_for(self, constructs: list[str]) -> list[Rule]: ...
    def gaps_for(self, topics: list[str]) -> list[Gap]: ...
    def toolchain(self) -> Toolchain: ...
```

### 4.2 Execution interface (contract 3)

This is what lets Phase 2 compare COBOL and the translation without knowing how the translation is written. Every unit is treated as a function from field values to field values.

- Values are canonical strings. Decimals are plain decimal strings with the exact scale (`"-123.40"`). Alphanumerics keep their exact length, padding included.
- Keys are `field_id`s from the data dictionary. A unit's state holds every field in its `reads` and `writes`.
- Phase 0 ships a `driver_template/` in the target language (JSON parsing, canonical encoding, a dispatch table). Phase 1 fills in the table mapping each `unit_id` to its translated function.
- Phase 2 builds the COBOL side of the same interface itself (for example a GnuCOBOL wrapper that loads the state, performs the paragraph, and dumps the fields).

```json
// driver stdin
{"unit_id": "CALC-FEE", "state": {"WS-AMOUNT": "123.45", "WS-FEE": "0.00"}}
// driver stdout
{"unit_id": "CALC-FEE", "status": "ok", "message": null,
 "state": {"WS-AMOUNT": "123.45", "WS-FEE": "6.17"}}
```

`status` is `ok` or `error`. An `error` is a runtime failure inside the unit, for example a size error the COBOL would also raise.

### 4.3 Submission (contract 4)

A submission is an immutable snapshot of the agent's project plus a description of what it claims.

```python
@dataclass
class Scope:
    unit_ids: list[str]              # units claimed as implemented in this submission
    regression_unit_ids: list[str]   # earlier-accepted units to re-check
    required_tier: Literal['tested', 'bounded', 'proven']   # copied from the run's gate

@dataclass
class Submission:                    # submissions/<sid>/submission.json
    schema_version: str
    submission_id: str               # 'S-0007'
    run_id: str
    kb_version: str                  # Phase 2 refuses a mismatch with the current KB
    attempt: int                     # 1-based, per scope
    scope: Scope
    project_root: str                # code location inside the snapshot, e.g. 'project/'
    driver_cmd: list[str]            # run from project_root; speaks the execution interface
    notes: str | None                # free text from the agent, for humans
```

### 4.4 Report (contract 5)

The report is what Phase 1 learns from. Counterexamples must always be concrete: field values the agent can replay.

```python
Tier = Literal['unchecked', 'tested', 'bounded', 'proven']   # ordered, weakest first

@dataclass
class StageResult:
    name: Literal['build', 'lint', 'differential', 'verification']
    status: Literal['pass', 'fail', 'skipped', 'error']
    duration_s: float

@dataclass
class UnitResult:
    unit_id: str
    tier: Tier                       # strongest evidence reached for this unit
    status: Literal['pass', 'fail', 'unchecked']

@dataclass
class Counterexample:
    inputs: dict[str, str]           # field_id -> canonical value
    expected: dict[str, str]         # COBOL result
    actual: dict[str, str]           # target result

@dataclass
class CodeLocation:
    file: str
    line: int

@dataclass
class Finding:
    finding_id: str                  # 'F-001'
    stage: str
    unit_id: str | None
    severity: Literal['blocker', 'warning', 'info']
    category: Literal['build_error', 'lint', 'behavior_mismatch', 'verification_failed',
                      'verification_unknown', 'timeout', 'infra_error']
    message: str                     # plain words, readable by an agent
    location: CodeLocation | None    # in the target code
    cobol_ref: SourceSpan | None     # the COBOL the finding is about
    counterexample: Counterexample | None
    kb_refs: list[str]               # rule_ids / gap_ids that explain the failure
    reproduce: str | None            # command that re-runs just this check

@dataclass
class Report:                        # reports/<sid>/report.json
    schema_version: str
    submission_id: str
    kb_version: str
    verdict: Literal['green', 'red', 'error']
    stages: list[StageResult]
    units: list[UnitResult]
    findings: list[Finding]
    summary: str                     # 2 to 5 lines the agent reads first
```

**Verdict rules**

- **green:** every unit in `unit_ids` and `regression_unit_ids` reached at least `required_tier`, and there are no blocker findings.
- **red:** at least one blocker finding caused by the submitted code.
- **error:** Phase 2 itself failed (infrastructure, tool crash, KB version mismatch). The same submission is checked again and the attempt is not counted against Phase 1's budget.

**Tiers**

| Tier | Meaning |
| --- | --- |
| `proven` | Formally shown equivalent to the COBOL (or to its spec) for all inputs |
| `bounded` | Formally shown equivalent within stated bounds, such as PIC ranges and loop limits |
| `tested` | Passed differential tests against the COBOL oracle; no proof |
| `unchecked` | Nothing ran for this unit |

A `verification_unknown` finding (solver timeout, unsupported construct) is a warning unless the run's required tier needs that proof.

### 4.5 Events (contract 6)

Every module appends to one log per run. Nobody edits or deletes lines. This is the trace for debugging and the data for evaluation.

```python
@dataclass
class Event:                         # runs/<run_id>/events.jsonl, one JSON object per line
    ts: str                          # ISO 8601, UTC
    run_id: str
    module: Literal['phase0', 'phase1', 'phase2', 'runner']
    kind: str                        # 'kb_built', 'submission_created', 'check_finished', ...
    unit_id: str | None
    submission_id: str | None
    data: dict                       # kind-specific; include token and time costs where known
```

### 4.6 Command-line surface

| Command | What it does | Writes |
| --- | --- | --- |
| `phase0 build --workspace W` | Builds the KB from `source/` and `config.yaml` | `kb/` |
| `phase0 query <method> [args] --workspace W` | Answers one KB query as JSON on stdout | nothing |
| `phase1 run --workspace W [--units U1,U2]` | Translates the units, looping with Phase 2 until green or out of budget | `staging/`, `submissions/`, events |
| `phase2 check --workspace W --submission S-0007 [--until STAGE]` | Checks one snapshot; stages run in order and stop at the first failure unless `--until` names a later stage | `reports/S-0007/` |

Exit codes are the same for every command: `0` means the command ran (a red verdict is not a failed command; read the report), `2` means bad input or a contract violation, `3` means an internal error.

## 5. Workspace and staging area

Everything the modules exchange is a file under one `workspace/` directory, and every directory has exactly one writer. The agent's working copy (`staging/`) is mutable, but Phase 2 only ever checks an immutable snapshot of it (`submissions/`). That way the agent can keep editing while a check runs, and every report refers to exact code.

```text
workspace/
├── config.yaml                 # run settings: target language, gate, budgets
├── source/                     # COBOL input and copybooks, read-only
├── kb/                         # Phase 0 output
│   ├── manifest.json
│   ├── source/                 # units.json, data_dictionary.json, call_graph.json
│   └── target/                 # toolchain.json, mapping_rules.json, semantic_gaps.json,
│                               # runtime/ (CobolDecimal etc.), driver_template/
├── staging/                    # Phase 1's mutable working project
├── submissions/
│   └── S-0007/                 # immutable snapshot
│       ├── submission.json
│       └── project/            # copy of staging/ taken at submit time
├── reports/
│   └── S-0007/                 # Phase 2 output for that snapshot
│       ├── report.json
│       └── artifacts/          # logs, solver output, generated tests
├── accepted/                   # latest green project, written by the runner
└── runs/
    └── R-001/
        ├── events.jsonl        # append-only
        └── state.json          # per-unit status, maintained by the runner
```

**Who writes what**

| Path | Written by | Read by | Mutability |
| --- | --- | --- | --- |
| `config.yaml` | Humans | All | Edited between runs only |
| `source/` | Humans | Phase 0, Phase 2 | Read-only |
| `kb/` | Phase 0 | Phase 1, Phase 2 | Rebuilt as a whole; every rebuild gets a new `kb_version` |
| `staging/` | Phase 1 | Phase 1 | Mutable |
| `submissions/<sid>/` | Phase 1, through `submit` | Phase 2, runner | Written once, never changed |
| `reports/<sid>/` | Phase 2 | Phase 1, runner | Written once |
| `accepted/` | Runner | Humans, evaluation | Replaced on each promotion |
| `runs/<run_id>/events.jsonl` | All modules | All | Append-only |
| `runs/<run_id>/state.json` | Runner | All | Runner only |

**Submit semantics.** Phase 1 implements `submit`, but every implementation must behave the same way:

1. Allocate the next id by creating `submissions/S-NNNN/` with `mkdir`; if the directory already exists, take the next number.
2. Copy `staging/` to `submissions/S-NNNN/project/`.
3. Write `submission.json` last. A submission without it is incomplete and Phase 2 ignores it.
4. Append a `submission_created` event.

Phase 2 follows the same pattern for reports: write to a temporary name, then rename to `report.json`, so a reader never sees a half-written report.

**Rules for the project in staging**

- It must build with `Toolchain.build_cmd` from `project_root`, and it must contain the KB's runtime library unchanged at `runtime_dir`. Phase 2 compares it byte for byte with `kb/target/runtime/` and reports any difference as a blocker finding (`build_error`).
- Tests the agent writes may live in the project, but Phase 2 does not trust them. Its verdict comes from its own oracle runs.
- Paths inside any JSON are relative to the snapshot or workspace root, never absolute, so a workspace can be moved or zipped.
- Phase 2 reads snapshots only. It never reads `staging/`.

**Promotion.** Each submission snapshots the whole project, so the latest green snapshot contains every unit accepted before it. When a report is green, the runner records `accepted_units[unit_id] = submission_id` in `state.json` and copies that snapshot's project to `accepted/`.

## 7. Phase 0 links: how the KB reaches Phase 1 and Phase 2

Phase 1 and Phase 2 use the knowledge base only through the files and queries in section 4.1, and Phase 0 never talks to either of them while a run is in progress. `phase0 build` runs before the run starts; after that the KB is read-only.

| Information | Phase 1 uses it to | Phase 2 uses it to | Where it lives |
| --- | --- | --- | --- |
| Units, spans, reads and writes | Order and scope the work (leaves first) | Decide which state to feed and compare | `list_units`, `get_unit` |
| Field definitions | Choose correct target types | Generate inputs inside PIC ranges; canonicalise values | `get_field` |
| COBOL text | Read what must be translated | Build the oracle from the original `source/` | `source_text` |
| Mapping rules and semantic gaps | Follow the required patterns | Explain failures through `kb_refs` | `rules_for`, `gaps_for` |
| Toolchain | Build, test and lint locally | Run build and lint | `toolchain` |
| Runtime library | Use it unchanged for all COBOL numerics | Check it is unchanged; verify it once per `kb_version` | `kb/target/runtime/` |
| Driver template | Fill in the dispatch table | Run the driver | `kb/target/driver_template/` |

**Rules for the link**

- **Pinned version.** Phase 1 writes the current `kb_version` into every submission. Phase 2 compares it with `kb/manifest.json` and returns a verdict of `error` (category `infra_error`, message naming both versions) on a mismatch. Rebuilding the KB during a run is not allowed in iteration 1.
- **Facts versus summaries.** Phase 2 may use only extracted facts (spans, reads, writes, field types). LLM-written fields such as `summary` are hints for Phase 1 and must never be the only source of something Phase 2 depends on.
- **Runtime library trust.** Phase 2 verifies the runtime library once per `kb_version` with its own tooling (property tests against GnuCOBOL first, proofs later) and records a `runtime_verified` event. Until that event exists, reports state that the library is trusted but unverified.
- **COBOL dialect and compile flags** live in `config.yaml` (section 8), where Phase 0 and Phase 2 both read them.

**Closing the loop.** Failures should improve the KB over time without any module editing another's files:

1. Phase 2 findings carry `kb_refs`. A mismatch caused by decimal truncation points to the `G-TRUNCATE` gap, and Phase 1 reads that gap's `required_handling` on its next attempt.
2. When knowledge is missing, Phase 1 or Phase 2 appends a `kb_gap_reported` event with the topic, the evidence (`submission_id` and `finding_id`), and a suggested rule if there is one.
3. Phase 0's owner reads those events between runs, adds or fixes rules, and rebuilds. The new `kb_version` applies from the next run.

## 8. Pipeline runner, run record and metrics

A thin shared runner sequences the phases and keeps run state. It contains no migration logic, and because it works from the event log alone it does not care how any module is implemented.

**What the runner does**

1. Reads `config.yaml` and creates `runs/<run_id>/`.
2. Calls `phase0 build` and stops if it fails.
3. Calls `phase1 run`. Phase 1 owns the inner translate-and-check loop (section 6) and calls `phase2 check` itself whenever it wants feedback.
4. Watches `events.jsonl`. On each `check_finished` event it updates `state.json` and promotes green snapshots (section 5).
5. When Phase 1 finishes, creates a final submission from `accepted/` covering every accepted unit and requests all stages. This catches bugs that only appear when units are combined.
6. Writes `runs/<run_id>/summary.json` with the metrics below.

**`state.json` is derived, not authoritative.** The event log is the truth. `state.json` can always be rebuilt by replaying the log. Phase 1 reads it before each submit and must not submit a unit whose status is `accepted` or `failed`.

```json
{
  "run_id": "R-001",
  "kb_version": "9f3a1c...",
  "units": {
    "CALC-FEE":   {"status": "accepted", "attempts": 3, "tier": "bounded", "accepted_by": "S-0007"},
    "READ-INPUT": {"status": "failed",   "attempts": 5, "tier": "unchecked", "last_submission": "S-0011"}
  }
}
```

**Run configuration**

```yaml
run:
  id: R-001
source:
  entry: source/PAYROLL.cbl
  dialect: ibm              # passed to the GnuCOBOL compile
  compile_flags: []
target:
  language: java
  version: "21"
gate:
  required_tier: tested     # tested | bounded | proven
budgets:
  attempts_per_unit: 5
  check_retries_on_error: 2 # free retries when Phase 2 itself fails
```

**Events the runner relies on.** Modules may emit more kinds, but these are required:

| Kind | Emitted by | Data |
| --- | --- | --- |
| `kb_built` | Phase 0 | `kb_version` |
| `unit_started` | Phase 1 | `unit_id`, first time the agent works on it |
| `submission_created` | Phase 1 | `submission_id`, scope |
| `unit_abandoned` | Phase 1 | `unit_id`, reason |
| `check_started` | Phase 2 | `submission_id` |
| `check_finished` | Phase 2 | `submission_id`, verdict, per-unit tiers |
| `runtime_verified` | Phase 2 | `kb_version`, tier reached |
| `kb_gap_reported` | Any | topic, evidence, suggested rule |
| `llm_usage` | Any | model, tokens in and out, cost if known |

Each module may also write freely to its own `runs/<run_id>/<module>/` directory for private traces such as prompts and tool calls.

**Metrics** are computed from events and reports only, so no module needs extra instrumentation:

- Build rate: share of first submissions that compile.
- Attempts to green per unit, and units ending in each tier (`proven`, `bounded`, `tested`) or `failed`.
- Failure categories from reports, which show where the agent struggles (for example decimal truncation).
- Tokens, cost and wall time per unit, per stage, and per program.

**Replay.** Phase 2 derives its test inputs from a seed stored in `reports/<sid>/artifacts/`, so re-running `phase2 check` on any old snapshot reproduces its verdict.

## 9. Independent development and integration testing

Each of us can build against the other two modules from day one, because every module ships a stub that satisfies its contracts. Integration is then a matter of swapping stubs for real modules one at a time.

**Repository layout**

```text
repo/
├── integration/
│   ├── contracts/     # JSON Schemas, valid and invalid examples, `contracts validate`
│   ├── fixtures/      # sample COBOL program, sample KB, hand translations, seeded-bug translations
│   └── runner/        # the pipeline runner (section 8)
├── phase0/            # Knowledge module, free internal layout
├── phase1/            # Translator module, free internal layout
└── phase2/            # Checker module, free internal layout
```

**Stubs, shipped on day one**

| Module | Stub | What it unblocks |
| --- | --- | --- |
| Phase 0 | A hand-written KB for one tiny COBOL program (three units, a handful of fields, two rules, one gap, a toolchain, a small runtime library and driver template), served by a `phase0 query` that reads it | Phase 1 and Phase 2 can start without a parser |
| Phase 1 | `phase1 run --stub`: submits a pre-written translation of the sample program, with no LLM | Phase 2 receives real submissions; the runtime library gets exercised |
| Phase 2 | `phase2 check --stub`: returns canned reports (one green, one red with a counterexample, one error) chosen by the submission's `notes` | Phase 1 can build and test its feedback handling |

**Contract tests.** The three dataclass families in section 4 are exported as JSON Schemas into `integration/contracts/`, with one valid and one invalid example per schema. `contracts validate <path>` checks any file. Each module runs it on everything it writes; a failure is a contract violation (exit code 2).

**Milestones.** Each milestone swaps one more stub for the real module. The order is chosen so that nobody waits on a module that is not built yet.

| Milestone | Real modules | What runs | Done when |
| --- | --- | --- | --- |
| M0 · Contracts frozen | None (all stubs) | Sample program through the runner with all three stubs | Schemas validate; the runner produces `summary.json` |
| M1 · Real KB | Phase 0 | Phase 0 builds the KB for the sample program; stubs read it | `phase0 build` output validates; every `phase0 query` method answers |
| M2 · Real checker | Phase 2 (+ Phase 0) | Phase 1 stub submits hand translations, correct and seeded-bug versions | Green on the correct one; red with a useful counterexample on each seeded bug (decimal truncation, rounding, sign handling) |
| M3 · Real translator, one unit | All three | The agent translates one paragraph and loops with real feedback until green | One unit reaches `accepted` |
| M4 · Whole sample program | All three | Multi-unit program, final combined check | `accepted/` exists and `summary.json` has metrics |

**Definition of done for iteration 1**

- One runner command takes the sample COBOL program to `accepted/` and `summary.json` with no manual step.
- Phase 2 catches every seeded bug and reports it with a counterexample the agent can replay.
- A red verdict visibly changes Phase 1's next submission, so feedback reaches the agent.
- Swapping any one module for its stub still runs the pipeline end to end, which shows the coupling is only through contracts.

**Working agreements**

- Contract changes go through a pull request that all three of us approve (section 10).
- Every module's README starts with a "How to call me" block: the commands from section 4.6 and one command that works on the sample workspace. Our coding agents use that block, plus this document, as the specification when they integrate each other's work.
- Dataset building is a separate task. For integration, one small sample program with a few paragraphs is enough.

## 10. Contract changes, risks and open questions

Contracts will change as we learn, so the change process matters as much as the first version. The rule of thumb: anything additive is cheap, anything else needs all three of us.

**Changing a contract**

1. Propose it as a pull request to `integration/contracts/`: the schema change, a valid and an invalid example, and the matching edit to this document.
2. All three of us approve. Adding an optional field is a minor version bump (1.0 to 1.1). Removing, renaming or repurposing a field is a major bump.
3. Consumers ignore fields they do not know, so additive changes never break anyone. Producers never remove or repurpose a field within a major version.
4. Stubs and fixtures are updated in the same pull request, so the stubs always match the current contracts.

**Risks**

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| Fall-through and PERFORM THRU make some paragraphs impossible to treat as clean functions | The state-in, state-out interface would describe the wrong thing | The KB marks `falls_through_to`. Phase 1 may claim a wider scope (a section or `PROGRAM`) and Phase 2 checks at the scope claimed |
| The oracle is GnuCOBOL, not the original mainframe compiler | "Correct" means "matches GnuCOBOL" | The dialect is set in `config.yaml`, and every report names the oracle it used |
| Canonical value encoding is read differently by two modules | Silent false mismatches or false passes | The encoding rules live in Phase 0's driver template, with encoding fixtures in the contract tests |
| Solver timeouts and unsupported constructs | Proofs are not always reachable | Tiers (`bounded`, `tested`) and `verification_unknown` warnings are part of the report contract |
| The agent hard-codes outputs to pass visible tests | A false green | Phase 2 shows only failing counterexamples, keeps a seeded hidden input set, and ignores the agent's own tests (section 5) |
| A bug in the runtime library poisons every translation | All units share it | Phase 2 verifies it once per `kb_version` and emits `runtime_verified` |

**Open questions**

| Question | Proposed default | Owner |
| --- | --- | --- |
| How are encoding edge cases (signed zero, group items, OCCURS arrays, COMP-3) written as canonical strings? | Decide on the sample program first, then extend; record each case as a fixture | Phase 0, reviewed by Phase 2 |
| How are unsupported constructs flagged? | Add `unsupported: list[str]` to `Unit` (a minor version bump, 1.1) so Phase 1 and Phase 2 can skip them | Phase 0 |
| How are file inputs and outputs represented once they are in scope? | Out of scope for iteration 1; extend the execution interface with named files later | All |
| How is a second target language added? | One `kb/target/<language>/` directory per language, chosen in `config.yaml`; no contract change | Phase 0 |
| How many counterexamples go into one finding? | At most 3 per finding, smallest first, so feedback stays short | Phase 2 |
