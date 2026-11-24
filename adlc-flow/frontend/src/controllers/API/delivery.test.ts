import {
  cycleFixture,
  cyclePlanningFixture,
  fixture,
  ids,
} from "../../../tests/delivery-workspace-preview/fixture";
import { api } from "./api";
import { deliveryApi, deliveryError } from "./delivery";

jest.mock("./api", () => ({ api: { get: jest.fn(), post: jest.fn() } }));
beforeEach(() => jest.clearAllMocks());
test("detailed planning sends exact cycle/spec proof, not approval or runtime authority", async () => {
  const row = cyclePlanningFixture();
  const operation = row.cycle!.planning_operations![0];
  (api.post as jest.Mock).mockResolvedValue({ data: operation });
  await deliveryApi.generateDetailed(
    row,
    "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
  );
  expect(api.post).toHaveBeenCalledWith(
    expect.stringContaining(`/cycles/${row.cycle!.id}/planning/generate`),
    {
      expected_revision: row.revision,
      cycle_id: row.cycle!.id,
      spec_digest: row.cycle!.spec_digest,
      workflow_digest: row.workflow_digest,
      command_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
    },
  );
});
test.each(["cycle", "spec", "graph"])(
  "planning response rejects mismatched %s binding",
  async (mismatch) => {
    const row = cyclePlanningFixture();
    const operation = { ...row.cycle!.planning_operations![0] };
    if (mismatch === "cycle") operation.cycle_id = ids.flow;
    if (mismatch === "spec") operation.spec_digest = `sha256:${"f".repeat(64)}`;
    if (mismatch === "graph")
      operation.preview_plan = {
        ...operation.preview_plan!,
        metadata: { cycle_id: ids.flow },
      };
    (api.post as jest.Mock).mockResolvedValue({ data: operation });
    await expect(
      deliveryApi.generateDetailed(row, "dddddddd-dddd-4ddd-8ddd-dddddddddddd"),
    ).rejects.toThrow();
  },
);
test("cycle commands carry selection/version proof and no claimed authority", async () => {
  const row = cycleFixture();
  const command = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
  (api.post as jest.Mock).mockResolvedValue({
    data: { revision: 5, cycle_id: "a2222222-2222-4222-8222-222222222222" },
  });
  await deliveryApi.prepareCycle(row, "CSV only", command);
  expect(api.post).toHaveBeenCalledWith(
    expect.stringContaining(`${ids.row}/cycles`),
    {
      expected_revision: row.revision,
      workflow_digest: row.workflow_digest,
      cycle_id: row.cycle!.id,
      command_id: command,
      predecessor_id: row.cycle!.id,
      goal: "CSV only",
    },
  );
});

test("reading another cycle passes its ID without changing server state", async () => {
  const row = cycleFixture("draft");
  (api.get as jest.Mock).mockResolvedValue({ data: row });
  expect((await deliveryApi.get(ids.row, row.cycle!.id)).plan).toBeNull();
  expect(api.get).toHaveBeenCalledWith(expect.stringContaining(ids.row), {
    params: { cycle_id: row.cycle!.id },
  });
  expect(api.post).not.toHaveBeenCalled();
});
test.each(["wrong-cycle", "borrowed-run", "foreign-product", "missing-cycles"])(
  "mismatched cycle data fails closed: %s",
  async (mismatch) => {
    const row = cycleFixture("draft");
    if (mismatch === "wrong-cycle")
      row.cycle!.id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
    if (mismatch === "borrowed-run") row.run = fixture(3).run;
    if (mismatch === "foreign-product") row.cycle!.delivery_id = ids.flow;
    if (mismatch === "missing-cycles") row.cycles = undefined;
    (api.get as jest.Mock).mockResolvedValue({ data: row });
    await expect(
      deliveryApi.get(ids.row, "a2222222-2222-4222-8222-222222222222"),
    ).rejects.toThrow();
  },
);
test("review commands send immutable version proof, not role, actor or approval status", async () => {
  const row = fixture(2);
  (api.post as jest.Mock).mockResolvedValue({
    data: { revision: 5, approved: true },
  });
  await deliveryApi.approvePlan(row);
  expect(api.post).toHaveBeenCalledWith(
    expect.stringContaining(`${ids.row}/approve-plan`),
    {
      expected_revision: 4,
      workflow_digest: row.workflow_digest,
      plan_digest: row.plan_digest,
    },
  );
});
test("malformed server permissions cannot enable controls", async () => {
  (api.get as jest.Mock).mockResolvedValue({
    data: { ...fixture(1), permissions: { write: "true", execute: true } },
  });
  await expect(deliveryApi.get(ids.row)).rejects.toThrow();
});
test("unknown acknowledgement is never treated as success", async () => {
  (api.post as jest.Mock).mockResolvedValue({ data: { accepted: true } });
  await expect(deliveryApi.start(fixture(2))).rejects.toThrow();
  expect(api.post).toHaveBeenCalledTimes(1);
});
test("pagination uses the server offset and validates every returned snapshot", async () => {
  (api.get as jest.Mock).mockResolvedValue({
    data: { items: [fixture(1)], total: 31, offset: 30 },
  });
  expect((await deliveryApi.list(30)).items).toHaveLength(1);
  expect(api.get).toHaveBeenCalledWith(
    expect.stringContaining("adlc/deliveries"),
    { params: { offset: 30, limit: 30 } },
  );
});
test("private details and arbitrary errors are never reflected as trusted UI copy", () => {
  expect(
    deliveryError({
      response: {
        data: { detail: { code: "UNKNOWN", message: "secret-value" } },
      },
    }),
  ).not.toContain("secret-value");
});

test("unavailable iteration runtime explains that dispatch has not happened", () => {
  expect(
    deliveryError({
      response: {
        data: { detail: { code: "DELIVERY_HARNESS_LOOP_NOT_READY" } },
      },
    }),
  ).toContain("Chưa tạo lượt chạy hay gọi agent");
});
