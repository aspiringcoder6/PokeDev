import "@testing-library/jest-dom";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { workspaceDashboard } from "@/controllers/API/workspace-dashboard";
import { liveWorkflows } from "@/controllers/API/live-workflows";
import WorkspaceDashboard from "./workspace-dashboard";
import { dashboardFixture } from "./workspace-dashboard.test-data";
import {
  dashboardHistoryUrl,
  localDashboardDay,
  matchesDashboardHistory,
  waitingAge,
} from "./workspace-dashboard-model";

afterEach(() => jest.restoreAllMocks());
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const result = render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <WorkspaceDashboard identity="owner" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return () => {
    result.unmount();
    client.clear();
  };
}

test("real snapshot metrics have explicit denominators and links retain project, date and state filters", async () => {
  const read = jest
    .spyOn(workspaceDashboard, "read")
    .mockResolvedValue(dashboardFixture());
  const plan = jest.spyOn(liveWorkflows, "plan"),
    execute = jest.spyOn(liveWorkflows, "execute");
  const stop = mount();
  const rate = await screen.findByRole("link", {
    name: "Tỷ lệ thành công: 50%",
  });
  expect(rate).toHaveAttribute(
    "href",
    expect.stringContaining("status=SUCCEEDED"),
  );
  expect(screen.getByText(/1\/2 lượt đã kết thúc/)).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Đang thực hiện: 1" }),
  ).not.toHaveAttribute("href", expect.stringContaining("from="));
  fireEvent.change(screen.getByLabelText("Project trên dashboard"), {
    target: { value: "project-a" },
  });
  await waitFor(() => expect(read).toHaveBeenCalledWith(28, "project-a"));
  fireEvent.click(screen.getByRole("button", { name: "7 ngày" }));
  await waitFor(() => expect(read).toHaveBeenCalledWith(7, "project-a"));
  expect(plan).not.toHaveBeenCalled();
  expect(execute).not.toHaveBeenCalled();
  stop();
});

test("the inbox includes old work, filters kinds and points directly at the bound question or plan", async () => {
  jest.spyOn(workspaceDashboard, "read").mockResolvedValue(dashboardFixture());
  const answer = jest.spyOn(liveWorkflows, "answer");
  const stop = mount();
  const inbox = within(
    await screen.findByRole("region", { name: "Cần bạn xử lý" }),
  );
  await inbox.findByText("Chọn cách xử lý dữ liệu");
  expect(inbox.getByRole("link", { name: "Trả lời" })).toHaveAttribute(
    "href",
    "/work?project=project-a&run=active&focus=q1",
  );
  expect(inbox.getByRole("link", { name: "Xem kế hoạch" })).toHaveAttribute(
    "href",
    expect.stringContaining("tab=spec"),
  );
  expect(inbox.getByText("Chưa có mốc chờ")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Loại việc cần xử lý"), {
    target: { value: "inputs" },
  });
  expect(
    inbox.queryByText("Kế hoạch đang chờ bạn duyệt"),
  ).not.toBeInTheDocument();
  expect(inbox.getByText("Chọn cách xử lý dữ liệu")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Tìm trong hàng chờ"), {
    target: { value: "không khớp" },
  });
  expect(inbox.getByText("Không có việc khớp bộ lọc")).toBeInTheDocument();
  expect(answer).not.toHaveBeenCalled();
  stop();
});

test("unavailable sources never turn into an empty healthy inbox or a fabricated 100 percent rate", async () => {
  const fixture = dashboardFixture();
  fixture.sources.errors = ["questions"];
  fixture.attention = [];
  fixture.totals.attention_now = 0;
  fixture.totals.success_rate = null;
  fixture.totals.finished = 0;
  jest.spyOn(workspaceDashboard, "read").mockResolvedValue(fixture);
  const stop = mount();
  await screen.findByRole("link", { name: "Cần bạn xử lý: —" });
  expect(
    screen.getByRole("link", { name: "Tỷ lệ thành công: —" }),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Chưa xác nhận được toàn bộ hàng chờ"),
  ).toBeInTheDocument();
  expect(
    screen.queryByText("Không có việc nào đang cần bạn xử lý"),
  ).not.toBeInTheDocument();
  stop();
});

test("a refresh outage retains the previous snapshot with an explicit stale-data message", async () => {
  const read = jest
    .spyOn(workspaceDashboard, "read")
    .mockResolvedValueOnce(dashboardFixture())
    .mockRejectedValue(new Error("offline"));
  const stop = mount();
  await screen.findByRole("link", { name: "Lượt tạo trong 28 ngày: 3" });
  fireEvent.click(screen.getByRole("button", { name: "Cập nhật dashboard" }));
  await waitFor(() => expect(read).toHaveBeenCalledTimes(2));
  await screen.findByText(/Đang giữ số liệu ở lần đọc gần nhất/);
  expect(
    screen.getByRole("link", { name: "Lượt tạo trong 28 ngày: 3" }),
  ).toBeInTheDocument();
  stop();
});

test("revoked access hides cached workspace totals instead of treating it as a temporary outage", async () => {
  jest
    .spyOn(workspaceDashboard, "read")
    .mockResolvedValueOnce(dashboardFixture())
    .mockRejectedValue({
      response: { status: 403, data: { detail: { code: "DENIED" } } },
    });
  const stop = mount();
  await screen.findByRole("link", { name: "Lượt tạo trong 28 ngày: 3" });
  fireEvent.click(screen.getByRole("button", { name: "Cập nhật dashboard" }));
  await screen.findByText(/Chưa đọc được dashboard/);
  expect(
    screen.queryByRole("link", { name: "Lượt tạo trong 28 ngày: 3" }),
  ).not.toBeInTheDocument();
  stop();
});

test("history filters use the same Vietnam day boundary and preserve active work across dates", () => {
  expect(localDashboardDay("2026-10-21T17:00:00Z")).toBe("2026-10-22");
  const url = new URL(
    dashboardHistoryUrl(
      "p",
      { from: "2026-10-22", to: "2026-10-28", days: 7 },
      "SUCCEEDED",
    ),
    "http://localhost",
  );
  expect(
    matchesDashboardHistory(
      { state: "SUCCEEDED", created_at: "2026-10-21T17:00:00Z" },
      url.searchParams,
    ),
  ).toBe(true);
  expect(
    matchesDashboardHistory(
      { state: "SUCCEEDED", created_at: "2026-10-21T16:59:59Z" },
      url.searchParams,
    ),
  ).toBe(false);
  expect(
    matchesDashboardHistory(
      { state: "UNCONFIRMED", created_at: "2026-10-22T00:00:00Z" },
      url.searchParams,
    ),
  ).toBe(false);
  expect(
    matchesDashboardHistory(
      { state: "RUNNING", created_at: "2025-01-01T00:00:00Z" },
      new URLSearchParams("status=active"),
    ),
  ).toBe(true);
  expect(waitingAge(null)).toBe("Chưa có mốc chờ");
});
