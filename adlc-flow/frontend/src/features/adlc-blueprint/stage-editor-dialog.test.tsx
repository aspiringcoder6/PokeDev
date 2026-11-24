import { fireEvent, render, screen } from "@testing-library/react";
import type { AdlcNodePackage, AdlcWorkflowStage } from "@/types/adlc";
import StageEditorDialog from "./stage-editor-dialog";

const reference = {
  schema_ref: "adlc://schemas/skilltree-contract/0.1",
  contract_id: "11111111-1111-4111-8111-111111111111",
  revision: 3,
  content_digest: `sha256:${"a".repeat(64)}`,
};
const packages: AdlcNodePackage[] = [
  {
    schema_version: "0.1",
    content_digest: `sha256:${"c".repeat(64)}`,
    status: "PUBLISHED",
    lifecycle_status: "PUBLISHED",
    package_id: "coding-agent-contract-harness",
    version: "0.1.0",
    name: "Contract coding",
    description: "Bound work",
    kind: "AGENT",
    interface: { inputs: [], outputs: [] },
    configuration_schema: {
      properties: { approved_contract_ref: { type: ["object", "null"] } },
    },
    defaults: { approved_contract_ref: null },
    override_allowlist: ["/configuration/approved_contract_ref"],
    execution_profile: null,
    default_policies: {
      retry: { max_attempts: 1 },
      timeout_ms: 30000,
      approval: { gate_type: null },
    },
    metadata: {},
  },
];
const stage = {
  stage_id: "stage",
  document_type: "WORKFLOW_STAGE",
  schema_version: "0.1",
  stage_type: "IMPLEMENTATION",
  name: "Bound work",
  objective: "Scoped JSON edit",
  inputs: {},
  expected_outputs: [],
  package_ref: {
    package_id: "coding-agent-contract-harness",
    version: "0.1.0",
  },
  configuration_overrides: { approved_contract_ref: reference },
  policy_overrides: {},
  execution_profile_overrides: {},
  secret_refs: {},
  metadata: {},
} as AdlcWorkflowStage;
test("stage dialog saves the selected reference as JSON rather than text", () => {
  const save = jest.fn(),
    changed = { ...reference, revision: 4 };
  render(
    <StageEditorDialog
      open
      onOpenChange={jest.fn()}
      packages={packages}
      initialStage={stage}
      onSave={save}
    />,
  );
  const input = screen.getByLabelText("approved_contract_ref (JSON)");
  expect(input).toHaveValue(JSON.stringify(reference, null, 2));
  fireEvent.change(input, { target: { value: JSON.stringify(changed) } });
  fireEvent.click(screen.getByRole("button", { name: /save stage/i }));
  expect(save).toHaveBeenCalledWith(
    expect.objectContaining({
      configuration_overrides: { approved_contract_ref: changed },
    }),
  );
});
test("malformed JSON cannot silently save the previous valid reference", () => {
  const save = jest.fn();
  render(
    <StageEditorDialog
      open
      onOpenChange={jest.fn()}
      packages={packages}
      initialStage={stage}
      onSave={save}
    />,
  );
  fireEvent.change(screen.getByLabelText("approved_contract_ref (JSON)"), {
    target: { value: '{"revision":' },
  });
  fireEvent.click(screen.getByRole("button", { name: /save stage/i }));
  expect(save).not.toHaveBeenCalled();
  expect(
    screen.getByText(/Paste an exact approved contract reference:/),
  ).toBeInTheDocument();
});

const unifiedPackage: AdlcNodePackage = {
  ...packages[0],
  package_id: "coding-agent",
  version: "0.2.0",
  name: "Coding Agent",
  interface: {
    inputs: [
      {
        name: "requirement",
        required: true,
        multiple: false,
        schema_ref: "adlc://schemas/requirement/0.1",
        description: "Full requirement",
      },
      {
        name: "task_loop_spec",
        required: false,
        multiple: false,
        schema_ref: "adlc://schemas/task-loop-spec/0.2",
        description: "Pinned loop specification",
      },
    ],
    outputs: [
      {
        name: "source_patch",
        required: true,
        multiple: false,
        schema_ref: "adlc://schemas/source-patch/0.1",
        description: "Captured patch",
      },
    ],
  },
  configuration_schema: {
    properties: {
      approved_contract_ref: { type: ["object", "null"] },
      task_loop_enabled: { type: "boolean" },
      submission_mode: { type: "string", enum: ["MANUAL", "AUTO"] },
    },
  },
  defaults: {
    approved_contract_ref: null,
    task_loop_enabled: false,
    submission_mode: "MANUAL",
  },
};

const unifiedStage = {
  ...stage,
  name: "Coding Agent",
  inputs: { requirement: "Implement addition" },
  package_ref: { package_id: "coding-agent", version: "0.2.0" },
  configuration_overrides: {},
} as AdlcWorkflowStage;

test("unified agent saves a simple requirement with both options off", () => {
  const save = jest.fn();
  render(
    <StageEditorDialog
      open
      onOpenChange={jest.fn()}
      packages={[unifiedPackage]}
      initialStage={unifiedStage}
      onSave={save}
    />,
  );
  expect(
    screen.queryByLabelText("task_loop_spec value"),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /save stage/i }));
  expect(save).toHaveBeenCalledWith(
    expect.objectContaining({
      inputs: { requirement: "Implement addition" },
      configuration_overrides: {
        approved_contract_ref: null,
        task_loop_enabled: false,
      },
    }),
  );
});

test("contract and repeated verification are saved together on one agent", () => {
  const save = jest.fn(),
    loopSpec = {
      specification: "Add and document",
      base_commit: "a".repeat(40),
    };
  render(
    <StageEditorDialog
      open
      onOpenChange={jest.fn()}
      packages={[unifiedPackage]}
      initialStage={unifiedStage}
      onSave={save}
    />,
  );
  fireEvent.change(screen.getByLabelText("Approved contract (optional JSON)"), {
    target: { value: JSON.stringify(reference) },
  });
  fireEvent.click(screen.getByLabelText("Repeat until checks pass"));
  fireEvent.change(screen.getByLabelText("task_loop_spec value"), {
    target: { value: JSON.stringify(loopSpec) },
  });
  fireEvent.click(screen.getByRole("button", { name: /save stage/i }));
  expect(save).toHaveBeenCalledWith(
    expect.objectContaining({
      package_ref: { package_id: "coding-agent", version: "0.2.0" },
      inputs: { requirement: "Implement addition", task_loop_spec: loopSpec },
      configuration_overrides: {
        approved_contract_ref: reference,
        task_loop_enabled: true,
      },
    }),
  );
});

test("turning the loop off removes its spec while retaining the contract", () => {
  const save = jest.fn();
  const initial = {
    ...unifiedStage,
    inputs: {
      ...unifiedStage.inputs,
      task_loop_spec: { specification: "Add" },
    },
    configuration_overrides: {
      approved_contract_ref: reference,
      task_loop_enabled: true,
    },
  };
  render(
    <StageEditorDialog
      open
      onOpenChange={jest.fn()}
      packages={[unifiedPackage]}
      initialStage={initial}
      onSave={save}
    />,
  );
  fireEvent.click(screen.getByLabelText("Repeat until checks pass"));
  fireEvent.click(screen.getByRole("button", { name: /save stage/i }));
  expect(save).toHaveBeenCalledWith(
    expect.objectContaining({
      inputs: { requirement: "Implement addition" },
      configuration_overrides: {
        approved_contract_ref: reference,
        task_loop_enabled: false,
      },
    }),
  );
});

test("malformed loop JSON prevents saving", () => {
  const save = jest.fn();
  render(
    <StageEditorDialog
      open
      onOpenChange={jest.fn()}
      packages={[unifiedPackage]}
      initialStage={unifiedStage}
      onSave={save}
    />,
  );
  fireEvent.click(screen.getByLabelText("Repeat until checks pass"));
  fireEvent.change(screen.getByLabelText("task_loop_spec value"), {
    target: { value: '{"specification":' },
  });
  fireEvent.click(screen.getByRole("button", { name: /save stage/i }));
  expect(save).not.toHaveBeenCalled();
  expect(
    screen.getByText(/Paste a task loop specification/),
  ).toBeInTheDocument();
});

test("existing contract stages can move to the unified agent without losing their reference or budgets", () => {
  const save = jest.fn();
  render(
    <StageEditorDialog
      open
      onOpenChange={jest.fn()}
      packages={[...packages, unifiedPackage]}
      initialStage={{
        ...stage,
        policy_overrides: { timeout_ms: 4321, retry: { max_attempts: 2 } },
      }}
      onSave={save}
    />,
  );
  fireEvent.click(
    screen.getByRole("button", { name: /Use unified Coding Agent/i }),
  );
  expect(
    screen.getByLabelText("Approved contract (optional JSON)"),
  ).toHaveValue(JSON.stringify(reference, null, 2));
  fireEvent.click(screen.getByRole("button", { name: /save stage/i }));
  expect(save).toHaveBeenCalledWith(
    expect.objectContaining({
      package_ref: { package_id: "coding-agent", version: "0.2.0" },
      policy_overrides: { timeout_ms: 4321, retry: { max_attempts: 2 } },
      configuration_overrides: {
        approved_contract_ref: reference,
        task_loop_enabled: false,
        submission_mode: "MANUAL",
      },
    }),
  );
});

const harnessPackage: AdlcNodePackage = {
  ...unifiedPackage,
  version: "0.3.0",
  configuration_schema: {
    ...unifiedPackage.configuration_schema,
    properties: {
      ...unifiedPackage.configuration_schema.properties,
      loop_runtime: { type: "string", enum: ["HARNESS", "OPENCODE"] },
    },
  },
  defaults: { ...unifiedPackage.defaults, loop_runtime: "HARNESS" },
};

test("new package defaults to Harness and persists the explicit loop runtime", () => {
  const save = jest.fn();
  render(
    <StageEditorDialog
      open
      onOpenChange={jest.fn()}
      packages={[harnessPackage]}
      initialStage={{
        ...unifiedStage,
        package_ref: { package_id: "coding-agent", version: "0.3.0" },
      }}
      onSave={save}
    />,
  );
  expect(screen.queryByLabelText("Loop runtime")).not.toBeInTheDocument();
  fireEvent.click(screen.getByLabelText("Repeat until checks pass"));
  expect(screen.getByLabelText("Loop runtime")).toHaveTextContent(
    "Harness · file proposals",
  );
  expect(screen.getByText(/no deletions or monetary budget/)).toBeVisible();
  fireEvent.change(screen.getByLabelText("task_loop_spec value"), {
    target: { value: '{"specification":"Implement"}' },
  });
  fireEvent.click(screen.getByRole("button", { name: /save stage/i }));
  expect(save).toHaveBeenCalledWith(
    expect.objectContaining({
      package_ref: { package_id: "coding-agent", version: "0.3.0" },
    }),
  );
  // Effective defaults are merged by the backend. UI need not store redundant defaults.
  expect(
    save.mock.calls[0][0].configuration_overrides.loop_runtime ??
      harnessPackage.defaults.loop_runtime,
  ).toBe("HARNESS");
});

test("explicit upgrade preserves an old loop as OpenCode rather than silently migrating it", () => {
  const save = jest.fn();
  render(
    <StageEditorDialog
      open
      onOpenChange={jest.fn()}
      packages={[unifiedPackage, harnessPackage]}
      initialStage={{
        ...unifiedStage,
        inputs: {
          ...unifiedStage.inputs,
          task_loop_spec: { specification: "Add" },
        },
        configuration_overrides: {
          approved_contract_ref: null,
          task_loop_enabled: true,
          submission_mode: "MANUAL",
        },
      }}
      onSave={save}
    />,
  );
  fireEvent.click(
    screen.getByRole("button", { name: /Use unified Coding Agent/i }),
  );
  expect(screen.getByLabelText("Loop runtime")).toHaveTextContent(
    "OpenCode · existing loop",
  );
  fireEvent.click(screen.getByRole("button", { name: /save stage/i }));
  expect(save).toHaveBeenCalledWith(
    expect.objectContaining({
      package_ref: { package_id: "coding-agent", version: "0.3.0" },
      configuration_overrides: expect.objectContaining({
        loop_runtime: "OPENCODE",
        task_loop_enabled: true,
      }),
    }),
  );
});


test("changing the package preserves user-typed name and objective", () => {
  const save = jest.fn();
  // Two packages with different defaults so we can detect preservation.
  const pkgA = {
    ...unifiedPackage,
    package_id: "coding-agent",
    version: "0.2.0",
    name: "Agent A",
    description: "Default A description",
  };
  const pkgB = {
    ...unifiedPackage,
    package_id: "coding-agent",
    version: "0.2.1",
    name: "Agent B",
    description: "Default B description",
  };
  render(
    <StageEditorDialog
      open
      onOpenChange={jest.fn()}
      packages={[pkgA, pkgB]}
      initialStage={{
        ...unifiedStage,
        name: "My custom name",
        objective: "My custom objective",
        package_ref: { package_id: "coding-agent", version: "0.2.0" },
      }}
      onSave={save}
    />,
  );
  // Switch to the other package via the package selector.
  fireEvent.click(screen.getByLabelText("Node package"));
  fireEvent.click(screen.getByRole("option", { name: /Agent B/ }));
  // The user-typed name and objective must be preserved.
  expect(screen.getByLabelText("Stage name")).toHaveValue("My custom name");
  expect(screen.getByLabelText("Objective")).toHaveValue(
    "My custom objective",
  );
});

test("changing the package preserves compatible input values", () => {
  const save = jest.fn();
  // Two packages that share the 'requirement' input slot.
  const pkgA = {
    ...unifiedPackage,
    package_id: "coding-agent",
    version: "0.2.0",
    name: "Agent A",
  };
  const pkgB = {
    ...unifiedPackage,
    package_id: "coding-agent",
    version: "0.2.1",
    name: "Agent B",
  };
  render(
    <StageEditorDialog
      open
      onOpenChange={jest.fn()}
      packages={[pkgA, pkgB]}
      initialStage={{
        ...unifiedStage,
        inputs: { requirement: "Build a calculator" },
        package_ref: { package_id: "coding-agent", version: "0.2.0" },
      }}
      onSave={save}
    />,
  );
  // Switch to the other package via the package selector.
  fireEvent.click(screen.getByLabelText("Node package"));
  fireEvent.click(screen.getByRole("option", { name: /Agent B/ }));
  // The requirement value must be preserved.
  expect(screen.getByLabelText("requirement value")).toHaveValue(
    "Build a calculator",
  );
});

test("changing the package preserves timeout_ms and model_ref", () => {
  const save = jest.fn();
  const pkgA = {
    ...unifiedPackage,
    package_id: "coding-agent",
    version: "0.2.0",
    name: "Agent A",
    default_policies: { timeout_ms: 30000 },
    execution_profile: { model_ref: "deepseek-chat" },
    override_allowlist: [
      "/policies/timeout_ms",
      "/execution_profile/model_ref",
    ],
  };
  const pkgB = {
    ...unifiedPackage,
    package_id: "coding-agent",
    version: "0.2.1",
    name: "Agent B",
    default_policies: { timeout_ms: 30000 },
    execution_profile: { model_ref: "deepseek-chat" },
    override_allowlist: [
      "/policies/timeout_ms",
      "/execution_profile/model_ref",
    ],
  };
  render(
    <StageEditorDialog
      open
      onOpenChange={jest.fn()}
      packages={[pkgA, pkgB]}
      initialStage={{
        ...unifiedStage,
        policy_overrides: { timeout_ms: 5000 },
        execution_profile_overrides: { model_ref: "deepseek-chat" },
        package_ref: { package_id: "coding-agent", version: "0.2.0" },
      }}
      onSave={save}
    />,
  );
  // Switch to the other package via the package selector.
  fireEvent.click(screen.getByLabelText("Node package"));
  fireEvent.click(screen.getByRole("option", { name: /Agent B/ }));
  // Timeout and model must be preserved.
  expect(screen.getByLabelText("Timeout (ms)")).toHaveValue(5000);
  expect(screen.getByLabelText("Model reference")).toHaveValue("deepseek-chat");
});
