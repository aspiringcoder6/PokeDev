import { getBaseUrl } from "@/customization/utils/urls";
import type { ReplayRead, ReplayScope } from "@/types/replay";
import type {
  ExtensionCapabilities,
  ProposalCommand,
  ProposalRead,
  ScreenshotRead,
} from "@/types/test-extensions";
import { api } from "./api";

const root = `${getBaseUrl().replace(/\/?$/, "/")}adlc`;
const run = (id: string) => `${root}/runs/${encodeURIComponent(id)}`;
const proposals = (id: string) => `${run(id)}/test-proposals`;
const screenshots = (row: ReplayRead) =>
  `${run(row.plan.workflow_run_id)}/replay-screenshots/${encodeURIComponent(row.plan.plan_id)}`;
export async function testExtensionCapabilities(): Promise<ExtensionCapabilities> {
  return (
    await api.get<ExtensionCapabilities>(`${root}/test-extension-capabilities`)
  ).data;
}
export async function listTestProposals(
  scope: ReplayScope,
): Promise<ProposalRead[]> {
  const path =
    "runId" in scope
      ? proposals(scope.runId)
      : `${root}/harness-sessions/${encodeURIComponent(scope.sessionId)}/test-proposals`;
  const rows: ProposalRead[] = [];
  for (let offset = 0; offset <= 200; offset += 100) {
    const page = (
      await api.get<ProposalRead[]>(path, { params: { offset, limit: 100 } })
    ).data;
    if (
      !Array.isArray(page) ||
      page.length > 100 ||
      rows.length + page.length > 200
    )
      throw new Error("Invalid proposal archive.");
    rows.push(...page);
    if (page.length < 100) return rows;
  }
  return rows;
}
export async function testProposalTool(
  runId: string,
  command: ProposalCommand,
): Promise<ProposalRead> {
  return (await api.post<ProposalRead>(`${proposals(runId)}/tools`, command))
    .data;
}
export async function testProposalAction(
  runId: string,
  row: ProposalRead,
  operation: "approve" | "materialize",
): Promise<ProposalRead> {
  return (
    await api.post<ProposalRead>(
      `${proposals(runId)}/${encodeURIComponent(row.reference.proposal_id)}/${operation}`,
      { reference: row.reference },
    )
  ).data;
}
export async function listReplayScreenshots(
  row: ReplayRead,
): Promise<ScreenshotRead[]> {
  const result = (await api.get<ScreenshotRead[]>(screenshots(row))).data;
  if (!Array.isArray(result) || result.length > 4)
    throw new Error("Invalid screenshot archive.");
  return result;
}
export async function sha256(bytes: ArrayBuffer): Promise<string> {
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return (
    "sha256:" +
    Array.from(new Uint8Array(hash), (b) =>
      b.toString(16).padStart(2, "0"),
    ).join("")
  );
}
export async function loadReplayScreenshot(
  row: ReplayRead,
  image: ScreenshotRead,
): Promise<Blob> {
  if (
    image.affects_verdict !== false ||
    image.capture_provenance_verified !== false ||
    image.authority !== "SUPPLEMENTARY_UNTRUSTED" ||
    image.plan_id !== row.plan.plan_id ||
    image.plan_digest !== row.plan_digest ||
    image.execution_id !== row.execution_id ||
    image.case_evidence_digest !== row.evidence_digest ||
    image.candidate_digest !== row.plan.candidate.content_digest ||
    image.media_type !== "image/png" ||
    !Number.isInteger(image.byte_size) ||
    image.byte_size < 1 ||
    image.byte_size > 262144
  )
    throw new Error("Invalid screenshot binding.");
  const response = await api.get(
    `${screenshots(row)}/${encodeURIComponent(image.attachment_id)}`,
    { responseType: "blob" },
  );
  const blob = response.data as Blob;
  if (
    response.headers["x-adlc-content-digest"] !== image.content_digest ||
    blob.size !== image.byte_size ||
    blob.type !== "image/png"
  )
    throw new Error("Screenshot reference mismatch.");
  const bytes = await blob.arrayBuffer();
  if ((await sha256(bytes)) !== image.content_digest)
    throw new Error("Screenshot checksum mismatch.");
  const signature = new Uint8Array(bytes).slice(0, 8);
  if (
    signature.length !== 8 ||
    ![137, 80, 78, 71, 13, 10, 26, 10].every((b, i) => signature[i] === b)
  )
    throw new Error("Invalid raster.");
  return blob;
}
export async function attachReplayScreenshot(
  row: ReplayRead,
  file: File,
  caption: string,
  caseId: string,
  idempotencyKey: string,
): Promise<ScreenshotRead> {
  if (file.type !== "image/png" || !file.size || file.size > 262144)
    throw new Error("Use a PNG of at most 256 KiB.");
  const bytes = await file.arrayBuffer();
  const base64 = btoa(
    Array.from(new Uint8Array(bytes), (b) => String.fromCharCode(b)).join(""),
  );
  return (
    await api.post<ScreenshotRead>(screenshots(row), {
      plan_digest: row.plan_digest,
      execution_id: row.execution_id,
      case_id: caseId,
      caption,
      png_base64: base64,
      input_digest: await sha256(bytes),
      idempotency_key: idempotencyKey,
    })
  ).data;
}
