import type { AdlcPlanTask, AdlcResolvedNodeSpec } from "@/types/adlc";

export const PLAN_TASK_POLICIES = {
  retry: { max_attempts: 2 },
  timeout_ms: 120000,
  approval: { gate_type: null },
  permissions: { mode: "PACKAGE_ALLOWLIST" },
  resources: {},
  runtime_overridable: [],
};

export function makeTask(
  id: string,
  name: string,
  dependencies: string[] = [],
): AdlcPlanTask {
  return {
    plan_task_id: id,
    source_workflow_stage_id: `stage-${id}`,
    resolved_node_spec_id: `spec-${id}`,
    resolved_node_digest: `sha256:${id}`,
    name,
    objective: `Complete ${name.toLowerCase()} for the user feature.`,
    task_type: "IMPLEMENTATION",
    dependency_task_ids: dependencies,
    input_bindings: [],
    inputs: {},
    expected_artifacts: ["source_patch"],
    effective_policies: PLAN_TASK_POLICIES,
    planning_rationale: "",
    priority: 50,
    metadata: {},
  };
}

export function makeSpec(id: string): AdlcResolvedNodeSpec {
  return {
    resolved_node_spec_id: `spec-${id}`,
    source_stage_id: `stage-${id}`,
    package_ref: { package_id: "coding-agent", version: "0.1.0" },
    kind: "AGENT",
    implementation: {
      adapter_type: "AGENT_PROVIDER",
      adapter_ref: "agent-provider:mock",
      entrypoint: "mock-task",
    },
    configuration: {},
    policies: PLAN_TASK_POLICIES,
    resolved_digest: `sha256:${id}`,
    execution_profile: null,
  };
}
