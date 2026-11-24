# ADR 0012: Tool-authored, human-approved contract documents

- Status: Accepted
- Date: 2026-10-07

## Context

ADLC owns workflow planning and acceptance, while Harness hosts agent tools and replaceable plugins (ADR 0011).
The next plugin must let a human and agent read one concrete roadmap and later show it on both hosts.
Assistant-generated JSON and in-memory canvas state do not provide authoritative revisioning or approval.
H4 patch bytes expire; an approved contract must survive session/workspace cleanup without that expiry.

The mentor's `vai-skilltree` repository (commit `2fc49b6733df2dcd1911eb21274ed4e5228bdce9`, package 1.9.0)
demonstrates semantic construction tools and separate geometry. Its current storage/session broadcast/file
and editable viewer behavior is not suitable as the approval authority. Adopt the approach, not those trust boundaries.

## Decision

ADLC is the single durable writer and approval authority. Harness plugins adapt small typed tool commands to it.
Skilltree is the first concrete document schema; the v0.1 foundation is deliberately type-specific, not a generic arbitrary-file service.

Semantic content has server-assigned IDs/revision, full scope/constraints/nodes/criteria and acyclic dependencies.
Layout, execution progress, validation and human approval are separate projections/receipts.
The writer stores canonical JSON and immutable historical revisions independently of patch retention.

Draft edits require optimistic revision checks and durable idempotency. A transaction fences edits versus approval.
Human approval binds an exact schema/document/revision/digest after declaration validation. New edits to that
approved contract are rejected; an explicit human fork creates a new draft without overwriting the original.
No agent tool can approve, import raw content, choose an owner/session/file path, or publish an authoritative contract.

Human authoring/approval requires an explicit active user access token, not auto-login/API keys or service credentials.
The six-tool bridge uses a separately configured, purpose-bound HMAC secret and resolves ownership from a registered
active/current attempt with a frozen dedicated authoring profile and required plugin lock. Existing coding profiles cannot use it.
Installed plugin bytes must be pinned by the trusted runtime when a dedicated authoring recipe is subsequently published.

Both UIs must eventually render the exact same semantic document/reference, using an escaped JSON fallback
for unknown renderers. Neither a viewer edit/import nor localStorage can create another authoritative version.

## Consequences and staging

- H5A supplies typed schemas/manifest, six tools, durable revisions, signed bridge, human approval/fork/export and tests.
  Feature and Harness plugin remain disabled by default; no current recipe/lock is altered.
- H5B supplies the shared renderer and safe dedicated authoring recipe/profile. No visual renderer ships in H5A.
- H5C pins approved references into planning/execution constraints and verifier evidence. Declared restrictions
  do not become OS/tool permissions by themselves; declaration validation does not mean a test ran.
- H5D can add recovery/live E2E coverage, with the project's approved test provider/model only.
- Durability requires operational backup of the contract and run stores. This is not cryptographic non-repudiation
  against an administrator who controls the host/database. Errors expose fixed codes, not sensitive transport text.
- H4B code-test verification remains a separate unfinished slice; H5A does not substitute for it.

## Alternatives rejected

- Letting the model print a whole accepted JSON document bypasses the typed writer and review history.
- Letting Harness and ADLC each own a mutable copy introduces synchronization and conflicting approvals.
- Reusing the 24-hour patch store allows accepted contract content to disappear.
- Prompt-only obedience, schema checks or visual locks cannot enforce executable constraints and must not be presented as doing so.

Implementation reference: milestone H5 notes.
