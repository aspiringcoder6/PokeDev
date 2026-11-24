import type { AdlcPlanValidationIssue } from "@/types/adlc";
import type { FlowType } from "@/types/flow";
import {
  isAdlcBlueprint,
  isAdlcEdge,
  isAdlcStageNode,
  mapAdlcIssuesToCanvas,
  normalizeAdlcCanvasGraph,
  shouldAutoPromptBlueprintRequest,
} from "../adlc-blueprint";

const FLOW_ID = "11111111-1111-4111-8111-111111111111";
const STAGE_ID = "22222222-2222-4222-8222-222222222222";
const NEXT_STAGE_ID = "33333333-3333-4333-8333-333333333333";

function stage(stageId: string, name: string) {
  return {
    document_type: "WORKFLOW_STAGE",
    schema_version: "0.1",
    stage_id: stageId,
    stage_type: "IMPLEMENTATION",
    name,
    objective: `Complete ${name}`,
    inputs: { requirement: name },
    expected_outputs: ["source_patch"],
    package_ref: { package_id: "coding-agent", version: "0.1.0" },
    configuration_overrides: {},
    execution_profile_overrides: {},
    policy_overrides: {},
    secret_refs: {},
    metadata: {},
  };
}

function blueprintFlow(): FlowType {
  return {
    id: FLOW_ID,
    name: "Blueprint",
    description: "",
    data: {
      adlc: {
        document_type: "WORKFLOW_DEFINITION",
        schema_version: "0.1",
        workflow_definition_id: FLOW_ID,
        version: 1,
        status: "DRAFT",
        default_policies: {},
        metadata: {},
      },
      nodes: [
        {
          id: "first",
          type: "genericNode",
          position: { x: 0, y: 0 },
          data: { adlc: stage(STAGE_ID, "First") },
        },
        {
          id: "second",
          type: "genericNode",
          position: { x: 300, y: 0 },
          data: { adlc: stage(NEXT_STAGE_ID, "Second") },
        },
      ],
      edges: [
        {
          id: "first-second",
          source: "first",
          target: "second",
          data: {
            adlc: {
              document_type: "WORKFLOW_EDGE",
              schema_version: "0.1",
              edge_id: "44444444-4444-4444-8444-444444444444",
              condition: "ON_SUCCESS",
              bindings: [],
              metadata: {},
            },
          },
        },
      ],
      viewport: { x: 0, y: 0, zoom: 1 },
    },
  } as unknown as FlowType;
}

describe("ADLC blueprint canvas mapping", () => {
  it("normalizes saved contract nodes and edges to dedicated renderers", () => {
    const flow = blueprintFlow();

    normalizeAdlcCanvasGraph(flow);

    expect(isAdlcBlueprint(flow)).toBe(true);
    expect(flow.data?.nodes.every(isAdlcStageNode)).toBe(true);
    expect(flow.data?.nodes[0].data.node.display_name).toBe("First");
    expect(flow.data?.edges.every(isAdlcEdge)).toBe(true);
    expect(flow.data?.edges[0]).toMatchObject({
      type: "adlcEdge",
      sourceHandle: "adlc-stage-output",
      targetHandle: "adlc-stage-input",
      reconnectable: false,
    });
  });

  it("rebinds an imported blueprint marker to the saved flow id", () => {
    const flow = blueprintFlow();
    if (flow.data?.adlc) {
      flow.data.adlc.workflow_definition_id =
        "99999999-9999-4999-8999-999999999999";
    }

    normalizeAdlcCanvasGraph(flow);

    expect(flow.data?.adlc?.workflow_definition_id).toBe(FLOW_ID);
    expect(isAdlcBlueprint(flow)).toBe(true);
  });

  it("maps semantic stage and edge findings back to canvas elements", () => {
    const flow = blueprintFlow();
    normalizeAdlcCanvasGraph(flow);
    const issues: AdlcPlanValidationIssue[] = [
      {
        code: "STAGE_INPUT_UNBOUND",
        message: "Input is missing",
        path: "/stages/1/inputs/requirement",
        details: { stage_id: NEXT_STAGE_ID },
      },
      {
        code: "STAGE_BINDING_INCOMPATIBLE",
        message: "Schemas differ",
        path: "/edges/0/bindings/0",
        details: {},
      },
    ];

    const mapped = mapAdlcIssuesToCanvas(
      issues,
      flow.data!.nodes,
      flow.data!.edges,
    );

    expect(mapped.nodeIssues.second).toEqual([issues[0]]);
    expect(mapped.edgeIssues["first-second"]).toEqual([issues[1]]);
    expect(mapped.globalIssues).toEqual([]);
  });
});

describe("shouldAutoPromptBlueprintRequest", () => {
  const base = {
    flowId: "flow-1",
    executableNodeCount: 0,
    isBlueprint: false,
    dismissedFlowIds: [] as string[],
    welcomeOpen: false,
    assistantOpen: false,
  };

  it("prompts fresh empty non-blueprint flows", () => {
    expect(shouldAutoPromptBlueprintRequest(base)).toBe(true);
  });

  it("never prompts without a flow id", () => {
    expect(
      shouldAutoPromptBlueprintRequest({ ...base, flowId: undefined }),
    ).toBe(false);
  });

  it("never prompts flows that already contain component nodes", () => {
    expect(
      shouldAutoPromptBlueprintRequest({
        ...base,
        executableNodeCount: 2,
      }),
    ).toBe(false);
  });

  it("never prompts marked blueprint flows", () => {
    expect(
      shouldAutoPromptBlueprintRequest({ ...base, isBlueprint: true }),
    ).toBe(false);
  });

  it("does not prompt flows the user dismissed this session", () => {
    expect(
      shouldAutoPromptBlueprintRequest({
        ...base,
        dismissedFlowIds: ["other-flow", "flow-1"],
      }),
    ).toBe(false);
  });

  it("waits while the welcome overlay or assistant panel is open", () => {
    expect(
      shouldAutoPromptBlueprintRequest({ ...base, welcomeOpen: true }),
    ).toBe(false);
    expect(
      shouldAutoPromptBlueprintRequest({ ...base, assistantOpen: true }),
    ).toBe(false);
  });
});
