# ADR 0020: Proposal-only test extensions and supplementary raster evidence

- Status: Accepted (bounded local UI/authoring; remote activation pending)
- Date: 2026-10-13

## Context

H6B has a trusted deterministic HTTP-JSON runner, frozen case/target/JUnit validation,
confirmed cancellation and retained evidence. The downloaded TestForge package is
still only a client; browser/load runners, backend idempotence, cancellation, cleanup
and model routing have not been certified. Registering its exploration/healing/perf
tools or treating an uploaded screenshot as proof would bypass the fixed-standard
verification boundary. H6D needs useful shared UI without inventing that capability.

## Decision

Keep published profiles, schemas, runner bytes, locks and TaskResult/callback semantics
unchanged. Add separately versioned sidecars and a bounded durable archive:

- Proposal JSON is created/mutated by six small scoped backend tools, frozen with an
  exact digest before explicit owner approval. After freezing, changes fork a successor
  with no inherited approval/permissions. No agent approval/execute/Submit tool exists.
- A reviewed suite revision can materialize idempotently into a new H6B **DRAFT**.
  Exact replay approval, Run, comparison and Submit remain separate. Old evidence is
  never healed or silently reclassified. Natural-language requirements remain outside
  this fixture profile's deterministic enforcement; changed expected values are clearly
  shown as a different typed standard, not proof of the previous standard.
- Exploration/performance are non-executable planning proposals. Target/data envelopes
  and workload ceilings are closed/bounded, but planning limits are not runtime controls.
  Unknown/risky execution fails closed even after human proposal approval.
- Uploaded static PNGs are checksummed, normalized, owner/run/execution/case-bound
  **supplementary untrusted references**, never assertion evidence. They cannot change
  PASS/FAIL. No arbitrary artifact URL, HTML/SVG or agent upload route is added.
- The existing protected renderer is reused in Run Detail and Harness Verify, including
  coverage, same-standard history, safe image previews, proposal revisions and advisory
  context. Harness remains read-only and receives no ADLC owner credentials.

## Consequences

H6D is useful without remote/model execution: humans and agents can inspect the same
records, iterate drafts and explicitly review new standards. Private screenshot data
requires operator retention review; there is no automatic deletion/GC. Durable creation
keys prevent duplicate successor drafts after a cross-store interruption, not exactly-once
remote side effects. Future live profiles require reviewed backend target/data authority,
idempotence, cancellation, cleanup, attested artifacts and approved model routing;
adding a flag or forging `approved_by` cannot activate an absent executor.

## Alternatives not taken

Install the raw upstream seven-tool client; enable automatic self-healing; accept any
image/URL as proof; proxy owner approval through Harness; or redefine published H6B
records in place. Each would weaken an existing authority/evidence boundary.

Implementation/activation: [H6D](../milestones/harness-h6.md).
