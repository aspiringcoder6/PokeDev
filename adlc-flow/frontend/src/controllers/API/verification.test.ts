import { webcrypto } from "node:crypto";
import { verificationFixture } from "@/components/adlc/VerificationPanel/test-fixtures";
import { api } from "./api";
import { downloadVerification, listVerifications } from "./verification";

jest.mock("./api", () => ({ api: { get: jest.fn() } }));

beforeEach(() => {
  jest.clearAllMocks();
  Object.defineProperty(globalThis, "crypto", {
    configurable: true,
    value: webcrypto,
  });
  URL.createObjectURL = jest.fn(() => "blob:offline-evidence");
  URL.revokeObjectURL = jest.fn();
  jest.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});
afterEach(() => jest.restoreAllMocks());

test("archive reads all bounded pages instead of silently hiding older sessions", async () => {
  const row = verificationFixture();
  (api.get as jest.Mock)
    .mockResolvedValueOnce({ data: Array.from({ length: 100 }, () => row) })
    .mockResolvedValueOnce({ data: [row] });
  expect(await listVerifications({ sessionId: "source-session" })).toHaveLength(
    101,
  );
  expect(api.get).toHaveBeenLastCalledWith(
    expect.stringContaining("source-session/verifications"),
    { params: { offset: 100, limit: 100 } },
  );
});

test("invalid archive response is not rendered as a verification", async () => {
  (api.get as jest.Mock).mockResolvedValue({ data: { verdict: "PASS" } });
  await expect(listVerifications({ runId: "run-one" })).rejects.toThrow();
});

test("download checks actual bytes, not just the server's claimed digest", async () => {
  const row = verificationFixture("SUBMITTED");
  (api.get as jest.Mock).mockResolvedValue({
    headers: { "x-adlc-content-digest": row.evidence_digest },
    data: { arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer },
  });
  await expect(downloadVerification("run-one", row)).rejects.toThrow(
    "Evidence checksum mismatch.",
  );
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});

test("download reference mismatch is rejected before reading bytes", async () => {
  const row = verificationFixture("SUBMITTED");
  const arrayBuffer = jest.fn();
  (api.get as jest.Mock).mockResolvedValue({
    headers: { "x-adlc-content-digest": "sha256:wrong" },
    data: { arrayBuffer },
  });
  await expect(downloadVerification("run-one", row)).rejects.toThrow(
    "Evidence reference mismatch.",
  );
  expect(arrayBuffer).not.toHaveBeenCalled();
});

test("checksummed evidence downloads once and releases its object URL", async () => {
  const row = verificationFixture("SUBMITTED");
  const bytes = new Uint8Array([1, 2, 3]);
  const hash = await webcrypto.subtle.digest("SHA-256", bytes);
  row.evidence_digest =
    "sha256:" +
    Array.from(new Uint8Array(hash), (b) =>
      b.toString(16).padStart(2, "0"),
    ).join("");
  (api.get as jest.Mock).mockResolvedValue({
    headers: { "x-adlc-content-digest": row.evidence_digest },
    data: { arrayBuffer: async () => bytes.buffer },
  });
  await downloadVerification("run-one", row);
  expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledTimes(1);
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:offline-evidence");
});
