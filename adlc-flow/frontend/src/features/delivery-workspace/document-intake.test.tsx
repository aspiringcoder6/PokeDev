import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AuthContext } from "@/contexts/authContext";
import {
  documentIntake,
  type IntakeDocument,
} from "@/controllers/API/document-intake";
import { liveWorkflows, type LiveRun } from "@/controllers/API/live-workflows";
import DocumentIntake from "./document-intake";

jest.mock("@/components/core/sanitizedMarkdown", () => ({
  SanitizedMarkdown: ({ chatMessage }: { chatMessage: string }) => (
    <p>{chatMessage}</p>
  ),
}));
const project = {
  project_id: "project-a",
  name: "Application",
  repository: "admin/app",
  repository_id: 36,
  repository_url: "http://gitea/admin/app",
  branch: "main",
  base_commit: "a".repeat(40),
};
let current: IntakeDocument;
let items: IntakeDocument[];
const open = jest.fn();
function mount(selected = "1") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <AuthContext.Provider
        value={
          {
            userData: { id: "owner", is_superuser: true },
          } as React.ContextType<typeof AuthContext>
        }
      >
        <MemoryRouter>
          <DocumentIntake
            identity="owner"
            projects={[project]}
            selectedId={selected}
            onSelect={jest.fn()}
            onOpenRun={open}
            onConnectProject={jest.fn()}
          />
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
  return {
    client,
    stop: () => {
      view.unmount();
      client.clear();
    },
  };
}
beforeEach(() => {
  jest.spyOn(documentIntake, "archive").mockImplementation(
    async () =>
      (current = {
        ...current,
        state: "ARCHIVED",
        archived_at: "2026-10-29T00:00:00Z",
        approval: undefined,
        progress: { enabled: false },
        notifications: { enabled: false },
      }),
  );
  jest.spyOn(documentIntake, "restore").mockImplementation(async () => {
    const { archived_at: _, ...restored } = current;
    return (current = {
      ...restored,
      state: restored.project_id ? "NEEDS_REVIEW" : "NEEDS_PROJECT",
      approval: undefined,
    });
  });
  jest.spyOn(documentIntake, "checkRevision").mockImplementation(
    async (_id, command) =>
      (current = {
        ...current,
        revision_request: {
          ...current.revision_request!,
          invocation_id:
            command.invocation_id || current.revision_request?.invocation_id,
          state: "FAILED",
          error_code: "INTAKE_REVISION_AGENT_FAILED",
        },
      }),
  );
  jest.spyOn(documentIntake, "notifications").mockImplementation(
    async (_id, enabled) =>
      (current = {
        ...current,
        notifications: { enabled, state: "NEEDS_CONFIGURATION" },
      }),
  );
  jest.spyOn(documentIntake, "revise").mockImplementation(
    async (_id, command) =>
      (current = {
        ...current,
        state: "NEEDS_CHANGES",
        approval: undefined,
        revision_request: {
          ...command,
          id: command.request_id,
          page_version: 8,
          at: "2026-10-29T00:00:00Z",
          state: "SENT",
        },
      }),
  );
  open.mockClear();
  current = {
    document_id: "1",
    title: "Add reporting",
    doc_type: "ptyc",
    lifecycle_id: "lc-thread",
    page_id: "123",
    confluence_url: "https://example.atlassian.net/wiki/pages/123",
    slack_url: "https://slack.com/archives/C01234567/p123",
    slack_channel: "C01234567",
    slack_thread: "123.456",
    source_status: "approved",
    created_at: "2026-10-28T00:00:00Z",
    state: "NEEDS_PROJECT",
    body: "Source requirements and acceptance criteria",
    page_version: 8,
    digest: "a".repeat(64),
  };
  items = [current];
  jest
    .spyOn(documentIntake, "list")
    .mockImplementation(async (_project, includeArchived) => ({
      items: items
        .map((doc) => (doc.document_id === current.document_id ? current : doc))
        .filter((doc) => includeArchived || !doc.archived_at),
      rules: [],
      can_manage: true,
      stale: false,
      checked_at: "2026-10-28T01:00:00Z",
    }));
  jest.spyOn(documentIntake, "read").mockImplementation(async () => current);
  jest.spyOn(documentIntake, "assign").mockImplementation(
    async (_id, project_id, instructions) =>
      (current = {
        ...current,
        project_id,
        repository: project.repository,
        instructions,
        state: "NEEDS_REVIEW",
        digest: "b".repeat(64),
      }),
  );
  jest.spyOn(documentIntake, "decide").mockImplementation(
    async (_id, digest, decision) =>
      (current = {
        ...current,
        state: decision === "approve" ? "APPROVED" : "REJECTED",
        approval: {
          digest,
          decision,
          at: "2026-10-28T02:00:00Z",
          page_version: 8,
        },
      }),
  );
  jest.spyOn(documentIntake, "plan").mockResolvedValue({
    run_id: "run-a",
    project_id: project.project_id,
  } as LiveRun);
  jest.spyOn(documentIntake, "progress").mockImplementation(
    async (_id, enabled) =>
      (current = {
        ...current,
        progress: {
          enabled,
          state: enabled ? "SYNCED" : "DISABLED",
          link: "https://example.atlassian.net/wiki/pages/900",
          synced_at: "2026-10-28T10:00:00Z",
        },
      }),
  );
  jest.spyOn(liveWorkflows, "workflows").mockResolvedValue({ items: [] });
  jest
    .spyOn(crypto, "randomUUID")
    .mockReturnValue("11111111-1111-4111-8111-111111111111");
});
afterEach(() => jest.restoreAllMocks());

test("sends version-bound feedback to the bot without approving or starting a run", async () => {
  current.project_id = project.project_id;
  const view = mount();
  fireEvent.change(
    await screen.findByRole("textbox", { name: "Góp ý sửa tài liệu" }),
    { target: { value: "Clarify the year filter and unit access." } },
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Gửi yêu cầu sửa về bot" }),
  );
  await waitFor(() =>
    expect(documentIntake.revise).toHaveBeenCalledWith("1", {
      digest: current.digest,
      request_id: "11111111-1111-4111-8111-111111111111",
      feedback: "Clarify the year filter and unit access.",
    }),
  );
  expect(
    await screen.findByText("Workloop đã nhận · đang chờ bot cập nhật"),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Duyệt cho project" }),
  ).toBeDisabled();
  expect(documentIntake.decide).not.toHaveBeenCalled();
  expect(documentIntake.plan).not.toHaveBeenCalled();
  view.stop();
});

test("enables source-thread notifications and explains missing configuration", async () => {
  const view = mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Bật thông báo Slack" }),
  );
  await waitFor(() =>
    expect(documentIntake.notifications).toHaveBeenCalledWith("1", true),
  );
  expect(
    await screen.findByText(/cần lưu mã bot trong Cài đặt/),
  ).toBeInTheDocument();
  expect(documentIntake.plan).not.toHaveBeenCalled();
  view.stop();
});

test("a tracked bot failure leaves the original readable and allows revised feedback", async () => {
  current = {
    ...current,
    project_id: project.project_id,
    state: "NEEDS_CHANGES",
    revision_request: {
      id: "revision-a",
      digest: current.digest!,
      at: "2026-10-29T00:00:00Z",
      page_version: 8,
      state: "PROCESSING",
      feedback: "Clarify the year filter.",
      transport: "native-spec",
      invocation_id: "ag-test-1",
    },
  };
  const view = mount();
  expect(
    await screen.findByText("Bot đang cập nhật tài liệu"),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Duyệt cho project" }),
  ).toBeDisabled();
  fireEvent.click(
    screen.getByRole("button", { name: "Kiểm tra tiến độ cập nhật" }),
  );
  expect(
    await screen.findByText("Bot chưa cập nhật được tài liệu"),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("textbox", { name: "Góp ý sửa tài liệu" }),
  ).toBeEnabled();
  expect(documentIntake.checkRevision).toHaveBeenCalledWith("1", {
    request_id: "revision-a",
  });
  expect(documentIntake.revise).not.toHaveBeenCalled();
  expect(documentIntake.decide).not.toHaveBeenCalled();
  view.stop();
});

test("a legacy request requires an explicit invocation before checking its outcome", async () => {
  current = {
    ...current,
    state: "NEEDS_CHANGES",
    revision_request: {
      id: "revision-old",
      digest: current.digest!,
      at: "2026-10-29T00:00:00Z",
      page_version: 8,
      state: "SENT",
      feedback: "Clarify the year filter.",
    },
  };
  const view = mount();
  fireEvent.click(await screen.findByText("Đối soát lượt chưa có biên nhận"));
  const check = screen.getByRole("button", {
    name: "Kiểm tra lượt bot đã chọn",
  });
  expect(check).toBeDisabled();
  fireEvent.change(screen.getByRole("textbox", { name: "Mã lượt bot" }), {
    target: { value: "ag-legacy" },
  });
  fireEvent.click(check);
  await waitFor(() =>
    expect(documentIntake.checkRevision).toHaveBeenCalledWith("1", {
      request_id: "revision-old",
      invocation_id: "ag-legacy",
    }),
  );
  expect(documentIntake.revise).not.toHaveBeenCalled();
  view.stop();
});

test("automatically received source-approved documents still need project review and never run on read", async () => {
  const view = mount();
  expect(
    await screen.findByText("Source requirements and acceptance criteria"),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Hội thoại Slack/ })).toHaveAttribute(
    "href",
    current.slack_url,
  );
  expect(
    screen.getByRole("button", { name: "Duyệt cho project" }),
  ).toBeDisabled();
  expect(documentIntake.decide).not.toHaveBeenCalled();
  expect(documentIntake.plan).not.toHaveBeenCalled();
  view.stop();
});
test("assigns a project and optional channel rule before a separate approval", async () => {
  const view = mount();
  fireEvent.change(
    await screen.findByRole("combobox", { name: "Project nhận yêu cầu" }),
    { target: { value: project.project_id } },
  );
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.change(screen.getByRole("textbox", { name: "Chỉ dẫn bổ sung" }), {
    target: { value: "Backend only" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Lưu phạm vi" }));
  await waitFor(() =>
    expect(documentIntake.assign).toHaveBeenCalledWith(
      "1",
      project.project_id,
      "Backend only",
      true,
      false,
    ),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Duyệt cho project" }),
    ).toBeEnabled(),
  );
  expect(documentIntake.decide).not.toHaveBeenCalled();
  view.stop();
});
test("approves the exact digest then starts the normal owned run only after an explicit planning action", async () => {
  current = {
    ...current,
    project_id: project.project_id,
    state: "NEEDS_REVIEW",
  };
  const view = mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Duyệt cho project" }),
  );
  await waitFor(() =>
    expect(documentIntake.decide).toHaveBeenCalledWith(
      "1",
      "a".repeat(64),
      "approve",
    ),
  );
  const plan = await screen.findByRole("button", { name: "Lập kế hoạch" });
  expect(documentIntake.plan).not.toHaveBeenCalled();
  fireEvent.click(plan);
  await waitFor(() =>
    expect(documentIntake.plan).toHaveBeenCalledWith("1", {
      digest: "a".repeat(64),
      command_id: expect.any(String),
    }),
  );
  expect(open).toHaveBeenCalledWith({
    run_id: "run-a",
    project_id: project.project_id,
  });
  view.stop();
});
test("new documents arrive on refresh without pasting a Confluence link", async () => {
  const view = mount("");
  await screen.findByRole("button", { name: /Add reporting/ });
  items.push({ ...current, document_id: "2", title: "A new Slack request" });
  await act(async () => {
    await view.client.invalidateQueries({
      queryKey: ["document-intake", "owner"],
    });
  });
  expect(
    await screen.findByRole("button", { name: /A new Slack request/ }),
  ).toBeInTheDocument();
  expect(screen.queryByPlaceholderText(/Confluence/)).not.toBeInTheDocument();
  view.stop();
});
test("a changed document revokes approval while preserving an unsaved scope draft", async () => {
  current = {
    ...current,
    project_id: project.project_id,
    state: "APPROVED",
    approval: {
      digest: current.digest!,
      at: "2026-10-28T02:00:00Z",
      decision: "approve",
      page_version: 8,
    },
  };
  const view = mount();
  fireEvent.change(
    await screen.findByRole("textbox", { name: "Chỉ dẫn bổ sung" }),
    { target: { value: "Do not lose this draft" } },
  );
  expect(screen.getByRole("button", { name: "Lập kế hoạch" })).toBeDisabled();
  current = {
    ...current,
    body: "Revised requirements",
    page_version: 9,
    digest: "c".repeat(64),
    state: "CHANGED",
    approval: undefined,
  };
  await act(async () => {
    await view.client.invalidateQueries({
      queryKey: ["intake-document", "owner"],
    });
  });
  expect(await screen.findByText("Revised requirements")).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "Chỉ dẫn bổ sung" })).toHaveValue(
    "Do not lose this draft",
  );
  expect(
    screen.getByRole("button", { name: "Duyệt cho project" }),
  ).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: "Lập kế hoạch" }),
  ).not.toBeInTheDocument();
  view.stop();
});
test("cached document remains readable during an outage and cannot be approved", async () => {
  current = {
    ...current,
    project_id: project.project_id,
    state: "NEEDS_REVIEW",
    stale: true,
  };
  const view = mount();
  await screen.findByText("Source requirements and acceptance criteria");
  expect(
    screen.getByRole("button", { name: "Duyệt cho project" }),
  ).toBeDisabled();
  expect(screen.getByRole("alert")).toHaveTextContent("nội dung đã lưu");
  view.stop();
});

test("Slack progress sharing is an explicit action and does not approve or start a run", async () => {
  const view = mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Bật đồng bộ tiến độ" }),
  );
  await waitFor(() =>
    expect(documentIntake.progress).toHaveBeenCalledWith("1", true),
  );
  expect(
    await screen.findByRole("link", { name: /Xem báo cáo/ }),
  ).toHaveAttribute("href", "https://example.atlassian.net/wiki/pages/900");
  expect(documentIntake.plan).not.toHaveBeenCalled();
  expect(documentIntake.decide).not.toHaveBeenCalled();
  view.stop();
});

test("a delivered Slack notice opens the exact acknowledged message", async () => {
  const messageUrl =
    "https://adlcfactory.slack.com/archives/C01234567/p1793249999123456";
  current = {
    ...current,
    notifications: {
      enabled: true,
      state: "SENT",
      last_message_url: messageUrl,
    },
  };
  const view = mount();
  expect(
    await screen.findByRole("link", { name: "Mở thông báo đã gửi" }),
  ).toHaveAttribute("href", messageUrl);
  expect(documentIntake.notifications).not.toHaveBeenCalled();
  view.stop();
});

test("a started revision keeps its approval and opens the latest linked retry", async () => {
  current = {
    ...current,
    project_id: project.project_id,
    state: "APPROVED",
    approval: {
      digest: current.digest!,
      at: "2026-10-28T02:00:00Z",
      decision: "approve",
      page_version: 8,
    },
    run_id: "retry-child",
    run_state: "SUCCEEDED",
    run_started_at: "2026-10-28T02:01:00Z",
    plan_command: {
      id: "command-a",
      state: "PLANNING",
      digest: current.digest!,
    },
  };
  const view = mount();
  expect(await screen.findByRole("button", { name: "Từ chối" })).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: "Lập kế hoạch" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Mở lượt chạy/ }));
  expect(open).toHaveBeenCalledWith({
    project_id: project.project_id,
    run_id: "retry-child",
  });
  view.stop();
});
test("an uncertain planning response reuses the same command and blocks double submission", async () => {
  current = {
    ...current,
    project_id: project.project_id,
    state: "APPROVED",
    approval: {
      digest: current.digest!,
      at: "2026-10-28T02:00:00Z",
      decision: "approve",
      page_version: 8,
    },
  };
  (documentIntake.plan as jest.Mock).mockRejectedValueOnce(
    new Error("network"),
  );
  const view = mount();
  fireEvent.click(await screen.findByRole("button", { name: "Lập kế hoạch" }));
  await screen.findByRole("alert");
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Lập kế hoạch" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Lập kế hoạch" }));
  await waitFor(() => expect(documentIntake.plan).toHaveBeenCalledTimes(2));
  const calls = (documentIntake.plan as jest.Mock).mock.calls;
  expect(calls[1][1].command_id).toBe(calls[0][1].command_id);
  view.stop();
});

test("archived requests have a recovery view and restoring never approves them", async () => {
  const view = mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Lưu trữ yêu cầu" }),
  );
  await screen.findByRole("region", { name: "Yêu cầu đã lưu trữ" });
  expect(documentIntake.archive).toHaveBeenCalledWith("1");
  expect(
    screen.queryByRole("button", { name: "Duyệt cho project" }),
  ).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Lọc tài liệu"), {
    target: { value: "archived" },
  });
  await waitFor(() =>
    expect(documentIntake.list).toHaveBeenCalledWith(undefined, true),
  );
  fireEvent.click(screen.getByRole("button", { name: "Khôi phục yêu cầu" }));
  await screen.findByLabelText("Project nhận yêu cầu");
  expect(documentIntake.restore).toHaveBeenCalledWith("1");
  expect(current.approval).toBeUndefined();
  expect(current.notifications?.enabled).toBe(false);
  view.stop();
});

test("an active revision cannot be hidden by archiving", async () => {
  current.revision_request = {
    id: "revision",
    digest: current.digest!,
    at: "2026-10-29T00:00:00Z",
    page_version: 8,
    state: "PROCESSING",
    feedback: "Clarify the year filter.",
    invocation_id: "ag-test",
  };
  const view = mount();
  expect(
    await screen.findByRole("button", { name: "Lưu trữ yêu cầu" }),
  ).toBeDisabled();
  expect(documentIntake.archive).not.toHaveBeenCalled();
  view.stop();
});
