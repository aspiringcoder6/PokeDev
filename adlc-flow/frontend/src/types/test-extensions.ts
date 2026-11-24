import type { ContractReference } from "./contracts";
import type { ReplayCase } from "./replay";
export interface ProposalReference {
  proposal_id: string;
  revision: number;
  document_digest: string;
}
export interface TestPermissions {
  target_profile_ref: "target-profile:disposable-http-json/0.1.0";
  credential_ref: "credential-profile:ephemeral-fixture/0.1.0";
  environment: "non-production";
  data_scope: "synthetic-run-owned-only";
  allowed_methods: ["GET"];
  allowed_paths: ["/fixture"];
  network_scope: "allocated-loopback-target-only";
  cleanup: "release-owned-target";
  cancellation: "confirmed-worker-cancel";
  max_duration_seconds: number;
}
export interface PerformanceBudget {
  virtual_users: number;
  duration_seconds: number;
  requests_per_second: number;
  max_requests: number;
  p95_latency_ms_max: number;
  failed_requests_max: number;
}
export interface TestProposal {
  schema_version: "0.1";
  profile_ref: "test-extension-profile:proposals/0.1.0";
  proposal_id: string;
  revision: number;
  parent_reference: ProposalReference | null;
  source: {
    workflow_run_id: string;
    plan_id: string;
    plan_digest: string;
    suite_digest: string;
    candidate_digest: string;
    project_id: string;
    source_session_id: string;
    contract_reference: ContractReference;
  };
  authoring_session_id: string | null;
  kind: "suite-revision" | "exploration" | "performance";
  title: string;
  rationale: string;
  cases: ReplayCase[];
  permissions: TestPermissions | null;
  performance: PerformanceBudget | null;
  heal: false;
  models_used: false;
  executable: false;
  verification_evidence: false;
}
export interface ProposalRead {
  document: TestProposal;
  reference: ProposalReference;
  state: "DRAFT" | "READY_FOR_REVIEW" | "APPROVED" | "MATERIALIZED";
  created_at: string;
  approved_by: string | null;
  approved_at: string | null;
  materialized_plan_id: string | null;
}
export type ProposalCommand =
  | {
      operation: "init";
      source_plan_id: string;
      kind: TestProposal["kind"];
      title: string;
      rationale: string;
      parent_reference?: ProposalReference;
      idempotency_key: string;
    }
  | {
      operation: "upsert_case";
      reference: ProposalReference;
      case: ReplayCase;
      idempotency_key: string;
    }
  | {
      operation: "remove_case";
      reference: ProposalReference;
      case_id: string;
      idempotency_key: string;
    }
  | {
      operation: "set_permissions";
      reference: ProposalReference;
      permissions: TestPermissions;
      performance: PerformanceBudget | null;
      idempotency_key: string;
    }
  | { operation: "get_status"; proposal_id: string }
  | {
      operation: "validate";
      reference: ProposalReference;
      idempotency_key: string;
    };
export interface ExtensionCapabilities {
  schema_version: "0.1";
  profile_ref: TestProposal["profile_ref"];
  enabled: boolean;
  human_actions_configured: boolean;
  exploration_ready: false;
  performance_ready: false;
  screenshot_capture_ready: false;
  blockers: string[];
}
export interface ScreenshotRead {
  schema_version: "0.1";
  profile_ref: "evidence-profile:supplementary-png/0.1.0";
  attachment_id: string;
  workflow_run_id: string;
  plan_id: string;
  plan_digest: string;
  execution_id: string;
  candidate_digest: string;
  case_id: string;
  caption: string;
  authority: "SUPPLEMENTARY_UNTRUSTED";
  affects_verdict: false;
  capture_provenance_verified: false;
  uploaded_by: string;
  uploaded_at: string;
  input_digest: string;
  content_digest: string;
  media_type: "image/png";
  byte_size: number;
  width: number;
  height: number;
  case_evidence_digest: string;
}
