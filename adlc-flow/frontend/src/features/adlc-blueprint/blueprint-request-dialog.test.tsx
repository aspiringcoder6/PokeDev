import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockGenerateAdlcBlueprint = jest.fn();

jest.mock("@/controllers/API/adlc", () => ({
  __esModule: true,
  generateAdlcBlueprint: (...args: unknown[]) =>
    mockGenerateAdlcBlueprint(...args),
}));

jest.mock("@/components/common/genericIconComponent", () => ({
  __esModule: true,
  default: ({ name, className }: { name: string; className?: string }) => (
    <span data-testid={`icon-${name}`} className={className ?? ""} />
  ),
}));

import BlueprintRequestDialog from "./blueprint-request-dialog";

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

const generationResult = {
  flow_id: "flow-1",
  applied: true,
  stages: [
    {
      node_id: "adlc-stage-1",
      stage_id: "stage-1",
      name: "Implement",
      stage_type: "IMPLEMENTATION",
      package: "coding-agent@0.1.0",
    },
  ],
  edges: [],
  warnings: [],
  data: { nodes: [], edges: [], viewport: { x: 0, y: 0, zoom: 1 } },
};

const renderDialog = (
  overrides: Partial<Parameters<typeof BlueprintRequestDialog>[0]> = {},
) => {
  const props = {
    open: true,
    onOpenChange: jest.fn(),
    flowId: "flow-1",
    hasStages: false,
    onGenerated: jest.fn(),
    ...overrides,
  };
  render(<BlueprintRequestDialog {...props} />);
  return props;
};

beforeEach(() => {
  jest.clearAllMocks();
  mockGenerateAdlcBlueprint.mockResolvedValue(generationResult);
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("BlueprintRequestDialog — rendering", () => {
  it("renders the requirement textarea, close (X) control and submit button", () => {
    renderDialog();

    expect(
      screen.getByTestId("adlc-blueprint-request-dialog"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Workflow requirement")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
    expect(
      screen.getByTestId("adlc-blueprint-request-submit"),
    ).toBeInTheDocument();
  });

  it("starts with the submit button disabled until a requirement is typed", async () => {
    const user = userEvent.setup();
    renderDialog();

    const submit = screen.getByTestId("adlc-blueprint-request-submit");
    expect(submit).toBeDisabled();

    await user.type(
      screen.getByLabelText("Workflow requirement"),
      "Build a todo app.",
    );
    expect(submit).toBeEnabled();
  });

  it("labels the dialog for modify mode when the flow already has stages", () => {
    renderDialog({ hasStages: true });

    expect(screen.getByText("Request a blueprint change")).toBeInTheDocument();
    expect(screen.getByText("Requested change")).toBeInTheDocument();
  });
});

describe("BlueprintRequestDialog — pre-filled defaults", () => {
  it("pre-fills the requirement textarea when defaultRequirement is provided", () => {
    renderDialog({
      defaultRequirement: "Create a heart app with click handler.",
    });

    const textarea = screen.getByLabelText(
      "Workflow requirement",
    ) as HTMLTextAreaElement;
    expect(textarea.value).toBe("Create a heart app with click handler.");
  });

  it("pre-fills the instructions textarea when defaultInstructions is provided", () => {
    renderDialog({
      defaultRequirement: "Build something.",
      defaultInstructions: "Keep it minimal.",
    });

    const requirement = screen.getByLabelText(
      "Workflow requirement",
    ) as HTMLTextAreaElement;
    const instructions = screen.getByLabelText(/extra instructions/i) as HTMLTextAreaElement;
    expect(requirement.value).toBe("Build something.");
    expect(instructions.value).toBe("Keep it minimal.");
  });

  it("enables the submit button immediately when a default is provided", () => {
    renderDialog({
      defaultRequirement: "Create a heart app.",
    });

    expect(screen.getByTestId("adlc-blueprint-request-submit")).toBeEnabled();
  });

  it("lets the user edit the pre-filled text before submitting", async () => {
    const user = userEvent.setup();
    renderDialog({
      defaultRequirement: "Original requirement.",
    });

    const textarea = screen.getByLabelText(
      "Workflow requirement",
    ) as HTMLTextAreaElement;
    await user.clear(textarea);
    await user.type(textarea, "Edited requirement.");

    expect(textarea.value).toBe("Edited requirement.");
  });

  it("submits the edited (not the original) requirement", async () => {
    const user = userEvent.setup();
    renderDialog({
      defaultRequirement: "Original requirement.",
    });

    const textarea = screen.getByLabelText(
      "Workflow requirement",
    ) as HTMLTextAreaElement;
    await user.clear(textarea);
    await user.type(textarea, "Edited requirement.");
    await user.click(screen.getByTestId("adlc-blueprint-request-submit"));

    await waitFor(() => {
      expect(mockGenerateAdlcBlueprint).toHaveBeenCalledWith(
        "flow-1",
        "Edited requirement.",
        undefined,
      );
    });
  });

  it("starts empty when no default is provided", () => {
    renderDialog();

    const textarea = screen.getByLabelText(
      "Workflow requirement",
    ) as HTMLTextAreaElement;
    expect(textarea.value).toBe("");
  });
});

describe("BlueprintRequestDialog — close behavior", () => {
  it("closes via the X button so the user can build the blueprint manually", async () => {
    const user = userEvent.setup();
    const props = renderDialog();

    await user.click(screen.getByRole("button", { name: "Close" }));

    expect(props.onOpenChange).toHaveBeenCalledWith(false);
  });

  it("closes via the 'Close and build manually' footer action", async () => {
    const user = userEvent.setup();
    const props = renderDialog();

    await user.click(
      screen.getByRole("button", { name: /close and build manually/i }),
    );

    expect(props.onOpenChange).toHaveBeenCalledWith(false);
  });

  it("blocks closing while a generation request is in flight", async () => {
    const user = userEvent.setup();
    let resolveRequest: (value: unknown) => void = () => {};
    mockGenerateAdlcBlueprint.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveRequest = resolve;
        }),
    );
    const props = renderDialog();

    await user.type(
      screen.getByLabelText("Workflow requirement"),
      "Build a todo app.",
    );
    await user.click(screen.getByTestId("adlc-blueprint-request-submit"));

    expect(screen.queryByRole("button", { name: "Close" })).toBeNull();
    expect(
      screen.getByRole("button", { name: /close and build manually/i }),
    ).toBeDisabled();
    expect(props.onOpenChange).not.toHaveBeenCalled();

    resolveRequest(generationResult);
    await waitFor(() =>
      expect(props.onGenerated).toHaveBeenCalledWith(generationResult),
    );
  });
});

describe("BlueprintRequestDialog — submit", () => {
  it("sends the requirement to the DSH-backed API and applies the result", async () => {
    const user = userEvent.setup();
    const props = renderDialog();

    await user.type(
      screen.getByLabelText("Workflow requirement"),
      "Build a todo app.",
    );
    await user.click(screen.getByTestId("adlc-blueprint-request-submit"));

    await waitFor(() =>
      expect(mockGenerateAdlcBlueprint).toHaveBeenCalledWith(
        "flow-1",
        "Build a todo app.",
        undefined,
      ),
    );
    await waitFor(() =>
      expect(props.onGenerated).toHaveBeenCalledWith(generationResult),
    );
    expect(props.onOpenChange).toHaveBeenCalledWith(false);
  });

  it("forwards the optional extra instructions", async () => {
    const user = userEvent.setup();
    renderDialog();

    await user.type(
      screen.getByLabelText("Workflow requirement"),
      "Build a todo app.",
    );
    await user.type(
      screen.getByLabelText(/Extra instructions/),
      "Single approval gate.",
    );
    await user.click(screen.getByTestId("adlc-blueprint-request-submit"));

    await waitFor(() =>
      expect(mockGenerateAdlcBlueprint).toHaveBeenCalledWith(
        "flow-1",
        "Build a todo app.",
        "Single approval gate.",
      ),
    );
  });

  it("shows the API error inline and keeps the dialog open", async () => {
    const user = userEvent.setup();
    mockGenerateAdlcBlueprint.mockRejectedValue(
      new Error("The DSH web gateway is unreachable"),
    );
    const props = renderDialog();

    await user.type(
      screen.getByLabelText("Workflow requirement"),
      "Build a todo app.",
    );
    await user.click(screen.getByTestId("adlc-blueprint-request-submit"));

    expect(
      await screen.findByText(/The DSH web gateway is unreachable/),
    ).toBeInTheDocument();
    expect(props.onGenerated).not.toHaveBeenCalled();
    expect(props.onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it("keeps submit disabled without a requirement", async () => {
    const user = userEvent.setup();
    renderDialog();

    const submit = screen.getByTestId("adlc-blueprint-request-submit");
    expect(submit).toBeDisabled();
    await user.click(submit);

    expect(mockGenerateAdlcBlueprint).not.toHaveBeenCalled();
    expect(screen.queryByText(/generate blueprint/i)).toBeInTheDocument();
  });
});
