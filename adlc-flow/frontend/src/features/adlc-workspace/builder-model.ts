import { translateUi } from "@/i18n/ui";
import type { AdlcNodePackage } from "@/types/adlc";
import type {
  AdlcAuthoringBlock,
  AdlcStageNodeType,
  AllNodeType,
  EdgeType,
} from "@/types/flow";
import {
  ADLC_STAGE_SOURCE_HANDLE,
  ADLC_STAGE_TARGET_HANDLE,
  createAdlcCompatibilityNode,
  createAdlcEdgeData,
  createAdlcStage,
  createAdlcWorkflowEdge,
  isAdlcStageNode,
} from "@/utils/adlc-blueprint";
import roadmap from "../../../../../adlc_components/package-roadmap/catalog.json";
import i18n from "@/i18n";

export const plannedPackages = roadmap.packages;
export type PlannedPackage = (typeof plannedPackages)[number];
export type LibraryEntry =
  | { type: "requirement" }
  | { type: "published"; package: AdlcNodePackage }
  | { type: "planned"; package: PlannedPackage };

const replaced = new Set([
  "coding-agent-deepseek-harness",
  "coding-agent-contract-harness",
  "task-loop-opencode",
  "coding-agent-opencode",
  "task-loop",
]);
export function visiblePackages(packages: AdlcNodePackage[]) {
  const unified = packages.some(
    (p) =>
      p.package_id === "coding-agent" &&
      ["0.2.0", "0.2.1", "0.3.0"].includes(p.version),
  );
  const latest = new Map<string, AdlcNodePackage>();
  for (const p of packages) {
    if (
      p.lifecycle_status !== "PUBLISHED" ||
      (unified && replaced.has(p.package_id))
    )
      continue;
    const previous = latest.get(p.package_id);
    if (
      !previous ||
      p.version.localeCompare(previous.version, undefined, { numeric: true }) >
        0
    )
      latest.set(p.package_id, p);
  }
  return [...latest.values()].sort((a, b) => {
    const rank = (p: AdlcNodePackage) =>
      p.package_id === "coding-agent"
        ? 0
        : p.package_id === "approval"
          ? 1
          : p.package_id === "skilltree-authoring-deepseek-harness"
            ? 2
            : 3;
    return rank(a) - rank(b) || a.name.localeCompare(b.name);
  });
}
export function packageLabel(p: AdlcNodePackage) {
  return p.package_id === "approval"
    ? translateUi("Human Approval")
    : p.package_id === "skilltree-authoring-deepseek-harness"
      ? translateUi("Contract Author")
      : translateUi(p.name.replace(/\s*\(Mock\)\s*$/, ""));
}
export function blockName(node: AllNodeType) {
  return (
    node.data.adlcDraft?.name ??
    node.data.adlc?.name ??
    node.data.node.display_name
  );
}
export function createLibraryNode(
  entry: LibraryEntry,
  position: { x: number; y: number },
): AdlcStageNodeType {
  const id = `adlc-stage-${crypto.randomUUID()}`;
  if (entry.type === "published") {
    const stage = createAdlcStage(entry.package, {
      name: packageLabel(entry.package),
      inputs: Object.fromEntries(
        entry.package.interface.inputs
          .filter(
            (slot) =>
              slot.required ||
              (entry.package.package_id === "coding-agent" &&
                slot.name === "requirement"),
          )
          .map((slot) => [slot.name, ""]),
      ),
    });
    return {
      id,
      type: "adlcStageNode",
      position,
      selected: true,
      data: {
        id,
        type: "adlcStage",
        adlc: stage,
        node: createAdlcCompatibilityNode(stage),
      },
    };
  }
  const draft: AdlcAuthoringBlock = {
    document_type: "ADLC_AUTHORING_BLOCK",
    schema_version: "0.1",
    block_id: crypto.randomUUID(),
    kind: entry.type === "requirement" ? "REQUIREMENT" : "PLANNED_PACKAGE",
    name:
      entry.type === "requirement"
        ? translateUi("Requirement")
        : translateUi(entry.package.name),
    objective:
      entry.type === "requirement"
        ? translateUi("Describe the outcome for this workflow.")
        : translateUi(entry.package.description),
    ...(entry.type === "requirement"
      ? { requirement: "" }
      : { proposed_package_id: entry.package.package_id }),
  };
  return {
    id,
    type: "adlcStageNode",
    position,
    selected: true,
    data: {
      id,
      type: "adlcAuthoring",
      adlcDraft: draft,
      node: {
        display_name: draft.name,
        description: draft.objective,
        template: {},
        outputs: [],
        documentation: "",
        type: "adlcAuthoring",
      },
    },
  };
}

export function connectionError(
  source: string,
  target: string,
  nodes: AllNodeType[],
  edges: EdgeType[],
): string | null {
  if (
    !nodes.some((n) => n.id === source) ||
    !nodes.some((n) => n.id === target)
  )
    return translateUi("Choose two stages in this workflow.");
  if (source === target) return translateUi("A stage cannot depend on itself.");
  if (
    nodes.find((n) => n.id === target)?.data.adlcDraft?.kind === "REQUIREMENT"
  )
    return translateUi(
      "Requirements are workflow inputs and cannot have an incoming dependency.",
    );
  if (edges.some((e) => e.source === source && e.target === target))
    return translateUi("These stages are already connected.");
  const pending = [target],
    seen = new Set<string>();
  while (pending.length) {
    const id = pending.pop()!;
    if (id === source)
      return translateUi("This connection would create a circular dependency.");
    if (seen.has(id)) continue;
    seen.add(id);
    pending.push(...edges.filter((e) => e.source === id).map((e) => e.target));
  }
  return null;
}
export function createDependency(
  source: string,
  target: string,
  nodes: AllNodeType[],
): EdgeType {
  const metadata = createAdlcWorkflowEdge();
  if (
    nodes.find((n) => n.id === source)?.data.adlcDraft?.kind === "REQUIREMENT"
  )
    metadata.metadata.authoring_input = "requirement";
  return {
    id: `adlc-edge-${metadata.edge_id}`,
    source,
    target,
    type: "adlcEdge",
    sourceHandle: ADLC_STAGE_SOURCE_HANDLE,
    targetHandle: ADLC_STAGE_TARGET_HANDLE,
    reconnectable: false,
    data: createAdlcEdgeData(metadata, source, target),
  };
}
export function arrangeNodes(
  nodes: AllNodeType[],
  edges: EdgeType[],
): AllNodeType[] {
  const ranks = new Map<string, number>(),
    pending = [...nodes];
  while (pending.length) {
    const ready = pending.filter((n) =>
      edges.filter((e) => e.target === n.id).every((e) => ranks.has(e.source)),
    );
    if (!ready.length) return nodes;
    for (const n of ready) {
      ranks.set(
        n.id,
        Math.max(
          0,
          ...edges
            .filter((e) => e.target === n.id)
            .map((e) => (ranks.get(e.source) ?? 0) + 1),
        ),
      );
      pending.splice(pending.indexOf(n), 1);
    }
  }
  const row = new Map<number, number>();
  return nodes.map((n) => {
    const rank = ranks.get(n.id) ?? 0,
      index = row.get(rank) ?? 0;
    row.set(rank, index + 1);
    return { ...n, position: { x: 80 + rank * 330, y: 80 + index * 230 } };
  });
}
export function plannedCount(nodes: AllNodeType[]) {
  return nodes.filter((n) => n.data.adlcDraft?.kind === "PLANNED_PACKAGE")
    .length;
}
export function boundRequirementInputs(
  nodeId: string,
  nodes: AllNodeType[],
  edges: EdgeType[],
) {
  return edges
    .filter(
      (e) =>
        e.target === nodeId &&
        nodes.find((n) => n.id === e.source)?.data.adlcDraft?.kind ===
          "REQUIREMENT",
    )
    .map((e) =>
      String(e.data?.adlc?.metadata.authoring_input ?? "requirement"),
    );
}
export function packageForNode(node: AllNodeType, packages: AdlcNodePackage[]) {
  return isAdlcStageNode(node)
    ? packages.find(
        (p) =>
          p.package_id === node.data.adlc.package_ref.package_id &&
          p.version === node.data.adlc.package_ref.version,
      )
    : undefined;
}
