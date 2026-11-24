import { webcrypto } from "node:crypto";
import { replayFixture } from "@/components/adlc/ReplayPanel/test-fixtures";
import { proposalFixture } from "@/components/adlc/TestProposalPanel/test-fixtures";
import { api } from "./api";
import {
  listTestProposals,
  loadReplayScreenshot,
  testProposalAction,
  testProposalTool,
} from "./test-extensions";

jest.mock("./api", () => ({ api: { get: jest.fn(), post: jest.fn() } }));
beforeEach(() => jest.clearAllMocks());
test("exact references and scoped session reads never expose an execute endpoint", async () => {
  (api.get as jest.Mock).mockResolvedValue({ data: [] });
  await listTestProposals({ sessionId: "session/one" });
  expect(api.get).toHaveBeenCalledWith(
    expect.stringContaining("/harness-sessions/session%2Fone/test-proposals"),
    { params: { offset: 0, limit: 100 } },
  );
  const row = proposalFixture("READY_FOR_REVIEW");
  (api.post as jest.Mock).mockResolvedValue({ data: row });
  await testProposalAction("run-one", row, "approve");
  expect(api.post).toHaveBeenCalledWith(
    expect.stringContaining("/proposal-one/approve"),
    { reference: row.reference },
  );
  await testProposalTool("run-one", {
    operation: "get_status",
    proposal_id: row.reference.proposal_id,
  });
  expect(api.post).toHaveBeenLastCalledWith(
    expect.stringContaining("/test-proposals/tools"),
    { operation: "get_status", proposal_id: "proposal-one" },
  );
});
test("screenshot loader checks bytes/hash/mime before a Blob may be previewed", async () => {
  Object.defineProperty(globalThis, "crypto", {
    configurable: true,
    value: webcrypto,
  });
  const row = replayFixture("READY_FOR_SUBMISSION"),
    bytes = new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10, 0]).buffer;
  const hash =
    "sha256:" +
    Buffer.from(await webcrypto.subtle.digest("SHA-256", bytes)).toString(
      "hex",
    );
  const image = {
    affects_verdict: false,
    capture_provenance_verified: false,
    authority: "SUPPLEMENTARY_UNTRUSTED",
    plan_id: row.plan.plan_id,
    plan_digest: row.plan_digest,
    execution_id: row.execution_id,
    candidate_digest: row.plan.candidate.content_digest,
    case_evidence_digest: row.evidence_digest,
    content_digest: hash,
    media_type: "image/png",
    byte_size: 9,
    attachment_id: "image-one",
  } as Parameters<typeof loadReplayScreenshot>[1];
  const blob = {
    size: 9,
    type: "image/png",
    arrayBuffer: async () => bytes,
  } as Blob;
  (api.get as jest.Mock).mockResolvedValue({
    data: blob,
    headers: { "x-adlc-content-digest": hash },
  });
  expect(await loadReplayScreenshot(row, image)).toBe(blob);
  (api.get as jest.Mock).mockResolvedValue({
    data: { ...blob, arrayBuffer: async () => new Uint8Array(9).buffer },
    headers: { "x-adlc-content-digest": hash },
  });
  await expect(loadReplayScreenshot(row, image)).rejects.toThrow("checksum");
  await expect(
    loadReplayScreenshot(row, { ...image, affects_verdict: true as false }),
  ).rejects.toThrow("binding");
});
