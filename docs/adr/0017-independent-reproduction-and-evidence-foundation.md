# ADR 0017: Independent reproduction and evidence foundation

Status: Accepted — H6A JSON-fixture foundation; remote broker rollout pending

## Context

Coding success, agent review and H5 machine-policy proof are useful but do not establish
that a candidate meets an objective, fixed specification through real execution.
The imported Sandbox/TestForge/Memory plugins cannot safely be installed wholesale as
verification authority. The available broker exposes generic execution with untyped
success schemas and no documented operation reconciliation/ownership attestation.

## Decision

Add a separately versioned verification boundary, durable owner-scoped ADLC archive,
protected execution-plane plugin and shared Verify panel. Start with one bounded JSON
fixture reconstructed from an accepted Harness patch and pinned local-project commit.
The owner freezes and separately approves exact contract/candidate/case references.
The protected observer executes real cases without receiving expected values; ADLC's
fixed comparator alone produces PASS/FAIL from complete authenticated observations.

Incomplete execution, timeout, zero cases, stale candidate, invalid signatures or unknown
dispatch produce no binary verdict. A missing field that was actually observed produces
FAIL. Submit publishes a prepared PASS or FAIL report, not deployment authority.
Restart observes saved intent/evidence without another candidate/model execution.

Local-fixture is a JSON-only pilot, not an arbitrary-code security sandbox. A remote adapter
is present but fails closed unless scoped session/image/result guarantees are confirmed.
The supplied broker is not live-certified. Broader TestForge replay, target materialization,
quality-gate wiring and memory are subsequent slices with independent authority review.

## Consequences and alternatives

The UI distinguishes Review, reproduction, verdict and report publication. Evidence remains
readable with Harness offline/cleaned up and is linked to its exact source attempt/session.
Approved plans cannot be edited; another draft gets a new ID. Existing H4/H5 contracts,
callbacks, recipes and original task/run status are not rewritten. This slice does not add
an orchestrator TESTING node or claim the full roadmap/application was verified.

Rejected alternatives: trust `testing.outcome=PASSED`, let candidate code author its own
receipt, submit generic sandbox commands with caller-supplied `approved_by`, or retry an
ambiguous create automatically. No such route can upgrade agent statements to evidence.

## Implementation constraints

Closed models plus runtime cross-record validation; exact digest commands; explicit owner
login for writes; scoped independent worker/broker credentials; bounded JSON, cases,
timeout/concurrency/storage; protected publisher runner; atomic intent/checkpoint; safe UI.
Single worker per protected directory. Checksums protect integrity against accidental
corruption; admins and receipt-signing worker remain trusted. Any stronger runner/profile
must use a new version and retain old evidence semantics.
The local publisher lives outside model/source mounts. The shared model-bearing Harness
does not acquire receipt signing/broker credentials from environment forwarding and cannot
activate publication through env flags alone. A production publisher needs a separate
execution plane: a model-writable journal must never be upgraded to a signed attestation.

See [H6A implementation, activation and test evidence](../milestones/harness-h6.md).
