# H6B frozen replay v0.1

New profile `verification-profile:http-json-replay/0.1.0`; not an extension of
H6A's JSON-observation profile or an upstream TestForge result schema.

Seven closed schemas are exported from `langflow.adlc.replay_models` by
`adlc-flow/scripts/generate_adlc_replay_schemas.py`. Run its `--check` mode to
verify parity. Runtime semantic validation is also required: JSON Schema alone
does not recompute plan/suite/config hashes, authorize an owner, authenticate a
receipt, validate JUnit coverage or attest target cleanup.

The plan binds an approved contract reference and captured pinned JSON candidate
to 1–16 required scalar equality / HTTP status assertions. The suite digest uses
UTF-8 canonical JSON `{schema_version:"0.1", cases:[...]}` including all defaulted
case fields, criterion IDs/indexes and expected values. Transfer `suite_json` as
exact bytes so `42.0` and Unicode serialization cannot drift across runtimes.
The target config is fixed; no agent-supplied URL, command, password or account is
accepted. `heal=false`, models disabled and required skips prohibited.

A receipt must bind the actual allocated loopback instance to the execution ID
and frozen candidate response digest. Safe JUnit must contain exactly the required
ordered cases, matching failure counts, no skips/errors or external entities. A
complete assertion contradiction is FAIL; missing evidence or execution failure
is NOT_VERIFIED with no binary report. Recovered checkpoints use `exit_code=null`
and never invent an observed process exit. Cancelled is not FAIL or PASS.

Provider `local-http-fixture` runs only a trusted disposable JSON HTTP service.
It does not execute project code or the TestForge backend. Reports explicitly set
`application_verified=false`, `contract_fully_verified=false` and
`natural_language_enforced=false`. The legacy broker is intentionally not a
registered provider. See [H6B rollout](../../../docs/milestones/harness-h6.md).
