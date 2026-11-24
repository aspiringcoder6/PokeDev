import { memoryViewFixture } from "@/components/adlc/MemoryPanel/test-fixtures";
import { api } from "./api";
import { checkMemory, memoryView, queryMemory } from "./project-memory";

jest.mock("./api", () => ({ api: { get: jest.fn(), post: jest.fn() } }));
beforeEach(() => jest.clearAllMocks());
test("session/run API paths are scoped and pagination bounded", async () => {
  (api.get as jest.Mock).mockResolvedValue({ data: memoryViewFixture() });
  await memoryView({ sessionId: "session/one" });
  expect(api.get).toHaveBeenCalledWith(
    expect.stringContaining("/harness-sessions/session%2Fone/project-memory"),
    { params: { limit: 100, offset: 0 } },
  );
});
test("malformed archive refuses silent unbounded pagination", async () => {
  (api.get as jest.Mock).mockResolvedValue({
    data: { records: new Array(101).fill({}) },
  });
  await expect(memoryView({ runId: "run-one" })).rejects.toThrow(
    "MEMORY_RESPONSE_INVALID",
  );
});
test("query and health cannot choose a backend dataset or destination", async () => {
  (api.post as jest.Mock).mockResolvedValue({ data: { ready: true } });
  const command = { query: "earlier", top_k: 5, idempotency_key: "one" };
  await queryMemory("run-one", command);
  await checkMemory("run-one");
  expect(api.post).toHaveBeenNthCalledWith(
    1,
    expect.stringContaining("/runs/run-one/project-memory/context"),
    command,
  );
  expect(api.post).toHaveBeenNthCalledWith(
    2,
    expect.stringContaining("/runs/run-one/project-memory/health"),
  );
});
