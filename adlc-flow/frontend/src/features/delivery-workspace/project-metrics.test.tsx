import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import {
  projectMetrics,
  type ProjectMetricSummary,
} from "@/controllers/API/project-metrics";
import ProjectMetrics, { metricDuration } from "./project-metrics";

jest.mock("@/controllers/API/project-metrics", () => ({
  projectMetrics: {
    read: jest.fn(),
    refresh: jest.fn(),
    savePricing: jest.fn(),
  },
}));
const usage = {
  tokens: null,
  sessions: 2,
  measured_sessions: 0,
  priced_sessions: 0,
  cost_usd: null,
  cost_kind: "unavailable",
  partial: true,
  last_measured_at: null,
};
const fixture = (): ProjectMetricSummary => ({
  project_id: "project",
  days: 30,
  models: [{ provider: "netmind", model: "test-model" }],
  totals: {
    runs: 1,
    finished: 1,
    succeeded: 1,
    success_rate: 1,
    unconfirmed: 0,
    average_active_seconds: 120,
    human_wait_seconds: 30,
    human_interventions: 1,
    repair_rounds: 1,
  },
  usage,
  pricing: { revision: 1, rates: [], updated_at: null },
  refresh: { running: false, updated_at: null, error_code: null },
  runs: [
    {
      run_id: "run",
      title: "Improve the counter",
      state: "SUCCEEDED",
      created_at: "2026-10-27T10:00:00Z",
      workflow: { name: "Human review flow", revision: 3, workflow_id: "flow" },
      timing: {
        total_seconds: 160,
        active_seconds: 120,
        active_source: "derived_from_timestamps",
        human_wait_seconds: 30,
        approval_wait_seconds: 10,
        human_interventions: 1,
        repair_rounds: 1,
        verification_attempts: 2,
      },
      usage,
    },
  ],
});
function setup(data = fixture()) {
  (projectMetrics.read as jest.Mock).mockResolvedValue(data);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const result = render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ProjectMetrics
          identity="owner"
          project={
            {
              project_id: "project",
              name: "Counter",
              repository: "admin/counter",
            } as never
          }
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...result, client };
}
beforeEach(() => jest.clearAllMocks());

test("missing telemetry is unknown and lineage opens the exact run and workflow", async () => {
  const { unmount, client } = setup();
  expect(await screen.findByText("100%")).toBeInTheDocument();
  expect(screen.getAllByText("Chưa có dữ liệu").length).toBeGreaterThan(1);
  expect(screen.getByRole("link", { name: /Xem lượt/ })).toHaveAttribute(
    "href",
    "/work?project=project&run=run",
  );
  expect(
    screen.getByRole("link", { name: /Human review flow/ }),
  ).toHaveAttribute(
    "href",
    "/work?project=project&view=workflows&workflow=flow",
  );
  expect(screen.getByText(/0\/2 session có số liệu/)).toBeInTheDocument();
  expect(projectMetrics.savePricing).not.toHaveBeenCalled();
  unmount();
  client.clear();
});

test("pricing requires all explicit rates including cache and saves with current revision", async () => {
  const { unmount, client } = setup();
  await screen.findByText("100%");
  fireEvent.click(screen.getByText("Bảng giá dùng để ước tính"));
  fireEvent.click(screen.getByRole("button", { name: "Thêm giá model" }));
  expect(screen.getByRole("button", { name: "Lưu bảng giá" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Nguồn / ngày áp dụng giá"), {
    target: { value: "Contract 2026-10-27" },
  });
  for (const [label, value] of [
    ["Đầu vào thường", "1"],
    ["Đọc cache", "0"],
    ["Ghi cache", "0"],
    ["Đầu ra", "3"],
  ])
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  (projectMetrics.savePricing as jest.Mock).mockResolvedValue({});
  fireEvent.click(screen.getByRole("button", { name: "Lưu bảng giá" }));
  await waitFor(() =>
    expect(projectMetrics.savePricing).toHaveBeenCalledWith("project", 1, [
      {
        provider: "netmind",
        model: "test-model",
        source: "Contract 2026-10-27",
        input: 1,
        cache_read: 0,
        cache_write: 0,
        output: 3,
      },
    ]),
  );
  unmount();
  client.clear();
});

test("source failure keeps measured token labels and never labels an estimate as a bill", async () => {
  const data = fixture();
  data.refresh.error_code = "LIVE_METRICS_SOURCE_UNAVAILABLE";
  data.usage = {
    ...usage,
    tokens: 1234,
    measured_sessions: 1,
    cost_usd: 0.0012,
    priced_sessions: 1,
  };
  const { unmount, client } = setup(data);
  expect(
    await screen.findByText(/Chưa đọc được số liệu mới/),
  ).toBeInTheDocument();
  expect(screen.getByText("1.234")).toBeInTheDocument();
  expect(screen.getByText("Chi phí ước tính")).toBeInTheDocument();
  expect(metricDuration(null)).toBe("Chưa có dữ liệu");
  unmount();
  client.clear();
});
