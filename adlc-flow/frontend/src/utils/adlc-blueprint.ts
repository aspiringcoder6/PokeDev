import axios from "axios";
import type {
  AdlcNodePackage,
  AdlcPlanValidationIssue,
  AdlcServiceError,
  AdlcWorkflowEdge,
  AdlcWorkflowMarker,
  AdlcWorkflowStage,
} from "@/types/adlc";
import type {
  AdlcStageNodeType,
  AllNodeType,
  EdgeDataType,
  EdgeType,
  FlowType,
  NodeDataType,
} from "@/types/flow";

export const ADLC_STAGE_SOURCE_HANDLE = "adlc-stage-output";
export const ADLC_STAGE_TARGET_HANDLE = "adlc-stage-input";

export function adlcGraphMeaning(nodes: AllNodeType[], edges: EdgeType[]) {
  return JSON.stringify({
    nodes: nodes
      .map((n) => ({ id: n.id, stage: n.data.adlc, draft: n.data.adlcDraft }))
      .sort((a, b) => a.id.localeCompare(b.id)),
    edges: edges
      .map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        adlc: e.data?.adlc,
      }))
      .sort((a, b) => a.id.localeCompare(b.id)),
  });
}

export function isAdlcBlueprint(flow?: FlowType): boolean {
  return (
    flow?.data?.adlc?.document_type === "WORKFLOW_DEFINITION" &&
    flow.data.adlc.schema_version === "0.1"
  );
}

/**
 * Decide whether the blueprint request dialog should auto-open for the flow
 * the user just entered: only fresh, still-empty, non-blueprint flows are
 * prompted, and only when no stronger onboarding overlay (welcome, assistant)
 * is currently in front. Flows the user dismissed keep their opt-out.
 */
export function shouldAutoPromptBlueprintRequest(options: {
  flowId: string | undefined;
  executableNodeCount: number;
  isBlueprint: boolean;
  dismissedFlowIds: string[];
  welcomeOpen: boolean;
  assistantOpen: boolean;
}): boolean {
  if (!options.flowId) return false;
  if (options.executableNodeCount > 0) return false;
  if (options.isBlueprint) return false;
  if (options.dismissedFlowIds.includes(options.flowId)) return false;
  if (options.welcomeOpen || options.assistantOpen) return false;
  return true;
}

export function isAdlcStageNode(
  node: AllNodeType | undefined,
): node is AdlcStageNodeType & {
  data: NodeDataType & { adlc: AdlcWorkflowStage };
} {
  return (
    node?.type === "adlcStageNode" &&
    node.data.adlc?.document_type === "WORKFLOW_STAGE"
  );
}

export function isAdlcEdge(edge: EdgeType): boolean {
  return (
    edge.type === "adlcEdge" ||
    edge.data?.adlc?.document_type === "WORKFLOW_EDGE"
  );
}

export function adlcPackageKey(nodePackage: {
  package_id: string;
  version: string;
}): string {
  return `${nodePackage.package_id}@${nodePackage.version}`;
}

export function createAdlcWorkflowMarker(flowId: string): AdlcWorkflowMarker {
  return {
    document_type: "WORKFLOW_DEFINITION",
    schema_version: "0.1",
    workflow_definition_id: flowId,
    version: 1,
    status: "DRAFT",
    default_policies: {},
    metadata: {},
  };
}

export function stageTypeForPackage(nodePackage: AdlcNodePackage): string {
  const types: Record<AdlcNodePackage["kind"], string> = {
    AGENT: "IMPLEMENTATION",
    TESTING: "TESTING",
    REVIEW: "REVIEW",
    APPROVAL: "APPROVAL",
    ROUTER: "ROUTER",
    JOIN: "JOIN",
  };
  return types[nodePackage.kind];
}

export function createAdlcStage(
  nodePackage: AdlcNodePackage,
  values?: Partial<AdlcWorkflowStage>,
): AdlcWorkflowStage {
  return {
    document_type: "WORKFLOW_STAGE",
    schema_version: "0.1",
    stage_id: crypto.randomUUID(),
    stage_type: stageTypeForPackage(nodePackage),
    name: nodePackage.name.replace(/\s*\(Mock\)\s*$/, ""),
    objective: nodePackage.description || `Complete ${nodePackage.name}.`,
    inputs: {},
    expected_outputs: nodePackage.interface.outputs.map((slot) => slot.name),
    package_ref: {
      package_id: nodePackage.package_id,
      version: nodePackage.version,
    },
    configuration_overrides: {},
    execution_profile_overrides: {},
    policy_overrides: {},
    secret_refs: {},
    metadata: {},
    ...values,
  };
}

export function createAdlcCompatibilityNode(stage: AdlcWorkflowStage) {
  return {
    description: stage.objective,
    template: {},
    display_name: stage.name,
    documentation: "",
    outputs: [],
    type: "adlcStage",
  };
}

export function createAdlcWorkflowEdge(): AdlcWorkflowEdge {
  return {
    document_type: "WORKFLOW_EDGE",
    schema_version: "0.1",
    edge_id: crypto.randomUUID(),
    condition: "ON_SUCCESS",
    bindings: [],
    metadata: {},
  };
}

export function createAdlcEdgeData(
  metadata: AdlcWorkflowEdge | undefined,
  sourceId: string,
  targetId: string,
): EdgeDataType {
  return {
    ...(metadata ? { adlc: metadata } : {}),
    sourceHandle: {
      dataType: "ADLC_DEPENDENCY",
      id: sourceId,
      name: "dependency",
      output_types: ["ADLC_DEPENDENCY"],
    },
    targetHandle: {
      fieldName: "dependency",
      id: targetId,
      name: "dependency",
      type: "ADLC_DEPENDENCY",
      inputTypes: ["ADLC_DEPENDENCY"],
    },
  };
}

export function normalizeAdlcCanvasGraph(flow: FlowType): void {
  if (!isAdlcBlueprint(flow) || !flow.data?.adlc) return;
  const marker = flow.data.adlc;
  if (flow.id && marker.workflow_definition_id !== flow.id) {
    marker.workflow_definition_id = flow.id;
  }
  const stageNodeIds = new Set<string>();
  flow.data.nodes = flow.data.nodes.map((node) => {
    const adlc = (node.data as { adlc?: AdlcWorkflowStage }).adlc;
    if (adlc?.document_type !== "WORKFLOW_STAGE") return node;
    stageNodeIds.add(node.id);
    return {
      ...node,
      type: "adlcStageNode",
      data: {
        ...node.data,
        id: node.id,
        type: "adlcStage",
        adlc,
        node: createAdlcCompatibilityNode(adlc),
      },
    } as AdlcStageNodeType;
  });
  flow.data.edges = flow.data.edges.map((edge) => {
    if (!stageNodeIds.has(edge.source) || !stageNodeIds.has(edge.target)) {
      return edge;
    }
    return {
      ...edge,
      type: "adlcEdge",
      sourceHandle: ADLC_STAGE_SOURCE_HANDLE,
      targetHandle: ADLC_STAGE_TARGET_HANDLE,
      reconnectable: false,
      data: {
        ...edge.data,
        ...createAdlcEdgeData(edge.data?.adlc, edge.source, edge.target),
      },
    };
  });
}

export type AdlcCanvasIssueMap = {
  nodeIssues: Record<string, AdlcPlanValidationIssue[]>;
  edgeIssues: Record<string, AdlcPlanValidationIssue[]>;
  globalIssues: AdlcPlanValidationIssue[];
};

function appendIssue(
  target: Record<string, AdlcPlanValidationIssue[]>,
  id: string,
  issue: AdlcPlanValidationIssue,
) {
  target[id] = [...(target[id] ?? []), issue];
}

export function mapAdlcIssuesToCanvas(
  issues: AdlcPlanValidationIssue[],
  nodes: AllNodeType[],
  edges: EdgeType[],
): AdlcCanvasIssueMap {
  const nodeIssues: Record<string, AdlcPlanValidationIssue[]> = {};
  const edgeIssues: Record<string, AdlcPlanValidationIssue[]> = {};
  const globalIssues: AdlcPlanValidationIssue[] = [];
  const stages = nodes.filter(isAdlcStageNode);
  const stageByContractId = new Map(
    stages.map((node) => [node.data.adlc.stage_id, node]),
  );
  const blueprintEdges = edges.filter(isAdlcEdge);

  for (const issue of issues) {
    const stageId =
      typeof issue.details?.stage_id === "string"
        ? issue.details.stage_id
        : undefined;
    const stageFromDetails = stageId
      ? stageByContractId.get(stageId)
      : undefined;
    if (stageFromDetails) {
      appendIssue(nodeIssues, stageFromDetails.id, issue);
      continue;
    }

    const nodeIndex = issue.path?.match(/^\/nodes\/(\d+)/)?.[1];
    if (nodeIndex !== undefined && nodes[Number(nodeIndex)]) {
      appendIssue(nodeIssues, nodes[Number(nodeIndex)].id, issue);
      continue;
    }

    const stageIndex = issue.path?.match(/^\/stages\/(\d+)/)?.[1];
    if (stageIndex !== undefined && stages[Number(stageIndex)]) {
      appendIssue(nodeIssues, stages[Number(stageIndex)].id, issue);
      continue;
    }

    const edgeMatch = issue.path?.match(/^\/edges(?:\/(\d+))?/);
    if (edgeMatch) {
      const edgeIndex = edgeMatch[1];
      if (edgeIndex !== undefined && blueprintEdges[Number(edgeIndex)]) {
        appendIssue(edgeIssues, blueprintEdges[Number(edgeIndex)].id, issue);
      } else {
        for (const edge of blueprintEdges) {
          appendIssue(edgeIssues, edge.id, issue);
        }
      }
      continue;
    }

    globalIssues.push(issue);
  }

  return { nodeIssues, edgeIssues, globalIssues };
}

export function getAdlcPlanningError(error: unknown): {
  message: string;
  issues: AdlcPlanValidationIssue[];
} {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail as AdlcServiceError | string;
    if (typeof detail === "string") {
      return { message: detail, issues: [] };
    }
    if (detail && typeof detail.message === "string") {
      return {
        message: detail.message,
        issues: Array.isArray(detail.details?.issues)
          ? detail.details.issues
          : [],
      };
    }
  }
  return {
    message:
      error instanceof Error
        ? error.message
        : "Unable to validate the ADLC blueprint.",
    issues: [],
  };
}
