# ADR 0024 Explicit Lark conversation routing

Date: 2026-11-26
Status: Accepted (automated, PostgreSQL, desktop and live group/DM routing)
Deciders: PokeDev maintainer's LI-03 request and implementation decisions within that scope

## Context

LI-02 creates private requirements from authenticated text DMs. Groups and replies need durable routing that survives reconnects and does not confuse independent requests in the same chat. Lark root, parent and thread identifiers are distinct, and the current mention scope does not establish receipt of every unmentioned reply.

## Decision

Persist conversation bindings and message aliases scoped by app, tenant and chat. Resolve replies only through known native message anchors; conflicting or missing targets require an explicit `/intake <UUID> <text>` command. Validate the linked native owner and current project permission for every operation. A group has one explicitly configured project context, which may be an unbound private draft.

Store follow-up text as conversation evidence attached to the private intake. It does not silently replace the original brief, answer a future agent question or approve work. Group receipts acknowledge the action and link to the protected web record without quoting private content. Other group members do not gain intake or project access.

Introduce separate v2 wire models/endpoints while preserving v1 and pending transport records. Persist send routes with the outbox and alias accepted bot receipts back to their conversation. Group replies use native thread delivery. Require a bot mention by default; enable unmentioned replies per group only after observing actual delivery, and only accept replies with a known binding. An unmentioned native topic root or unknown thread cannot create an intake.

## Alternatives considered

- Route to the most recent request in a chat: easy to implement, but ambiguous conversations can mutate the wrong requirement; rejected.
- Use a single thread ID as the only key: compact, but fails before the provider creates a thread and loses parent/bot-receipt relationships; rejected.
- Expose or share every group-created requirement with all members: convenient collaboration, but bypasses private ownership and project policy; rejected.
- Append every reply directly into the brief: convenient editing, but conflates source evidence with confirmed requirements and can overflow or overwrite user edits; rejected.

## Consequences and recovery

The user must link their identity and the operator must explicitly configure pilot groups. Multiple requests remain independent; target selection occasionally requires a command. Native permissions, aliases, inbox and outbox remain authoritative rather than process memory. Rollout adds tables and backfills existing LI-02 DM anchors without changing stored content or receipts. Stop the connector and disable the new flags for rollback; retain history and reconcile unknown sends. See the [implementation plan](../plans/li03-implementation.md).

## Validation

316 backend checks, 34 connector/probe checks, 12 desktop component checks and the production frontend build passed. An isolated PostgreSQL schema exercised migration/adoption, legacy DM and bot-receipt backfill, independent group threads, DM replies, deduplication and delivery receipts; the schema was rolled back. The native pilot preserved the existing account link and LI-02 request, and the browser displayed its original source after migration.

Two user-sent mentioned roots in the allowed pilot group created distinct private requests. Mentioned replies were attached to the correct A/B request, with their native thread identifiers retained and all four business receipts DELIVERED. The desktop displayed two distinct source histories while both briefs stayed at revision 1. Unmentioned messages were visible in Lark Web but have no corresponding persisted event in this observation; support remains disabled.

Two tests in the actual bot DM also passed: an explicit `/intake` selection and a reply to the original LI-02 bot receipt both appended to that existing request. The reply parent matched the persisted provider receipt alias. Both acknowledgements were DELIVERED, no extra intake was created, and the desktop showed three source entries while the brief remained revision 1. The first messages labelled as DM tests had been posted to the group without a mention; they were excluded from DM evidence.
