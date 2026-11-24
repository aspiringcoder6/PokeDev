import { documentIntake } from "@/controllers/API/document-intake";
import "@testing-library/jest-dom";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthContext } from "@/contexts/authContext";
import { liveWorkflows } from "@/controllers/API/live-workflows";
import {
  workloopIntegration,
  slackNotificationConnection,
  type WorkloopConnection,
} from "@/controllers/API/workloop-integration";
import WorkloopIntegrationPage from "./workloop-integration-page";

const connection: WorkloopConnection = {
  checked_at: "2026-10-28T04:00:00Z",
  workloop: {
    available: true,
    url: "http://10.0.10.195:8903",
    integration_url: "http://10.0.10.195:8903/integration",
  },
  mcp: {
    available: true,
    url: "http://10.0.10.195:8107/mcp",
    server: { name: "workloop-factory", version: "1.30" },
  },
  slack: {
    registered: true,
    connector_connected: false,
    bot_response_status: "unverified",
    app_id: "A0CA54Q7FV3",
    bot_url: "https://slack.com/app_redirect?app=A0CA54Q7FV3",
    workspace_url: "https://adlcfactory.slack.com/",
    scope: "conversation_and_spec",
  },
  errors: [],
};
function mount(admin = true, cached = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  if (cached)
    client.setQueryData(["workloop-integration", "owner"], connection, {
      updatedAt: 1,
    });
  const result = render(
    <QueryClientProvider client={client}>
      <AuthContext.Provider
        value={
          {
            userData: { id: "owner", is_superuser: admin },
          } as React.ContextType<typeof AuthContext>
        }
      >
        <WorkloopIntegrationPage />
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
  return () => {
    result.unmount();
    client.clear();
  };
}
beforeEach(() => {
  jest
    .spyOn(slackNotificationConnection, "read")
    .mockResolvedValue({ configured: false, identity: null });
  jest.spyOn(documentIntake, "list").mockResolvedValue({
    items: [],
    rules: [],
    can_manage: true,
    stale: false,
  });
  jest.spyOn(workloopIntegration, "read").mockResolvedValue(connection);
  jest.spyOn(liveWorkflows, "projects").mockResolvedValue({
    items: [
      {
        project_id: "p",
        name: "Military Youth",
        repository: "admin/youth",
        repository_id: 1,
        repository_url: "http://gitea/admin/youth",
        branch: "main",
        base_commit: "a".repeat(40),
      },
    ],
  });
});
afterEach(() => jest.restoreAllMocks());

test("saves a bot connection through a password field and clears the token after success", async () => {
  const save = jest
    .spyOn(slackNotificationConnection, "save")
    .mockResolvedValue({
      configured: true,
      identity: {
        user: "test-bot",
        team: "ADLC",
        bot_id: "B12345",
        verified_at: "2026-10-29T00:00:00Z",
      },
    });
  const stop = mount();
  const field = await screen.findByLabelText("Mã bot Slack");
  expect(field).toHaveAttribute("type", "password");
  fireEvent.change(field, { target: { value: "xoxb-example-only" } });
  fireEvent.click(
    screen.getByRole("button", { name: "Kiểm tra và lưu kết nối" }),
  );
  await waitFor(() => expect(save).toHaveBeenCalledWith("xoxb-example-only"));
  await waitFor(() => expect(field).toHaveValue(""));
  stop();
});

test("uses the existing bot and distinguishes registration from a verified response", async () => {
  const plan = jest.spyOn(liveWorkflows, "plan");
  const execute = jest.spyOn(liveWorkflows, "execute");
  const stop = mount();
  expect(await screen.findByText("Đã có cấu hình")).toBeInTheDocument();
  expect(
    screen.getByText(/Phản hồi của bot cần được kiểm tra/),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: /Mở bot trên Slack/ }),
  ).toHaveAttribute("href", connection.slack.bot_url);
  fireEvent.click(screen.getByRole("button", { name: "Kiểm tra kết nối" }));
  await waitFor(() =>
    expect(workloopIntegration.read).toHaveBeenCalledTimes(2),
  );
  expect(plan).not.toHaveBeenCalled();
  expect(execute).not.toHaveBeenCalled();
  stop();
});

test("prepares project context for copying without sending a message", async () => {
  const writeText = jest.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  const stop = mount();
  await screen.findByRole("option", { name: "Military Youth" });
  fireEvent.change(screen.getByLabelText("Project"), {
    target: { value: "p" },
  });
  fireEvent.change(screen.getByLabelText("Ý tưởng hoặc tính năng"), {
    target: { value: "Soạn yêu cầu quản lý đoàn viên" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Sao chép yêu cầu" }));
  await screen.findByRole("button", { name: "Đã sao chép" });
  expect(writeText).toHaveBeenCalledWith(
    expect.stringContaining("Repo: http://gitea/admin/youth"),
  );
  expect(writeText).toHaveBeenCalledWith(
    expect.stringContaining("Soạn yêu cầu quản lý đoàn viên"),
  );
  stop();
});

test("ordinary members do not probe the shared administrative connection", () => {
  const stop = mount(false);
  expect(screen.getByRole("status")).toHaveTextContent("Quản trị viên");
  expect(workloopIntegration.read).not.toHaveBeenCalled();
  expect(liveWorkflows.projects).not.toHaveBeenCalled();
  stop();
});

test("a connection outage is shown as unknown and revoked access hides cached results", async () => {
  jest.mocked(workloopIntegration.read).mockResolvedValue({
    ...connection,
    mcp: { ...connection.mcp, available: false, server: null },
    slack: { ...connection.slack, registered: null },
    errors: ["mcp"],
  });
  let stop = mount();
  expect(await screen.findByText("Chưa kết nối được")).toBeInTheDocument();
  expect(
    within(
      screen.getByRole("region", { name: "Trạng thái kết nối" }),
    ).getByText("Chưa xác minh"),
  ).toBeInTheDocument();
  stop();
  jest
    .mocked(workloopIntegration.read)
    .mockRejectedValue({ response: { status: 403 } });
  stop = mount(true, true);
  await screen.findByRole("alert");
  expect(screen.queryByText("Đã có cấu hình")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: /Mở bot trên Slack/ }),
  ).not.toBeInTheDocument();
  stop();
});
