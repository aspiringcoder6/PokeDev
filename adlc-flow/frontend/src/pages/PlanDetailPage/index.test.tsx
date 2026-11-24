import { act, render, screen } from "@testing-library/react";
import { useParams } from "react-router-dom";
import {
  approveAdlcExecutionPlan,
  createAdlcRunFromExecutionPlan,
  getAdlcExecutionPlan,
} from "@/controllers/API/adlc";
import {
  makeSpec,
  makeTask,
} from "@/features/adlc-blueprint/plan-task-graph-fixtures";
import type { AdlcExecutionPlan } from "@/types/adlc";
import PlanDetailPage from ".";

jest.mock("react-router-dom", () => ({
  ...jest.requireActual("react-router-dom"),
  useParams: jest.fn(),
}));
const navigateMock = jest.fn();
jest.mock("@/customization/hooks/use-custom-navigate", () => ({
  useCustomNavigate: () => navigateMock,
}));
jest.mock("@/components/common/genericIconComponent", () => () => null);
jest.mock("@/controllers/API/adlc", () => ({
  getAdlcExecutionPlan: jest.fn(),
  approveAdlcExecutionPlan: jest.fn(),
  createAdlcRunFromExecutionPlan: jest.fn(),
}));

function makePlan(
  overrides: Partial<AdlcExecutionPlan> = {},
): AdlcExecutionPlan {
  const tasks = [
    makeTask("analyze", "Analyze"),
    makeTask("backend", "Backend", ["analyze"]),
    makeTask("frontend", "Frontend", ["analyze"]),
    makeTask("testing", "Testing", ["backend", "frontend"]),
  ];
  const specs = [
    makeSpec("analyze"),
    makeSpec("backend"),
    makeSpec("frontend"),
    makeSpec("testing"),
  ];
  return {
    schema_version: "0.1",
    execution_plan_id: "plan-1",
    workflow_definition_id: "flow-1",
    workflow_definition_version: 1,
    plan_version: 1,
    status: "VALIDATED",
    validation_status: "VALID",
    validation_errors: [],
    warnings: [],
    assumptions: [],
    approval_required: true,
    tasks,
    resolved_node_specs: specs,
    generated_by: "user-1",
    generated_at: "2026-09-24T09:00:00Z",
    metadata: {},
    ...overrides,
  };
}

describe("PlanDetailPage", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (useParams as jest.Mock).mockReturnValue({ planId: "plan-1" });
    (getAdlcExecutionPlan as jest.Mock).mockResolvedValue(makePlan());
  });

  it("renders the plan header, dependency graph, and task metadata", async () => {
    render(<PlanDetailPage />);

    expect(await screen.findByText("Execution Plan")).toBeVisible();
    expect(screen.getByText(/Plan plan-1/)).toBeVisible();
    expect(screen.getByText("Task dependency graph")).toBeVisible();
    expect(screen.getAllByTestId("plan-task-node")).toHaveLength(4);
    expect(screen.getAllByTestId("plan-task-edge")).toHaveLength(4);
    expect(screen.getAllByText("Backend")).toHaveLength(2);
    expect(
      screen.getAllByText(/agent-provider:mock \(mock-task\)/),
    ).toHaveLength(4);
    expect(screen.getAllByText(/Depends on:/)).toHaveLength(4);
    expect(
      screen.getAllByText(/max 2 attempt\(s\) · 120000 ms timeout/),
    ).toHaveLength(4);
    expect(
      screen.queryByRole("button", { name: /Run This Plan/ }),
    ).not.toBeInTheDocument();
  });

  it("displays historical plans that do not include executor metadata", async () => {
    const historical = makePlan();
    historical.resolved_node_specs = historical.resolved_node_specs.map(
      ({ implementation, ...spec }) => spec,
    );
    (getAdlcExecutionPlan as jest.Mock).mockResolvedValue(historical);
    render(<PlanDetailPage />);

    expect(await screen.findByText("Execution Plan")).toBeVisible();
    expect(screen.getAllByText(/Executor unavailable/)).toHaveLength(4);
    expect(screen.getAllByTestId("plan-task-node")).toHaveLength(4);
  });

  it("offers Accept plan while validation-required and hides Run", async () => {
    render(<PlanDetailPage />);

    const accept = await screen.findByRole("button", { name: "Accept plan" });
    expect(accept).toBeEnabled();
    expect(
      screen.queryByRole("button", { name: /Run This Plan/ }),
    ).not.toBeInTheDocument();

    (approveAdlcExecutionPlan as jest.Mock).mockResolvedValue(
      makePlan({ status: "APPROVED" }),
    );
    await act(async () => {
      accept.click();
    });

    expect(approveAdlcExecutionPlan).toHaveBeenCalledWith("plan-1");
    // Run button appears immediately after approval — no waiting for
    // subtask pre-generation. Subtasks are generated on-demand when
    // each task starts executing.
    const run = await screen.findByRole("button", { name: /Run This Plan/ });
    expect(run).toBeEnabled();
  });

  it("runs an approved plan and navigates to the new run", async () => {
    (getAdlcExecutionPlan as jest.Mock).mockResolvedValue(
      makePlan({ status: "APPROVED", approval_required: true }),
    );
    (createAdlcRunFromExecutionPlan as jest.Mock).mockResolvedValue({
      id: "run-9",
    });

    render(<PlanDetailPage />);

    const run = await screen.findByRole("button", { name: /Run This Plan/ });
    await act(async () => {
      run.click();
    });

    expect(createAdlcRunFromExecutionPlan).toHaveBeenCalledWith(
      "plan-1",
      expect.any(String),
    );
    expect(navigateMock).toHaveBeenCalledWith("/runs/run-9");
  });

  it("shows the empty state for an invalid plan without tasks", async () => {
    (getAdlcExecutionPlan as jest.Mock).mockResolvedValue(
      makePlan({
        status: "INVALID",
        validation_status: "INVALID",
        tasks: [],
        resolved_node_specs: [],
      }),
    );

    render(<PlanDetailPage />);

    expect(await screen.findByText(/no executable tasks/)).toBeVisible();
    expect(screen.queryByTestId("plan-task-node")).not.toBeInTheDocument();
  });

  it("links to the run history filtered by this plan", async () => {
    render(<PlanDetailPage />);

    const viewRuns = await screen.findByRole("button", {
      name: "View runs",
    });
    await act(async () => {
      viewRuns.click();
    });

    expect(navigateMock).toHaveBeenCalledWith("/runs/?planId=plan-1");
  });

  it("surfaces the load error with a way back", async () => {
    (getAdlcExecutionPlan as jest.Mock).mockRejectedValue(
      new Error("plan not found"),
    );

    render(<PlanDetailPage />);

    expect(await screen.findByText("plan not found")).toBeVisible();
  });
});
