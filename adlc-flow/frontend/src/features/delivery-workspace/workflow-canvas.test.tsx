import "@testing-library/jest-dom";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import {
  liveWorkflows,
  type ProjectWorkflow,
} from "@/controllers/API/live-workflows";
import WorkflowCanvas from "./workflow-canvas";
import { starterGraph } from "./workflow-canvas-model";

jest.mock("@xyflow/react", () => ({
  useNodesState: (initial: unknown) => {
    const [nodes, setNodes] = require("react").useState(initial);
    return [nodes, setNodes, jest.fn()];
  },
  ReactFlowProvider: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
  ReactFlow: ({
    nodes,
    onNodeClick,
  }: {
    nodes: { id: string; data: { task: { title: string } } }[];
    onNodeClick: (e: null, node: unknown) => void;
  }) => (
    <div>
      {nodes.map((node) => (
        <button key={node.id} onClick={() => onNodeClick(null, node)}>
          {node.id}
        </button>
      ))}
    </div>
  ),
  Background: () => null,
  BackgroundVariant: { Dots: "dots" },
  Controls: () => null,
  MiniMap: () => null,
  Handle: () => null,
  Position: { Left: "left", Right: "right" },
  MarkerType: { ArrowClosed: "arrowclosed" },
}));

beforeAll(() => {
  global.structuredClone = (value) => JSON.parse(JSON.stringify(value));
});
afterEach(() => jest.restoreAllMocks());

function setup() {
  const graph = starterGraph();
  graph.nodes[0].task.write_paths = ["counter.mjs"];
  graph.nodes[1].task.write_paths = ["tests/test_page.py"];
  const workflow: ProjectWorkflow = {
    workflow_id: "workflow-a",
    project_id: "project-a",
    name: "Counter workflow",
    revision: 1,
    digest: "a".repeat(64),
    ready: true,
    graph,
  };
  const use = jest.fn(),
    saved = jest.fn();
  const save = jest
    .spyOn(liveWorkflows, "saveWorkflow")
    .mockImplementation(async (body) => ({
      ...workflow,
      graph: body.graph,
      name: body.name,
      revision: 2,
      digest: "b".repeat(64),
    }));
  const router = createMemoryRouter(
    [
      {
        path: "/work",
        element: (
          <WorkflowCanvas
            workflow={workflow}
            projects={[
              {
                project_id: "project-a",
                name: "Counter",
                repository: "admin/counter",
              } as never,
            ]}
            onClose={jest.fn()}
            onSaved={saved}
            onUse={use}
          />
        ),
      },
    ],
    { initialEntries: ["/work"] },
  );
  const result = render(<RouterProvider router={router} />);
  return { ...result, save, use, saved };
}

test("canvas edits persist file scope and dependencies without starting an agent", async () => {
  const { unmount, save, use } = setup();
  fireEvent.click(screen.getByRole("button", { name: "Phạm vi" }));
  fireEvent.change(screen.getByLabelText("File được phép sửa 1"), {
    target: { value: "src/counter.mjs" },
  });
  expect(
    screen.getByRole("button", { name: /Dùng cho yêu cầu mới/ }),
  ).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Kết nối" }));
  fireEvent.change(screen.getByLabelText("Nhận từ task"), {
    target: { value: "TEST" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Thêm kết nối" }));
  fireEvent.click(screen.getByRole("button", { name: "Lưu workflow" }));
  await waitFor(() => expect(save).toHaveBeenCalled());
  const payload = save.mock.calls[0][0];
  expect(payload.expected_digest).toBe("a".repeat(64));
  expect(payload.graph.nodes[0].task.write_paths).toEqual(["src/counter.mjs"]);
  expect(payload.graph.edges).toContainEqual({ source: "TEST", target: "DEV" });
  expect(use).not.toHaveBeenCalled();
  await screen.findByText(/Đã lưu phiên bản 2/);
  fireEvent.click(screen.getByRole("button", { name: /Dùng cho yêu cầu mới/ }));
  expect(use).toHaveBeenCalledWith(
    expect.objectContaining({ digest: "b".repeat(64), revision: 2 }),
  );
  unmount();
});

test("ordered steps, multiline content, undo and redo persist the user's task contract", async () => {
  const { unmount, save } = setup();
  fireEvent.change(screen.getByLabelText("Bước 1"), {
    target: { value: "Đọc source\nGiữ nguyên giao diện desktop" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Thêm bước" }));
  fireEvent.change(screen.getByLabelText("Bước 2"), {
    target: { value: "Thực hiện thay đổi trong file đã chọn" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Đưa bước 2 lên" }));
  expect(screen.getByLabelText("Bước 1")).toHaveValue(
    "Thực hiện thay đổi trong file đã chọn",
  );
  fireEvent.click(screen.getByRole("button", { name: "Hoàn tác canvas" }));
  expect(screen.getByLabelText("Bước 1")).toHaveValue(
    "Đọc source\nGiữ nguyên giao diện desktop",
  );
  fireEvent.click(screen.getByRole("button", { name: "Làm lại canvas" }));
  fireEvent.click(screen.getByRole("button", { name: "Lưu workflow" }));
  await waitFor(() => expect(save).toHaveBeenCalled());
  expect(save.mock.calls[0][0].graph.nodes[0].task.steps).toEqual([
    "Thực hiện thay đổi trong file đã chọn",
    "Đọc source\nGiữ nguyên giao diện desktop",
  ]);
  unmount();
});

test("unapplied or invalid JSON cannot silently save the previous graph", async () => {
  const { unmount, save } = setup();
  fireEvent.click(screen.getByRole("tab", { name: "JSON nâng cao" }));
  const input = screen.getByLabelText(/Cấu trúc workflow/);
  const valid = JSON.parse((input as HTMLTextAreaElement).value);
  fireEvent.change(input, { target: { value: '{"nodes":[]}' } });
  expect(screen.getByRole("button", { name: "Lưu workflow" })).toBeDisabled();
  fireEvent.click(
    screen.getByRole("button", { name: "Áp dụng JSON vào canvas" }),
  );
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Cấu trúc workflow không hợp lệ",
  );
  expect(save).not.toHaveBeenCalled();
  valid.nodes[0].task.steps = ["Thực hiện từ cấu hình JSON đã nhập"];
  fireEvent.change(input, { target: { value: JSON.stringify(valid) } });
  fireEvent.click(
    screen.getByRole("button", { name: "Áp dụng JSON vào canvas" }),
  );
  expect(screen.getByLabelText("Bước 1")).toHaveValue(
    "Thực hiện từ cấu hình JSON đã nhập",
  );
  fireEvent.click(screen.getByRole("button", { name: "Lưu workflow" }));
  await waitFor(() => expect(save).toHaveBeenCalled());
  expect(save.mock.calls[0][0].graph.nodes[0].task.steps).toEqual([
    "Thực hiện từ cấu hình JSON đã nhập",
  ]);
  unmount();
});

test("repository picker adds real indexed paths and preserves existing protected tests", async () => {
  const files = jest.spyOn(liveWorkflows, "files").mockResolvedValue({
    project_id: "project-a",
    commit: "c".repeat(40),
    paths: ["src/app.ts", "tests/test_existing.py"],
    truncated: false,
  });
  const { unmount, save } = setup();
  fireEvent.click(screen.getByRole("button", { name: "Phạm vi" }));
  fireEvent.click(
    screen.getByRole("button", { name: "Duyệt file của project" }),
  );
  fireEvent.click(await screen.findByRole("checkbox", { name: "src/app.ts" }));
  expect(
    screen.getByRole("checkbox", { name: /tests\/test_existing.py/ }),
  ).toBeDisabled();
  expect(files).toHaveBeenCalledWith("project-a");
  fireEvent.click(screen.getByRole("button", { name: "Xong" }));
  fireEvent.click(screen.getByRole("button", { name: "Lưu workflow" }));
  await waitFor(() => expect(save).toHaveBeenCalled());
  expect(save.mock.calls[0][0].graph.nodes[0].task.write_paths).toEqual([
    "counter.mjs",
    "src/app.ts",
  ]);
  unmount();
});

test("a template changes only the draft, preserves verification and can be undone", () => {
  const { unmount, save, use } = setup();
  fireEvent.click(screen.getByRole("button", { name: "Mẫu workflow" }));
  fireEvent.click(screen.getByRole("button", { name: /Duyệt và yêu cầu sửa/ }));
  fireEvent.click(screen.getByRole("button", { name: "Áp dụng mẫu" }));
  expect(save).not.toHaveBeenCalled();
  expect(use).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "GATE" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "Kiểm chứng & preview" }));
  expect(screen.getByLabelText("Lệnh kiểm tra 1")).toHaveValue(
    "python -m unittest discover -s tests -v",
  );
  fireEvent.click(screen.getByRole("button", { name: "Hoàn tác canvas" }));
  fireEvent.click(screen.getByRole("tab", { name: "Canvas" }));
  expect(screen.getByRole("button", { name: "REVIEW" })).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "GATE" }),
  ).not.toBeInTheDocument();
  unmount();
});

test("an invalid quoted command blocks save instead of silently saving the previous command", () => {
  const { unmount, save } = setup();
  fireEvent.click(screen.getByRole("tab", { name: "Kiểm chứng & preview" }));
  fireEvent.change(screen.getByLabelText("Lệnh kiểm tra 1"), {
    target: { value: 'python "broken' },
  });
  expect(screen.getByRole("button", { name: "Lưu workflow" })).toBeDisabled();
  expect(save).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("tab", { name: /^Canvas$/ }));
  fireEvent.click(screen.getByRole("tab", { name: "Kiểm chứng & preview" }));
  expect(screen.getByLabelText("Lệnh kiểm tra 1")).toHaveValue(
    'python "broken',
  );
  fireEvent.change(screen.getByLabelText("Lệnh kiểm tra 1"), {
    target: { value: "node --test tests/test_counter.mjs" },
  });
  expect(screen.getByRole("button", { name: "Lưu workflow" })).toBeEnabled();
  unmount();
});

test("a save response preserves edits made while that request was in flight", async () => {
  const { unmount, save } = setup();
  let finish: (result: ProjectWorkflow) => void = () => {};
  save.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  fireEvent.change(screen.getByLabelText("Bước 1"), {
    target: { value: "Nội dung đã gửi để lưu trước" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Lưu workflow" }));
  fireEvent.change(screen.getByLabelText("Bước 1"), {
    target: { value: "Nội dung mới nhập trong lúc đang lưu" },
  });
  const body = save.mock.calls[0][0];
  await act(async () =>
    finish({
      workflow_id: body.workflow_id,
      project_id: body.project_id,
      name: body.name,
      graph: body.graph,
      revision: 2,
      digest: "b".repeat(64),
      ready: true,
    }),
  );
  expect(screen.getByLabelText("Bước 1")).toHaveValue(
    "Nội dung mới nhập trong lúc đang lưu",
  );
  expect(
    screen.getByRole("button", { name: /Dùng cho yêu cầu mới/ }),
  ).toBeDisabled();
  expect(screen.getByText(/Có thay đổi chưa lưu/)).toBeInTheDocument();
  unmount();
});
