import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { ComponentProps } from "react";
import { createPortal } from "react-dom";
import {
  cycleFixture,
  fixture,
  ids,
} from "../../../tests/delivery-workspace-preview/fixture";
import { DeliveryExperience } from "./workspace-page";

jest.mock("./live-workspace", () => ({ __esModule: true, default: () => null }));

jest.mock("@/controllers/API/adlc", () => ({
  generateAdlcBlueprint: jest.fn(),
  getAdlcHarnessResults: jest.fn(),
  getAdlcHarnessSessions: jest.fn(),
}));
jest.mock("@/controllers/API/verification", () => ({
  listVerifications: jest.fn(),
}));
// The separately-tested markdown/highlighter and runtime controls are advanced children.
jest.mock("@/pages/RunDetailPage/HarnessResults", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/pages/RunDetailPage/HarnessSessions", () => ({
  __esModule: true,
  default: () => null,
}));

function setup(
  overrides: Partial<ComponentProps<typeof DeliveryExperience>> = {},
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  client.setQueryData(["delivery-verification", ids.row, ids.run], []);
  client.setQueryData(["delivery-captured-results", ids.row, ids.run], []);
  const props: ComponentProps<typeof DeliveryExperience> = {
    row: null,
    items: [],
    projects: [],
    roles: ["developer"],
    onCreate: jest.fn().mockResolvedValue(undefined),
    onAction: jest.fn().mockResolvedValue(undefined),
    onOpen: jest.fn(),
    onNew: jest.fn(),
    onRefresh: jest.fn(),
    onNote: jest.fn().mockResolvedValue(undefined),
    onAdvanced: jest.fn(),
    ...overrides,
  };
  const view = (changes = {}) => (
    <QueryClientProvider client={client}>
      <DeliveryExperience {...props} {...changes} />
    </QueryClientProvider>
  );
  return { ...render(view()), props, view };
}

test("a successor draft never shows the previous run, approval or Start controls", () => {
  const row = cycleFixture("draft");
  const input = setup({
    row,
    onSelectCycle: jest.fn(),
    onPrepareCycle: jest.fn(),
    onUpdateCycle: jest.fn(),
  });
  expect(
    screen.getByText("Mục tiêu đã được lưu, chưa có kế hoạch mới"),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: /Bắt đầu thực hiện/ }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /Duyệt kế hoạch này/ }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /Xem thay đổi & duyệt/ }),
  ).not.toBeInTheDocument();
  expect(input.props.onAction).not.toHaveBeenCalled();
});
test("a developer cannot select or grant the Admin role", () => {
  setup();
  expect(screen.getByRole("option", { name: "Developer" })).toBeInTheDocument();
  expect(
    screen.queryByRole("option", { name: "Admin" }),
  ).not.toBeInTheDocument();
});
test("without roles the screen shows personal scope, not all four privileged roles", () => {
  setup({ roles: [] });
  expect(screen.getAllByRole("option").map((x) => x.textContent)).toEqual([
    "Cá nhân",
    "Không gian cá nhân mặc định",
  ]);
});
test("requirement is submitted explicitly, not synthesized by a simulated run", () => {
  const { props } = setup();
  fireEvent.change(screen.getByLabelText("Tên công việc"), {
    target: { value: "My application" },
  });
  fireEvent.change(screen.getByLabelText("Bạn cần ứng dụng làm được gì?"), {
    target: { value: "Track team tasks." },
  });
  fireEvent.click(
    screen.getByRole("button", { name: /Tạo workflow từ yêu cầu/ }),
  );
  expect(props.onCreate).toHaveBeenCalledWith(
    "My application",
    "Track team tasks.",
    "",
  );
  expect(props.onAction).not.toHaveBeenCalled();
});

test("a folder browser portal cannot submit the requirement or dispatch a planner", () => {
  const { props } = setup({
    projectPicker: () =>
      createPortal(
        <form
          data-testid="folder-form"
          onSubmit={(event) => event.preventDefault()}
        >
          <button type="submit">Browse folder</button>
        </form>,
        document.body,
      ),
  });
  fireEvent.change(screen.getByLabelText("Tên công việc"), {
    target: { value: "Scoped app" },
  });
  fireEvent.change(screen.getByLabelText("Bạn cần ứng dụng làm được gì?"), {
    target: { value: "Only plan on explicit submit." },
  });
  fireEvent.submit(screen.getByTestId("folder-form"));
  expect(props.onCreate).not.toHaveBeenCalled();
});
test("workflow approval requires a checkbox and sends the frozen reviewed version", async () => {
  const row = fixture(1);
  const { props } = setup({ row });
  fireEvent.click(screen.getByRole("button", { name: /Duyệt các giai đoạn$/ }));
  const confirm = screen.getByRole("button", { name: /Xác nhận phê duyệt/ });
  expect(confirm).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(confirm);
  await waitFor(() =>
    expect(props.onAction).toHaveBeenCalledWith("approve-workflow", row),
  );
});
test("a changed revision invalidates an open confirmation, without rebasing it", () => {
  const row = fixture(1);
  const { rerender, view, props } = setup({ row });
  fireEvent.click(screen.getByRole("button", { name: /Duyệt các giai đoạn$/ }));
  fireEvent.click(screen.getByRole("checkbox"));
  rerender(view({ row: { ...row, revision: row.revision + 1 } }));
  expect(
    screen.getByRole("button", { name: /Xác nhận phê duyệt/ }),
  ).toBeDisabled();
  expect(screen.getByText(/Nội dung đã đổi/)).toBeInTheDocument();
  expect(props.onAction).not.toHaveBeenCalled();
});
test("read-only or refreshing records cannot be approved", () => {
  const row = fixture(1);
  setup({ row, refreshing: true });
  expect(
    screen.getByRole("button", { name: /Duyệt các giai đoạn$/ }),
  ).toBeDisabled();
});
test("succeeded execution without evidence is not reported as Verify PASS", () => {
  setup({ row: fixture(4) });
  expect(screen.getByText("Chưa có Verify độc lập")).toBeInTheDocument();
  expect(screen.queryByText(/báo cáo Verify đạt/)).not.toBeInTheDocument();
});
test("release approval opens the existing patch/evidence review instead of blindly approving", () => {
  const row = fixture(3);
  row.run!.approval_requests = [
    {
      approval_request_id: ids.flow,
      workflow_run_id: ids.run,
      task_run_id: ids.plan,
      status: "PENDING",
      title: "Review source changes",
      context: { summary: "Read the source patch before release." },
    },
  ];
  const { props } = setup({ row });
  fireEvent.click(screen.getByRole("button", { name: /Xem thay đổi & duyệt/ }));
  expect(props.onAdvanced).toHaveBeenCalledWith(`/runs/${ids.run}`);
  expect(props.onAction).not.toHaveBeenCalled();
});

test("saved plan graph is the default, and list switching never dispatches or approves", () => {
  const row = fixture(2);
  const { props } = setup({ row });
  expect(screen.getAllByTestId("plan-task-node")).toHaveLength(
    row.plan!.tasks.length,
  );
  expect(screen.getAllByTestId("plan-task-edge")).toHaveLength(5);
  expect(screen.getByText(/một công việc cho mỗi giai đoạn/)).toBeVisible();
  const graphIds = screen
    .getAllByTestId("plan-task-node")
    .map((node) => node.getAttribute("data-plan-task-id"));
  fireEvent.click(
    screen.getByRole("button", { name: "Danh sách" }),
  );
  const list = screen.getByRole("region", {
    name: "Sơ đồ và danh sách công việc",
  });
  expect(
    Array.from(list.querySelectorAll("[data-plan-task-id]")).map((node) =>
      node.getAttribute("data-plan-task-id"),
    ),
  ).toEqual(graphIds);
  fireEvent.click(screen.getByRole("button", { name: "Sơ đồ" }));
  expect(screen.getAllByTestId("plan-task-node")).toHaveLength(5);
  expect(props.onAction).not.toHaveBeenCalled();
  expect(props.onCreate).not.toHaveBeenCalled();
});

test("selecting a task shows truthful details and can navigate dependencies without approval", async () => {
  const row = fixture(2);
  const task = row.plan!.tasks[2];
  task.inputs = {
    task_loop_spec: JSON.stringify({
      acceptance_criteria: [
        {
          criterion_id: "c1",
          description: "Locked acceptance requirement",
          check_refs: ["suite"],
        },
      ],
      writable_paths: ["app.py"],
    }),
  };
  const { props } = setup({ row });
  const node = screen.getByRole("button", { name: task.name });
  node.focus();
  expect(node).toHaveFocus();
  fireEvent.click(node);
  const drawer = screen.getByRole("dialog");
  expect(
    within(drawer).getByRole("heading", { name: task.name }),
  ).toBeVisible();
  expect(
    within(drawer).getByText("Locked acceptance requirement"),
  ).toBeVisible();
  expect(within(drawer).getByText("app.py")).toBeVisible();
  expect(within(drawer).getByText("Chưa có thông tin phân công")).toBeVisible();
  expect(within(drawer).queryByText(/Verify PASS/)).toBeNull();
  fireEvent.click(
    within(drawer).getByRole("button", { name: /Làm rõ yêu cầu & tiêu chí/ }),
  );
  expect(
    within(drawer).getByRole("heading", { name: row.plan!.tasks[0].name }),
  ).toBeVisible();
  expect(props.onAction).not.toHaveBeenCalled();
  expect(props.onAdvanced).not.toHaveBeenCalled();
});

test("the open drawer refreshes canonical task status and links to the existing evidence page", () => {
  const row = fixture(3);
  const { props, rerender, view } = setup({ row });
  fireEvent.click(screen.getByRole("button", { name: /Kế hoạch$/ }));
  fireEvent.click(
    screen.getByRole("button", { name: row.plan!.tasks[2].name }),
  );
  expect(
    within(screen.getByRole("dialog")).getByText("Đang thực hiện"),
  ).toBeVisible();
  const changed: typeof row = JSON.parse(JSON.stringify(row));
  changed.run!.tasks[2].status = "SUCCEEDED";
  rerender(view({ row: changed }));
  expect(
    within(screen.getByRole("dialog")).getByText("Hoàn tất"),
  ).toBeVisible();
  fireEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", {
      name: /Xem thay đổi & bằng chứng/,
    }),
  );
  expect(props.onAdvanced).toHaveBeenCalledWith(`/runs/${ids.run}`);
  expect(props.onAction).not.toHaveBeenCalled();
});

test.each(["digest", "plan", "run"])(
  "a changed %s closes a drawer rather than showing stale task data",
  (change) => {
    const row = fixture(3);
    const { rerender, view } = setup({ row });
    fireEvent.click(screen.getByRole("button", { name: /Kế hoạch$/ }));
    fireEvent.click(
      screen.getByRole("button", {
        name: row.plan!.tasks[0].name,
      }),
    );
    expect(screen.getByRole("dialog")).toBeVisible();
    const changed: typeof row = JSON.parse(JSON.stringify(row));
    if (change === "digest") changed.plan_digest = "new";
    if (change === "plan") changed.plan!.execution_plan_id = "new";
    if (change === "run") changed.run!.id = "new";
    rerender(view({ row: changed }));
    expect(screen.queryByRole("dialog")).toBeNull();
  },
);
