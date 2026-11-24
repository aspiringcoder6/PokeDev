import {
  approveAdlcExecutionPlan,
  approveAdlcPlanProposal,
  approveAdlcRun,
  cancelAdlcRun,
  createAdlcExecutionPlan,
  createAdlcRun,
  createAdlcRunFromExecutionPlan,
  generateAdlcPlanProposal,
  getAdlcExecutionPlan,
  getAdlcHarnessResults,
  getAdlcHarnessSourcePatchPreview,
  getAdlcNodePackage,
  getAdlcPlanProposal,
  getAdlcRun,
  getAdlcRunControls,
  getAdlcRunEvents,
  getAdlcRunTasks,
  getAdlcSourcePatch,
  getAdlcTaskLoop,
  getAdlcTaskLoopRuntime,
  listAdlcNodePackages,
  listAdlcRuns,
  pauseAdlcRun,
  reconcileAdlcHarnessRun,
  regenerateAdlcExecutionPlan,
  regenerateAdlcPlanProposal,
  rejectAdlcPlanProposal,
  rejectAdlcRun,
  respondToAdlcHarnessInteraction,
  resumeAdlcRun,
  retryAdlcTask,
  validateAdlcExecutionPlan,
  validateAdlcPlanProposal,
} from "../adlc";
import { api } from "../api";

jest.mock("../api", () => ({
  api: {
    get: jest.fn(),
    post: jest.fn(),
  },
}));

jest.mock("@/customization/utils/urls", () => ({
  getBaseUrl: () => "/api/v1/",
}));

const mockApi = api as jest.Mocked<typeof api>;

describe("ADLC loop operator API", () => {
  beforeEach(() => jest.clearAllMocks());

  it("encodes both run and task IDs for checkpoint reads", async () => {
    mockApi.get.mockResolvedValue({ data: { iterations: [] } });
    await getAdlcTaskLoop("run/owner", "task/retry");
    expect(mockApi.get).toHaveBeenCalledWith(
      "/api/v1/adlc/runs/run%2Fowner/tasks/task%2Fretry/task-loop",
    );
    await getAdlcTaskLoopRuntime("run/owner", "task/retry");
    expect(mockApi.get).toHaveBeenLastCalledWith(
      "/api/v1/adlc/runs/run%2Fowner/tasks/task%2Fretry/task-loop-runtime",
    );
    await getAdlcRunControls("run/owner");
    expect(mockApi.get).toHaveBeenLastCalledWith(
      "/api/v1/adlc/runs/run%2Fowner/controls",
    );
  });

  it.each([
    ["pause", pauseAdlcRun],
    ["resume", resumeAdlcRun],
    ["cancel", cancelAdlcRun],
  ] as const)("uses the existing %s control", async (action, control) => {
    mockApi.post.mockResolvedValue({ data: { id: "run/owner" } });
    await control("run/owner");
    expect(mockApi.post).toHaveBeenCalledWith(
      `/api/v1/adlc/runs/run%2Fowner/${action}`,
    );
  });

  it("retains review feedback in the approval command", async () => {
    mockApi.post.mockResolvedValue({ data: {} });
    await rejectAdlcRun(
      "approval-1",
      "Fix the recurring failure in the next run.",
    );
    expect(mockApi.post).toHaveBeenCalledWith(
      "/api/v1/adlc/approvals/approval-1/reject",
      { comment: "Fix the recurring failure in the next run." },
    );
  });
});

describe("ADLC API", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("generates a proposal using the configured planner and optional decomposition limits", async () => {
    const proposal = { proposal_id: "proposal-1", status: "GENERATED" };
    mockApi.post.mockResolvedValue({ data: proposal });
    expect(await generateAdlcPlanProposal("flow/1", { maxTasks: 20 })).toEqual(
      proposal,
    );
    expect(mockApi.post).toHaveBeenCalledWith(
      "/api/v1/adlc/workflow-definitions/flow%2F1/plan-proposals",
      { maxTasks: 20 },
    );
  });

  it("returns the approved proposal and its executable plan together", async () => {
    const approval = {
      proposal: { proposal_id: "proposal-1", status: "APPROVED" },
      execution_plan: { execution_plan_id: "plan-1", status: "APPROVED" },
    };
    mockApi.post.mockResolvedValue({ data: approval });
    expect(await approveAdlcPlanProposal("proposal/1", "Reviewed")).toEqual(
      approval,
    );
    expect(mockApi.post).toHaveBeenCalledWith(
      "/api/v1/adlc/plan-proposals/proposal%2F1/approve",
      { comment: "Reviewed" },
    );
  });

  it("uses the proposal lifecycle endpoints with encoded identities", async () => {
    mockApi.get.mockResolvedValue({ data: {} });
    mockApi.post.mockResolvedValue({ data: {} });
    await getAdlcPlanProposal("proposal/1");
    await validateAdlcPlanProposal("proposal/1");
    await regenerateAdlcPlanProposal("proposal/1");
    await rejectAdlcPlanProposal("proposal/1");
    expect(mockApi.get).toHaveBeenCalledWith(
      "/api/v1/adlc/plan-proposals/proposal%2F1",
    );
    for (const command of ["validate", "regenerate", "reject"]) {
      expect(mockApi.post).toHaveBeenCalledWith(
        `/api/v1/adlc/plan-proposals/proposal%2F1/${command}`,
        {},
      );
    }
  });

  it("reads a prepared patch by scoped identity without submitting it", async () => {
    mockApi.get.mockResolvedValue({
      data: { format: "harness-git-diff-v1", files: [] },
    });
    await getAdlcHarnessSourcePatchPreview("run/1", "session/1", "artifact/1");
    expect(mockApi.get).toHaveBeenCalledWith(
      "/api/v1/adlc/runs/run%2F1/harness-sessions/session%2F1/artifacts/artifact%2F1",
    );
    expect(mockApi.post).not.toHaveBeenCalled();
  });

  it("starts a run from a flow id", async () => {
    mockApi.post.mockResolvedValue({ data: { id: "run-1" } });

    await createAdlcRun("flow-1");

    expect(mockApi.post).toHaveBeenCalledWith("/api/v1/adlc/runs", {
      flowId: "flow-1",
      executionMode: "LEGACY_FLOW",
    });
  });

  it("lists owner-scoped history with status, workflow and pagination", async () => {
    const page = { runs: [], total: 0, limit: 25, offset: 25 };
    mockApi.get.mockResolvedValue({ data: page });
    expect(
      await listAdlcRuns({
        status: "WAITING_APPROVAL",
        flowId: "flow-1",
        offset: 25,
      }),
    ).toEqual(page);
    expect(mockApi.get).toHaveBeenCalledWith("/api/v1/adlc/runs", {
      params: {
        status: "WAITING_APPROVAL",
        flow_id: "flow-1",
        limit: 25,
        offset: 25,
      },
    });
  });

  it("uses each run resource and command endpoint", async () => {
    mockApi.get.mockResolvedValue({ data: { events: [] } });
    mockApi.post.mockResolvedValue({ data: { id: "run-1" } });

    await getAdlcRun("run-1");
    await getAdlcRunTasks("run-1");
    await getAdlcRunEvents("run-1");
    await getAdlcSourcePatch("run-1", "artifact-1");
    await retryAdlcTask("task-1");
    await approveAdlcRun("approval-1");
    await rejectAdlcRun("approval-1");

    expect(mockApi.get).toHaveBeenNthCalledWith(1, "/api/v1/adlc/runs/run-1");
    expect(mockApi.get).toHaveBeenNthCalledWith(
      2,
      "/api/v1/adlc/runs/run-1/tasks",
    );
    expect(mockApi.get).toHaveBeenNthCalledWith(
      3,
      "/api/v1/adlc/runs/run-1/events",
    );
    expect(mockApi.get).toHaveBeenNthCalledWith(
      4,
      "/api/v1/adlc/runs/run-1/artifacts/artifact-1",
    );
    expect(mockApi.post).toHaveBeenNthCalledWith(
      1,
      "/api/v1/adlc/tasks/task-1/retry",
    );
    expect(mockApi.post).toHaveBeenNthCalledWith(
      2,
      "/api/v1/adlc/approvals/approval-1/approve",
      {},
    );
    expect(mockApi.post).toHaveBeenNthCalledWith(
      3,
      "/api/v1/adlc/approvals/approval-1/reject",
      {},
    );
  });

  it("sends a Harness interaction response with the wire-contract field name", async () => {
    mockApi.post.mockResolvedValue({ data: { status: "RUNNING" } });

    await respondToAdlcHarnessInteraction(
      "run/1",
      "session/1",
      "interaction/1",
      { action: "approve" },
    );

    expect(mockApi.post).toHaveBeenCalledWith(
      "/api/v1/adlc/runs/run%2F1/harness-sessions/session%2F1/interactions/interaction%2F1/responses",
      { schema_version: "0.1", response: { action: "approve" } },
    );
  });

  it("reads retained results from the ADLC archive endpoint", async () => {
    const results = [
      { attempt_id: "attempt-1", result: { output: { summary: "done" } } },
    ];
    mockApi.get.mockResolvedValue({ data: results });

    expect(await getAdlcHarnessResults("run/1")).toEqual(results);
    expect(mockApi.get).toHaveBeenCalledWith(
      "/api/v1/adlc/runs/run%2F1/harness-results",
    );
  });

  it("requests bounded Harness reconciliation for one run", async () => {
    mockApi.post.mockResolvedValue({
      data: {
        inspected: 1,
        recovered_results: 1,
        submitted_sessions: 0,
        unavailable_sessions: 0,
      },
    });

    await reconcileAdlcHarnessRun("run/1");

    expect(mockApi.post).toHaveBeenCalledWith(
      "/api/v1/adlc/runs/run%2F1/harness/reconcile",
      {},
    );
  });

  it("uses the blueprint package and planning endpoints", async () => {
    mockApi.get.mockResolvedValue({ data: [] });
    mockApi.post.mockResolvedValue({
      data: { execution_plan_id: "plan-1" },
    });

    await listAdlcNodePackages();
    await getAdlcNodePackage("coding-agent", "0.1.0");
    await createAdlcExecutionPlan("flow-1");
    await getAdlcExecutionPlan("plan-1");
    await regenerateAdlcExecutionPlan("plan-1", "regenerate-1");
    await validateAdlcExecutionPlan("plan-1");
    await approveAdlcExecutionPlan("plan-1");
    await createAdlcRunFromExecutionPlan("plan-1", "request-1");

    expect(mockApi.get).toHaveBeenNthCalledWith(
      1,
      "/api/v1/adlc/node-packages",
    );
    expect(mockApi.get).toHaveBeenNthCalledWith(
      2,
      "/api/v1/adlc/node-packages/coding-agent/versions/0.1.0",
    );
    expect(mockApi.post).toHaveBeenNthCalledWith(
      1,
      "/api/v1/adlc/workflow-definitions/flow-1/plans",
    );
    expect(mockApi.get).toHaveBeenNthCalledWith(
      3,
      "/api/v1/adlc/execution-plans/plan-1",
    );
    expect(mockApi.post).toHaveBeenNthCalledWith(
      2,
      "/api/v1/adlc/execution-plans/plan-1/regenerate",
      { idempotencyKey: "regenerate-1" },
    );
    expect(mockApi.post).toHaveBeenNthCalledWith(
      3,
      "/api/v1/adlc/execution-plans/plan-1/validate",
    );
    expect(mockApi.post).toHaveBeenNthCalledWith(
      4,
      "/api/v1/adlc/execution-plans/plan-1/approve",
      {},
    );
    expect(mockApi.post).toHaveBeenNthCalledWith(
      5,
      "/api/v1/adlc/execution-plans/plan-1/runs",
      { idempotencyKey: "request-1" },
    );
  });
});
