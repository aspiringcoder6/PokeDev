import { fireEvent, render, screen } from "@testing-library/react";
import * as api from "@/controllers/API/collaboration";
import { ResourceDetail, RunContents } from "./project-page";

jest.mock("@/customization/hooks/use-custom-navigate", () => ({
  useCustomNavigate: () => jest.fn(),
}));
jest.mock("@/controllers/API/collaboration", () => ({
  ...jest.requireActual("@/controllers/API/collaboration"),
  decideShared: jest.fn(),
  saveSharedWorkflow: jest.fn(),
  compileShared: jest.fn(),
}));
const user = "00000000-0000-4000-8000-000000000001";
const id = "00000000-0000-4000-8000-000000000002";
const pid = "00000000-0000-4000-8000-000000000003";
const sha = `sha256:${"a".repeat(64)}`;
function fixture(): api.SharedResource {
  return {
    id,
    project_id: pid,
    kind: "CONTRACT",
    title: "Pagination",
    created_by: user,
    origin_owner_id: user,
    responsible_ids: [user],
    revision: 2,
    content_digest: sha,
    status: "SUBMITTED",
    dependencies: {},
    parent_id: null,
    updated_at: "2026-10-17T01:00:00Z",
    created_at: "2026-10-17T01:00:00Z",
    payload: { scope: { objective: "Validate pages" }, nodes: [] },
    selected_revision: 2,
    policy_revision: 6,
    stale_dependencies: false,
    can_decide: true,
    reviewers: [{ user_id: pid, username: "Independent BA" }],
    required_action: "contract:approve",
    decisions: [],
  };
}
const can = () => true;
beforeEach(() => jest.clearAllMocks());

test("a creator or missing permission cannot acquire a review action from the UI", () => {
  render(
    <ResourceDetail
      item={{ ...fixture(), can_decide: false }}
      busy={false}
      can={can}
      run={jest.fn()}
    />,
  );
  expect(
    screen.queryByRole("button", { name: /Duyệt đúng phiên bản/i }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByText(/Người tạo hoặc người điều khiển task/i),
  ).toBeInTheDocument();
});

test("review requires reading confirmation and a comment before a frozen receipt is sent", async () => {
  const run = jest.fn();
  const item = fixture();
  (api.decideShared as jest.Mock).mockResolvedValue({});
  render(<ResourceDetail item={item} busy={false} can={can} run={run} />);
  fireEvent.click(
    screen.getByRole("button", { name: /Duyệt đúng phiên bản/i }),
  );
  const confirm = screen.getByRole("button", { name: /Xác nhận quyết định/i });
  expect(confirm).toBeDisabled();
  expect(api.decideShared).not.toHaveBeenCalled();
  fireEvent.change(
    screen.getByRole("textbox", { name: /Nhận xét bắt buộc/i }),
    { target: { value: "Acceptance criteria are covered." } },
  );
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(confirm);
  expect(run).toHaveBeenCalledTimes(1);
  // The page's transaction runner invokes this, never the opening button.
  await run.mock.calls[0][0]();
  expect(api.decideShared).toHaveBeenCalledWith(
    item,
    "APPROVE",
    "Acceptance criteria are covered.",
  );
});

test("a background revision or policy refresh cannot silently rebase an open approval", () => {
  const run = jest.fn();
  const item = fixture();
  const mounted = render(
    <ResourceDetail item={item} busy={false} can={can} run={run} />,
  );
  fireEvent.click(
    screen.getByRole("button", { name: /Duyệt đúng phiên bản/i }),
  );
  fireEvent.change(
    screen.getByRole("textbox", { name: /Nhận xét bắt buộc/i }),
    { target: { value: "Reviewed" } },
  );
  fireEvent.click(screen.getByRole("checkbox"));
  mounted.rerender(
    <ResourceDetail
      item={{ ...item, policy_revision: 7 }}
      busy={false}
      can={can}
      run={run}
    />,
  );
  expect(
    screen.getByRole("button", { name: /Xác nhận quyết định/i }),
  ).toBeDisabled();
  expect(screen.getByRole("alert")).toHaveTextContent("quyền đã đổi");
  expect(run).not.toHaveBeenCalled();
});

test("a change request records responsibility without editing Verify evidence", async () => {
  const run = jest.fn();
  const item = {
    ...fixture(),
    kind: "VERIFICATION" as const,
    payload: { report: { verdict: "FAIL" }, evidence_digest: sha },
  };
  (api.decideShared as jest.Mock).mockResolvedValue({});
  render(<ResourceDetail item={item} busy={false} can={can} run={run} />);
  fireEvent.click(screen.getByRole("button", { name: /Yêu cầu chỉnh sửa/i }));
  fireEvent.change(
    screen.getByRole("textbox", { name: /Nhận xét bắt buộc/i }),
    { target: { value: "Reproduce the failing case again." } },
  );
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: /Xác nhận quyết định/i }));
  await run.mock.calls[0][0]();
  expect(api.decideShared).toHaveBeenCalledWith(
    item,
    "REQUEST_CHANGES",
    "Reproduce the failing case again.",
  );
  expect(item.payload.report.verdict).toBe("FAIL");
});

test("a stale workflow edit remains a draft and never overwrites a newer revision", () => {
  const item = {
    ...fixture(),
    kind: "WORKFLOW" as const,
    status: "DRAFT",
    payload: { stages: [], edges: [] },
    dependencies: {
      contract: { resource_id: pid, revision: 2, content_digest: sha },
    },
  };
  const run = jest.fn();
  const mounted = render(
    <ResourceDetail item={item} busy={false} can={can} run={run} />,
  );
  fireEvent.click(screen.getByRole("button", { name: /Chỉnh workflow/i }));
  mounted.rerender(
    <ResourceDetail
      item={{ ...item, revision: 3 }}
      busy={false}
      can={can}
      run={run}
    />,
  );
  expect(
    screen.getByRole("button", { name: /Lưu revision workflow/i }),
  ).toBeDisabled();
  expect(screen.getByRole("alert")).toHaveTextContent("không tự ghi đè");
  expect(api.saveSharedWorkflow).not.toHaveBeenCalled();
});

test("a pending lookup disables decisions, even when an older response allowed them", () => {
  render(<ResourceDetail item={fixture()} busy can={can} run={jest.fn()} />);
  expect(
    screen.getByRole("button", { name: /Duyệt đúng phiên bản/i }),
  ).toBeDisabled();
});

test("team Run Detail shows canonical task/events and never exposes an execution button", () => {
  render(
    <RunContents
      payload={{
        status: "CREATED",
        tasks: [
          {
            id,
            name: "Implement pagination",
            status: "PENDING",
            executor: { service: "agent-provider:deepseek-harness" },
          },
        ],
        events: [
          {
            event_id: pid,
            event_type: "workflow_run.created",
            status: "CREATED",
            occurred_at: "2026-10-17T01:00:00Z",
          },
        ],
      }}
    />,
  );
  expect(screen.getByText("Implement pagination")).toBeInTheDocument();
  expect(screen.getByText("workflow_run.created")).toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
