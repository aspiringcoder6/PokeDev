import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ButtonHTMLAttributes } from "react";
import { MemoryRouter } from "react-router-dom";
import { harnessDemoApi } from "@/controllers/API/harness-demo";
import HarnessDemoPage from ".";

jest.mock("@/controllers/API/harness-demo", () => ({
  harnessDemoApi: {
    capabilities: jest.fn(),
    list: jest.fn(),
    get: jest.fn(),
    create: jest.fn(),
    plan: jest.fn(),
    restart: jest.fn(),
    approve: jest.fn(),
    issue: jest.fn(),
  },
}));
jest.mock("@/features/adlc-workspace/create-github-workflow", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/components/ui/button", () => ({
  Button: ({
    children,
    variant: _variant,
    ...props
  }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: string }) => (
    <button {...props}>{children}</button>
  ),
}));

const mocks = harnessDemoApi as jest.Mocked<typeof harnessDemoApi>;
const capabilities = {
  ready: true,
  blockers: [],
  requirement: "Fix pagination",
  sandbox: null,
  memory_mode: "CURATED_LOCAL",
  github_repository: "vanguard-lint/vanguard",
  github_writes_enabled: false,
  workflow: {
    workflow_ref: "demo",
    stages: [
      {
        id: "plan",
        actor: "Harness orchestrator",
        input: "requirement",
        output: "task plan",
      },
    ],
  },
};
const record = {
  id: "a",
  status: "AWAITING_PLAN_APPROVAL",
  requirement: "Fix pagination",
  requirement_digest: "sha256:requirement",
  events: [],
  plan: { steps: ["Read skill", "Fix"] },
  plan_digest: "sha256:exact-plan",
};

beforeEach(() => {
  jest.clearAllMocks();
  mocks.capabilities.mockResolvedValue(capabilities);
  mocks.list.mockResolvedValue([]);
  mocks.get.mockResolvedValue(record);
});

test("retained native diagnostics identify rejection without offering approval or replay", async () => {
  mocks.get.mockResolvedValue({
    ...record,
    status: "FAILED",
    error_code: "DEMO_NATIVE_ACTIVITY_INVALID",
    native_diagnostics: {
      runtime_version: "0.1.1",
      stage: "PLAN",
      native_activity: { violations: [{ kind: "OFF_STAGE_TOOL", count: 1 }] },
    },
  });
  render(
    <MemoryRouter initialEntries={["/?run=a"]}>
      <HarnessDemoPage />
    </MemoryRouter>,
  );
  expect(await screen.findByText(/"OFF_STAGE_TOOL"/)).toBeInTheDocument();
  expect(screen.getByText(/"runtime_version": "0.1.1"/)).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /Duyệt plan/ }),
  ).not.toBeInTheDocument();
  expect(mocks.plan).not.toHaveBeenCalled();
  expect(mocks.approve).not.toHaveBeenCalled();
});

test("Harness has product labels with honest local memory, scope and disabled remote publishing", async () => {
  render(
    <MemoryRouter>
      <HarnessDemoPage />
    </MemoryRouter>,
  );
  expect(
    await screen.findByText(/Bộ nhớ cục bộ · chưa kết nối backend/),
  ).toBeInTheDocument();
  expect(screen.getByText(/Chưa bật phát hành GitHub/)).toBeInTheDocument();
  expect(
    screen.getByText(/Python pagination, một tệp source/),
  ).toBeInTheDocument();
  expect(screen.queryByText(/\bdemo\b/i)).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: /Tạo GitHub issue/ }),
  ).toBeDisabled();
  expect(screen.getByText(/IN: requirement/)).toBeInTheDocument();
  expect(screen.getByLabelText("1. Soạn yêu cầu")).toHaveValue(
    "Fix pagination",
  );
});

test("approval requires explicit confirmation and sends only the exact server digest", async () => {
  mocks.approve.mockResolvedValue({ ...record, status: "RUNNING" });
  render(
    <MemoryRouter initialEntries={["/?run=a"]}>
      <HarnessDemoPage />
    </MemoryRouter>,
  );
  const button = await screen.findByRole("button", {
    name: "Duyệt plan · bắt đầu task loop",
  });
  expect(button).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(button);
  await waitFor(() =>
    expect(mocks.approve).toHaveBeenCalledWith(
      "a",
      "plan",
      "sha256:exact-plan",
    ),
  );
  expect(mocks.plan).not.toHaveBeenCalled();
});

test("missing service readiness disables model execution, never generates fixture success", async () => {
  mocks.capabilities.mockResolvedValue({
    ...capabilities,
    ready: false,
    blockers: ["DEMO_HARNESS_NOT_READY"],
  });
  mocks.get.mockResolvedValue({ ...record, status: "DRAFT" });
  render(
    <MemoryRouter initialEntries={["/?run=a"]}>
      <HarnessDemoPage />
    </MemoryRouter>,
  );
  expect(await screen.findByText("Harness chưa sẵn sàng.")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: /Chạy orchestrator/ }),
  ).toBeDisabled();
  expect(screen.getByText(/Chưa có thực thi/)).toBeInTheDocument();
});

test("tool receipts use readable product titles while preserving raw evidence", async () => {
  mocks.get.mockResolvedValue({
    ...record,
    events: [
      {
        seq: 1,
        stage: "demo_sandbox_checks",
        at: "2026-10-14T12:00:00Z",
        output: { exit_code: 0 },
      },
    ],
  });
  render(
    <MemoryRouter initialEntries={["/?run=a"]}>
      <HarnessDemoPage />
    </MemoryRouter>,
  );
  expect(
    await screen.findByText(/#1 · Kiểm tra của agent/),
  ).toBeInTheDocument();
  expect(screen.queryByText(/demo_sandbox_checks/)).not.toBeInTheDocument();
  expect(screen.getByText(/"exit_code": 0/)).toBeInTheDocument();
});

test("retained candidate and independent proof are visible; interrupted sessions cannot be approved", async () => {
  mocks.get.mockResolvedValue({
    ...record,
    interrupted: true,
    status: "AWAITING_MERGE_APPROVAL",
    handoff_digest: "sha256:commit",
    candidate: { changes: { "app.py": "source" } },
    verification: { checks: [{ executed_tests: 4 }] },
    commit: "exact-git-sha",
  });
  render(
    <MemoryRouter initialEntries={["/?run=a"]}>
      <HarnessDemoPage />
    </MemoryRouter>,
  );
  expect(
    await screen.findByText(/Agent commit: exact-git-sha/),
  ).toBeInTheDocument();
  expect(screen.getByText(/Verify độc lập/)).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /Duyệt commit/ }),
  ).not.toBeInTheDocument();
});

test("session selector uses live status instead of stale list status without replaying work", async () => {
  mocks.list.mockResolvedValue([{ ...record, status: "PUBLISHING" }]);
  mocks.get.mockResolvedValue({ ...record, status: "SUCCEEDED" });
  render(
    <MemoryRouter initialEntries={["/?run=a"]}>
      <HarnessDemoPage />
    </MemoryRouter>,
  );
  expect(
    await screen.findByRole("heading", { name: "Hoàn tất" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("option", { name: "a · Hoàn tất" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("option", { name: /Orchestrator đang merge\/push/ }),
  ).not.toBeInTheDocument();
  expect(mocks.plan).not.toHaveBeenCalled();
  expect(mocks.approve).not.toHaveBeenCalled();
});

test("explicit fresh session keeps the old failure and never starts model or carries approval", async () => {
  const failed = {
    ...record,
    status: "FAILED",
    error_code: "DEMO_HARNESS_WRITER_LEASE_BLOCKED",
  };
  const child = {
    id: "new",
    status: "DRAFT",
    requirement: "Fix pagination",
    requirement_digest: "sha256:requirement",
    events: [],
    restart_of: "a",
  };
  mocks.get.mockImplementation(async (id) => (id === "new" ? child : failed));
  mocks.restart.mockResolvedValue(child);
  render(
    <MemoryRouter initialEntries={["/?run=a"]}>
      <HarnessDemoPage />
    </MemoryRouter>,
  );
  const button = await screen.findByRole("button", {
    name: "Tạo phiên mới từ yêu cầu này",
  });
  expect(screen.getByText(/Harness còn khóa writer/)).toBeInTheDocument();
  expect(mocks.restart).not.toHaveBeenCalled();
  fireEvent.click(button);
  await waitFor(() => expect(mocks.restart).toHaveBeenCalledWith("a"));
  expect(await screen.findByText(/Phiên mới từ a/)).toBeInTheDocument();
  expect(mocks.plan).not.toHaveBeenCalled();
  expect(mocks.approve).not.toHaveBeenCalled();
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
});

test("a rejected native turn shows retained diagnostics but never exposes approval", async () => {
  mocks.get.mockResolvedValue({
    ...record,
    status: "FAILED",
    error_code: "DEMO_NATIVE_ACTIVITY_INVALID",
  });
  render(
    <MemoryRouter initialEntries={["/?run=a"]}>
      <HarnessDemoPage />
    </MemoryRouter>,
  );
  expect(
    await screen.findByText(/Phiên model có hoạt động không phù hợp/),
  ).toBeInTheDocument();
  expect(screen.getByText("Chẩn đoán phiên")).toBeInTheDocument();
  expect(
    screen.getByText(/"error_code": "DEMO_NATIVE_ACTIVITY_INVALID"/),
  ).toBeInTheDocument();
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(mocks.plan).not.toHaveBeenCalled();
  expect(mocks.approve).not.toHaveBeenCalled();
});
