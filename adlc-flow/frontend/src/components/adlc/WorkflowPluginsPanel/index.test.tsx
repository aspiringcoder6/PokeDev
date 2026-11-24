import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import WorkflowPluginsPanel, { PluginResult } from ".";
import { workflowPluginApi } from "@/controllers/API/workflow-plugins";

jest.mock("@/controllers/API/workflow-plugins", () => ({
  workflowPluginApi: { view: jest.fn(), health: jest.fn() },
}));
jest.mock("@/components/ui/button", () => ({
  Button: ({ children, size, variant, ...props }: any) => (
    <button {...props}>{children}</button>
  ),
}));

const health = {
  id: "check-1",
  operation: "HEALTH" as const,
  state: "SUCCEEDED",
  verification_evidence: false as const,
  data: { testforge: { status: "ok" }, agentmemory: { status: "ok" } },
};

beforeEach(() => jest.clearAllMocks());

test("health action displays actual backend result and leaves data operations unconfigured", async () => {
  (workflowPluginApi.view as jest.Mock).mockResolvedValue({
    enabled: true,
    connections: [],
    records: [],
  });
  (workflowPluginApi.health as jest.Mock).mockResolvedValue(health);
  render(<WorkflowPluginsPanel runId="run-a" />);
  const button = await screen.findByRole("button", {
    name: "Kiểm tra kết nối",
  });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  expect(
    await screen.findByText("TestForge: Kết nối thành công"),
  ).toBeInTheDocument();
  expect(
    screen.getByText("AgentMemory: Kết nối thành công"),
  ).toBeInTheDocument();
  expect(screen.getByText(/Chưa gắn dataset AgentMemory/)).toBeInTheDocument();
  expect(workflowPluginApi.health).toHaveBeenCalledWith(
    "run-a",
    expect.any(String),
  );
  expect(workflowPluginApi.health).toHaveBeenCalledTimes(1);
});

test("retained memory context is escaped and never presented as Verify PASS", () => {
  const { container } = render(
    <PluginResult
      record={{
        id: "read-a",
        operation: "MEMORY_CONTEXT",
        state: "SUCCEEDED",
        verification_evidence: false,
        data: { context: '<img src=x onerror="alert(1)">' },
      }}
    />,
  );
  expect(screen.getAllByText(/<img src=x/).length).toBeGreaterThan(0);
  expect(container.querySelector("img")).toBeNull();
  expect(
    screen.getByText(/chưa phải phán quyết Verify độc lập/),
  ).toBeInTheDocument();
  expect(screen.queryByText("PASS")).not.toBeInTheDocument();
});

test("backend loss keeps archived task results visible and explains unknown dispatch", async () => {
  (workflowPluginApi.view as jest.Mock).mockRejectedValue(new Error("offline"));
  render(
    <WorkflowPluginsPanel
      runId="run-a"
      taskResults={[
        {
          id: "job-a",
          operation: "TESTFORGE_REPLAY",
          state: "UNKNOWN",
          verification_evidence: false,
          error_code: "WORKFLOW_PLUGIN_DISPATCH_UNCONFIRMED",
          data: null,
        },
      ]}
    />,
  );
  expect(
    await screen.findByText(/Chưa xác nhận job đã được tạo/),
  ).toBeInTheDocument();
  expect(screen.getByText("Chưa xác nhận kết quả")).toBeInTheDocument();
  expect(
    await screen.findByText(/Không tải được kết quả plugin/),
  ).toBeInTheDocument();
  expect(workflowPluginApi.health).not.toHaveBeenCalled();
});
