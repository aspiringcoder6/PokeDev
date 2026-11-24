# Contract execution resources v0.1 — H5C

Status: implemented, opt-in. These separately versioned resources do not modify
the frozen base task contracts or published H5A/H5B producer schemas.

| Resource | Meaning |
| --- | --- |
| `contract-execution-binding.schema.json` | Exact approved reference, supported policy/digest, accepted-plan links and full current attempt/session correlation. |
| `contract-execution-policy.schema.json` | Registered path/action/tool policy and ordered machine predicate inventory; never arbitrary natural-language enforcement. |
| `contract-execution-proof.schema.json` | Real captured artifact identity/checksum/base commit/paths and versioned per-criterion boolean evidence. |
| `contract-execution-result.schema.json` | Kernel-generated handoff (`outputs.contract_reference`, `outputs.source_patch`, `evidence`); fixed summary. |
| `contract-execution-read.schema.json` | Owner-authorized binding/source/proof projection for both UIs. |
| `contract-execution-bridge.schema.json` | Closed kernel-only bind/report envelope; no caller-selected owner, plan, contract or workspace. |

`ContractReference` retains exactly `{schema_ref, contract_id, revision, content_digest}`.
The semantic document and its approval receipt remain in the H5A source store.
Binding/policy/proof hashes use full validated models, sorted keys, compact UTF-8 JSON,
explicit defaults/nulls and no NaN. Do not hash a pretty-printed projection.
Evidence flags are exact booleans and timestamps require time zones. Git IDs are exactly 40 or 64 hex characters.

Registered predicates:

- `verifier:contract-source-patch/0.1.0`, ARTIFACT: at least one changed file in the accepted capture.
- `verifier:contract-no-changes/0.1.0`, ARTIFACT: zero changed files.
- `verifier:contract-json-syntax/0.1.0`, TEST: at least one changed JSON file; all changed JSON files parse.

Unknown/HUMAN verifiers, kind mismatches, unknown actions, unsupported path grammar and contradictory predicates
reject before a model turn. Read-only cannot require source changes. Criterion text is retained for review,
not treated as an executable test. `criteria_executed=true` and `execution_policy_enforced=true` mean only these
registered predicates and the bounded file/action policy; `natural_language_enforced=false` is mandatory.
They do not prove implementation correctness, DAG execution order, arbitrary test success or deployment.

Bridge purpose is `adlc-contract-execution-v1\n`, distinct from authoring/writer purposes; commands are ≤32 KiB,
responses ≤512 KiB. Proofs have ≤128 paths and ≤256 criterion checks. Combinations may hit wire bounds before
individual field limits: reject rather than truncate. Binding/proof store has no automatic TTL/eviction,
1,000 attempts and 64 MiB payload bounds. Patch bytes retain the existing 24-hour/512-KiB/128-file limits.

From `adlc-flow`, regenerate/check only these new resources:

```powershell
.\.venv\Scripts\python.exe -m scripts.generate_adlc_contract_execution_schemas --check
```

Runtime models validate cross-field authority/integrity beyond JSON Schema. Identical proof retries replay;
conflicting proof never replaces persisted evidence. Neither schemas nor a bridge key grant human approval.
See [ADR 0014](../../../../docs/adr/0014-approved-contract-execution-policy-and-evidence.md).
