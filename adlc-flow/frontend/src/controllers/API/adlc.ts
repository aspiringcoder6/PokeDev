import { getBaseUrl } from "@/customization/utils/urls";
import type {
  AdlcExecutionPlan,
  AdlcHarnessInteractionReceipt,
  AdlcHarnessReconciliationReport,
  AdlcHarnessRunResult,
  AdlcHarnessRunSession,
  AdlcHarnessSession,
  AdlcHarnessSubmissionReceipt,
  AdlcLoopRuntimeView,
  AdlcNodePackage,
  AdlcPlanProposal,
  AdlcPlanValidationIssue,
  AdlcProposalApprovalResponse,
  AdlcRunEventsResponse,
  AdlcRunListResponse,
  AdlcRunOperatorControls,
  AdlcSourcePatch,
  AdlcTaskActivity,
  AdlcTaskAgentActivity,
  AdlcTaskRun,
  AdlcTaskLoopInspection,
  AdlcTaskSubtasks,
  AdlcWorkflowRun,
  WorkflowRunStatus,
} from "@/types/adlc";
import type { FlowDataType } from "@/types/flow";
import { api } from "./api";

const adlcUrl = `${getBaseUrl().replace(/\/?$/, "/")}adlc`;

export async function listAdlcRuns(
  options: {
    status?: WorkflowRunStatus;
    flowId?: string;
    limit?: number;
    offset?: number;
  } = {},
): Promise<AdlcRunListResponse> {
  const response = await api.get<AdlcRunListResponse>(`${adlcUrl}/runs`, {
    params: {
      status: options.status,
      flow_id: options.flowId,
      limit: options.limit ?? 25,
      offset: options.offset ?? 0,
    },
  });
  return response.data;
}

export async function createAdlcRun(flowId: string): Promise<AdlcWorkflowRun> {
  const response = await api.post<AdlcWorkflowRun>(`${adlcUrl}/runs`, {
    flowId,
    executionMode: "LEGACY_FLOW",
  });
  return response.data;
}

export async function getAdlcRun(runId: string): Promise<AdlcWorkflowRun> {
  const response = await api.get<AdlcWorkflowRun>(`${adlcUrl}/runs/${runId}`);
  return response.data;
}

export async function getAdlcRunTasks(runId: string): Promise<AdlcTaskRun[]> {
  const response = await api.get<AdlcTaskRun[]>(
    `${adlcUrl}/runs/${runId}/tasks`,
  );
  return response.data;
}

export async function getAdlcTaskActivity(
  runId: string,
  taskRunId: string,
): Promise<AdlcTaskActivity> {
  const response = await api.get<AdlcTaskActivity>(
    `${adlcUrl}/runs/${encodeURIComponent(runId)}/tasks/${encodeURIComponent(taskRunId)}/activity`,
  );
  return response.data;
}

export async function getAdlcTaskSubtasks(
  runId: string,
  taskRunId: string,
): Promise<AdlcTaskSubtasks> {
  const response = await api.get<AdlcTaskSubtasks>(
    `${adlcUrl}/runs/${encodeURIComponent(runId)}/tasks/${encodeURIComponent(taskRunId)}/subtasks`,
  );
  return response.data;
}

export async function getAdlcSubtaskActivity(
  runId: string,
  taskRunId: string,
  subtaskId: string,
): Promise<AdlcTaskAgentActivity> {
  const response = await api.get<AdlcTaskAgentActivity>(
    `${adlcUrl}/runs/${encodeURIComponent(runId)}/tasks/${encodeURIComponent(taskRunId)}/subtasks/${encodeURIComponent(subtaskId)}/activity`,
  );
  return response.data;
}

export async function getAdlcTaskLoop(
  runId: string,
  taskRunId: string,
): Promise<AdlcTaskLoopInspection> {
  const response = await api.get<AdlcTaskLoopInspection>(
    `${adlcUrl}/runs/${encodeURIComponent(runId)}/tasks/${encodeURIComponent(taskRunId)}/task-loop`,
  );
  return response.data;
}

export async function getAdlcRunControls(
  runId: string,
): Promise<AdlcRunOperatorControls> {
  const response = await api.get<AdlcRunOperatorControls>(
    `${adlcUrl}/runs/${encodeURIComponent(runId)}/controls`,
  );
  return response.data;
}

export async function getAdlcTaskLoopRuntime(
  runId: string,
  taskRunId: string,
): Promise<AdlcLoopRuntimeView> {
  const response = await api.get<AdlcLoopRuntimeView>(
    `${adlcUrl}/runs/${encodeURIComponent(runId)}/tasks/${encodeURIComponent(taskRunId)}/task-loop-runtime`,
  );
  return response.data;
}

export async function pauseAdlcRun(runId: string): Promise<AdlcWorkflowRun> {
  const response = await api.post<AdlcWorkflowRun>(
    `${adlcUrl}/runs/${encodeURIComponent(runId)}/pause`,
  );
  return response.data;
}

export async function resumeAdlcRun(runId: string): Promise<AdlcWorkflowRun> {
  const response = await api.post<AdlcWorkflowRun>(
    `${adlcUrl}/runs/${encodeURIComponent(runId)}/resume`,
  );
  return response.data;
}

export async function cancelAdlcRun(runId: string): Promise<AdlcWorkflowRun> {
  const response = await api.post<AdlcWorkflowRun>(
    `${adlcUrl}/runs/${encodeURIComponent(runId)}/cancel`,
  );
  return response.data;
}

export async function getAdlcRunEvents(
  runId: string,
): Promise<AdlcRunEventsResponse> {
  const response = await api.get<AdlcRunEventsResponse>(
    `${adlcUrl}/runs/${runId}/events`,
  );
  return response.data;
}

export async function getAdlcHarnessSessions(
  runId: string,
): Promise<AdlcHarnessRunSession[]> {
  const response = await api.get<AdlcHarnessRunSession[]>(
    `${adlcUrl}/runs/${encodeURIComponent(runId)}/harness-sessions`,
  );
  return response.data;
}

export async function getAdlcHarnessResults(
  runId: string,
): Promise<AdlcHarnessRunResult[]> {
  const response = await api.get<AdlcHarnessRunResult[]>(
    `${adlcUrl}/runs/${encodeURIComponent(runId)}/harness-results`,
  );
  return response.data;
}

export async function respondToAdlcHarnessInteraction(
  runId: string,
  sessionId: string,
  interactionId: string,
  response: Record<string, unknown>,
): Promise<AdlcHarnessInteractionReceipt> {
  const result = await api.post<AdlcHarnessInteractionReceipt>(
    `${adlcUrl}/runs/${encodeURIComponent(runId)}/harness-sessions/${encodeURIComponent(sessionId)}/interactions/${encodeURIComponent(interactionId)}/responses`,
    { schema_version: "0.1", response },
  );
  return result.data;
}

export async function submitAdlcHarnessSession(
  runId: string,
  sessionId: string,
): Promise<AdlcHarnessSubmissionReceipt> {
  const response = await api.post<AdlcHarnessSubmissionReceipt>(
    `${adlcUrl}/runs/${encodeURIComponent(runId)}/harness-sessions/${encodeURIComponent(sessionId)}/submit`,
    {},
  );
  return response.data;
}

export async function reconcileAdlcHarnessRun(
  runId: string,
): Promise<AdlcHarnessReconciliationReport> {
  const response = await api.post<AdlcHarnessReconciliationReport>(
    `${adlcUrl}/runs/${encodeURIComponent(runId)}/harness/reconcile`,
    {},
  );
  return response.data;
}

export async function reconcileAdlcContractVerification(
  runId: string,
  sessionId: string,
): Promise<AdlcHarnessSession> {
  const response = await api.post<AdlcHarnessSession>(
    `${adlcUrl}/runs/${encodeURIComponent(runId)}/harness-sessions/${encodeURIComponent(sessionId)}/reconcile-verification`,
    {},
  );
  return response.data;
}

export async function getAdlcSourcePatch(
  runId: string,
  artifactId: string,
): Promise<AdlcSourcePatch> {
  const response = await api.get<AdlcSourcePatch>(
    `${adlcUrl}/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId)}`,
  );
  return response.data;
}

export async function getAdlcHarnessSourcePatchPreview(
  runId: string,
  sessionId: string,
  artifactId: string,
): Promise<AdlcSourcePatch> {
  const response = await api.get<AdlcSourcePatch>(
    `${adlcUrl}/runs/${encodeURIComponent(runId)}/harness-sessions/${encodeURIComponent(sessionId)}/artifacts/${encodeURIComponent(artifactId)}`,
  );
  return response.data;
}

export async function retryAdlcTask(taskId: string): Promise<AdlcWorkflowRun> {
  const response = await api.post<AdlcWorkflowRun>(
    `${adlcUrl}/tasks/${taskId}/retry`,
  );
  return response.data;
}

export async function approveAdlcRun(
  approvalId: string,
  comment?: string,
): Promise<AdlcWorkflowRun> {
  const response = await api.post<AdlcWorkflowRun>(
    `${adlcUrl}/approvals/${approvalId}/approve`,
    comment ? { comment } : {},
  );
  return response.data;
}

export async function rejectAdlcRun(
  approvalId: string,
  comment?: string,
): Promise<AdlcWorkflowRun> {
  const response = await api.post<AdlcWorkflowRun>(
    `${adlcUrl}/approvals/${approvalId}/reject`,
    comment ? { comment } : {},
  );
  return response.data;
}

export async function listAdlcNodePackages(
  includeLegacy = false,
): Promise<AdlcNodePackage[]> {
  const response = await api.get<AdlcNodePackage[]>(
    `${adlcUrl}/node-packages${includeLegacy ? "?include_legacy=true" : ""}`,
  );
  return response.data;
}

export async function getAdlcNodePackage(
  packageId: string,
  version: string,
): Promise<AdlcNodePackage> {
  const response = await api.get<AdlcNodePackage>(
    `${adlcUrl}/node-packages/${encodeURIComponent(packageId)}/versions/${encodeURIComponent(version)}`,
  );
  return response.data;
}

export async function createAdlcExecutionPlan(
  workflowId: string,
): Promise<AdlcExecutionPlan> {
  const response = await api.post<AdlcExecutionPlan>(
    `${adlcUrl}/workflow-definitions/${workflowId}/plans`,
  );
  return response.data;
}

export interface AdlcPlanProposalOptions {
  mode?: "MOCK" | "LLM";
  maxTasks?: number;
  maxTasksPerStage?: number;
  maxDepth?: number;
}

export async function generateAdlcPlanProposal(
  workflowId: string,
  options: AdlcPlanProposalOptions = {},
): Promise<AdlcPlanProposal> {
  const response = await api.post<AdlcPlanProposal>(
    `${adlcUrl}/workflow-definitions/${encodeURIComponent(workflowId)}/plan-proposals`,
    options,
  );
  return response.data;
}

export async function getAdlcPlanProposal(
  proposalId: string,
): Promise<AdlcPlanProposal> {
  const response = await api.get<AdlcPlanProposal>(
    `${adlcUrl}/plan-proposals/${encodeURIComponent(proposalId)}`,
  );
  return response.data;
}

export async function validateAdlcPlanProposal(
  proposalId: string,
): Promise<AdlcPlanProposal> {
  const response = await api.post<AdlcPlanProposal>(
    `${adlcUrl}/plan-proposals/${encodeURIComponent(proposalId)}/validate`,
    {},
  );
  return response.data;
}

export async function approveAdlcPlanProposal(
  proposalId: string,
  comment?: string,
): Promise<AdlcProposalApprovalResponse> {
  const response = await api.post<AdlcProposalApprovalResponse>(
    `${adlcUrl}/plan-proposals/${encodeURIComponent(proposalId)}/approve`,
    comment ? { comment } : {},
  );
  return response.data;
}

export async function regenerateAdlcPlanProposal(
  proposalId: string,
  options: AdlcPlanProposalOptions = {},
): Promise<AdlcPlanProposal> {
  const response = await api.post<AdlcPlanProposal>(
    `${adlcUrl}/plan-proposals/${encodeURIComponent(proposalId)}/regenerate`,
    options,
  );
  return response.data;
}

export async function rejectAdlcPlanProposal(
  proposalId: string,
): Promise<AdlcPlanProposal> {
  const response = await api.post<AdlcPlanProposal>(
    `${adlcUrl}/plan-proposals/${encodeURIComponent(proposalId)}/reject`,
    {},
  );
  return response.data;
}

export async function getAdlcExecutionPlan(
  planId: string,
): Promise<AdlcExecutionPlan> {
  const response = await api.get<AdlcExecutionPlan>(
    `${adlcUrl}/execution-plans/${planId}`,
  );
  return response.data;
}

export async function regenerateAdlcExecutionPlan(
  planId: string,
  idempotencyKey: string,
): Promise<AdlcExecutionPlan> {
  const response = await api.post<AdlcExecutionPlan>(
    `${adlcUrl}/execution-plans/${planId}/regenerate`,
    { idempotencyKey },
  );
  return response.data;
}

export async function validateAdlcExecutionPlan(
  planId: string,
): Promise<AdlcExecutionPlan> {
  const response = await api.post<AdlcExecutionPlan>(
    `${adlcUrl}/execution-plans/${planId}/validate`,
  );
  return response.data;
}

export async function approveAdlcExecutionPlan(
  planId: string,
  comment?: string,
): Promise<AdlcExecutionPlan> {
  const response = await api.post<AdlcExecutionPlan>(
    `${adlcUrl}/execution-plans/${planId}/approve`,
    comment ? { comment } : {},
  );
  return response.data;
}

export async function createAdlcRunFromExecutionPlan(
  planId: string,
  idempotencyKey: string,
): Promise<AdlcWorkflowRun> {
  const response = await api.post<AdlcWorkflowRun>(
    `${adlcUrl}/execution-plans/${planId}/runs`,
    { idempotencyKey },
  );
  return response.data;
}

export interface AdlcBlueprintValidation {
  valid: boolean;
  issues: AdlcPlanValidationIssue[];
  warnings: AdlcPlanValidationIssue[];
  plan_status: string | null;
}

export interface AdlcBlueprintGenerationResult {
  flow_id: string;
  applied: boolean;
  stages: Array<{
    node_id: string;
    stage_id: string;
    name: string;
    stage_type: string;
    package: string;
  }>;
  edges: Array<{
    edge_id: string;
    source: string;
    target: string;
  }>;
  warnings: string[];
  dsh_session_id?: string | null;
  data: FlowDataType;
}

export async function generateAdlcBlueprint(
  flowId: string,
  requirement: string,
  instructions?: string,
): Promise<AdlcBlueprintGenerationResult> {
  const response = await api.post<AdlcBlueprintGenerationResult>(
    `${adlcUrl}/workflow-definitions/${flowId}/generate-blueprint`,
    { requirement, instructions: instructions || undefined },
    // A blueprint turn can run for minutes on the DSH server; never let a
    // client timeout abort it (axios 0 = no timeout).
    { timeout: 0 },
  );
  return response.data;
}

export async function validateAdlcBlueprint(
  flowId: string,
  deep = false,
): Promise<AdlcBlueprintValidation> {
  const response = await api.post<AdlcBlueprintValidation>(
    `${adlcUrl}/workflow-definitions/validate`,
    { flowId, deep },
  );
  return response.data;
}

export interface AdlcWorkflowDefinitionVersion {
  id: string;
  flow_id: string;
  version_number: number;
  status: string;
  description: string | null;
  created_by: string;
  created_at: string;
  data?: Record<string, unknown> | null;
}

export async function listAdlcDefinitionVersions(
  workflowId: string,
): Promise<AdlcWorkflowDefinitionVersion[]> {
  const response = await api.get<AdlcWorkflowDefinitionVersion[]>(
    `${adlcUrl}/workflow-definitions/${workflowId}/versions`,
  );
  return response.data;
}

export async function publishAdlcDefinitionVersion(
  workflowId: string,
  description?: string,
): Promise<AdlcWorkflowDefinitionVersion> {
  const response = await api.post<AdlcWorkflowDefinitionVersion>(
    `${adlcUrl}/workflow-definitions/${workflowId}/versions`,
    description ? { description } : {},
  );
  return response.data;
}

export async function rollbackAdlcDefinitionVersion(
  workflowId: string,
  versionNumber: number,
): Promise<AdlcWorkflowDefinitionVersion> {
  const response = await api.post<AdlcWorkflowDefinitionVersion>(
    `${adlcUrl}/workflow-definitions/${workflowId}/versions/${versionNumber}/rollback`,
  );
  return response.data;
}
