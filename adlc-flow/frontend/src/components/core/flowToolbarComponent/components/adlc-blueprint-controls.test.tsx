import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { usePermissions } from "@/contexts/permissionsContext";
import {
  approveAdlcPlanProposal,
  createAdlcRunFromExecutionPlan,
  generateAdlcBlueprint,
  generateAdlcPlanProposal,
  rejectAdlcPlanProposal,
  validateAdlcPlanProposal,
} from "@/controllers/API/adlc";
import {
  makeSpec,
  makeTask,
} from "@/features/adlc-blueprint/plan-task-graph-fixtures";
import useAdlcBlueprintStore from "@/stores/adlcBlueprintStore";
import type { AdlcExecutionPlan, AdlcPlanProposal } from "@/types/adlc";
import AdlcBlueprintControls from "./adlc-blueprint-controls";

const mockSaveFlow = jest.fn();
const mockNavigate = jest.fn();
const mockApplyFlowToCanvas = jest.fn();

jest.mock("@/components/common/genericIconComponent", () => () => null);
jest.mock("@/contexts/permissionsContext", () => ({
  usePermissions: jest.fn(),
}));
jest.mock("@/controllers/API/adlc", () => ({
  approveAdlcExecutionPlan: jest.fn(),
  createAdlcExecutionPlan: jest.fn(),
  generateAdlcBlueprint: jest.fn(),
  createAdlcRunFromExecutionPlan: jest.fn(),
  regenerateAdlcExecutionPlan: jest.fn(),
  generateAdlcPlanProposal: jest.fn(),
  approveAdlcPlanProposal: jest.fn(),
  validateAdlcPlanProposal: jest.fn(),
  regenerateAdlcPlanProposal: jest.fn(),
  rejectAdlcPlanProposal: jest.fn(),
}));
jest.mock("@/customization/hooks/use-custom-navigate", () => ({
  useCustomNavigate: () => mockNavigate,
}));
jest.mock("@/features/adlc-blueprint/stage-editor-dialog", () => () => null);
jest.mock("@/hooks/adlc/use-adlc-node-packages", () => ({
  useAdlcNodePackages: () => ({ data: [], isLoading: false }),
}));
jest.mock("@/hooks/flows/use-save-flow", () => ({
  __esModule: true,
  default: () => mockSaveFlow,
}));
jest.mock("@/hooks/flows/use-apply-flow-to-canvas", () => ({
  __esModule: true,
  default: () => mockApplyFlowToCanvas,
}));
jest.mock("@/stores/flowStore", () => {
  const { create } = jest.requireActual("zustand");
  return {
    __esModule: true,
    default: create(() => ({
      currentFlow: {
        locked: false,
        data: {
          adlc: { document_type: "WORKFLOW_DEFINITION", schema_version: "0.1" },
        },
      },
      nodes: [],
      edges: [],
      setCurrentFlow: jest.fn(),
      setNodes: jest.fn(),
      reactFlowInstance: null,
    })),
  };
});
jest.mock("@/stores/flowsManagerStore", () => {
  const { create } = jest.requireActual("zustand");
  return {
    __esModule: true,
    default: create(() => ({
      currentFlowId: "flow-1",
      takeSnapshot: jest.fn(),
    })),
  };
});

function makeProposal(
  overrides: Partial<AdlcPlanProposal> = {},
): AdlcPlanProposal {
  return {
    schema_version: "0.1",
    proposal_id: "proposal-1",
    workflow_definition_id: "flow-1",
    workflow_definition_version: 1,
    proposal_version: 1,
    status: "GENERATED",
    planner_mode: "MOCK",
    planner_version: "0.1",
    tasks: [
      {
        task_id: "implement",
        source_stage_id: "stage-1",
        name: "Implement feature",
        description: "Implement the requested feature",
        objective: "Complete the implementation",
        dependency_task_ids: [],
        assigned_package: { package_id: "coding-agent", version: "0.1.0" },
        expected_outputs: ["source_patch"],
        inputs: {},
        planning_rationale: "Implementation stage",
        priority: 50,
        metadata: {},
      },
    ],
    validation_errors: [],
    warnings: [],
    assumptions: [],
    clarifications: [],
    generated_by: "owner",
    generated_at: "2026-10-08T00:00:00Z",
    metadata: {},
    ...overrides,
  };
}

function makePlan(): AdlcExecutionPlan {
  return {
    schema_version: "0.1",
    execution_plan_id: "plan-1",
    workflow_definition_id: "flow-1",
    workflow_definition_version: 1,
    plan_version: 1,
    status: "APPROVED",
    validation_status: "VALID",
    validation_errors: [],
    warnings: [],
    assumptions: [],
    approval_required: true,
    tasks: [makeTask("implement", "Implement feature")],
    resolved_node_specs: [makeSpec("implement")],
    generated_by: "owner",
    generated_at: "2026-10-08T00:00:00Z",
    metadata: {},
  };
}

describe("blueprint proposal integration", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useAdlcBlueprintStore.getState().clearValidation();
    useAdlcBlueprintStore.setState({
      requestDialogOpen: false,
      dismissedRequestFlowIds: [],
    });
    (usePermissions as jest.Mock).mockReturnValue({ can: () => true });
    mockSaveFlow.mockResolvedValue(undefined);
    (generateAdlcPlanProposal as jest.Mock).mockResolvedValue(makeProposal());
  });

  it("keeps AI generation and plan actions available in the compact toolbar", () => {
    render(<AdlcBlueprintControls compact />);
    expect(screen.getByTestId("adlc-blueprint-request-button")).toBeEnabled();
    expect(screen.getByTestId("preview-adlc-plan-button")).toHaveTextContent(
      "Review plan",
    );
    expect(screen.getByTestId("propose-adlc-tasks-button")).toBeEnabled();
    expect(
      screen.queryByTestId("adlc-execution-mode-badge"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("add-adlc-stage-button"),
    ).not.toBeInTheDocument();
  });

  it("applies an AI blueprint without starting a run or retaining a stale plan", async () => {
    const data = { nodes: [], edges: [], viewport: { x: 0, y: 0, zoom: 1 } };
    (generateAdlcBlueprint as jest.Mock).mockResolvedValue({
      flow_id: "flow-1",
      applied: true,
      stages: [{ name: "Implement" }],
      edges: [],
      warnings: [],
      data,
    });
    useAdlcBlueprintStore.setState({ plan: makePlan() });
    render(<AdlcBlueprintControls />);
    fireEvent.click(screen.getByTestId("adlc-blueprint-request-button"));
    fireEvent.change(screen.getByLabelText("Workflow requirement"), {
      target: { value: "Build a todo app." },
    });
    fireEvent.click(screen.getByTestId("adlc-blueprint-request-submit"));
    await waitFor(() => {
      expect(mockApplyFlowToCanvas).toHaveBeenCalledWith(
        expect.objectContaining({ data }),
      );
    });
    expect(generateAdlcBlueprint).toHaveBeenCalledWith(
      "flow-1",
      "Build a todo app.",
      undefined,
    );
    expect(useAdlcBlueprintStore.getState().plan).toBeNull();
    expect(useAdlcBlueprintStore.getState().requestDialogOpen).toBe(false);
    expect(createAdlcRunFromExecutionPlan).not.toHaveBeenCalled();
  });

  it("saves the blueprint, validates a proposal, and starts its approved plan", async () => {
    (validateAdlcPlanProposal as jest.Mock).mockResolvedValue(
      makeProposal({ status: "VALIDATED" }),
    );
    (approveAdlcPlanProposal as jest.Mock).mockResolvedValue({
      proposal: makeProposal({
        status: "APPROVED",
        materialized_plan_id: "plan-1",
      }),
      execution_plan: makePlan(),
    });
    (createAdlcRunFromExecutionPlan as jest.Mock).mockResolvedValue({
      id: "run-1",
    });
    render(<AdlcBlueprintControls />);

    fireEvent.click(screen.getByTestId("propose-adlc-tasks-button"));
    expect(await screen.findByTestId("plan-proposal-dialog")).toBeVisible();
    expect(mockSaveFlow.mock.invocationCallOrder[0]).toBeLessThan(
      (generateAdlcPlanProposal as jest.Mock).mock.invocationCallOrder[0],
    );
    expect(generateAdlcPlanProposal).toHaveBeenCalledWith("flow-1");
    expect(screen.getByTestId("approve-proposal-button")).toBeDisabled();
    expect(createAdlcRunFromExecutionPlan).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("validate-proposal-button"));
    await waitFor(() => {
      expect(screen.getByTestId("approve-proposal-button")).toBeEnabled();
    });
    fireEvent.click(screen.getByTestId("approve-proposal-button"));
    expect(await screen.findByText("ADLC Plan Preview")).toBeVisible();
    expect(
      screen.queryByTestId("plan-proposal-dialog"),
    ).not.toBeInTheDocument();
    expect(approveAdlcPlanProposal).toHaveBeenCalledWith("proposal-1");
    expect(useAdlcBlueprintStore.getState().plan?.execution_plan_id).toBe(
      "plan-1",
    );
    expect(createAdlcRunFromExecutionPlan).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Run This Plan" }));
    await waitFor(() => {
      expect(createAdlcRunFromExecutionPlan).toHaveBeenCalledWith(
        "plan-1",
        expect.any(String),
      );
      expect(mockNavigate).toHaveBeenCalledWith("/runs/run-1");
    });
  });

  it("keeps invalid proposals out of the execution pipeline", async () => {
    (validateAdlcPlanProposal as jest.Mock).mockResolvedValue(
      makeProposal({
        status: "REVISION_REQUIRED",
        validation_errors: [
          { code: "EMPTY_PROPOSAL", message: "No runnable tasks", details: {} },
        ],
      }),
    );
    render(<AdlcBlueprintControls />);
    fireEvent.click(screen.getByTestId("propose-adlc-tasks-button"));
    fireEvent.click(await screen.findByTestId("validate-proposal-button"));
    expect(await screen.findByText(/No runnable tasks/)).toBeVisible();
    expect(screen.getByTestId("approve-proposal-button")).toBeDisabled();
    expect(approveAdlcPlanProposal).not.toHaveBeenCalled();
    expect(createAdlcRunFromExecutionPlan).not.toHaveBeenCalled();
  });

  it("requires execute permission before approving a valid proposal", async () => {
    (usePermissions as jest.Mock).mockReturnValue({
      can: (_flowId: string, action: string) => action !== "execute",
    });
    (generateAdlcPlanProposal as jest.Mock).mockResolvedValue(
      makeProposal({ status: "VALIDATED" }),
    );
    render(<AdlcBlueprintControls />);
    fireEvent.click(screen.getByTestId("propose-adlc-tasks-button"));
    expect(await screen.findByTestId("approve-proposal-button")).toBeDisabled();
    expect(screen.getByTestId("reject-proposal-button")).toBeDisabled();
    expect(approveAdlcPlanProposal).not.toHaveBeenCalled();
  });

  it("rejects a proposal without creating an execution plan", async () => {
    (rejectAdlcPlanProposal as jest.Mock).mockResolvedValue(
      makeProposal({ status: "REJECTED" }),
    );
    render(<AdlcBlueprintControls />);
    fireEvent.click(screen.getByTestId("propose-adlc-tasks-button"));
    fireEvent.click(await screen.findByTestId("reject-proposal-button"));
    await waitFor(() => {
      expect(useAdlcBlueprintStore.getState().proposal?.status).toBe(
        "REJECTED",
      );
    });
    expect(screen.getByTestId("regenerate-proposal-button")).toBeDisabled();
    expect(screen.getByTestId("approve-proposal-button")).toBeDisabled();
    expect(useAdlcBlueprintStore.getState().plan).toBeNull();
  });
});
