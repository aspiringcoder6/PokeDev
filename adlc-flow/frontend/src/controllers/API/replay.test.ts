import { createHash, webcrypto } from "node:crypto";
import { replayFixture } from "@/components/adlc/ReplayPanel/test-fixtures";
import { api } from "./api";
import { downloadReplay, listReplays, replayAction } from "./replay";

jest.mock("./api", () => ({ api: { get: jest.fn(), post: jest.fn() } }));
beforeEach(() => {
  jest.clearAllMocks();
  Object.defineProperty(globalThis, "crypto", {
    configurable: true,
    value: webcrypto,
  });
  URL.createObjectURL = jest.fn(() => "blob:test-owned-evidence");
  URL.revokeObjectURL = jest.fn();
  jest.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});
afterEach(() => jest.restoreAllMocks());
test("reads all bounded archive pages with exact session scope", async () => {
  (api.get as jest.Mock)
    .mockResolvedValueOnce({
      data: Array.from({ length: 100 }, () => replayFixture()),
    })
    .mockResolvedValueOnce({ data: [replayFixture()] });
  expect(await listReplays({ sessionId: "source-session" })).toHaveLength(101);
  expect(api.get).toHaveBeenLastCalledWith(
    expect.stringContaining("source-session/replays"),
    { params: { offset: 100, limit: 100 } },
  );
});
test("malformed archive or wrong header cannot become an evidence download", async () => {
  (api.get as jest.Mock).mockResolvedValue({ data: {} });
  await expect(listReplays({ runId: "run-one" })).rejects.toThrow();
  (api.get as jest.Mock).mockResolvedValue({
    headers: { "x-adlc-content-digest": "wrong" },
  });
  await expect(
    downloadReplay("run-one", replayFixture("SUBMITTED"), "junit"),
  ).rejects.toThrow("reference mismatch");
});
test.each(["json", "junit"] as const)(
  "%s actual bytes are checked before downloading",
  async (kind) => {
    const row = replayFixture("SUBMITTED");
    (api.get as jest.Mock).mockResolvedValue({
      headers: {
        "x-adlc-content-digest":
          kind === "junit" ? row.receipt!.junit_digest : row.evidence_digest,
      },
      data: { arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer },
    });
    await expect(downloadReplay("run-one", row, kind)).rejects.toThrow(
      "checksum mismatch",
    );
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  },
);
test("checksummed JUnit download is scoped and object URL released", async () => {
  const row = replayFixture("SUBMITTED"),
    bytes = new Uint8Array([1, 2, 3]);
  row.receipt!.junit_digest =
    "sha256:" + createHash("sha256").update(bytes).digest("hex");
  (api.get as jest.Mock).mockResolvedValue({
    headers: { "x-adlc-content-digest": row.receipt!.junit_digest },
    data: { arrayBuffer: async () => bytes.buffer },
  });
  await downloadReplay("run-one", row, "junit");
  expect(api.get).toHaveBeenCalledWith(
    expect.stringContaining("plan-one/evidence/junit"),
    { responseType: "blob" },
  );
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:test-owned-evidence");
});
test("explicit cancellation sends exact plan digest once; no automatic retries", async () => {
  const row = replayFixture("RUNNING");
  (api.post as jest.Mock).mockRejectedValue(new Error("unknown"));
  await expect(replayAction("run-one", row, "cancel")).rejects.toThrow();
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(api.post).toHaveBeenCalledWith(
    expect.stringContaining("plan-one/cancel"),
    { plan_digest: row.plan_digest },
  );
});
