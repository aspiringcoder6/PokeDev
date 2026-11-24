import type { ProposalRead } from "@/types/test-extensions";
import { replayFixture } from "../ReplayPanel/test-fixtures";
import { fixturePermissions } from ".";

export const extensionCaps = {
  schema_version: "0.1" as const,
  profile_ref: "test-extension-profile:proposals/0.1.0" as const,
  enabled: true,
  human_actions_configured: true,
  exploration_ready: false as const,
  performance_ready: false as const,
  screenshot_capture_ready: false as const,
  blockers: ["BROKER_IDEMPOTENCY_AND_CANCELLATION_REQUIRED"],
};
export function proposalFixture(
  state: ProposalRead["state"] = "DRAFT",
  kind: ProposalRead["document"]["kind"] = "suite-revision",
): ProposalRead {
  const r = replayFixture();
  return {
    reference: {
      proposal_id: "proposal-one",
      revision: 1,
      document_digest: "sha256:" + "1".repeat(64),
    },
    document: {
      schema_version: "0.1",
      profile_ref: "test-extension-profile:proposals/0.1.0",
      proposal_id: "proposal-one",
      revision: 1,
      parent_reference: null,
      source: {
        workflow_run_id: r.plan.workflow_run_id,
        plan_id: r.plan.plan_id,
        plan_digest: r.plan_digest,
        suite_digest: r.plan.suite_digest,
        candidate_digest: r.plan.candidate.content_digest,
        project_id: r.plan.candidate.project_id,
        source_session_id: r.plan.candidate.source_session_id,
        contract_reference: r.plan.contract_reference,
      },
      authoring_session_id: null,
      kind,
      title: "Review a new test standard",
      rationale: "The old frozen replay is never healed in place.",
      cases: r.plan.cases,
      permissions: state === "DRAFT" ? null : { ...fixturePermissions },
      performance:
        kind === "performance"
          ? {
              virtual_users: 2,
              duration_seconds: 10,
              requests_per_second: 2,
              max_requests: 20,
              p95_latency_ms_max: 500,
              failed_requests_max: 0,
            }
          : null,
      heal: false,
      models_used: false,
      executable: false,
      verification_evidence: false,
    },
    state,
    created_at: "2026-10-13T05:00:00Z",
    approved_by: ["APPROVED", "MATERIALIZED"].includes(state) ? "owner" : null,
    approved_at: ["APPROVED", "MATERIALIZED"].includes(state)
      ? "2026-10-13T05:01:00Z"
      : null,
    materialized_plan_id: state === "MATERIALIZED" ? "successor-plan" : null,
  };
}
