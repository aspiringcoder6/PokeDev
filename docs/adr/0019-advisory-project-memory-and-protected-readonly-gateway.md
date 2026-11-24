# ADR 0019 — Advisory project memory and a protected read-only gateway

Date: 2026-10-13 (Asia/Saigon)
Status: Accepted (local curated pilot and adapter; live Cognee certification pending)

## Context

The downloaded `vai_agentmemory@1.0.0`, revision
`65a84337aec82b9aa5166f0712e56428f7734355`, wraps Cognee MCP but is not its backend.
It defaults to a shared tenant, has no transport credential, injects tenancy before
the first handshake loads schemas, flattens provenance and exposes synthesis,
ingestion/self-improvement and deletion. `confirm=true` is not human authority.
Installing it unchanged beside the raw connector would bypass ADLC's owner boundary.

## Decision

Introduce `memory-profile:project-context/0.1.0` and
`gateway:adlc-memory-readonly/0.1.0`, separate from every contract/Verify schema.
ADLC derives tenant/project dataset from authenticated ownership and compiler-pinned
source context. Caller URLs, tenant/dataset names and permission booleans are rejected.
Each owner/project is bound to a separate reviewed read-only gateway credential in a
backend-only private registry. Gateway sessions never cross credentials or projects.

Initialize, negotiate a supported Streamable HTTP protocol, send the initialized
notification and successfully validate required scope schemas before any tool read.
Reconnection repeats those checks and reapplies scope. Reads alone may reconnect once;
there is no remote mutation/ingestion retry surface. Protocol/session behavior follows
the [MCP lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)
and [transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
specifications, within the deliberately limited supported adapter surface.

Require a structured scoped provenance projection; do not accept raw flattened prose
as a provenance-preserving read. Locally check retained text digests, document/chunk
identity, revision and timezone-aware freshness dates. Whole-source document digests
remain backend-declared, not independently verified. All context is
`ADVISORY_UNTRUSTED`, with `verification_evidence=false`,
`source_provenance_verified=false`, `models_used=false`.

Keep synthesis, ingestion/self-improvement and deletion absent, not merely hidden in
the UI. The new native plugin has three optional read-only tools and a Memory tab;
it never receives Cognee credentials or an ADLC user token. The UI reuses ADLC's protected
renderer. Signed tools require a current active bound attempt; session views are exact
and may also show human run-shared reads for the same pinned project, never another
session's agent-only reads. Backend loss or disabling memory does not hide archived
context, official contracts or verification evidence.

A separate loopback-only operator-curated gateway provides a usable no-model local
pilot. It performs deterministic lexical text search, not Cognee, GraphRAG or embeddings.
It freezes a bounded private configuration at startup, authenticates each read and
enforces scope. It has no write/delete/file/fetch/execution tool. Tests prove adapter
and local-gateway boundaries; they do not certify the mentor's service.

## Consequences and alternatives

- Normal runs, accepted contracts, callback/Submit behavior, quality gates and H6A/B
  evidence stay unchanged. Optional context cannot become an expected result.
- The raw downloaded plugin/connector remains uninstalled. No existing execution
  recipe/plugin lock is rewritten to gain memory implicitly.
- Configured/reachable is not certified. Live Cognee needs backend source/revision,
  enforced read-only auth/tenancy, provenance mapping, no-model route review and
  retention approval. Merely setting an environment URL or capability boolean is
  not that review.
- Retained context has its own bounded archive and durable command intent. An
  unfinished read is not automatically repeated after restart. No automatic GC,
  ingest or deletion is introduced. Source expiry is a freshness warning, not an
  assertion that the retained local snapshot has been erased.
- Shared default-tenant routing, agent-selected datasets and model-authored approval
  booleans were rejected. Curated post-acceptance outbox ingestion and explicit
  owner-approved deletion are later decisions, after model/retention policy review.

Implementation and activation: [H6C guide](../milestones/harness-h6.md).
