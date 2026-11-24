# ADR 0013 — Shared authenticated viewer and restricted contract authoring

Status: Accepted. Date: 2026-10-08. Extends ADR 0012; does not supersede its writer/approval authority.

## Context

H5A provides immutable tool-authored documents, not a visual integration or a safe model authoring recipe.
Published H4 runtime/driver bytes and historical recipes must remain reproducible. A second mutable document
store in Harness, unrestricted standard coding tools or model-authored result references would bypass H5A guarantees.

## Decision

1. Implement one ADLC renderer, used in Run Detail and an authenticated, read-only Harness session route.
   The native Harness plugin embeds that route with a fixed public deployment URL and exact selected session.
   Browser config contains no service credentials. Unknown/inconsistent data falls back to escaped JSON.
2. Human approve/fork remain ADLC explicit-owner-login actions on the exact current reference.
   Review consent is reference-bound; stale/historical views cannot write. Contract approval never submits a run.
3. Publish a dedicated MANUAL authoring package/profile with exactly six typed tools and a fixed tested model route.
   Agent setup restricts presentation/visibility; a dispatch guard also checks trusted definition and agent identities.
   Commit must prove the restriction was installed before follow-up. No shell, code runner, web or child-agent tools.
4. Use a separate authoring runtime/API/state namespace in a new plugin while reusing unchanged H4 libraries.
   Exact plugin-byte locks are outside self-hashed plugin directories; old locks/recipes are not resynced.
5. Derive the handoff from a purpose-separated signed ADLC read of the registered current attempt's only validated head.
   Reject failed turns, no/multiple drafts, unknown bindings and arbitrary assistant JSON. Verify exact writer reference again.
6. Keep feature/plugin activation off by default. UI/projection and declaration verification never claim acceptance criteria
   were executed or execution policy enforced. Approved-reference execution binding remains H5C.

## Consequences

- One canonical store survives Harness cleanup; both hosts show the same revision/receipt and do not import arbitrary files.
- Harness viewing needs ADLC owner login/cookie access and compatible embedding headers. An ADLC new-tab link is the safe fallback.
- Authoring cannot use native ask-user tools because the capability set is exactly six. Human contract review occurs in ADLC.
- The authoring run may hand off VALIDATED content; approval and coding execution are separate workflows.
- Existing H4 API/result verification is preserved. Backend recovery probes only fixed roots after 404 and never retries writes across roots.
- New UI/runtime changes after publication require deliberate versioning; hashes are not automatically rewritten to accept drift.

## Alternatives rejected

- Separate React/store implementations per host: risks semantic and authority drift.
- Global/latest-session broadcast or workspace JSON scanning: crosses owner/session boundaries and accepts untrusted authority.
- Tool-name visibility restriction alone: scoped registration/late shadowing/code-runner paths can evade it.
- Parsing assistant result JSON as the selected contract: bypasses writer identity and exact-session selection.
- Editing H4 published plugins and resyncing historical locks: destroys the accepted byte-boundary guarantee.

## Verification

Offline tests cover owner/session reads, purpose-separated HMAC, current-head selection, exact review/fork/history,
fallback rendering, denied non-authoring dispatch, failed-turn rejection, MANUAL submission and callback persistence.
Installed SDK checks use a separate process and do not create an agent or activate plugins. Deployment/live E2E
and visual browser sign-off are recorded separately in the H5B milestone document.
