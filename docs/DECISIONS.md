# Decisions log

One entry per decision: context, decision, alternatives. Newest last.

### D1 — Spec inputs that are missing
*Context:* the spec refers to `docs/proposal.pdf` and `docs/verification_notes.md`. Only the proposal
existed (as `Project Proposal - Verified Migration Harness-1.pdf` at the repo root); the notes file
does not exist, and the `<MIDEVAL_DATE>`/`<YOUR_NAME>` placeholders were unfilled.
*Decision:* copied the proposal to `docs/proposal.pdf` (original left in place); proceeded from the
spec alone (the spec wins over the notes anyway); owner name taken from the repo's git identity
("Nandini"); mid-eval date left as TBD in PLAN.md.
*Alternatives:* block and ask — rejected (spec says work autonomously).

### D2 — Where things run
*Context:* the machine is Windows 11. Windows has no Docker CLI, no GnuCOBOL, only a Java 8 JRE.
WSL2 Ubuntu 24.04 has Docker 29 (user in `docker` group), JDK 21, Python 3.12, make; `sudo` needs a
password, so nothing can be apt-installed on the host.
*Decision:* the orchestrator runs in WSL (Python 3.12 venv in `~/.venvs/cobol-verifier`, outside
`/mnt/d` for speed); **every** tool (GnuCOBOL, JDK 17, JBMC, OpenJML, Go, CrossHair) lives in one
pinned Docker image, which is also the sandbox. Git is driven from WSL (`core.filemode=false`).
*Alternatives:* run the verifier itself inside the container with the Docker socket mounted —
rejected (nested sandboxing is fragile and gives the untrusted code's container a path to the
daemon); install tools on the host — impossible without sudo, and unpinned.

### D3 — Pinned versions
*Context:* spec asks for pinned versions; downloads must be reproducible.
*Decision:* base `ubuntu:24.04@sha256:fe8156…`; GnuCOBOL 3.2 (GNU tarball, sha256-checked, built
`--without-db --without-xml2 --without-json` since indexed files/XML/JSON are out of scope);
CBMC/JBMC 6.8.0 (official Ubuntu 24.04 .deb, which ships `jbmc`, `core-models.jar`,
`cprover-api.jar`); OpenJML 21.0.28 (bundles its own JDK 21, checks Java 17 sources); Go 1.22.12;
JDK 17 from Ubuntu; Python 3.12 (Ubuntu 24.04's; spec says 3.11+); crosshair-tool 0.0.111,
icontract 2.7.3, tree-sitter 0.26.0 with java 0.23.5 / python 0.25.0 / go 0.25.0 grammars.
*Alternatives:* CBMC 6.11 (newest) — chose 6.8.0, a year old and widely used; Python 3.11 via
deadsnakes — unnecessary, 3.12 satisfies "3.11+".

### D4 — Unit granularity
*Context:* the report example uses paragraph ids (`LOANCALC::CALC-INTEREST`) but T1 is program-level.
*Decision:* a unit is a paragraph. Program-level tiers (T0a, T1, T2a) are computed once per program
and copied into each unit with `scope.level = "program"`; T1u/T2b/T3 are per paragraph. Statements
before the first paragraph form the unit `PROGRAM::(MAIN)`.
*Alternatives:* program-only units (loses the per-function story of the proposal); mixing program
and paragraph units in one histogram (confusing).

### D5 — Tiers that were not selected
*Context:* the six statuses don't include "not run"; `fast` mode doesn't run T3.
*Decision:* unselected tiers are `SKIPPED` with reason "not selected"; acceptance only considers
selected tiers and the report lists `tiers_considered`. A `fast`-mode acceptance therefore never
claims T3.
*Alternatives:* `NOT_APPLICABLE` — rejected, it would claim the tier cannot apply.

### D6 — T2/T3 ERROR and TIMEOUT block acceptance
*Context:* the spec's acceptance allows "PASS or a reasoned NOT_APPLICABLE" in T2/T3.
*Decision:* follow it literally: ERROR/TIMEOUT in a selected T2/T3 means abstain. Configurable via
`acceptance.t2_t3_allowed`.

### D7 — Run commands and working directories
*Context:* the example manifest uses `java -cp target/classes …`, but programs must run with
cwd = a fresh per-case directory (their data files live there) and a read-only repo.
*Decision:* `run.command` runs via `sh -c` with cwd = case dir, `$TARGET_ROOT` = built repo
(read-only). Relative tokens (and `-cp` entries) that exist in the repo are rewritten to absolute
paths under `$TARGET_ROOT`; the rewritten command is recorded.
*Alternatives:* cwd = repo root — rejected (data files would mix with sources and the comparison of
the final working directory would be polluted).

### D8 — Comparing output files
*Context:* "compare every output file's bytes".
*Decision:* after each run, every file in the case working directory is captured; the target must
produce exactly the same set of files with the same bytes (extra or missing files are failures of
kind `MISSING_OR_EXTRA_OUTPUT`). Input files are part of that set, so unexpected in-place
modification is caught too.
