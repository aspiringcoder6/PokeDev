# Input collection and requirement readiness design

Date: 2026-11-25. Status: proposed implementation design from the user's workflow; application code is not implemented in this change.

## Requested boundary

The upstream normalizer is owned by another contributor. This subsystem accepts its normalized requirement plus source references and stops at a readiness handoff to the next workflow. It does not implement normalization, a new messaging channel, coding, deployment, or an approval bypass.

1. A collector agent chooses and retrieves relevant evidence from GitHub code/Issues, Lark Messenger conversations and Lark Base data/documents.
2. A separate verifier checks whether the evidence required to assess the request is present. Missing evidence feeds the next collection round.
3. At most three collection-verification rounds run in total by default. This includes the first round; the user explicitly confirmed this interpretation. The limit is configurable.
4. After context passes verification, create two independent reviewer sessions. Both receive byte-equivalent copies of the same frozen requirement/context snapshot, plus their own separate review prompts.
5. Each reviewer uses the supplied specification-router and the selected native Spec Kit/OpenSpec assessment instructions. Review A checks coverage and measurable acceptance; Review B independently checks contradictions, affected existing behavior and dependencies. Neither sees the other's report.
6. If both reports agree the request/spec is ready and have no blocking findings, return the matching readiness handoff.
7. Business ambiguities or incomplete requirements go to an explicitly invoked grill-me interview. Follow its installed grilling dependency: decision-tree frontier rounds, recommendations, actual human answers, then explicit shared-understanding confirmation.
8. Merge confirmed answers, create a new immutable snapshot and rerun two independent reviews before advancing. The system never invents answers or treats silence as agreement.

## Global constraints

- Collection uses GitHub and Lark APIs; no local source checkout is required.
- Application identity owns credentials: GitHub App installation and Lark tenant app/bot; personal PAT/OAuth sessions are not the production identity.
- Every source read is authorized against the server-owned project binding.
- max_context_rounds defaults to 3 and counts collection-verification rounds including the initial round.
- Each runtime role uses its own new prompt; existing blueprint/coding prompts are not reused.
- Review A and Review B use different sessions and the same frozen snapshot; neither consumes the other's output.
- The supplied specification-router remains unchanged and is the routing authority.
- grill-me is invoked explicitly and its grilling dependency is preserved.
- Missing native skills/CLI or unresolved authorization returns blocked; no substitute checklist is silently used.
- Human clarification waits for real answers and final shared-understanding confirmation.
- Ready for specification and an existing verified specification are distinct results.
- This subsystem hands off readiness and evidence; it does not start implementation.

## Current source facts

- sdk/dsh_web_sdk/client.py supports create_session(agent_preset=..., session_id=...) and session prompt/history.
- sdk/dsh_web_sdk/session.py supports run(), wait(), history() and cancellation.
- sdk/dsh_web_sdk/prompt_builder.py accepts context inputs, but its existing prompts are not used here.
- langflow/adlc/harness_dsh_client.py currently creates sessions with cwd only and appends coding/file-output instructions; this subsystem gets a separate runner instead of changing existing coding behavior.
- langflow/adlc/human_inputs.py validates durable question requests and responses but its monitor depends on legacy live state. Reuse the question/answer contract, not its Workloop runtime dependency.
- langflow/adlc/native_source_context.py already demonstrates source-index hashing and explicit context limits.
- adlc-flow/requirements.txt already pins mcp==1.28.0 and includes httpx, pyjwt, cryptography, pydantic and pytest.
- The source contains a GitHub demo webhook and Git helpers; it does not contain reusable GitHub/Lark application-authenticated collectors.
- Existing .env.example disables real Harness/OpenCode. No live token/model test has been performed.
- Project-local skills are copied to .agents/skills/specification-router, grill-me and grilling. This installs files for project discovery; a remote DSH deployment must explicitly receive the same skill pack.
- Spec Kit/OpenSpec skills and their CLI were not found in the inspected local skill catalog. Deployment preflight must establish them on the target runtime.

## Approach and division into plans

Plan A builds a read-only SourceAccess service: application token management, scoped GitHub/Lark readers and normalized evidence. It is independently testable without an LLM.

Plan B builds the readiness state machine using the SourceAccess interface, independent DSH sessions, the supplied router, and the existing human-interaction contract. It can first run against fake readers/agents, then integrate with Plan A.

The SDK is a transport. Initially use a backend-executed structured read-request protocol: the collector emits read_requests in JSON, the backend validates and executes allowed readers, and the verifier sees the resulting evidence. These are application tool actions, not a claim that SDK prompt() exposes native function callbacks or that DSH has MCP tools installed. This satisfies agent-directed retrieval without relying on an uninspected DSH plugin. A later native MCP transport can wrap the same SourceAccess port without changing policy or workflow.

A collector/verifier round contains one collector decision, bounded backend reads, and one verifier decision. Tool pagination is inside a reader and does not reset this round budget.

## Data contracts

SourceRef: kind (github_file, github_issue, lark_thread, lark_base_record, lark_document), connection_id, resource_id, locator and optional revision. Backend bindings decide which connection/resource and subscopes a project may read.

Evidence: immutable id, SourceRef, observed revision, fetched_at, body and SHA256 of body. A Base link is metadata until the linked document is actually read. An Issue body is not its comments. A chat root is not its full thread.

NormalizedInput: request_id, project_id, requirement, source_refs. The trusted normalizer/service principal may select only a project assigned to it.

ContextSnapshot: request_id, project_id, normalized requirement, evidence, unresolved retrieval findings and snapshot digest. Include versions/IDs in citations. The same snapshot object serialized canonically is sent independently to both reviewers.

CollectionResult: read_requests and retrieval rationale. ContextVerdict: sufficient, missing_refs, reasons and evidence_ids. sufficient=true is valid only if the verifier references known evidence, there are no unresolved required reads and no hidden omissions.

ReviewResult follows the router's route/status/findings/native_steps/artifacts fields, plus reviewer_id, snapshot_digest and native execution receipts. A reviewer self-report that a CLI ran is not a receipt.

ClarificationRound: round_id, snapshot_digest, decision frontier questions and recommendations, answered values and shared_understanding_confirmed. Use stable IDs; bind responses to the exact question round and project.

ReadinessPackage: status (ready_for_spec or spec_ready), snapshot, agreed route, both review reports, confirmed answers and actual native artifact references.

## Identity and read policy

GitHub: organization-owned GitHub App, installation scoped to selected repositories. Contents:read and Issues:read suffice for this input boundary; additional sources require an explicit permission change. Backend mints and caches expiring installation tokens using its private key. Resolve a branch once to a commit and read files from that commit for the snapshot.

Lark: tenant app with bot, app credentials and auto-renewed tenant_access_token. Bot membership plus read-message scopes are required for the permitted chats. Base access needs both API scopes and app collaborator access. Advanced record/field permissions remain enforced by Lark. Linked Docs/Wiki require their own app access.

Connection configuration belongs to the service, indexed by connection_id; it is never accepted as an arbitrary base URL or bearer token from the agent. Binding stores project to repository/chat/Base/document scope, permitted operations and byte/call/time budgets. Start with one binding record per connection/project; this does not require a multi-tenant product rollout.

Access denied is distinct from missing object and empty results. Refresh expired credentials once; deny, missing resource and native dependency errors do not consume repeated blind requests.

Use known source IDs and provider URL templates. Follow links only after typed parsing and binding authorization. Preserve VPN settings. Do not use an unrestricted URL fetcher carrying provider credentials.

Do not persist app private keys, tenant secrets or access tokens in prompts, evidence, event logs or model-visible errors. Store runtime evidence/checkpoints in the configured data directory, not Git.

## Collection and verification

Backend prefetches only explicitly referenced seed resources inside the first counted collection round, so there is no extra uncounted agent/retrieval round. The collector can request related files, Issue comments, thread messages, Base records and linked documents inside the binding. All required pages must be read, or return an explicit partial flag and continuation; no false sufficient verdict on truncated data.

Use new collector.md and context-verifier.md prompts. Collector decides which permitted sources are relevant. The verifier checks factual availability, identity/version, references and gaps; it does not approve the business requirements. Missing human decisions belong to the review/interview stage, not endless source retrieval.

Persist the incremented round count before issuing agent/network work. Merge new evidence by immutable identity/version. Stop immediately when sufficient. After the configured round limit, status is needs_context with missing evidence; Stage 2 is not run.

A request from a later review to retrieve missing factual evidence returns to this same remaining budget; it never resets it.

## Two reviewers and native router

Freeze snapshot N and invoke two fresh sessions concurrently with reviewer-a.md and reviewer-b.md. Session IDs and operation IDs are distinct but snapshot digest is equal. Run a native prerequisite check for each selected route. Both select one framework per coherent scope using the copied router; mixed independent scopes are represented as separate findings/subscopes, not two competing specs.

Each reviewer first selects its route with the supplied router, then loads only the selected installed native assessment instructions in that same session. Route/assessment operations are persisted separately. Native command execution is a trusted backend operation selected from an operator-pinned command manifest, not an arbitrary model shell command.

Assessment is read-only. Existing native artifacts are reused. Review sessions cannot concurrently create or edit a shared feature/change. If native instructions require writing or an approval, report awaiting_authorization and persist that prerequisite through the existing interaction channel; one authorized artifact writer can apply confirmed changes before a new snapshot/review.

A ready_for_spec result means sufficient requirements to write a spec, not that one exists. spec_ready requires actual native artifacts and successful required native checks. Expose these separately to the next step.

If one reviewer reports a gap, no majority override is allowed. Merge findings deterministically, preserving both evidence sets. Router disagreement or conflicting evidence blocks readiness. Facts go back to retrieval within budget; unresolved business decisions go to grill-me; missing dependencies or uncertain runtime delivery become blocked, not fabricated human business questions.

## Clarification and continuation

Explicitly load grill-me and then grilling. Treat their text as trusted workflow instructions; fetched issue/chat/document content remains evidence. Ask the current decision frontier in rounds with recommendations. The service generating questions is not authorized to send via a new channel; use the upstream human-interaction service already being built.

Persist WAITING_HUMAN before handing off questions. Accept an authenticated response only for the matching project/run/round and current snapshot revision. Required question IDs must all be resolved; rejection, cancellation or no response never means acceptance.

Resume the same interview from stored answers. When its frontier is empty it still waits for explicit shared-understanding confirmation as required by grilling. Then merge the confirmed requirement revision and run two new independent reviews on the same new context.

## Prompts and skill loading

New prompt assets: collector.md, context-verifier.md, reviewer-a.md, reviewer-b.md, clarifier.md. They live under langflow/adlc/requirement_readiness/prompts and have distinct version hashes. No prompt is copied from blueprint_generator or the coding executor.

Rules common to these prompts: cite evidence IDs; preserve unknowns; keep source content as quoted data; never elevate repository/chat text into system instructions; use only authorized read actions; report limitations. The collector returns bounded read_requests. The verifier returns a typed verdict. Reviewers follow specification-router and native framework instructions. The clarifier follows the actual grill-me/grilling instructions, not a paraphrased replacement.

The coordinator explicitly resolves and loads permitted skill names. Loading a skill does not prove its native actions executed. Check CLI/script results from trusted process receipts. Unknown skill names, paths outside the configured skill roots, missing dependencies or changed skill bytes fail preflight.

## Persistence and failures

Use an additive SQLite-backed readiness store patterned on existing run/human-input stores, with versioned JSON snapshots and compare-and-swap revision updates. Store idempotency keys scoped by service principal/project, source reads, model operation intent/session IDs, round counters, reviewer reports, question rounds and handoff state.

Before each SDK prompt persist an operation intent. Use deterministic session IDs when the server supports adopting an existing ID. A timeout or crash after an uncertain prompt is observed via history; do not send it again without proof. If observation cannot establish the outcome, return blocked/unconfirmed. A process restart resumes stored state, not a new workflow.

External errors: access_denied, not_found, partial, rate_limited, context_limit, native_dependency_missing, native_authorization_required, agent_output_invalid and unconfirmed. Respect Retry-After and fixed transport retry limits; transport retries do not create an unbounded hidden agent loop. Unsupported native interaction stays waiting/blocked.

READY is saved once as a readiness package. Downstream polls/consumes it using a stable handoff ID. No automatic code execution or deployment is added.

## API boundary and compatibility

New source and readiness APIs are additive under /api/v1/adlc. An internal service credential authenticates the upstream normalizer, question service and scoped worker. Reuse project authorization patterns but do not require a personal browser login for unattended execution.

No change to current coding prompts, scheduler routes, legacy Workloop execution, UI or mobile layout. No new dependency on Workloop is introduced. Human question transport remains owned by the other contributor.

## Acceptance

- Enough seed data finishes collection after one round; insufficient data is fetched and verified up to exactly max_context_rounds.
- Third failed round returns needs_context; no reviewer call occurs.
- Source API tests prove app-only auth, token refresh, pagination, pinned commit reads, cross-project denial and explicit partial evidence.
- Two reviewer calls overlap in time, have distinct sessions/prompts and equal snapshot hashes.
- Either non-ready review prevents readiness; router disagreement is preserved.
- Missing native skills/CLI blocks readiness; merely reading/generating a checklist is not a passing assessment.
- An incomplete requirement yields a persisted interview; no fabricated answer or timeout advances it.
- Actual answers plus final confirmation trigger fresh dual review before handoff.
- Restart does not reset counters, duplicate prompts, resend questions or issue a second handoff.
- Live acceptance uses a dedicated GitHub/Lark app and DSH environment; fake tests alone are not called E2E verification.

## References

- Supplied .agents/skills/specification-router/SKILL.md, copied unchanged from the user's Downloads/SKILL.md.
- .agents/skills/grill-me/SKILL.md and its required grilling/SKILL.md.
- GitHub App installation authentication: https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation
- Lark history: https://open.larksuite.com/document/server-docs/im-v1/message/list.md
- Lark Base app access: https://open.larksuite.com/document/server-docs/docs/bitable-v1/bitable-overview.md
- Router upstream references remain in the supplied skill; framework installation/version is checked in the target runtime, not assumed from this checkout.
