# ADR 0015 — Recover exact verification, never replay an uncertain model turn

Status: Accepted. Date: 2026-10-08. Extends ADR 0014's recovery boundary only for a new opt-in release.

## Context

H5C fails closed when a process loses its guarded write ledger or ADLC has persisted evidence before Harness
persists its result. Recapturing changes the artifact ID/time and conflicts with immutable evidence. An uncertain
restart must not call a paid model again, accept a new reference, silently relax policy or convert a human decision.
Published H4/H5A/H5B/H5C bytes and locks must remain reproducible.

## Decision

1. Add `coding-agent-contract-harness@0.2.0` with a separately installed/locked
   `vai-adlc-contract-recovery@0.1.0` companion and fixed API/state/clone namespace. Reuse the unchanged H5C
   capability/policy/schema/verifier code under a five-plugin integrity lock; no additional agent authority.
   Explicit `recovery_ref`, exact recipe version and new disabled feature flag select this release.
2. Save a private bounded atomic/fsynced/checksummed complete candidate checkpoint **before** the external proof
   publication. Its request/binding/reference, original artifact bytes/checksum/base/paths, proof and result are immutable.
3. Restart reconciles only a VERIFYING completed checkpoint against the current signed registered ADLC binding/proof.
   Reuse identical saved proof/candidate, or publish that same proof if absent. Never recapture, rewrite proof, rerun/resume
   a model, reset a DB, choose latest reference or auto-Submit. MANUAL READY remains a human decision.
4. Narrow bridge outages keep VERIFYING with a fixed recovery diagnostic. An owner/current-attempt/correlation/version
   checked empty-body API command retries this reconciliation. It is not the existing generic run reconciliation operation.
   Reject racing original in-flight verification. Invalid/conflicting/expired/missing checkpoints require a new attempt.
5. Interrupting an uncheckpointed ACCEPTED/PROVISIONING/RUNNING/WAITING_INTERACTION session requires an explicit
   new attempt. Stale questions are cancelled rather than resumed without their guarded write ledger.
6. Keep existing immutable signed callback outbox/deduplication and independent coordinator evidence gate. Final/Historical
   results do not require live Harness availability or enabled recovery flags; expired bytes are not revived.

## Consequences and limits

The proof-publication/candidate-persistence crash window is reconciled with original identities, not a cross-store transaction.
Unfinished model turn resumption and distributed worker leases remain out of scope. One writer per runtime directory;
coherent backups include all ADLC and Harness stores. Power-loss guarantees depend on storage/OS behavior; Windows
process-crash tests do not certify hardware durability. New and original execution rows must not be enabled/hot-switched
together because they share tool names. Natural-language correctness remains explicitly unverified.

Default activation stays off. Implementing H5D does not authorize silently changing real owner login/account/key settings.
Live sign-off requires an actual owner decision and the documented running stack. Future companion bytes require a new
release/version, never a rewrite of published locks.

## Verification

Real owned test-child process termination on both sides of proof publication, exact byte/checksum/result restoration,
lost acknowledgement, bridge retry, expiry/corruption/conflict and zero model replay; real isolated Git/tool/capture flow;
actual SQLite/callback/coordinator reopen and once-only final outcome with negative missing-evidence gate;
owner/current-attempt controls, fixed routing, UI component and bounded read-only preflight checks.
Live and browser sign-off are recorded separately in the H5D milestone notes.
