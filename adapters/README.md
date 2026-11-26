# adapters: pluggable bridges into the harness

`verifiers/` implements `harness.types.Verifier` (`verify(Candidate) -> Verdict`).

| adapter | what it is |
|---|---|
| `verifiers.contract:ContractVerifier(cmd)` | generic: runs `<cmd> check --workspace W --submission S` and reads `reports/S/report.json` (agreement 4.4). Point `cmd` at any checker that follows the contract. |
| `verifiers.nan:NanVerifier` | `ContractVerifier` preconfigured with `verifiers/nan/bin/phase2`, the glue over Nan's formal verifier (`verifier/` package, untouched). See `verifiers/nan/README.md`. |

To add a checker: implement a class with `verify(candidate) -> Verdict` (or ship a CLI following the contract and use
`ContractVerifier`), then name it under `harness.verifier.adapter` in `config.yaml`.
