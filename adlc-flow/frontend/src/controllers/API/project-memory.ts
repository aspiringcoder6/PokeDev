import { getBaseUrl } from "@/customization/utils/urls";
import type {
  MemoryQuery,
  MemoryRead,
  MemoryScope,
  MemoryView,
} from "@/types/project-memory";
import { api } from "./api";

const root = `${getBaseUrl().replace(/\/?$/, "/")}adlc`;
const runPath = (id: string) =>
  `${root}/runs/${encodeURIComponent(id)}/project-memory`;
export async function memoryView(scope: MemoryScope): Promise<MemoryView> {
  const path =
    "runId" in scope
      ? runPath(scope.runId)
      : `${root}/harness-sessions/${encodeURIComponent(scope.sessionId)}/project-memory`;
  let result: MemoryView | undefined;
  for (let offset = 0; offset <= 200; offset += 100) {
    const page = (
      await api.get<MemoryView>(path, { params: { limit: 100, offset } })
    ).data;
    if (
      !page?.capabilities ||
      typeof page.capabilities.profile_ref !== "string" ||
      typeof page.capabilities.enabled !== "boolean" ||
      typeof page.capabilities.configured !== "boolean" ||
      (page.binding !== null &&
        (!page.binding ||
          typeof page.binding.source_ref !== "string" ||
          typeof page.binding.project_id !== "string" ||
          typeof page.binding.workflow_run_id !== "string" ||
          typeof page.binding.base_commit !== "string")) ||
      !Array.isArray(page?.records) ||
      page.records.length > 100 ||
      (result?.records.length ?? 0) + page.records.length > 200
    )
      throw new Error("MEMORY_RESPONSE_INVALID");
    result = result
      ? { ...result, records: [...result.records, ...page.records] }
      : page;
    if (page.records.length < 100) return result;
  }
  return result!;
}
export async function queryMemory(
  runId: string,
  command: MemoryQuery,
): Promise<MemoryRead> {
  return (await api.post<MemoryRead>(`${runPath(runId)}/context`, command))
    .data;
}
export async function checkMemory(runId: string): Promise<{ ready: boolean }> {
  // No dataset/URL/tenant/body passes through, even for a readiness check.
  return (await api.post(`${runPath(runId)}/health`)).data;
}
