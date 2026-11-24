import type { ContractRead, ContractReference } from "@/types/contracts";

export const SCHEMA_REF = "adlc://schemas/skilltree-contract/0.1";
export const RENDERER_REF = "adlc-renderer:skilltree/0.1";
export const referenceKey = (ref: ContractReference) =>
  `${ref.schema_ref}|${ref.contract_id}|${ref.revision}|${ref.content_digest}`;

export function isSupportedContract(value: ContractRead): boolean {
  try {
    return supportedContract(value);
  } catch {
    return false;
  }
}

function supportedContract(value: ContractRead): boolean {
  const doc = value?.document;
  const ref = value?.reference;
  if (
    value?.schema_version !== "0.1" ||
    doc?.schema_ref !== SCHEMA_REF ||
    doc.renderer_ref !== RENDERER_REF ||
    doc.document_type !== "skilltree" ||
    doc.schema_version !== "0.1" ||
    doc.producer_plugin !== "plugin:vai-adlc-skilltree/0.1.0" ||
    ref?.schema_ref !== SCHEMA_REF ||
    ref.contract_id !== doc.contract_id ||
    ref.revision !== doc.revision ||
    !Number.isInteger(doc.revision) ||
    doc.revision < 1 ||
    doc.revision > 512 ||
    !/^sha256:[0-9a-f]{64}$/.test(ref.content_digest) ||
    !Array.isArray(doc.nodes) ||
    doc.nodes.length > 128 ||
    !Array.isArray(doc.dependencies) ||
    doc.dependencies.length > 256 ||
    !["DRAFT", "VALIDATED", "APPROVED"].includes(value.status)
  )
    return false;
  if (
    typeof doc.title !== "string" ||
    typeof doc.scope?.objective !== "string" ||
    typeof doc.constraints?.read_only !== "boolean" ||
    ![
      doc.scope.in_scope,
      doc.scope.out_of_scope,
      doc.constraints.allowed_paths,
      doc.constraints.forbidden_actions,
    ].every(
      (list) =>
        Array.isArray(list) && list.every((text) => typeof text === "string"),
    )
  )
    return false;
  const ids = new Set(doc.nodes.map((node) => node.node_id));
  if (
    ids.size !== doc.nodes.length ||
    doc.nodes.some(
      (node) =>
        typeof node.node_id !== "string" ||
        !["MILESTONE", "TASK", "DECISION"].includes(node.kind) ||
        typeof node.title !== "string" ||
        typeof node.description !== "string" ||
        !Array.isArray(node.acceptance_criteria) ||
        node.acceptance_criteria.some(
          (criterion) =>
            typeof criterion.description !== "string" ||
            !["HUMAN", "TEST", "ARTIFACT"].includes(criterion.verification) ||
            !(
              criterion.verifier_ref === null ||
              typeof criterion.verifier_ref === "string"
            ),
        ),
    )
  )
    return false;
  if (
    doc.dependencies.some(
      (edge) =>
        !ids.has(edge.source_id) ||
        !ids.has(edge.target_id) ||
        !["REQUIRES", "CONTAINS"].includes(edge.relation),
    )
  )
    return false;
  if (
    value.validation &&
    (value.validation.content_digest !== ref.content_digest ||
      value.validation.criteria_executed !== false ||
      typeof value.validation.passed !== "boolean" ||
      typeof value.validation.checked_at !== "string" ||
      typeof value.validation.validator_ref !== "string" ||
      !Array.isArray(value.validation.checks) ||
      value.validation.checks.some(
        (check) =>
          typeof check.check_id !== "string" ||
          typeof check.passed !== "boolean" ||
          typeof check.summary !== "string",
      ))
  )
    return false;
  if (value.status !== "DRAFT" && value.validation?.passed !== true)
    return false;
  if (
    value.status === "APPROVED" &&
    (!value.approval ||
      referenceKey(value.approval.reference) !== referenceKey(ref))
  )
    return false;
  if (value.status !== "APPROVED" && value.approval) return false;
  if (
    value.approval &&
    (typeof value.approval.approval_id !== "string" ||
      typeof value.approval.approved_by !== "string" ||
      typeof value.approval.approved_at !== "string" ||
      !(
        value.approval.comment === null ||
        typeof value.approval.comment === "string"
      ))
  )
    return false;
  if (
    doc.supersedes &&
    (doc.supersedes.schema_ref !== SCHEMA_REF ||
      typeof doc.supersedes.contract_id !== "string" ||
      !Number.isInteger(doc.supersedes.revision) ||
      !/^sha256:[0-9a-f]{64}$/.test(doc.supersedes.content_digest))
  )
    return false;
  return skilltreeLayout(value) !== null;
}

// Layout is a pure projection. Coordinates are never written into the contract.
export function skilltreeLayout(contract: ContractRead) {
  const { nodes, dependencies } = contract.document;
  const depth = new Map(nodes.map((node) => [node.node_id, 0]));
  const remaining = new Map(nodes.map((node) => [node.node_id, 0]));
  for (const edge of dependencies)
    remaining.set(edge.target_id, (remaining.get(edge.target_id) ?? 0) + 1);
  const ready = nodes
    .filter((node) => remaining.get(node.node_id) === 0)
    .map((node) => node.node_id);
  let visited = 0;
  for (let index = 0; index < ready.length; index++) {
    const id = ready[index];
    visited++;
    for (const edge of dependencies.filter((item) => item.source_id === id)) {
      depth.set(
        edge.target_id,
        Math.max(depth.get(edge.target_id) ?? 0, (depth.get(id) ?? 0) + 1),
      );
      const next = (remaining.get(edge.target_id) ?? 0) - 1;
      remaining.set(edge.target_id, next);
      if (next === 0) ready.push(edge.target_id);
    }
  }
  if (visited !== nodes.length) return null;
  const rows = new Map<number, number>();
  const points = new Map<string, { x: number; y: number }>();
  for (const node of nodes) {
    const column = depth.get(node.node_id) ?? 0;
    const row = rows.get(column) ?? 0;
    points.set(node.node_id, { x: 24 + column * 288, y: 24 + row * 120 });
    rows.set(column, row + 1);
  }
  return {
    points,
    width: Math.max(288, ...[...points.values()].map((p) => p.x + 264)),
    height: Math.max(144, ...[...points.values()].map((p) => p.y + 112)),
  };
}
