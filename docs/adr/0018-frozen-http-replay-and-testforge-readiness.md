# 0018 — Frozen HTTP replay and explicit TestForge readiness

Status: Accepted for the local fixture pilot; real TestForge activation remains blocked.
Date: 2026-10-13 (Asia/Saigon; source inspection on 2026-10-12).

## Context

H6A established owner-controlled frozen candidates, exact approval, protected reproduction,
comparison and retained evidence. H6B needs a frozen multi-case suite, actual target identity,
JUnit coverage and cancellation. The supplied `vai-testforce` source is a client wrapper,
not its Windows broker or runners. Its default private broker cannot currently be reached
from this workstation. A completed job or a log tail cannot establish a verification verdict.

## Decision

Introduce `verification-profile:http-json-replay/0.1.0` and a separate protected
`vai-adlc-replay-runtime@0.1.0` pilot. Serve one frozen JSON candidate through a disposable,
authenticated loopback HTTP fixture and make actual GET requests for every required case.
Expected values belong to the approved suite, not the target. Validate exact candidate,
instance, suite, config, pinned runner, observations, process/checkpoint outcome and bounded
safe JUnit before producing PASS/FAIL. This proves fixture assertions, not application behavior.

The human authorizes the exact plan digest. Approve, execute, cancel and Submit are separate.
Edits create a successor draft; no in-flight oracle changes, healing, required skips, model
calls, arbitrary targets, production accounts, cleanup DELETEs or shell commands are accepted.

Reuse H6A's ownership, captured candidate freezer and bounded archive mechanics through
internal profile parameters. Preserve H6A schemas, table, runner bytes/hash and public behavior.
Give H6B a separate table, default database, key, HMAC domains and API namespace. Observe-only
restart recovery never recreates a process, target or model turn. Save cancellation intent
before stopping an in-memory owned child; only authenticated bound confirmation makes it
CANCELLED. Never kill a persisted/unproven PID. A completed receipt wins a late cancel race.
The runner has its own hard lifetime even if its parent publisher dies.

Publish signing credentials/journals only in a protected process and storage outside all
candidate/model mounts. Shared model-container plugin activation throws rather than exporting
a trusted receipt authority. Nothing is added to the active Harness patch/compose for H6B.
Use the existing native Verify plugin to display the same owner-protected ADLC read-only page.

Do not adapt the raw upstream POSTs by guesswork. Keep `testforge_ready=false` until backend
source/revision, schemas, authenticated transfer/evidence, idempotency lookup, cancellation,
target/credential policy and no-model/no-heal routing have been reviewed and implemented.

## Consequences and alternatives

The local pilot is immediately testable without provider keys, Docker, VPN or a production
target. Both UIs show the exact suite and archived evidence, with remote TestForge visibly
blocked. It does not yet prove Playwright/browser regression, staging integration, performance,
whole-contract compliance or a workflow quality gate. Its Submit publishes an independent
archive record, not a coding TaskResult, callback, deployment or release permission.

Rejected alternatives: install all raw tools and trust `completed`; auto-heal an approved
suite; expose an arbitrary localhost/public URL; repeat a timed-out create; trust agent-written
JUnit or an `approved_by` string; rewrite H6A proofs in place; claim our fixture is TestForge.

Rollout, exact scope, tests, localhost topology and remaining prerequisites:
[H6B milestone](../milestones/harness-h6.md).
