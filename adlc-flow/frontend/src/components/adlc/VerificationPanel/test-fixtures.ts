import type { VerificationRead } from "@/types/verification";
import { copyContract } from "../ContractViewer/test-fixtures";

export function verificationFixture(
  state: VerificationRead["state"] = "DRAFT",
  verdict: "PASS" | "FAIL" = "PASS",
): VerificationRead {
  const contract = copyContract();
  const expected = verdict === "PASS" ? 42 : 43;
  const value: VerificationRead = {
    plan: {
      schema_version: "0.1",
      profile_ref: "verification-profile:json-fixture/0.1.0",
      plan_id: "plan-one",
      revision: 1,
      workflow_run_id: "run-one",
      contract_reference: contract.reference,
      timeout_seconds: 15,
      candidate: {
        source_task_id: "task-one",
        source_attempt_id: "attempt-one",
        source_session_id: "source-session",
        artifact_id: "artifact-one",
        artifact_digest: "sha256:" + "a".repeat(64),
        base_commit: "b".repeat(40),
        project_id: "project-one",
        source_ref: "project-one/base",
        file: "h6a-fixture.json",
        content_digest: "sha256:" + "c".repeat(64),
        encoding: "canonical-json",
      },
      cases: [
        {
          case_id: "answer",
          pointer: "/answer",
          expected,
          criterion_node_id: contract.document.nodes[0].node_id,
          criterion_index: 0,
        },
      ],
    },
    plan_digest: "sha256:" + "d".repeat(64),
    state,
    approved_by: state === "DRAFT" ? null : "owner",
    approved_at: state === "DRAFT" ? null : "2026-10-12T09:00:00Z",
    execution_id:
      state === "DRAFT" || state === "APPROVED" ? null : "execution-one",
    receipt: null,
    report: null,
    error_code: null,
    evidence_digest: null,
    created_at: "2026-10-12T08:59:00Z",
    submitted_at: state === "SUBMITTED" ? "2026-10-12T09:01:00Z" : null,
  };
  if (state === "READY_FOR_SUBMISSION" || state === "SUBMITTED") {
    value.receipt = {
      schema_version: "0.1",
      execution_id: "execution-one",
      plan_digest: value.plan_digest,
      candidate_digest: value.plan.candidate.content_digest,
      runner_ref: "runner:adlc-json-fixture/0.1.0",
      runner_digest:
        "sha256:c2afb80f9585dd021ed819fdb5d115f8d602f2c63d50e587365dbc43d3b9966f",
      provider: "local-fixture",
      sandbox_session_id: null,
      image_ref: null,
      tests_run: 1,
      completion_mode: "process-exit",
      exit_code: 0,
      observations: [
        { case_id: "answer", pointer: "/answer", found: true, observed: 42 },
      ],
      started_at: "2026-10-12T09:00:30Z",
      completed_at: "2026-10-12T09:00:31Z",
    };
    value.report = {
      schema_version: "0.1",
      plan_digest: value.plan_digest,
      candidate_digest: value.plan.candidate.content_digest,
      receipt_digest: "sha256:" + "f".repeat(64),
      verdict,
      comparator_ref: "validator:json-fixture/0.1.0",
      natural_language_enforced: false,
      contract_fully_verified: false,
      checks: [
        {
          case_id: "answer",
          pointer: "/answer",
          expected,
          observed: 42,
          found: true,
          passed: verdict === "PASS",
        },
      ],
    };
    value.evidence_digest = "sha256:" + "0".repeat(64);
  }
  return value;
}

export const fixtureCapabilities = {
  enabled: true,
  human_actions_configured: true,
  worker_ready: true,
  profile_ref: "verification-profile:json-fixture/0.1.0",
  scope_description: "Fixture only",
  provider: "local-fixture",
};
