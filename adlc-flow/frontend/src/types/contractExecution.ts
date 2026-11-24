import type { ContractRead, ContractReference } from "./contracts";

export interface ExecutionCriterion {
  node_id: string;
  criterion_index: number;
  verifier_ref: string;
}
export interface ContractExecutionRead {
  binding: {
    schema_version: "0.1";
    scope: ContractRead["binding"];
    execution_plan_id: string;
    resolved_node_digest: string;
    reference: ContractReference;
    policy: {
      policy_ref: string;
      contract_reference: ContractReference;
      read_only: boolean;
      allowed_paths: string[];
      denied_actions: string[];
      criteria: ExecutionCriterion[];
      natural_language_enforced: false;
    };
    policy_digest: string;
    bound_at: string;
  };
  contract: ContractRead;
  proof: {
    reference: ContractReference;
    policy_digest: string;
    artifact_id: string;
    artifact_checksum: string;
    base_commit: string;
    changed_paths: string[];
    checks: (ExecutionCriterion & { passed: boolean })[];
    checked_at: string;
    criteria_executed: true;
    execution_policy_enforced: true;
    natural_language_enforced: false;
  } | null;
}
