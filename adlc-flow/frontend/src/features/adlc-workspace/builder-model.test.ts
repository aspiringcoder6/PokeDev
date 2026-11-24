import type { AdlcNodePackage } from "@/types/adlc";
import type { FlowType } from "@/types/flow";
import {
  adlcGraphMeaning,
  createAdlcWorkflowMarker,
  normalizeAdlcCanvasGraph,
} from "@/utils/adlc-blueprint";
import approvalDefinition from "../../../../../adlc_components/packages/approval/0.1.0/package.json";
import codingDefinition from "../../../../../adlc_components/packages/coding-agent/0.2.0/package.json";
import {
  arrangeNodes,
  boundRequirementInputs,
  connectionError,
  createDependency,
  createLibraryNode,
  plannedPackages,
  visiblePackages,
} from "./builder-model";

const coding = {
  ...codingDefinition,
  lifecycle_status: "PUBLISHED",
} as unknown as AdlcNodePackage;
const approval = {
  ...approvalDefinition,
  lifecycle_status: "PUBLISHED",
} as unknown as AdlcNodePackage;
const setup = () => {
  const nodes = [
    createLibraryNode({ type: "requirement" }, { x: 0, y: 0 }),
    createLibraryNode({ type: "published", package: coding }, { x: 330, y: 0 }),
    createLibraryNode(
      { type: "published", package: approval },
      { x: 660, y: 0 },
    ),
  ];
  return {
    nodes,
    edges: [
      createDependency(nodes[0].id, nodes[1].id, nodes),
      createDependency(nodes[1].id, nodes[2].id, nodes),
    ],
  };
};
test("published package instances keep independent identity, inputs and configuration", () => {
  const a = createLibraryNode(
      { type: "published", package: coding },
      { x: 0, y: 0 },
    ),
    b = createLibraryNode(
      { type: "published", package: coding },
      { x: 0, y: 0 },
    );
  a.data.adlc!.configuration_overrides.task_loop_enabled = true;
  a.data.adlc!.inputs.requirement = "First task";
  expect(a.data.adlc!.stage_id).not.toBe(b.data.adlc!.stage_id);
  expect(b.data.adlc!.inputs).toEqual({ requirement: "" });
  expect(b.data.adlc!.configuration_overrides).toEqual({});
});
test("all eight planned packages have versioned authoring blocks and no executable reference", () => {
  expect(plannedPackages).toHaveLength(8);
  for (const p of plannedPackages) {
    const node = createLibraryNode(
      { type: "planned", package: p },
      { x: 0, y: 0 },
    );
    expect(node.data.adlc).toBeUndefined();
    expect(node.data.adlcDraft).toMatchObject({
      document_type: "ADLC_AUTHORING_BLOCK",
      schema_version: "0.1",
      kind: "PLANNED_PACKAGE",
      proposed_package_id: p.package_id,
    });
    expect(p.executable).toBe(false);
  }
});
test("requirement wires declare a named literal input", () => {
  const { nodes, edges } = setup();
  expect(boundRequirementInputs(nodes[1].id, nodes, edges)).toEqual([
    "requirement",
  ]);
  expect(edges[0].data!.adlc!.bindings).toEqual([]);
});
test("connections reject cycles, self-links, duplicates, missing nodes and incoming requirement wires", () => {
  const { nodes, edges } = setup();
  expect(connectionError(nodes[1].id, nodes[1].id, nodes, edges)).toMatch(
    /itself/,
  );
  expect(connectionError(nodes[0].id, nodes[1].id, nodes, edges)).toMatch(
    /already/,
  );
  expect(connectionError(nodes[2].id, nodes[1].id, nodes, edges)).toMatch(
    /circular/,
  );
  expect(connectionError(nodes[2].id, nodes[0].id, nodes, edges)).toMatch(
    /workflow inputs/,
  );
  expect(connectionError("missing", nodes[1].id, nodes, edges)).toMatch(
    /two stages/,
  );
});
test("fan-out and fan-in stay valid and arrange in parallel", () => {
  const { nodes, edges } = setup();
  const branch = createLibraryNode(
    { type: "planned", package: plannedPackages[1] },
    { x: 0, y: 0 },
  );
  nodes.push(branch);
  expect(connectionError(nodes[0].id, branch.id, nodes, edges)).toBeNull();
  edges.push(
    createDependency(nodes[0].id, branch.id, nodes),
    createDependency(branch.id, nodes[2].id, nodes),
  );
  const arranged = arrangeNodes(nodes, edges);
  expect(arranged[1].position.x).toBe(arranged[3].position.x);
  expect(arranged[1].position.y).not.toBe(arranged[3].position.y);
  expect(adlcGraphMeaning(arranged, edges)).toBe(
    adlcGraphMeaning(nodes, edges),
  );
});
test("selection and movement do not change execution meaning; inputs and dependencies do", () => {
  const { nodes, edges } = setup();
  const before = adlcGraphMeaning(nodes, edges);
  const moved = nodes.map((n) => ({
    ...n,
    selected: !n.selected,
    position: { x: n.position.x + 100, y: 200 },
  }));
  expect(adlcGraphMeaning(moved, edges)).toBe(before);
  moved[1].data.adlc!.inputs.requirement = "Changed";
  expect(adlcGraphMeaning(moved, edges)).not.toBe(before);
  expect(adlcGraphMeaning(nodes, [])).not.toBe(before);
});
test("draft blocks and their connections survive normalization and JSON persistence", () => {
  const { nodes, edges } = setup();
  nodes.push(
    createLibraryNode(
      { type: "planned", package: plannedPackages[0] },
      { x: 100, y: 200 },
    ),
  );
  edges.push(createDependency(nodes[1].id, nodes[3].id, nodes));
  const saved = JSON.parse(
    JSON.stringify({
      id: "workflow",
      name: "Workflow",
      description: "",
      data: {
        adlc: createAdlcWorkflowMarker("workflow"),
        nodes,
        edges,
        viewport: { x: 91, y: -80, zoom: 0.55 },
      },
    }),
  ) as FlowType;
  normalizeAdlcCanvasGraph(saved);
  expect(adlcGraphMeaning(saved.data!.nodes, saved.data!.edges)).toBe(
    adlcGraphMeaning(nodes, edges),
  );
  expect(saved.data!.viewport).toEqual({ x: 91, y: -80, zoom: 0.55 });
});
test("the palette uses authorized latest versions and hides replaced coding families", () => {
  const old = { ...coding, version: "0.1.0" },
    replaced = { ...coding, package_id: "coding-agent-deepseek-harness" },
    deprecated = {
      ...approval,
      version: "0.0.1",
      lifecycle_status: "DEPRECATED",
    } as AdlcNodePackage;
  expect(
    visiblePackages([old, replaced, coding, approval, deprecated]),
  ).toEqual([coding, approval]);
});
