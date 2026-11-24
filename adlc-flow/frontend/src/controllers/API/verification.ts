import { getBaseUrl } from "@/customization/utils/urls";
import type { ContractReference } from "@/types/contracts";
import type {
  VerificationCandidates,
  VerificationCapabilities,
  VerificationCase,
  VerificationRead,
  VerificationScope,
} from "@/types/verification";
import { api } from "./api";

const root = `${getBaseUrl().replace(/\/?$/, "/")}adlc`;
const runPath = (runId: string) =>
  `${root}/runs/${encodeURIComponent(runId)}/verifications`;

export async function verificationCapabilities(): Promise<VerificationCapabilities> {
  return (
    await api.get<VerificationCapabilities>(`${root}/verification-capabilities`)
  ).data;
}
export async function verificationCandidates(
  runId: string,
): Promise<VerificationCandidates> {
  return (
    await api.get<VerificationCandidates>(
      `${root}/runs/${encodeURIComponent(runId)}/verification-candidates`,
    )
  ).data;
}
export async function listVerifications(
  scope: VerificationScope,
): Promise<VerificationRead[]> {
  const path =
    "runId" in scope
      ? runPath(scope.runId)
      : `${root}/harness-sessions/${encodeURIComponent(scope.sessionId)}/verifications`;
  const result: VerificationRead[] = [];
  // The archive is bounded to 200 plans. Never silently show just its first page.
  for (let offset = 0; offset <= 200; offset += 100) {
    const page = (
      await api.get<VerificationRead[]>(path, {
        params: { offset, limit: 100 },
      })
    ).data;
    if (
      !Array.isArray(page) ||
      page.length > 100 ||
      result.length + page.length > 200
    )
      throw new Error("Invalid verification archive.");
    result.push(...page);
    if (page.length < 100) return result;
  }
  return result;
}
export async function createVerification(
  runId: string,
  input: {
    source_task_id: string;
    artifact_id: string;
    file: string;
    contract_reference: ContractReference;
    cases: VerificationCase[];
    idempotency_key: string;
    timeout_seconds: number;
  },
): Promise<VerificationRead> {
  return (await api.post<VerificationRead>(runPath(runId), input)).data;
}
export async function verificationAction(
  runId: string,
  record: VerificationRead,
  operation: "approve" | "execute" | "reconcile" | "submit",
): Promise<VerificationRead> {
  return (
    await api.post<VerificationRead>(
      `${runPath(runId)}/${encodeURIComponent(record.plan.plan_id)}/${operation}`,
      { plan_digest: record.plan_digest },
    )
  ).data;
}
export async function downloadVerification(
  runId: string,
  record: VerificationRead,
): Promise<void> {
  if (!record.evidence_digest) throw new Error("Evidence is unavailable.");
  const result = await api.get(
    `${runPath(runId)}/${encodeURIComponent(record.plan.plan_id)}/evidence`,
    { responseType: "blob" },
  );
  if (result.headers["x-adlc-content-digest"] !== record.evidence_digest)
    throw new Error("Evidence reference mismatch.");
  const bytes = await (result.data as Blob).arrayBuffer();
  if (bytes.byteLength > 131072) throw new Error("Evidence exceeds its limit.");
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  const actual =
    "sha256:" +
    Array.from(new Uint8Array(hash), (b) =>
      b.toString(16).padStart(2, "0"),
    ).join("");
  if (actual !== record.evidence_digest)
    throw new Error("Evidence checksum mismatch.");
  const url = URL.createObjectURL(result.data);
  try {
    const link = document.createElement("a");
    link.href = url;
    link.download = `${record.plan.plan_id}.verification.json`;
    link.click();
  } finally {
    URL.revokeObjectURL(url);
  }
}
