export type WorkflowRunStatus =
  | "CREATED"
  | "QUEUED"
  | "RUNNING"
  | "PAUSED"
  | "WAITING_APPROVAL"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELLED";

export type WorkflowExecutionMode =
  | "LEGACY_FLOW"
  | "EXECUTION_PLAN"
  | "MOCK_WORKFLOW";

// ----------------------------------------------------------------------
// Subtask types (plan orchestration)
// ----------------------------------------------------------------------

export type SubtaskStatus =
  | "pending"
  | "ready"
  | "running"
  | "succeeded"
  | "failed"
  | "skipped"
  | "cancelled";

export interface AdlcSubtaskRun {
  id: string;
  task_run_id: string;
  name: string;
  description?: string;
  status: SubtaskStatus;
  dependencies: string[];
  trigger: "on_success" | "on_failure" | "on_completed";
  started_at?: string | null;
  completed_at?: string | null;
  duration_ms?: number | null;
  result?: Record<string, unknown> | null;
  error?: { code: string; message: string } | null;
  attempt_id?: string | null;
}

export interface AdlcSubtaskSummary {
  total: number;
  succeeded: number;
  failed: number;
  running: number;
  pending: number;
  skipped: number;
}

export interface AdlcTaskSubtasks {
  task_run_id: string;
  subtasks: AdlcSubtaskRun[];
  summary: AdlcSubtaskSummary;
  is_mock?: boolean;
  note?: string | null;
}

export type TaskRunStatus =
  | "PENDING"
  | "READY"
  | "RUNNING"
  | "WAITING_APPROVAL"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELLED"
  | "SKIPPED";

export type ApprovalStatus =
  | "PENDING"
  | "APPROVED"
  | "REJECTED"
  | "CANCELLED"
  | "EXPIRED";

export interface AdlcPlanTaskTraceability {
  execution_plan_id: string;
  plan_task_id: string;
  source_workflow_stage_id: string;
  resolved_node_spec_id: string;
  package_id: string;
  package_version: string;
  package_content_digest: string;
  resolved_node_digest: string;
}

export interface AdlcTaskRun {
  id: string;
  workflow_run_id: string;
  key: string;
  name: string;
  task_type: string;
  status: TaskRunStatus;
  dependency_task_run_ids: string[];
  retry_count: number;
  executor?: { service: string; operation: string };
  request?: { constraints?: Record<string, unknown> | null } | null;
  result?: {
    output?: unknown;
    error?: { code: string; message: string } | null;
  } | null;
  artifacts?: AdlcArtifact[];
  plan_traceability?: AdlcPlanTaskTraceability;
  current_attempt_id?: string;
  started_at?: string;
  completed_at?: string;
}

export interface AdlcRunOperatorControls {
  workflow_run_id: string;
  can_pause: boolean;
  can_resume: boolean;
  can_cancel: boolean;
  pause_requested: boolean;
  pause_reason: string | null;
}

export interface AdlcLoopCheck {
  check_id: string;
  label: string;
  kind: "BEHAVIORAL" | "CONTRACT" | "MOCK";
  passed: boolean;
  exit_code: number | null;
  executed_tests: number | null;
  timed_out: boolean | null;
}

export interface AdlcLoopIteration {
  iteration: number;
  attempt_id: string;
  session_id: string | null;
  phase:
    | "RESERVED"
    | "AGENT_RUNNING"
    | "CANDIDATE_CAPTURED"
    | "VERIFIED"
    | "FINISHED";
  status: "IN_PROGRESS" | "PASSED" | "CHECKS_FAILED" | "FAILED" | "CANCELLED";
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  candidate_id: string | null;
  candidate_digest: string | null;
  parent_candidate_id: string | null;
  changed_paths: string[];
  patch_artifact_id: string | null;
  checks: AdlcLoopCheck[];
  total_tokens: number | null;
  cost: number | null;
  stop_reason: string | null;
}

export interface AdlcTaskLoopInspection {
  schema_version: "0.1";
  workflow_run_id: string;
  task_run_id: string;
  mode: "COMMAND" | "MOCK";
  history_source:
    | "CHECKPOINT"
    | "MEMORY"
    | "RUN_SNAPSHOT"
    | "UNAVAILABLE"
    | "NOT_STARTED";
  history_complete: boolean;
  unavailable_reason: string | null;
  spec_digest: string | null;
  max_iterations: number | null;
  max_duration_ms: number | null;
  max_total_tokens: number | null;
  max_total_cost: number | null;
  elapsed_ms: number | null;
  total_tokens: number | null;
  total_cost: number | null;
  current_candidate_id: string | null;
  current_candidate_digest: string | null;
  stopped: boolean;
  stop_reason: string | null;
  can_retry: boolean;
  recovery_available: boolean;
  iterations: AdlcLoopIteration[];
  failure_patterns: {
    check_id: string;
    label: string;
    kind: AdlcLoopCheck["kind"];
    iterations: number[];
  }[];
}

export interface AdlcLoopRuntimeView {
  schema_version: "0.1" | "0.2";
  workflow_run_id: string;
  task_run_id: string;
  binding_source: "CHECKPOINT" | "LEGACY" | "NOT_STARTED" | "UNAVAILABLE";
  protocol_ref:
    | "task-loop-runtime:iteration/0.1.0"
    | "task-loop-runtime:iteration/0.2.0"
    | null;
  execution_unified_with_harness: false;
  runtime: {
    protocol_ref:
      | "task-loop-runtime:iteration/0.1.0"
      | "task-loop-runtime:iteration/0.2.0";
    cost_reporting?: "UNAVAILABLE";
    runtime_ref: string;
    family: "OPENCODE" | "HARNESS" | "CUSTOM";
    provider_id: string;
    model_id: string;
    agent: string | null;
    modes: ("WORKSPACE_EDIT" | "FILE_PROPOSAL")[];
    fresh_sessions: true;
    reported_usage: true;
    cancellation: true;
  } | null;
}

export interface AdlcArtifact {
  artifact_id: string;
  workflow_run_id: string;
  task_run_id: string;
  kind: string;
  attempt_id?: string;
  name: string;
  media_type: string;
  uri: string;
  producer?: string;
  size_bytes: number;
  checksum: { algorithm: "SHA256"; value: string };
  expires_at?: string;
  metadata: Record<string, unknown>;
}

export interface AdlcTaskActivityEntry {
  seq: number;
  kind:
    | "prompt"
    | "text"
    | "reasoning"
    | "tool"
    | "patch"
    | "system"
    | "event"
    | string;
  title: string;
  detail?: string | null;
  status?: string | null;
  occurred_at?: string | null;
}

export interface AdlcTaskAgentActivity {
  source: string;
  session_id?: string | null;
  directory?: string | null;
  running: boolean;
  entries: AdlcTaskActivityEntry[];
  entries_total: number;
  note?: string | null;
  updated_at: string;
}

export interface AdlcTaskActivity {
  task_run_id: string;
  attempt_id?: string | null;
  status: string;
  executor_service: string;
  name: string;
  task_type: string;
  requirement?: string | null;
  objective?: string | null;
  output_summary?: string | null;
  output_outputs: Record<string, unknown>;
  error_code?: string | null;
  error_message?: string | null;
  metrics: Record<string, unknown>;
  result_metadata: Record<string, unknown>;
  started_at?: string | null;
  completed_at?: string | null;
  agent?: AdlcTaskAgentActivity | null;
}

export interface AdlcSourcePatch {
  artifact: AdlcArtifact;
  format: "opencode-vcs-diff-v1" | "harness-git-diff-v1";
  base_commit?: string | null;
  files: Array<{
    file: string;
    patch: string;
    additions: number;
    deletions: number;
    status?: string;
  }>;
  reported_files: string[];
}

export interface AdlcApprovalRequest {
  approval_request_id: string;
  workflow_run_id: string;
  task_run_id: string;
  status: ApprovalStatus;
  title: string;
  decision?: { comment?: string | null; effect?: string } | null;
  context: {
    summary: string;
    payload?: {
      reviewed_candidates?: {
        task_run_id: string;
        artifact_id: string;
        candidate_id: string | null;
        candidate_digest: string;
        iteration: number | null;
      }[];
      harness_workflow_review?: unknown;
    };
  };
}

export interface AdlcRunEvent {
  event_id: string;
  event_type: string;
  sequence: number;
  status: string;
  previous_status?: string;
  occurred_at: string;
  task_run_id?: string;
  approval_request_id?: string;
  attempt_id?: string;
  payload?: Record<string, unknown>;
}

export interface AdlcWorkflowRun {
  id: string;
  execution_mode: WorkflowExecutionMode;
  flow_id?: string;
  execution_plan_id?: string;
  name: string;
  status: WorkflowRunStatus;
  tasks: AdlcTaskRun[];
  approval_requests: AdlcApprovalRequest[];
  events: AdlcRunEvent[];
  created_at: string;
  completed_at?: string;
  run_number?: number | null;
}

export interface AdlcRunEventsResponse {
  workflow_run_id: string;
  events: AdlcRunEvent[];
}

export interface AdlcWorkflowRunSummary {
  id: string;
  name: string;
  execution_mode: WorkflowExecutionMode;
  flow_id?: string | null;
  execution_plan_id?: string | null;
  status: WorkflowRunStatus;
  task_count: number;
  completed_task_count: number;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

export interface AdlcRunListResponse {
  runs: AdlcWorkflowRunSummary[];
  total: number;
  limit: number;
  offset: number;
}

export type AdlcHarnessSessionStatus =
  | "ACCEPTED"
  | "PROVISIONING"
  | "RUNNING"
  | "WAITING_INTERACTION"
  | "VERIFYING"
  | "READY_FOR_SUBMISSION"
  | "DELIVERING"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELLED";

export interface AdlcHarnessJsonSchemaProperty {
  type?: "string" | "boolean" | "number" | "integer" | "array";
  title?: string;
  description?: string;
  enum?: Array<string | number | boolean>;
  items?: {
    type?: "string" | "boolean" | "number" | "integer";
    enum?: Array<string | number | boolean>;
  };
  default?: string | number | boolean | Array<string | number | boolean>;
}

export interface AdlcHarnessInteraction {
  interaction_id: string;
  kind: "APPROVAL" | "FORM";
  status: "PENDING" | "SUBMITTED" | "CANCELLED" | "EXPIRED";
  title: string;
  prompt: string;
  schema_ref?: string | null;
  input_schema: {
    type?: string;
    properties?: Record<string, AdlcHarnessJsonSchemaProperty>;
    required?: string[];
    additionalProperties?: boolean;
  };
  ui_schema: Record<string, unknown>;
  requested_at: string;
  resolved_at?: string | null;
  response?: Record<string, unknown> | null;
  metadata: Record<string, unknown>;
}

export interface AdlcHarnessSessionResult {
  schema_version?: "0.1";
  session_id?: string;
  status?: "SUCCEEDED" | "FAILED" | "CANCELLED";
  output?: unknown;
  artifacts?: AdlcArtifact[];
  verification_reports?: AdlcHarnessVerificationReport[];
  interaction_records?: AdlcHarnessInteraction[];
  started_at?: string;
  completed_at?: string;
  trace_ref?: string | null;
  error?: {
    code?: string;
    message?: string;
    retryable?: boolean;
  } | null;
  metadata?: {
    driver?: {
      profile_ref?: string;
      provider?: string;
      model?: string;
      dsh_session_id?: string;
      bridge_source?: string;
    };
    [key: string]: unknown;
  };
}

export interface AdlcHarnessVerificationReport {
  verifier_ref: string;
  status: "PASSED" | "FAILED" | "ERROR" | "SKIPPED";
  checks: Array<{
    check_id: string;
    status: "PASSED" | "FAILED" | "ERROR" | "SKIPPED";
    summary: string;
  }>;
  started_at: string;
  completed_at: string;
}

export interface AdlcHarnessRunResult {
  attempt_id: string;
  task_run_id: string;
  attempt_status: string;
  result: AdlcHarnessSessionResult;
  stored_at: string;
}

export interface AdlcHarnessSession {
  schema_version: "0.1";
  session_id: string;
  status: AdlcHarnessSessionStatus;
  submission_mode: "AUTO" | "MANUAL";
  interactions: AdlcHarnessInteraction[];
  events?: {
    event_type: string;
    payload?: Record<string, unknown>;
  }[];
  result?: AdlcHarnessSessionResult | null;
  delivery_id?: string | null;
  delivery_status?:
    | "PENDING"
    | "DELIVERING"
    | "DELIVERED"
    | "DEAD_LETTER"
    | null;
  created_at: string;
  updated_at: string;
}

export interface AdlcHarnessRunSession {
  attempt_id: string;
  task_run_id: string;
  attempt_status: string;
  session: AdlcHarnessSession;
}

export interface AdlcHarnessInteractionReceipt {
  schema_version: "0.1";
  session_id: string;
  interaction: AdlcHarnessInteraction;
  status: AdlcHarnessSessionStatus;
  replayed: boolean;
}

export interface AdlcHarnessSubmissionReceipt {
  schema_version: "0.1";
  session_id: string;
  status: AdlcHarnessSessionStatus;
  delivery_id: string;
  delivery_status: "PENDING" | "DELIVERING" | "DELIVERED" | "DEAD_LETTER";
  replayed: boolean;
}

export interface AdlcHarnessReconciliationReport {
  inspected: number;
  recovered_results: number;
  submitted_sessions: number;
  unavailable_sessions: number;
}

export type AdlcNodePackageKind =
  | "AGENT"
  | "TESTING"
  | "REVIEW"
  | "APPROVAL"
  | "ROUTER"
  | "JOIN";

export interface AdlcPackageReference {
  package_id: string;
  version: string;
  content_digest?: string;
}

export interface AdlcInterfaceSlot {
  name: string;
  schema_ref: string;
  required: boolean;
  multiple: boolean;
  description: string;
}

export interface AdlcNodePackage {
  schema_version: "0.1";
  package_id: string;
  version: string;
  content_digest: string;
  status: "DRAFT" | "PUBLISHED" | "DEPRECATED";
  lifecycle_status: "DRAFT" | "PUBLISHED" | "DEPRECATED";
  name: string;
  description: string;
  kind: AdlcNodePackageKind;
  interface: {
    inputs: AdlcInterfaceSlot[];
    outputs: AdlcInterfaceSlot[];
  };
  configuration_schema: {
    type?: string;
    required?: string[];
    properties?: Record<
      string,
      {
        type?: string | string[];
        enum?: unknown[];
        description?: string;
        minimum?: number;
        maximum?: number;
        minLength?: number;
        maxLength?: number;
      }
    >;
  };
  defaults: Record<string, unknown>;
  override_allowlist: string[];
  execution_profile: {
    provider_ref: string;
    model_ref: string;
    system_prompt_ref: string;
    memory_policy_ref: string;
    sandbox_policy_ref: string;
  } | null;
  default_policies: {
    retry: { max_attempts: number };
    timeout_ms: number;
    approval: { gate_type: string | null };
  };
  metadata: Record<string, unknown>;
}

export interface AdlcWorkflowMarker {
  document_type: "WORKFLOW_DEFINITION";
  schema_version: "0.1";
  workflow_definition_id: string;
  version: number;
  status: "DRAFT" | "PUBLISHED" | "ARCHIVED";
  default_policies: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

export interface AdlcWorkflowStage {
  document_type: "WORKFLOW_STAGE";
  schema_version: "0.1";
  stage_id: string;
  stage_type: string;
  name: string;
  objective: string;
  inputs: Record<string, unknown>;
  expected_outputs: string[];
  package_ref: AdlcPackageReference;
  configuration_overrides: Record<string, unknown>;
  execution_profile_overrides: Record<string, unknown>;
  policy_overrides: Record<string, unknown>;
  secret_refs: Record<string, string>;
  metadata: Record<string, unknown>;
}

export interface AdlcSlotBinding {
  source_output: string;
  target_input: string;
}

export interface AdlcWorkflowEdge {
  document_type: "WORKFLOW_EDGE";
  schema_version: "0.1";
  edge_id: string;
  condition: AdlcEdgeCondition;
  bindings: AdlcSlotBinding[];
  metadata: Record<string, unknown>;
}

export interface AdlcPlanValidationIssue {
  code: string;
  message: string;
  path?: string;
  details: Record<string, unknown>;
}

export interface AdlcNodePolicies {
  retry: { max_attempts: number };
  timeout_ms: number;
  approval: { gate_type: string | null };
  permissions: { mode: string };
  resources: Record<string, unknown>;
  runtime_overridable: string[];
}

export interface AdlcResolvedNodeSpec {
  resolved_node_spec_id: string;
  source_stage_id: string;
  package_ref: AdlcPackageReference;
  kind: AdlcNodePackageKind;
  implementation?: AdlcNodeImplementation;
  configuration: Record<string, unknown>;
  policies: AdlcNodePolicies;
  assigned_capability?: string;
  resolved_digest: string;
  execution_profile: {
    provider_ref: string;
    model_ref: string;
    memory_policy_ref: string;
    sandbox_policy_ref: string;
  } | null;
}

export interface AdlcPlanTask {
  plan_task_id: string;
  source_workflow_stage_id: string;
  resolved_node_spec_id: string;
  resolved_node_digest: string;
  name: string;
  objective: string;
  task_type: string;
  dependency_task_ids: string[];
  input_bindings: Array<{
    source_plan_task_id: string;
    source_output: string;
    target_input: string;
  }>;
  inputs: Record<string, unknown>;
  expected_artifacts: string[];
  assigned_capability?: string;
  required_environment?: string;
  effective_policies: AdlcNodePolicies;
  planning_rationale: string;
  priority: number;
  metadata: Record<string, unknown>;
}

export interface AdlcExecutionPlan {
  schema_version: "0.1";
  execution_plan_id: string;
  workflow_definition_id: string;
  workflow_definition_version: number;
  plan_version: number;
  status:
    | "DRAFT"
    | "GENERATED"
    | "VALIDATED"
    | "APPROVED"
    | "EXECUTING"
    | "INVALID"
    | "REJECTED"
    | "SUPERSEDED";
  validation_status: "NOT_VALIDATED" | "VALID" | "INVALID";
  validation_errors: AdlcPlanValidationIssue[];
  warnings: AdlcPlanValidationIssue[];
  assumptions: string[];
  approval_required: boolean;
  tasks: AdlcPlanTask[];
  resolved_node_specs: AdlcResolvedNodeSpec[];
  generated_by: string;
  generated_at: string;
  approved_by?: string;
  approved_at?: string;
  supersedes_plan_id?: string;
  metadata: Record<string, unknown>;
}

export interface AdlcServiceError {
  code: string;
  message: string;
  details?: {
    issues?: AdlcPlanValidationIssue[];
    [key: string]: unknown;
  };
}

export interface AdlcNodeImplementation {
  adapter_type:
    | "AGENT_PROVIDER"
    | "TESTING_PROVIDER"
    | "REVIEW_PROVIDER"
    | "CONTROL";
  adapter_ref: string;
  entrypoint: string;
}

export interface AdlcPlanProposal {
  schema_version: "0.1";
  proposal_id: string;
  workflow_definition_id: string;
  workflow_definition_version: number;
  proposal_version: number;
  status: AdlcProposalStatus;
  planner_mode: "MOCK" | "LLM";
  planner_version: string;
  tasks: AdlcProposedTask[];
  validation_errors: AdlcPlanValidationIssue[];
  warnings: AdlcPlanValidationIssue[];
  assumptions: string[];
  clarifications: string[];
  generated_by: string;
  generated_at: string;
  approved_by?: string;
  approved_at?: string;
  supersedes_proposal_id?: string;
  materialized_plan_id?: string;
  metadata: Record<string, unknown>;
}

export interface AdlcProposalApprovalResponse {
  proposal: AdlcPlanProposal;
  execution_plan: AdlcExecutionPlan;
}

export interface AdlcProposedTask {
  task_id: string;
  source_stage_id: string;
  name: string;
  description: string;
  objective: string;
  parent_task_id?: string;
  dependency_task_ids: string[];
  assigned_package: AdlcPackageReference;
  expected_outputs: string[];
  inputs: Record<string, unknown>;
  planning_rationale: string;
  priority: number;
  metadata: Record<string, unknown>;
}

export type AdlcEdgeCondition = "ON_SUCCESS" | "ON_FAILURE" | "ALWAYS";

export type AdlcProposalStatus =
  | "GENERATED"
  | "VALIDATED"
  | "REVISION_REQUIRED"
  | "REJECTED"
  | "APPROVED";
