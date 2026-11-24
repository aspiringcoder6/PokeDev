export interface ContractReference {
  schema_ref: string;
  contract_id: string;
  revision: number;
  content_digest: string;
}

export interface SkilltreeNode {
  node_id: string;
  kind: "MILESTONE" | "TASK" | "DECISION";
  title: string;
  description: string;
  acceptance_criteria: {
    description: string;
    verification: "HUMAN" | "TEST" | "ARTIFACT";
    verifier_ref: string | null;
  }[];
}

export interface ContractRead {
  schema_version: "0.1";
  document: {
    schema_version: "0.1";
    document_type: string;
    schema_ref: string;
    producer_plugin: string;
    renderer_ref: string;
    contract_id: string;
    revision: number;
    title: string;
    scope: { objective: string; in_scope: string[]; out_of_scope: string[] };
    constraints: {
      read_only: boolean;
      allowed_paths: string[];
      forbidden_actions: string[];
    };
    supersedes: ContractReference | null;
    nodes: SkilltreeNode[];
    dependencies: {
      source_id: string;
      target_id: string;
      relation: "REQUIRES" | "CONTAINS";
    }[];
  };
  reference: ContractReference;
  binding: {
    workflow_run_id: string;
    task_run_id: string;
    session_id: string | null;
    request_id: string | null;
    attempt_id: string | null;
  };
  status: "DRAFT" | "VALIDATED" | "APPROVED";
  validation: {
    content_digest: string;
    passed: boolean;
    criteria_executed: false;
    checked_at: string;
    validator_ref: string;
    checks: { check_id: string; passed: boolean; summary: string }[];
  } | null;
  approval: {
    approval_id: string;
    reference: ContractReference;
    approved_by: string;
    approved_at: string;
    comment: string | null;
  } | null;
  created_at: string;
  authored_by: string;
  authored_via: "HUMAN" | "HARNESS_TOOL";
}

export interface ContractToolResult {
  schema_version: "0.1";
  contract: ContractRead;
  node_id: string | null;
  replayed: boolean;
}

export interface ContractViewerCapabilities {
  enabled: true;
  human_login_required: true;
  human_actions_configured: boolean;
  renderer_refs: string[];
  execution_policy_enforced: false;
}
