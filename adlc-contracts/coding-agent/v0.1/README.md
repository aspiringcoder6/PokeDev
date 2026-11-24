# Coding Agent contract verification v0.1

This additive boundary is used by `coding-agent@0.2.0` when an approved contract and task loop are enabled together. Existing task-loop v0.2 and document-execution v0.1 contracts retain their schemas.

[`contract-verification.schema.json`](contract-verification.schema.json) describes `CodingAgentContractVerification`, exposed as `contract_verification_report` alongside the task loop's `verification_report`.

The report binds:

- The exact owner-approved contract reference and compiled policy digest.
- The full task-loop specification digest.
- The captured candidate ID, content digest, and cumulative changed paths.
- The kernel-evaluated contract criterion results.
- `execution_policy_enforced: true` and `natural_language_enforced: false`.

Contract predicates and behavioral checks must both pass for the same candidate. The coordinator validates the immutable stored result and recomputes the supported contract predicates before accepting executor success. A final human review still applies.

The schema is generated from `langflow.adlc.coding_agent_loop_models.CodingAgentContractVerification`. Check parity from `adlc-flow`:

```powershell
.venv\Scripts\python.exe -m scripts.generate_adlc_coding_agent_schemas --check
```

Configuration, authorization, recovery, and runtime boundaries follow the unified Coding Agent design.
