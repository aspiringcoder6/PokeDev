import { getBaseUrl } from "@/customization/utils/urls";
import type { ContractExecutionRead } from "@/types/contractExecution";
import type {
  ContractRead,
  ContractReference,
  ContractToolResult,
  ContractViewerCapabilities,
} from "@/types/contracts";
import { api } from "./api";

const root = `${getBaseUrl().replace(/\/?$/, "/")}adlc`;
const runRoot = (runId: string) =>
  `${root}/runs/${encodeURIComponent(runId)}/contracts`;

export async function listContractExecutions(
  scope: { runId: string } | { sessionId: string },
): Promise<ContractExecutionRead[]> {
  const url =
    "runId" in scope
      ? `${root}/runs/${encodeURIComponent(scope.runId)}/contract-executions`
      : `${root}/harness-sessions/${encodeURIComponent(scope.sessionId)}/contract-executions`;
  if ("sessionId" in scope)
    return (await api.get<ContractExecutionRead[]>(url)).data;
  const result: ContractExecutionRead[] = [];
  for (let offset = 0; offset < 1000; offset += 100) {
    const page = (
      await api.get<ContractExecutionRead[]>(url, {
        params: { limit: 100, offset },
      })
    ).data;
    result.push(...page);
    if (page.length < 100) break;
  }
  return result;
}

export async function getContractViewerCapabilities(): Promise<ContractViewerCapabilities> {
  return (await api.get<ContractViewerCapabilities>(`${root}/contract-viewer`))
    .data;
}

export async function listContracts(
  scope: { runId: string } | { sessionId: string },
): Promise<ContractRead[]> {
  const url =
    "runId" in scope
      ? runRoot(scope.runId)
      : `${root}/harness-sessions/${encodeURIComponent(scope.sessionId)}/contracts`;
  const result: ContractRead[] = [];
  // Bounded pagination, not a global/latest-session cache. No head is silently hidden.
  for (let offset = 0; offset < 1000; offset += 100) {
    const page = (
      await api.get<ContractRead[]>(url, { params: { limit: 100, offset } })
    ).data;
    result.push(...page);
    if (page.length < 100) break;
  }
  return result;
}

export async function readContract(
  runId: string,
  id: string,
  revision: number,
): Promise<ContractRead> {
  return (
    await api.get<ContractRead>(`${runRoot(runId)}/${encodeURIComponent(id)}`, {
      params: { revision },
    })
  ).data;
}

export async function approveContract(
  runId: string,
  reference: ContractReference,
  idempotencyKey: string,
): Promise<ContractToolResult> {
  return (
    await api.post<ContractToolResult>(
      `${runRoot(runId)}/${encodeURIComponent(reference.contract_id)}/approve`,
      {
        reference,
        idempotency_key: idempotencyKey,
      },
    )
  ).data;
}

export async function forkContract(
  runId: string,
  reference: ContractReference,
  idempotencyKey: string,
): Promise<ContractToolResult> {
  return (
    await api.post<ContractToolResult>(
      `${runRoot(runId)}/${encodeURIComponent(reference.contract_id)}/fork`,
      {
        reference,
        idempotency_key: idempotencyKey,
      },
    )
  ).data;
}

export async function downloadContract(
  runId: string,
  reference: ContractReference,
): Promise<void> {
  const response = await api.get(
    `${runRoot(runId)}/${encodeURIComponent(reference.contract_id)}/file`,
    {
      params: { revision: reference.revision },
      responseType: "blob",
    },
  );
  if (response.headers["x-adlc-content-digest"] !== reference.content_digest) {
    throw new Error(
      "The downloaded reference changed. Refresh before downloading.",
    );
  }
  const url = URL.createObjectURL(response.data);
  try {
    const link = document.createElement("a");
    link.href = url;
    link.download = `${reference.contract_id}.r${reference.revision}.roadmap.json`;
    link.click();
  } finally {
    URL.revokeObjectURL(url);
  }
}
