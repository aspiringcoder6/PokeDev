# H6A independent verification v0.1

Status: implemented, opt-in, **JSON-fixture profile only**. Separate from the published
Harness `verification-report` enum and H5 contract-execution proof.

The closed schemas are generated from `langflow.adlc.verification_models`. They define
the candidate/approved-contract-bound plan, exact-digest commands, authenticated
execution receipt, deterministic comparison and retained owner-scoped record.
Unknown properties are rejected. Runtime validation additionally enforces unique
case/criterion identities, finite bounded scalars, timestamp ordering and full evidence
coverage; JSON Schema alone is not an execution/authorization authority.

`verification-profile:json-fixture/0.1.0` observes 1–16 scalar JSON-pointer values in one
reconstructed candidate. The observer does not receive expected values. ADLC compares
the observations to the human-approved plan. Only a complete bound receipt produces
PASS/FAIL. Zero tests, skipped/missing cases, invalid receipts and execution errors produce
no binary verdict. A genuinely missing pointer is an observed FAIL, not an execution error.

Both `natural_language_enforced` and `contract_fully_verified` are always false. The report
does not prove arbitrary roadmap semantics, testing of project code or permission to deploy.
Approval, execution, comparison and manual Submit are separate operations.

Receipt ingress is authenticated using the independent worker token and HMAC-SHA256
over `adlc-verification-receipt/v0.1\n` plus the **exact** `receipt_json` UTF-8 bytes.
After validation, ADLC retains a canonical plan/receipt/report download and its SHA-256.
Storage checksums detect corruption; they are not signatures against a malicious store admin.

To check parity, from `adlc-flow` with its Python environment and `PYTHONPATH` configured:

```powershell
.\.venv\Scripts\python.exe scripts\generate_adlc_verification_schemas.py --check
```

Without `--check` the generator prints a schema map to stdout, for deliberate editor updates.
Do not rewrite an accepted version when introducing a different runner or stronger profile.

See [rollout and limitations](../../../docs/milestones/harness-h6.md).
