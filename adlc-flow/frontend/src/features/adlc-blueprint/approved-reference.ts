import type { ContractReference } from "@/types/contracts";

export const APPROVED_REFERENCE_ERROR =
  "Paste an exact approved contract reference: schema_ref, contract_id, revision and content_digest. Approval and ownership are checked again when compiling.";
export function parseApprovedReference(text: string): ContractReference {
  let value;
  try {
    value = JSON.parse(text);
  } catch {
    throw new Error(APPROVED_REFERENCE_ERROR);
  }
  if (
    !value ||
    Array.isArray(value) ||
    typeof value !== "object" ||
    Object.keys(value).length !== 4 ||
    value.schema_ref !== "adlc://schemas/skilltree-contract/0.1" ||
    typeof value.contract_id !== "string" ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
      value.contract_id,
    ) ||
    !Number.isInteger(value.revision) ||
    value.revision < 1 ||
    value.revision > 512 ||
    typeof value.content_digest !== "string" ||
    !/^sha256:[0-9a-f]{64}$/.test(value.content_digest)
  ) {
    throw new Error(APPROVED_REFERENCE_ERROR);
  }
  return value as ContractReference;
}
