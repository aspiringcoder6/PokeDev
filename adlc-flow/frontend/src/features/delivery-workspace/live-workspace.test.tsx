import { documentIntake } from "@/controllers/API/document-intake";
import { projectWorkloop } from "@/controllers/API/project-workloop";
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
import { AuthContext } from "@/contexts/authContext";
import { deliveryApi } from "@/controllers/API/delivery";
import { liveWorkflows, type LiveRun } from "@/controllers/API/live-workflows";
import LiveWorkspace, {
  LiveRunDetail,
  safeLivePreview,
} from "./live-workspace";
import { workspaceDashboard } from "@/controllers/API/workspace-dashboard";
import { dashboardFixture } from "./workspace-dashboard.test-data";

jest.mock("@/components/core/sanitizedMarkdown", () => ({
  SanitizedMarkdown: ({ chatMessage }: { chatMessage: string }) => (
    <p>{chatMessage}</p>
  ),
}));
beforeAll(() => {
  global.structuredClone = (value) => JSON.parse(JSON.stringify(value));
});
const project = {
  project_id: "project-a",
  name: "Ghi chú",
  repository: "admin/notes",
  repository_id: 101,
  repository_url: "http://gitea/admin/notes",
  branch: "main",
  base_commit: "a".repeat(40),
};
const run: LiveRun = {
  run_id: "run-a",
  project_id: project.project_id,
  delivery_id: "delivery-a",
  title: "Thêm tìm kiếm ghi chú",
  requirement: "Tìm kiếm theo tiêu đề, không phân biệt chữ hoa chữ thường.",
  repository: project.repository,
  created_at: "2026-10-23T01:00:00Z",
  state: "PLAN_READY",
  phase: "planning",
  nodes: [],
  documents: [],
  plan: {
    title: "Tìm kiếm ghi chú",
    summary: "Theo repo ghi chú",
    digest: "a".repeat(64),
    tasks: [
      {
        id: "UI",
        title: "Thêm bộ lọc theo tiêu đề ghi chú",
        kind: "implement",
        depends_on: [],
        write_paths: ["app.js"],
        steps: ["Chuẩn hóa chuỗi tìm kiếm"],
        acceptance: ["Không phân biệt hoa thường"],
      },
      {
        id: "TEST",
        title: "Kiểm tra tìm kiếm theo spec",
        kind: "test",
        depends_on: [],
        write_paths: ["tests/search.py"],
        steps: ["So sánh kết quả sau chuẩn hóa"],
        acceptance: ["Kết quả trùng với tiêu đề"],
      },
    ],
    commands: [{ label: "Unit tests", argv: ["python", "-m", "unittest"] }],
  },
};

function mount(
  path = "/work?view=history",
  tools?: React.ReactNode,
  suppliedClient?: QueryClient,
) {
  const client =
    suppliedClient ||
    new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
  const result = render(
    <QueryClientProvider client={client}>
      <AuthContext.Provider
        value={
          { userData: { id: "owner" } } as React.ContextType<typeof AuthContext>
        }
      >
        <MemoryRouter initialEntries={[path]}>
          <LiveWorkspace tools={tools} />
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
  return () => {
    result.unmount();
    client.clear();
  };
}

beforeEach(() => {
  jest.spyOn(documentIntake, "list").mockResolvedValue({
    items: [],
    rules: [],
    can_manage: true,
    stale: false,
  });
  jest
    .spyOn(projectWorkloop, "attention")
    .mockResolvedValue({ items: [], partial: false });
  jest.spyOn(projectWorkloop, "jobs").mockResolvedValue({ items: [] });
  jest.spyOn(workspaceDashboard, "read").mockResolvedValue(dashboardFixture());
  jest.spyOn(liveWorkflows, "attention").mockResolvedValue({
    connected: true,
    active_runs: 0,
    requests: [],
    reviews: [],
  });
  jest.spyOn(liveWorkflows, "workflows").mockResolvedValue({ items: [] });
  jest.spyOn(liveWorkflows, "packageWorkflows").mockResolvedValue([]);
  jest.spyOn(liveWorkflows, "projects").mockResolvedValue({ items: [project] });
  jest
    .spyOn(deliveryApi, "folders")
    .mockResolvedValue([
      { id: project.project_id, name: project.name, is_owner: true },
    ]);
  jest.spyOn(liveWorkflows, "runs").mockResolvedValue({
    items: [
      run,
      {
        ...run,
        run_id: "tnqd-old",
        project_id: null,
        legacy: true,
        title: "TNQD — cải thiện tìm kiếm",
        repository: "admin/tnqd-sut",
        state: "SUCCEEDED",
      },
    ],
  });
  jest.spyOn(liveWorkflows, "read").mockResolvedValue(run);
  jest.spyOn(liveWorkflows, "readiness").mockResolvedValue({ ready: true });
  jest.spyOn(liveWorkflows, "repositories").mockResolvedValue({
    items: [
      {
        id: 102,
        name: "contacts",
        full_name: "admin/contacts",
        description: "Danh bạ",
        html_url: "http://gitea/admin/contacts",
        default_branch: "main",
        private: true,
      },
    ],
  });
});
afterEach(() => jest.restoreAllMocks());

test("history preserves distinct projects and TNQD; opening a run never plans or executes work", async () => {
  const plan = jest.spyOn(liveWorkflows, "plan"),
    execute = jest.spyOn(liveWorkflows, "execute");
  const stop = mount();
  await screen.findByText("TNQD — cải thiện tìm kiếm");
  expect(
    screen.queryByRole("button", { name: "Đặt lại demo" }),
  ).not.toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: /Thêm tìm kiếm ghi chú/ }),
  );
  await screen.findByRole("button", { name: "Duyệt & thực hiện" });
  fireEvent.click(screen.getByRole("button", { name: "Xem danh sách task" }));
  fireEvent.click(
    screen.getByRole("button", {
      name: "UI: Thêm bộ lọc theo tiêu đề ghi chú",
    }),
  );
  expect(screen.getByText("Chuẩn hóa chuỗi tìm kiếm")).toBeInTheDocument();
  expect(plan).not.toHaveBeenCalled();
  expect(execute).not.toHaveBeenCalled();
  stop();
});

test("choosing a project scopes history and a reloaded run is read by its identity", async () => {
  const stop = mount("/work?project=project-a&run=run-a");
  await screen.findByRole("button", { name: "Duyệt & thực hiện" });
  expect(liveWorkflows.runs).toHaveBeenCalledWith("project-a");
  expect(liveWorkflows.read).toHaveBeenCalledWith("run-a");
  stop();
});

test("existing and new repo choices are explicit and never create a workflow automatically", async () => {
  const connect = jest
      .spyOn(liveWorkflows, "connect")
      .mockResolvedValue(project),
    plan = jest.spyOn(liveWorkflows, "plan");
  const stop = mount();
  fireEvent.click(
    screen.getByRole("button", { name: "Chọn / tạo repo Gitea" }),
  );
  const dialog = await screen.findByRole("dialog");
  await within(dialog).findByText("admin/contacts · riêng tư");
  fireEvent.change(within(dialog).getByLabelText("Repo"), {
    target: { value: "102" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Kết nối repo" }));
  await waitFor(() =>
    expect(connect).toHaveBeenCalledWith({ repository_id: 102 }),
  );
  await screen.findByLabelText("Tên yêu cầu");
  expect(plan).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "Chọn repo khác hoặc tạo repo mới" }),
  );
  const newDialog = await screen.findByRole("dialog");
  fireEvent.click(
    within(newDialog).getByRole("button", { name: "Tạo repo mới" }),
  );
  fireEvent.change(within(newDialog).getByLabelText(/Tên repo mới/), {
    target: { value: "new-product" },
  });
  fireEvent.click(
    within(newDialog).getByRole("button", { name: "Tạo & kết nối repo" }),
  );
  await waitFor(() =>
    expect(connect).toHaveBeenCalledWith({
      new_repository_name: "new-product",
    }),
  );
  expect(plan).not.toHaveBeenCalled();
  stop();
});

test("only explicit review approval starts implementation", () => {
  const execute = jest.spyOn(liveWorkflows, "execute").mockResolvedValue(run),
    action = jest.fn((name, op) => op());
  const { unmount } = render(
    <LiveRunDetail run={run} busy="" action={action} reuse={jest.fn()} />,
  );
  expect(execute).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Duyệt & thực hiện" }));
  expect(execute).toHaveBeenCalledWith(run);
  unmount();
});

test("preview requires a separate unexpired loopback origin and excludes credentials", () => {
  const preview = {
    state: "LIVE",
    url: "http://localhost:45678/",
    expires_at: "2099-01-01T00:00:00Z",
  };
  expect(safeLivePreview(preview)).toBe(true);
  for (const url of [
    window.location.origin + "/",
    "https://outside.example/",
    "http://localhost:45678/?token=x",
    "http://user:pass@localhost:45678/",
  ])
    expect(safeLivePreview({ ...preview, url })).toBe(false);
  expect(safeLivePreview({ ...preview, expires_at: 1 })).toBe(false);
});

test("a saved project canvas is explicitly selected and its exact version is submitted", async () => {
  const workflow = {
    workflow_id: "workflow-a",
    project_id: project.project_id,
    name: "Counter workflow",
    digest: "c".repeat(64),
    revision: 3,
    ready: true,
    graph: { nodes: [], edges: [] },
  };
  jest
    .spyOn(liveWorkflows, "workflows")
    .mockResolvedValue({ items: [workflow] } as never);
  jest.spyOn(deliveryApi, "createFlow").mockResolvedValue({ id: "flow-a" });
  jest
    .spyOn(deliveryApi, "create")
    .mockResolvedValue({ id: "delivery-a" } as never);
  const plan = jest.spyOn(liveWorkflows, "plan").mockResolvedValue(run);
  const stop = mount("/work?project=project-a");
  await screen.findByRole("option", { name: "Counter workflow · v3" });
  expect(screen.getByLabelText("Workflow sử dụng")).toHaveValue("");
  fireEvent.change(screen.getByLabelText("Workflow sử dụng"), {
    target: { value: "workflow-a" },
  });
  fireEvent.change(screen.getByLabelText("Tên yêu cầu"), {
    target: { value: "Repair the counter" },
  });
  fireEvent.change(screen.getByLabelText("Mô tả và tiêu chí mong muốn"), {
    target: {
      value:
        "Increment integers and preserve the original protected test suite.",
    },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Phân tích & lập kế hoạch" }),
  );
  await waitFor(() =>
    expect(plan).toHaveBeenCalledWith(
      expect.objectContaining({
        project_id: "project-a",
        workflow_id: "workflow-a",
        workflow_digest: workflow.digest,
      }),
    ),
  );
  stop();
});

test("project tabs retain the selected project and creation opens from the sidebar", async () => {
  const plan = jest.spyOn(liveWorkflows, "plan");
  const stop = mount("/work?project=project-a");
  await screen.findByLabelText("Tên yêu cầu");
  fireEvent.click(
    within(
      screen.getByRole("navigation", { name: "Khu vực của project" }),
    ).getByRole("button", { name: "Workflow" }),
  );
  await screen.findByRole("heading", { name: "Workflow của project" });
  expect(liveWorkflows.workflows).toHaveBeenCalledWith("project-a");
  expect(
    within(
      screen.getByRole("navigation", { name: "Khu vực của project" }),
    ).queryByRole("button", { name: "Công cụ" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /^Tổng quan workspace/ }));
  expect(
    screen.queryByRole("heading", { name: "Workflow gói & chu kỳ phát triển" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Project mới" }));
  expect(
    screen.getByRole("heading", { name: "Workflow gói & chu kỳ phát triển" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Canvas gói" })).toHaveAttribute(
    "href",
    "/flows",
  );
  expect(
    screen.queryByRole("navigation", { name: "Khu vực của project" }),
  ).not.toBeInTheDocument();
  expect(plan).not.toHaveBeenCalled();
  stop();
});

test("workspace opens only the dashboard and keeps creation behind Project mới", async () => {
  const plan = jest.spyOn(liveWorkflows, "plan"),
    execute = jest.spyOn(liveWorkflows, "execute");
  const stop = mount("/work", <div>Workspace tools content</div>);
  expect(screen.queryByText("Workspace tools content")).not.toBeInTheDocument();
  expect(
    await screen.findByRole("heading", { name: "Tổng quan hoạt động" }),
  ).toBeInTheDocument();
  const tabs = within(
    screen.getByRole("navigation", { name: "Khu vực của workspace" }),
  );
  expect(
    tabs
      .getAllByRole("button")
      .map((button) => button.textContent?.replace(/\d+$/, "")),
  ).toEqual([
    "Tổng quan",
    "Yêu cầu & tài liệu",
    "Lịch sử công việc",
    "Kết quả",
  ]);
  expect(tabs.getByRole("button", { name: "Tổng quan" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect(screen.queryByLabelText("Tên yêu cầu")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Yêu cầu mới" }),
  ).not.toBeInTheDocument();
  fireEvent.click(tabs.getByRole("button", { name: /^Lịch sử công việc/ }));
  expect(
    await screen.findByText("TNQD — cải thiện tìm kiếm"),
  ).toBeInTheDocument();
  expect(plan).not.toHaveBeenCalled();
  expect(execute).not.toHaveBeenCalled();
  stop();
});

test("new project opens repo selection and orchestration without starting an agent", async () => {
  const plan = jest.spyOn(liveWorkflows, "plan");
  const execute = jest.spyOn(liveWorkflows, "execute");
  const stop = mount("/work", <div>Workspace tools content</div>);
  fireEvent.click(screen.getByRole("button", { name: "Project mới" }));
  expect(screen.getByText("Workspace tools content")).toBeInTheDocument();
  expect(
    screen.queryByRole("heading", { name: "Tổng quan hoạt động" }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Project mới" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  fireEvent.click(
    within(
      screen.getByRole("region", { name: "Bắt đầu project mới" }),
    ).getByRole("button", { name: "Chọn / tạo repo Gitea" }),
  );
  expect(await screen.findByRole("dialog")).toBeInTheDocument();
  expect(plan).not.toHaveBeenCalled();
  expect(execute).not.toHaveBeenCalled();
  stop();
});

test("dashboard history links use the complete permission-filtered index and open the plan tab", async () => {
  const data = dashboardFixture();
  data.history = Array.from({ length: 129 }, (_, index) => ({
    run_id: `item-${index}`,
    project_id: "project-a",
    title: `Lượt đã lọc ${index}`,
    repository: "admin/notes",
    state: "FAILED",
    created_at: "2026-10-27T12:00:00Z",
    category: "failed",
  }));
  jest.mocked(workspaceDashboard.read).mockResolvedValue(data);
  let stop = mount(
    "/work?view=history&filtered=1&range=28&from=2026-10-01&to=2026-10-28&status=FAILED",
  );
  await screen.findByRole("button", { name: /đang hiện 50\/129/ });
  expect(
    screen.getByRole("button", { name: /đang hiện 50\/129/ }),
  ).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Tìm lịch sử"), {
    target: { value: "Lượt đã lọc 128" },
  });
  expect(
    screen.getByRole("button", { name: /Lượt đã lọc 128/ }),
  ).toBeInTheDocument();
  expect(liveWorkflows.runs).not.toHaveBeenCalled();
  stop();
  stop = mount("/work?project=project-a&run=run-a&tab=spec");
  await screen.findByRole("button", { name: "Tài liệu & Memory" });
  expect(
    screen.getByRole("button", { name: "Tài liệu & Memory" }),
  ).toHaveAttribute("aria-selected", "true");
  stop();
});

test("filtered history hides its cached rows after access is revoked", async () => {
  const data = dashboardFixture();
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const key = ["workspace-dashboard", "owner", "", 28];
  client.setQueryData(key, data, { updatedAt: 1 });
  jest.mocked(workspaceDashboard.read).mockRejectedValue({
    response: { status: 403 },
  });
  const stop = mount("/work?view=history&filtered=1", undefined, client);
  await waitFor(() => expect(client.getQueryState(key)?.status).toBe("error"));
  expect(client.getQueryData(key)).toBeDefined();
  expect(screen.queryByText(data.history[0].title)).not.toBeInTheDocument();
  stop();
});

test("selecting a project from overview opens project work and returning clears project tabs", async () => {
  const stop = mount("/work");
  await screen.findByRole("heading", {
    name: "Tổng quan hoạt động",
  });
  fireEvent.click(await screen.findByRole("button", { name: /Ghi chú/ }));
  const tabs = within(
    await screen.findByRole("navigation", { name: "Khu vực của project" }),
  );
  expect(tabs.getByRole("button", { name: /^Công việc/ })).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect(
    tabs
      .getAllByRole("button")
      .map((button) => button.textContent?.replace(/\d+$/, "")),
  ).toEqual([
    "Công việc",
    "Yêu cầu & tài liệu",
    "Issue Gitea",
    "Workflow",
    "Kết quả",
    "Thống kê",
    "Môi trường",
    "Cài đặt",
  ]);
  expect(
    screen.queryByRole("heading", { name: "Workflow gói & chu kỳ phát triển" }),
  ).not.toBeInTheDocument();
  expect(liveWorkflows.runs).toHaveBeenCalledWith("project-a");
  fireEvent.click(screen.getByRole("button", { name: /^Tổng quan workspace/ }));
  expect(
    await screen.findByRole("heading", {
      name: "Tổng quan hoạt động",
    }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("navigation", { name: "Khu vực của project" }),
  ).not.toBeInTheDocument();
  stop();
});

test("old tools links stay at workspace level and project-only links without a project open overview", () => {
  let stop = mount("/work?view=advanced&project_id=project-a");
  expect(screen.getByRole("button", { name: "Project mới" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect(
    screen.getByRole("heading", { name: "Workflow gói & chu kỳ phát triển" }),
  ).toBeInTheDocument();
  stop();
  stop = mount("/work?view=environment");
  expect(
    screen.getByRole("heading", { name: "Tổng quan hoạt động" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByText("Chọn project để thiết lập môi trường"),
  ).not.toBeInTheDocument();
  stop();
});
