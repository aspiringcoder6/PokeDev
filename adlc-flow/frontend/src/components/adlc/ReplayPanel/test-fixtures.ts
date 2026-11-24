import type { ReplayRead } from "@/types/replay";
import { verificationFixture } from "../VerificationPanel/test-fixtures";
// Illustrative UI fixtures only. These are not real attestations or API inputs.
export function replayFixture(
  state: ReplayRead["state"] = "DRAFT",
  verdict: "PASS" | "FAIL" = "PASS",
): ReplayRead {
  const original = verificationFixture();
  const expected = verdict === "PASS" ? 42 : 43;
  const row: ReplayRead = {
    plan: {
      ...original.plan,
      profile_ref: "verification-profile:http-json-replay/0.1.0",
      candidate: { ...original.plan.candidate, file: "h6b-fixture.json" },
      cases: original.plan.cases.map((c) => ({
        ...c,
        expected,
        method: "GET",
        path: "/fixture",
        expected_status: 200,
      })),
      suite_digest: "sha256:" + "e".repeat(64),
      config_digest:
        "sha256:d634ef15e33d6ab44ac44f2d62da5d80ae97e718da7e5222a3e83566f742e191",
      target_profile_ref: "target-profile:disposable-http-json/0.1.0",
      credential_ref: "credential-profile:ephemeral-fixture/0.1.0",
      risk_class: "read-only-non-production",
      heal: false,
      models: false,
      skip_policy: "no-required-skips",
    },
    plan_digest: original.plan_digest,
    state,
    approved_by: state === "DRAFT" ? null : "fixture-owner",
    approved_at: state === "DRAFT" ? null : "2026-10-12T09:00:00Z",
    execution_id:
      state === "DRAFT" || state === "APPROVED" ? null : "execution-one",
    receipt: null,
    report: null,
    error_code: null,
    evidence_digest: null,
    created_at: original.created_at,
    submitted_at: state === "SUBMITTED" ? "2026-10-12T09:01:00Z" : null,
    cancel_requested_by: ["CANCELLED", "CANCEL_REQUESTED"].includes(state)
      ? "fixture-owner"
      : null,
    cancel_requested_at: ["CANCELLED", "CANCEL_REQUESTED"].includes(state)
      ? "2026-10-12T09:01:00Z"
      : null,
    cancelled_at: state === "CANCELLED" ? "2026-10-12T09:01:01Z" : null,
  };
  if (state === "SUBMITTED" || state === "READY_FOR_SUBMISSION") {
    row.receipt = {
      schema_version: "0.1",
      execution_id: "execution-one",
      plan_digest: row.plan_digest,
      candidate_digest: row.plan.candidate.content_digest,
      suite_digest: row.plan.suite_digest,
      config_digest: row.plan.config_digest,
      runner_ref: "runner:adlc-http-json-replay/0.1.0",
      runner_digest:
        "sha256:b181341587bdc60dde4be167d9504af960927cb173046cd26886bd27ae250803",
      provider: "local-http-fixture",
      target_profile_ref: row.plan.target_profile_ref,
      credential_ref: row.plan.credential_ref,
      target_instance_id: "execution-one",
      target_origin: "http://127.0.0.1:39001",
      target_released: true,
      heal: false,
      models_used: false,
      tests_run: 1,
      completion_mode: "process-exit",
      exit_code: verdict === "PASS" ? 0 : 1,
      observations: [
        {
          case_id: "answer",
          pointer: "/answer",
          found: true,
          observed: 42,
          http_status: 200,
          response_digest: row.plan.candidate.content_digest,
          outcome: verdict,
        },
      ],
      junit_xml: `<testsuite name="adlc-http-json-replay" tests="1" failures="${verdict === "PASS" ? "0" : "1"}" errors="0" skipped="0"><testcase classname="http-json-fixture" name="answer">${verdict === "FAIL" ? '<failure type="AssertionError">Frozen HTTP assertion did not match</failure>' : ""}</testcase></testsuite>`,
      junit_digest: "sha256:" + "f".repeat(64),
      started_at: "2026-10-12T09:00:30Z",
      completed_at: "2026-10-12T09:00:31Z",
    };
    row.report = {
      schema_version: "0.1",
      plan_digest: row.plan_digest,
      receipt_digest: "sha256:" + "f".repeat(64),
      candidate_digest: row.plan.candidate.content_digest,
      suite_digest: row.plan.suite_digest,
      config_digest: row.plan.config_digest,
      junit_digest: row.receipt.junit_digest,
      verdict,
      comparator_ref: "validator:http-json-replay/0.1.0",
      natural_language_enforced: false,
      contract_fully_verified: false,
      application_verified: false,
      required_cases: 1,
      completed_cases: 1,
      checks: [
        {
          case_id: "answer",
          pointer: "/answer",
          expected,
          observed: 42,
          found: true,
          expected_status: 200,
          observed_status: 200,
          passed: verdict === "PASS",
        },
      ],
    };
    row.evidence_digest = "sha256:" + "0".repeat(64);
  }
  return row;
}
export const replayFixtureCapabilities = {
  enabled: true,
  human_actions_configured: true,
  worker_ready: true,
  profile_ref: "verification-profile:http-json-replay/0.1.0",
  provider: "local-http-fixture",
  testforge_ready: false as const,
  testforge_blockers: ["BACKEND_SOURCE_AND_REVISION_REQUIRED"],
  scope_description: "HTTP fixture only",
};
