import { getBaseUrl } from "@/customization/utils/urls";
import type {
  CreateReplayInput,
  ReplayCapabilities,
  ReplayRead,
  ReplayScope,
} from "@/types/replay";
import { api } from "./api";

const root = `${getBaseUrl().replace(/\/?$/, "/")}adlc`;
const runPath = (id: string) =>
  `${root}/runs/${encodeURIComponent(id)}/replays`;

export async function replayCapabilities(): Promise<ReplayCapabilities> {
  return (await api.get<ReplayCapabilities>(`${root}/replay-capabilities`))
    .data;
}
export async function listReplays(scope: ReplayScope): Promise<ReplayRead[]> {
  const path =
    "runId" in scope
      ? runPath(scope.runId)
      : `${root}/harness-sessions/${encodeURIComponent(scope.sessionId)}/replays`;
  const rows: ReplayRead[] = [];
  for (let offset = 0; offset <= 200; offset += 100) {
    const page = (
      await api.get<ReplayRead[]>(path, { params: { offset, limit: 100 } })
    ).data;
    if (
      !Array.isArray(page) ||
      page.length > 100 ||
      rows.length + page.length > 200
    )
      throw new Error("Invalid replay archive.");
    rows.push(...page);
    if (page.length < 100) return rows;
  }
  return rows;
}
export async function createReplay(
  runId: string,
  input: CreateReplayInput,
): Promise<ReplayRead> {
  return (await api.post<ReplayRead>(runPath(runId), input)).data;
}
export async function replayAction(
  runId: string,
  row: ReplayRead,
  operation: "approve" | "execute" | "reconcile" | "submit" | "cancel",
): Promise<ReplayRead> {
  return (
    await api.post<ReplayRead>(
      `${runPath(runId)}/${encodeURIComponent(row.plan.plan_id)}/${operation}`,
      { plan_digest: row.plan_digest },
    )
  ).data;
}
export async function downloadReplay(
  runId: string,
  row: ReplayRead,
  kind: "json" | "junit",
): Promise<void> {
  const expected =
    kind === "junit" ? row.receipt?.junit_digest : row.evidence_digest;
  if (!expected) throw new Error("Evidence unavailable.");
  const response = await api.get(
    `${runPath(runId)}/${encodeURIComponent(row.plan.plan_id)}/evidence/${kind}`,
    { responseType: "blob" },
  );
  if (response.headers["x-adlc-content-digest"] !== expected)
    throw new Error("Evidence reference mismatch.");
  const bytes = await (response.data as Blob).arrayBuffer();
  if (bytes.byteLength > (kind === "junit" ? 32768 : 262144))
    throw new Error("Evidence exceeds its limit.");
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  const actual =
    "sha256:" +
    Array.from(new Uint8Array(hash), (b) =>
      b.toString(16).padStart(2, "0"),
    ).join("");
  if (actual !== expected) throw new Error("Evidence checksum mismatch.");
  const url = URL.createObjectURL(response.data);
  try {
    const link = document.createElement("a");
    link.href = url;
    link.download = `${row.plan.plan_id}.${kind === "junit" ? "junit.xml" : "replay.json"}`;
    link.click();
  } finally {
    URL.revokeObjectURL(url);
  }
}
