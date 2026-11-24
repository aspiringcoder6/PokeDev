import type { ContractRead, ContractReference } from "./contracts";

export type VerificationScope = { runId: string } | { sessionId: string };
export interface VerificationCase {
  case_id: string;
  pointer: string;
  expected: string | number | boolean | null;
  criterion_node_id: string;
  criterion_index: number;
}
export interface VerificationPlan {
  schema_version: "0.1";
  profile_ref: "verification-profile:json-fixture/0.1.0";
  plan_id: string;
  revision: 1;
  workflow_run_id: string;
  contract_reference: ContractReference;
  candidate: {
    source_task_id: string;
    source_attempt_id: string;
    source_session_id: string;
    artifact_id: string;
    artifact_digest: string;
    base_commit: string;
    project_id: string;
    source_ref: string;
    file: string;
    content_digest: string;
    encoding: "canonical-json";
  };
  cases: VerificationCase[];
  timeout_seconds: number;
}
export interface ExecutionReceipt {
  schema_version: "0.1";
  execution_id: string;
  plan_digest: string;
  candidate_digest: string;
  runner_ref: string;
  runner_digest: string;
  provider: "local-fixture" | "sandbox-kit";
  sandbox_session_id: string | null;
  image_ref: string | null;
  tests_run: number;
  completion_mode: "process-exit" | "durable-checkpoint";
  exit_code: number | null;
  observations: {
    case_id: string;
    pointer: string;
    found: boolean;
    observed: string | number | boolean | null;
  }[];
  started_at: string;
  completed_at: string;
}
export interface VerificationReport {
  schema_version: "0.1";
  plan_digest: string;
  receipt_digest: string;
  candidate_digest: string;
  verdict: "PASS" | "FAIL";
  comparator_ref: "validator:json-fixture/0.1.0";
  natural_language_enforced: false;
  contract_fully_verified: false;
  checks: {
    case_id: string;
    pointer: string;
    expected: string | number | boolean | null;
    observed: string | number | boolean | null;
    found: boolean;
    passed: boolean;
  }[];
}
export interface VerificationRead {
  plan: VerificationPlan;
  plan_digest: string;
  state:
    | "DRAFT"
    | "APPROVED"
    | "RUNNING"
    | "DISPATCH_UNCERTAIN"
    | "READY_FOR_SUBMISSION"
    | "SUBMITTED"
    | "NOT_VERIFIED";
  approved_by: string | null;
  approved_at: string | null;
  execution_id: string | null;
  receipt: ExecutionReceipt | null;
  report: VerificationReport | null;
  error_code: string | null;
  evidence_digest: string | null;
  created_at: string;
  submitted_at: string | null;
}
export interface VerificationCapabilities {
  enabled: boolean;
  human_actions_configured: boolean;
  worker_ready: boolean;
  profile_ref: string;
  scope_description: string;
  provider: string | null;
}
export interface VerificationCandidates {
  contracts: ContractRead[];
  patches: {
    source_task_id: string;
    artifact_id: string;
    task_name: string;
    files: string[];
  }[];
}
