# ADR 0010: Retain reviewable source patches temporarily

- Status: Accepted
- Date: 2026-09-17
- Scope: OpenCode source-patch artifacts, read authorization, and human review
- Supersedes: ADR 0009's non-retention decision; retains its service routing and disposable-worktree decisions

## Context

ADR 0009 captured and checksummed a disposable worktree's VCS diff but discarded the payload at cleanup. An
approver could see that files changed, but could not inspect the actual patch. Database-backed artifact storage is
planned but not yet required, and keeping the worktree alive would weaken the cleanup guarantee.

## Decision

1. Capture the complete VCS diff before worktree cleanup and retain a checksummed, immutable JSON payload in a
   bounded process-local store. Retention must not change the scheduler or executor contract.
2. Default to 2 MiB per artifact, 32 MiB total, and 24-hour retention. Prune expired payloads, but never silently
   evict an active payload. If retention fails, fail the task with a sanitized error rather than publishing a
   successful result whose patch cannot be reviewed.
3. Replace the old correlation-only URI with an ADLC Artifact reference. Expose an authenticated API that verifies
   workflow ownership, artifact membership, and exact run/task/attempt/checksum identity before returning bytes.
   Missing ownership appears as `404`; missing or expired bytes return `410`. Responses are non-cacheable.
4. Render patch text as text in Run Detail. Allow the UI's Approve action only after every captured patch loads;
   leave Reject available. This is UI behavior, not yet a server-side approval invariant.
5. Retain ADR 0009's exact service routing, opt-in package, detached worktree lifecycle, and no-touch main checkout.
   Approval does not apply or merge source changes.

## Consequences

Approvers can inspect what the coding attempt changed after its worktree has been removed. The bytes and run
state disappear on process restart or TTL expiry, and storage pressure can fail an otherwise successful coding
attempt. Source patches may contain secrets, so access is owner-scoped and the API must not log payload content.
The current local worktree remains unsuitable as a security boundary for hostile code.

## Alternatives considered

- Keep the worktree until approval: rejected because it complicates lifecycle and leaves executable task state
  alive while waiting for a human.
- Return raw patches in the TaskRun and event feed: rejected because polling would duplicate large, sensitive
  payloads across unrelated responses.
- Wait for database/object storage: rejected for this development slice; the in-memory store makes the review
  boundary testable now without committing to a persistence design.

## Follow-up

Add durable artifacts and run state together, an explicit reviewed apply/merge operation, and a backend approval
policy if patch availability must be enforced for non-UI clients. Those changes require separate decisions.
