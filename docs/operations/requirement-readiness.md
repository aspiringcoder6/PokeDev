# Requirement readiness service

The opt-in internal API is `/api/v1/adlc/requirement-readiness`. It accepts normalized input and performs
collection/verification, independent requirements reviews, then independent impact analysis and assessment.
It never starts implementation. Upstream normalization and HumanBridge delivery remain external ports.

Configure the six `ADLC_READINESS_*`/`ADLC_REQUIREMENT_READINESS_ENABLED` settings in `.env.example`,
source bindings, and dedicated DSH credentials. The native manifest also needs eight distinct `presets`
named collector, context-verifier, reviewer-a, reviewer-b, clarifier, impact-code, impact-requirements,
and assessor. Use compatible read-only presets. The checked-in `.agents/skills/readiness-manifest.json`
pins upstream instructions and provenance; it deliberately contains no deployed native route commands.
Provision Spec Kit/OpenSpec native instructions and executable read-only command/version bindings in
`routes` and `commands` before enabling. Missing dependencies stop blocked; reading a checklist is not
native verification. Keep artifact workspaces server-owned. Do not import personal sessions or credentials.

Service binding JSON uses `credentials` rows with `sha256` of a high-entropy bearer token, `principal_id`,
`projects` and `purposes` (submit/read/answer/select). Bind exact projects; a submit-only normalizer cannot
answer or select. Generate and distribute credentials outside Git. Source bindings are checked on each
read and handoff; service permissions reload at each API operation. Configure source retention and access
to the SQLite database and backups as sensitive project evidence.

POST `/runs` with request_id, project_id, requirement and optional source_refs. Identical submissions
deduplicate. GET `/runs/{id}` exposes checkpoints. GET `/runs/{id}/handoff` returns 409 until Stage 3 is
complete. The resulting handoff ID is stable. Stage 2 `ready_for_spec` differs from verified `spec_ready`.

Supply HumanBridge through backend composition for interview/authorization delivery. No messaging
adapter is created here. Frontier answers and explicit empty-frontier confirmation are separate commands.
POST `/runs/{id}/answers` with round_id, command_id, expected_revision and response `{answers,confirmed}`.
Real answers plus final confirmation create a new snapshot and two fresh reviews. Silence never advances.
Required option selection can use the API even without delivery: POST `/runs/{id}/selection` with
assessment_digest, option_id, command_id and expected_revision. The authenticated identity is retained.
Commands are atomic and idempotent; changed payloads under the same command ID conflict.

Human Gates are backend JSON `projects` mapping to `{mode,revision}`; absent entries default required.
Auto requires an explicit project policy and complete reports without blockers or material uncertainty.
Policy changes invalidate stale choices. An option selection grants no implementation, merge or deployment.

The lifespan worker resumes active checkpoints using run leases. Waiting states do not prompt again.
Interrupted/uncertain model calls inspect history and stop unconfirmed rather than blindly resending.
Inspect and reconcile those operations before operator retry. Preserve round counts and tool reservations;
never edit them to reset budgets. Recover SQLite with its backups, not unrelated ADLC data. Stop the
service before manual recovery or cancellation; cancellation must preserve in-flight uncertainty.

After rotating an app secret/private key, rebuild the source gateway to resolve the new secret reference.
Keep stable connection IDs. Never log bearer tokens, provider headers, secret values or full evidence.

Offline tests use fixtures, a real SQLite store and minimal FastAPI app. Live acceptance is separate and
requires GitHub/Lark apps, DSH presets, selected native CLIs and the human service: run an auto case,
a required selection and an interview. Claim `spec_ready` only with trusted native execution receipts.

The serialized SDK prompt envelope is capped at 1,400,000 bytes (or a lower deployment limit),
including JSON escaping. The complete ACE dependency instructions alone use about 679 KB before
snapshots/reports. Oversized context stops explicitly; evidence and instructions are never truncated.
Native command entries require fixed argv, mode, version_argv and the exact observed version output.
Execution receipts bind the run, selected route, operation, snapshot and current artifact hashes in the
approved artifact_workspace. Native step approval is a separate named transaction; it grants no source access.
HumanBridge implements publish_authorization/observe_authorization as well as questions and selections.
For selection delivery, deduplicate/observe by pending_selection.publication_id, including policy revision.
Startup and the worker reconcile waiting outbox intents without repeating model reasoning.
