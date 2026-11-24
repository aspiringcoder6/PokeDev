# ADLC Harness contract v0.1

Status: **DRAFT — H0/H1/H2/H3/H4A IMPLEMENTED**

This boundary lets the ADLC control plane dispatch an immutable task attempt to a DeepSeek Harness execution hub and accept exactly one authenticated terminal result. It does not replace the existing ADLC task contract; it adapts one `TaskRequest`/`TaskResult` attempt to an asynchronous external session.

## Boundary

1. ADLC resolves a node package and sends a `HarnessSessionRequest` containing references, policy constraints, a content-addressed plugin lock, and correlation IDs. It never sends resolved secret values or a callback URL.
2. Harness creates or replays a session by `idempotency_key`, records ordered state events, and runs the configured execution and verification plugins.
3. Harness exposes typed `APPROVAL` and `FORM` interactions that pause and resume the same agent session. These are execution inputs, not ADLC lifecycle `ApprovalRequest` records; terminal results never use a partial `TaskResult` to represent waiting.
4. Submission enqueues an immutable `HarnessResultDelivery` in a durable outbox. `AUTO` submits after verification; `MANUAL` requires an explicit submit action.
5. Harness signs the exact bytes as `HMAC-SHA256(secret, timestamp + "." + body)`. ADLC validates `X-ADLC-Timestamp`, `X-ADLC-Delivery-Id`, and `X-ADLC-Signature`, deduplicates by delivery ID, verifies correlation, and atomically accepts the result for its `TaskAttempt`.
6. ADLC serves accepted results from its own attempt ledger through owner-scoped `GET /api/v1/adlc/runs/{run_id}/harness-results`. A completed result never requires a live Harness session. Run Detail renders the archived output, verification, interaction history, and downloadable original result JSON; unsubmitted live previews are labelled separately and do not complete the workflow.

## Trust rules

- `callback_ref` selects a deployment-owned callback; arbitrary callback URLs are forbidden.
- `plugin_lock` is immutable for the session and identifies every required plugin by exact version and SHA-256 content digest.
- Harness recalculates installed plugin bytes at startup and before execution. Readiness and execution fail closed when the installed inventory differs from the trusted lock.
- Bearer authentication protects the Harness control API. A separate callback secret protects Harness-to-ADLC delivery.
- Unknown public fields are rejected. Extensibility belongs only in documented `metadata`, `context`, `constraints`, `payload`, `details`, or `custom` objects.
- Verification failure produces a terminal failed result; a successful webhook delivery does not turn a failed execution into a successful one.

## Schema entry points

H4A adds `artifact-read.schema.json` for authenticated, out-of-band captured bytes.
Existing result/delivery envelopes keep descriptor-only artifacts and no new required fields.
ADLC validates and retains the actual Git patch before accepting a terminal result.
Preview reads never accept or submit it. Byte expiry does not erase result history.
The standalone Draft 2020-12 schemas cover session creation/read, interaction responses and receipts, plugin inventory, events, submission receipts, verification reports, terminal results, delivery envelopes, callback receipts, run/session and archived run/result projections, reconciliation reports, and the coordinator-side task-attempt projection. Examples live under [`examples/`](./examples/), and [`state-machines.json`](./state-machines.json) is the machine-readable transition allow-list.

Schema files are generated from `langflow.adlc.harness_models` by `adlc-flow/scripts/generate_adlc_harness_schemas.py`. CI tests require generated schemas to remain byte-equivalent in meaning to the runtime models.
