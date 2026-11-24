import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthContext } from "@/contexts/authContext";
import {
  tnqdDemo,
  tnqdRunSchema,
  type TnqdRun,
} from "@/controllers/API/tnqd-demo";
import TnqdWorkflowPanel, { safeTnqdPreview } from "./tnqd-workflow";
jest.mock("@/components/core/sanitizedMarkdown", () => ({
  SanitizedMarkdown: ({ chatMessage }: { chatMessage: string }) => (
    <p>{chatMessage}</p>
  ),
}));

const task = {
  id: "T02",
  title: "Đưa tìm kiếm mới từ trang ba về trang đầu",
  operation: "patch.pagination",
  role: "coder",
  depends_on: ["T01"],
  steps: [
    "Đọc spec và đối chiếu trạng thái trang trước tìm kiếm",
    "Sửa search để phân biệt đổi điều kiện và chuyển trang",
    "Trả đề xuất thay đổi có giới hạn file component",
  ],
  inputs: ["PTYC được đọc lại từ Memory"],
  outputs: ["Đề xuất code theo anchor"],
  acceptance: ["Truy vấn mới về page zero", "Chuyển trang giữ đúng trang"],
  requirements: ["AC01", "AC03"],
  write_paths: ["membership-list.component.ts"],
  executor: "NATIVE_TASKLOOP",
};
const run: TnqdRun = {
  run_id: "run",
  created_at: "2026-10-22T00:00:00Z",
  phase: "execution",
  state: "RUNNING",
  nodes: [
    { id: "T02", title: task.title, state: "RUNNING", depends_on: ["T01"] },
  ],
  documents: [],
  plan: {
    title: "Kế hoạch thực hiện TNQD",
    summary:
      "Hai nhánh độc lập chia sẻ snapshot tài liệu, sau đó hợp nhất ở Verify.",
    tasks: [{ ...task, id: "T01", depends_on: [] }, task],
    digest: "frozen-plan",
    layers: [["T01"], ["T02"]],
    parallel_pair: ["T02", "T05"],
    max_parallel: 2,
  },
  memory: [
    {
      document_id: "PTYC",
      revision: "v1",
      mode: "POKEDEV_PROJECT_DOCUMENT_STORE",
      content_verified: true,
      retrieved_at: "2026-10-22T00:00:00Z",
    },
  ],
};
function show(value: TnqdRun) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const list = jest
    .spyOn(tnqdDemo, "list")
    .mockResolvedValue({ runs: [value] });
  render(
    <QueryClientProvider client={client}>
      <AuthContext.Provider
        value={
          { userData: { id: "owner" } } as React.ContextType<typeof AuthContext>
        }
      >
        <TnqdWorkflowPanel deliveryId="delivery" cycleId="cycle" canWrite />
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
  return { client, list };
}
afterEach(() => jest.restoreAllMocks());
test("loads the owned run, shows detailed dependencies and distinguishes local Memory; viewing never dispatches", async () => {
  const create = jest.spyOn(tnqdDemo, "plan"),
    execute = jest.spyOn(tnqdDemo, "execute");
  const { client, list } = show(run);
  await waitFor(() => expect(list).toHaveBeenCalledWith("delivery", "cycle"));
  await screen.findByText(/Cognee trên Harness chưa sẵn sàng/);
  fireEvent.click(screen.getByRole("button", { name: `T02: ${task.title}` }));
  expect(screen.getByText("Phụ thuộc: T01")).toBeInTheDocument();
  expect(screen.getByText(task.steps[0])).toBeInTheDocument();
  expect(create).not.toHaveBeenCalled();
  expect(execute).not.toHaveBeenCalled();
  expect(
    screen.getByRole("button", { name: "Tạo spec & kế hoạch" }),
  ).toBeDisabled();
  client.clear();
});
test("an uncertain run cannot create duplicate work", async () => {
  const { client } = show({ ...run, state: "UNCONFIRMED" });
  await screen.findByText("Cần đối soát");
  expect(
    screen.getByRole("button", { name: "Tạo spec & kế hoạch" }),
  ).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: "Đặt lại demo" }),
  ).not.toBeInTheDocument();
  client.clear();
});

test("a finished run remains visible without a reset action or automatic work", async () => {
  const plan = jest.spyOn(tnqdDemo, "plan"),
    execute = jest.spyOn(tnqdDemo, "execute");
  const { client } = show({ ...run, state: "SUCCEEDED" });
  await screen.findByText("Đã hoàn tất");
  expect(screen.queryByRole("button", { name: "Đặt lại demo" })).not.toBeInTheDocument();
  expect(plan).not.toHaveBeenCalled();
  expect(execute).not.toHaveBeenCalled();
  client.clear();
});
test("preview requires a live unexpired separate loopback origin", () => {
  const preview = {
    state: "LIVE",
    url: "http://localhost:45678/",
    expires_at: "2099-01-01T00:00:00Z",
    sandbox_id: "sandbox",
    artifact_sha256: "hash",
    data_mode: "fixture",
  };
  expect(safeTnqdPreview(preview)).toBe(true);
  for (const url of [
    "http://localhost:7860/",
    "http://localhost:9982/",
    "http://evil.local/",
    "javascript:alert(1)",
    "http://localhost:45678/?token=secret",
  ])
    expect(safeTnqdPreview({ ...preview, url })).toBe(false);
  expect(
    safeTnqdPreview({ ...preview, expires_at: "2000-01-01T00:00:00Z" }),
  ).toBe(false);
});

test("keeps the approved DAG and shows detailed followup tasks from TestForge", async () => {
  const followup = {
    ...task,
    id: "T14-R1",
    title: "Sửa trạng thái rỗng để giữ tổng số bằng 0",
    operation: "patch.empty",
    role: "developer",
    write_paths: ["membership-list.component.html"],
  };
  const { client } = show({
    ...run,
    followup_tasks: [followup],
    nodes: [
      ...run.nodes,
      { id: followup.id, state: "RUNNING", role: "developer" },
    ],
  });
  await screen.findByText("TaskLoop · xử lý phát hiện từ TestForge");
  fireEvent.click(
    screen.getByRole("button", {
      name: `Xem task phát sinh ${followup.id}: ${followup.title}`,
    }),
  );
  expect(
    screen.getByText("membership-list.component.html"),
  ).toBeInTheDocument();
  client.clear();
});

test("accepts native structured summaries without interpreting them as application success", () => {
  const parsed = tnqdRunSchema.parse({
    ...run,
    state: "FAILED",
    nodes: [
      {
        id: "T14-T1",
        state: "FAILED",
        summary: { status: "PARTIAL", coverage: { grounded: false } },
      },
    ],
  });
  expect(typeof parsed.nodes[0].summary).toBe("string");
  expect(parsed.state).toBe("FAILED");
  expect(parsed.nodes[0].state).toBe("FAILED");
});
