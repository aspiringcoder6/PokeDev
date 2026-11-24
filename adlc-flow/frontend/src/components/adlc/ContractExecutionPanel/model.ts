import type { ContractExecutionRead } from "@/types/contractExecution";
import { isSupportedContract, referenceKey } from "../ContractViewer/model";

const supported = new Set([
  "verifier:contract-source-patch/0.1.0",
  "verifier:contract-no-changes/0.1.0",
  "verifier:contract-json-syntax/0.1.0",
]);
function safePath(path: string): boolean {
  return (
    typeof path === "string" &&
    path.length > 0 &&
    path.length <= 255 &&
    !/[:\\*?[\]<>|]/.test(path) &&
    !Array.from(path).some(
      (char) => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127,
    ) &&
    path
      .split("/")
      .every(
        (part) =>
          part &&
          part !== "." &&
          part !== ".." &&
          !/[. ]$/.test(part) &&
          !/^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(part) &&
          !/^\.(?:git|ssh|aws|codex|agents|dsh)$/i.test(part) &&
          !/^\.env(?:\.|$)/i.test(part) &&
          !/^(?:credentials|secrets)(?:\.|$)/i.test(part) &&
          !/\.(?:pem|key|p12|pfx|ovpn)$/i.test(part),
      )
  );
}
function allowedPath(path: string, paths: string[]): boolean {
  return (
    safePath(path) &&
    paths.some(
      (p) => p === "*" || (p.endsWith("/") ? path.startsWith(p) : path === p),
    )
  );
}
export function supportedExecution(row: ContractExecutionRead): boolean {
  try {
    const { binding: b, contract, proof } = row;
    const ref = referenceKey(b.reference);
    const readOnly =
      contract.document.constraints.read_only ||
      contract.document.constraints.forbidden_actions.includes("write");
    const criteria = contract.document.nodes.flatMap((node) =>
      node.acceptance_criteria.map((c, i) => ({
        node_id: node.node_id,
        criterion_index: i,
        verifier_ref: c.verifier_ref,
      })),
    );
    if (
      !isSupportedContract(contract) ||
      contract.status !== "APPROVED" ||
      !contract.approval ||
      !b.scope.session_id ||
      !b.scope.attempt_id ||
      !b.scope.request_id ||
      b.schema_version !== "0.1" ||
      b.policy.policy_ref !== "policy:adlc-contract-repository/0.1.0" ||
      ref !== referenceKey(contract.reference) ||
      ref !== referenceKey(b.policy.contract_reference) ||
      b.policy.natural_language_enforced !== false ||
      !/^sha256:[0-9a-f]{64}$/.test(b.policy_digest) ||
      b.policy.read_only !== readOnly ||
      JSON.stringify(b.policy.allowed_paths) !==
        JSON.stringify(contract.document.constraints.allowed_paths) ||
      b.policy.allowed_paths.length === 0 ||
      b.policy.allowed_paths.length > 64 ||
      b.policy.allowed_paths.some(
        (p) => p !== "*" && !safePath(p.endsWith("/") ? p.slice(0, -1) : p),
      ) ||
      JSON.stringify(b.policy.denied_actions) !==
        JSON.stringify([
          "commit",
          "push",
          "deploy",
          "network",
          "shell",
          "subagent",
          "delete",
          ...(readOnly ? ["write"] : []),
        ]) ||
      criteria.length === 0 ||
      criteria.length !== b.policy.criteria.length ||
      criteria.some(
        (c, i) =>
          !c.verifier_ref ||
          !supported.has(c.verifier_ref) ||
          c.node_id !== b.policy.criteria[i].node_id ||
          c.criterion_index !== b.policy.criteria[i].criterion_index ||
          c.verifier_ref !== b.policy.criteria[i].verifier_ref ||
          contract.document.nodes.find((n) => n.node_id === c.node_id)
            ?.acceptance_criteria[c.criterion_index].verification !==
            (c.verifier_ref === "verifier:contract-json-syntax/0.1.0"
              ? "TEST"
              : "ARTIFACT") ||
          (readOnly && c.verifier_ref !== "verifier:contract-no-changes/0.1.0"),
      ) ||
      (criteria.some(
        (c) => c.verifier_ref === "verifier:contract-no-changes/0.1.0",
      ) &&
        criteria.some(
          (c) => c.verifier_ref !== "verifier:contract-no-changes/0.1.0",
        ))
    )
      return false;
    if (
      proof &&
      (ref !== referenceKey(proof.reference) ||
        proof.policy_digest !== b.policy_digest ||
        proof.criteria_executed !== true ||
        proof.execution_policy_enforced !== true ||
        proof.natural_language_enforced !== false ||
        !/^sha256:[0-9a-f]{64}$/.test(proof.artifact_checksum) ||
        !/^(?:[0-9a-f]{40}|[0-9a-f]{64})$/.test(proof.base_commit) ||
        proof.checks.length !== criteria.length ||
        !Array.isArray(proof.changed_paths) ||
        proof.changed_paths.length > 128 ||
        proof.changed_paths.some(
          (p) => !allowedPath(p, b.policy.allowed_paths),
        ) ||
        new Set(proof.changed_paths).size !== proof.changed_paths.length ||
        (readOnly && proof.changed_paths.length !== 0) ||
        proof.checks.some(
          (c, i) =>
            typeof c.passed !== "boolean" ||
            c.node_id !== criteria[i].node_id ||
            c.criterion_index !== criteria[i].criterion_index ||
            c.verifier_ref !== criteria[i].verifier_ref ||
            (c.verifier_ref === "verifier:contract-source-patch/0.1.0" &&
              c.passed !== proof.changed_paths.length > 0) ||
            (c.verifier_ref === "verifier:contract-no-changes/0.1.0" &&
              c.passed !== (proof.changed_paths.length === 0)) ||
            (c.verifier_ref === "verifier:contract-json-syntax/0.1.0" &&
              c.passed &&
              !proof.changed_paths.some((p) =>
                p.toLowerCase().endsWith(".json"),
              )),
        ))
    )
      return false;
    return true;
  } catch {
    return false;
  }
}
