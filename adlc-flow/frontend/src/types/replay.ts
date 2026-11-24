import type { ContractReference } from "./contracts";
import type {
  VerificationCase,
  VerificationPlan,
  VerificationScope,
} from "./verification";
export type ReplayScope = VerificationScope;
export interface ReplayCase extends VerificationCase {
  method: "GET";
  path: "/fixture";
  expected_status: number;
}
export interface ReplayPlan
  extends Omit<VerificationPlan, "profile_ref" | "cases"> {
  profile_ref: "verification-profile:http-json-replay/0.1.0";
  cases: ReplayCase[];
  suite_digest: string;
  config_digest: string;
  target_profile_ref: "target-profile:disposable-http-json/0.1.0";
  credential_ref: "credential-profile:ephemeral-fixture/0.1.0";
  risk_class: "read-only-non-production";
  heal: false;
  models: false;
  skip_policy: "no-required-skips";
}
export interface ReplayObservation {
  case_id: string;
  pointer: string;
  found: boolean;
  observed: string | number | boolean | null;
  http_status: number;
  response_digest: string;
  outcome: "PASS" | "FAIL";
}
export interface ReplayReceipt {
  schema_version: "0.1";
  execution_id: string;
  plan_digest: string;
  candidate_digest: string;
  suite_digest: string;
  config_digest: string;
  runner_ref: "runner:adlc-http-json-replay/0.1.0";
  runner_digest: string;
  provider: "local-http-fixture";
  target_profile_ref: ReplayPlan["target_profile_ref"];
  credential_ref: ReplayPlan["credential_ref"];
  target_instance_id: string;
  target_origin: string;
  target_released: true;
  heal: false;
  models_used: false;
  tests_run: number;
  completion_mode: "process-exit" | "durable-checkpoint";
  exit_code: number | null;
  observations: ReplayObservation[];
  junit_xml: string;
  junit_digest: string;
  started_at: string;
  completed_at: string;
}
export interface ReplayReport {
  schema_version: "0.1";
  plan_digest: string;
  receipt_digest: string;
  candidate_digest: string;
  suite_digest: string;
  config_digest: string;
  junit_digest: string;
  verdict: "PASS" | "FAIL";
  comparator_ref: "validator:http-json-replay/0.1.0";
  natural_language_enforced: false;
  contract_fully_verified: false;
  application_verified: false;
  required_cases: number;
  completed_cases: number;
  checks: {
    case_id: string;
    pointer: string;
    expected: ReplayCase["expected"];
    observed: ReplayCase["expected"];
    found: boolean;
    expected_status: number;
    observed_status: number;
    passed: boolean;
  }[];
}
export interface ReplayRead {
  plan: ReplayPlan;
  plan_digest: string;
  state:
    | "DRAFT"
    | "APPROVED"
    | "RUNNING"
    | "DISPATCH_UNCERTAIN"
    | "CANCEL_REQUESTED"
    | "CANCELLED"
    | "READY_FOR_SUBMISSION"
    | "SUBMITTED"
    | "NOT_VERIFIED";
  approved_by: string | null;
  approved_at: string | null;
  execution_id: string | null;
  receipt: ReplayReceipt | null;
  report: ReplayReport | null;
  error_code: string | null;
  evidence_digest: string | null;
  created_at: string;
  submitted_at: string | null;
  cancel_requested_by: string | null;
  cancel_requested_at: string | null;
  cancelled_at: string | null;
}
export interface ReplayCapabilities {
  enabled: boolean;
  human_actions_configured: boolean;
  worker_ready: boolean;
  profile_ref: string;
  provider: string | null;
  testforge_ready: false;
  testforge_blockers: string[];
  scope_description: string;
}
export interface CreateReplayInput {
  source_task_id: string;
  artifact_id: string;
  contract_reference: ContractReference;
  file: string;
  cases: ReplayCase[];
  timeout_seconds: number;
  idempotency_key: string;
}
