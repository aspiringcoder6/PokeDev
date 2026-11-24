import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";
import type { NativeLoops } from "@/controllers/API/product-loop";
import { NativeLoopView } from "./product-loop";

const data: NativeLoops = {
  context: {
    context_digest: "digest",
    base_commit: "a".repeat(40),
    goal: "Improve app",
    writable_paths: ["app.py"],
    max_iterations: 3,
    file_sizes: {},
    checks: [{ check_id: "acceptance", test_path: "test_acceptance.py" }],
  },
  capabilities: {
    ready: true,
    model: { provider: "netmind", model: "GLM" },
    max_iterations: 3,
  },
  error_code: null,
  loops: [],
};
const props = {
  data,
  busy: false,
  error: "",
  canRun: true,
  onPrepare: jest.fn(),
  onRefresh: jest.fn(),
  onDownload: jest.fn(),
};
test("viewing a native loop never creates an execution and preparing is explicit", () => {
  render(<NativeLoopView {...props} />);
  expect(props.onPrepare).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Chuẩn bị chạy" }));
  expect(props.onPrepare).toHaveBeenCalledTimes(1);
});
test("a receipt keeps real changes visible through a platform outage and escapes diff text", () => {
  const { container } = render(
    <NativeLoopView
      {...props}
      data={{
        ...data,
        capabilities: null,
        loops: [
          {
            loop_id: "id",
            state: "SUCCEEDED",
            created_at: "2026-10-21T12:00:00Z",
            diff: "+<img src=x onerror=alert(1)>",
            baseline: { passed: false },
            iterations: [
              {
                number: 1,
                state: "PASSED",
                passed: true,
                protected_intact: true,
              },
            ],
            changed_paths: ["app.py"],
            contract: { status: "DONE" },
            goal_state: { phase: "complete" },
            canonical_cycle_execution: false,
            release_status: "REVIEW_REQUIRED",
          },
        ],
      }}
    />,
  );
  expect(screen.getByText("Bản sửa đạt kiểm thử")).toBeInTheDocument();
  expect(screen.getByText("Test chưa đạt")).toBeInTheDocument();
  expect(screen.getByText("Hoàn tất")).toBeInTheDocument();
  expect(container.querySelector("img")).toBeNull();
  expect(screen.getByRole("button", { name: "Chuẩn bị chạy" })).toBeDisabled();
});
test("an uncertain acknowledgement prevents a second execution", () => {
  render(
    <NativeLoopView
      {...props}
      data={{
        ...data,
        loops: [
          {
            loop_id: "id",
            state: "UNCONFIRMED",
            created_at: "2026-10-21T12:00:00Z",
            diff: "",
            canonical_cycle_execution: false,
            release_status: "REVIEW_REQUIRED",
          },
        ],
      }}
    />,
  );
  expect(screen.getByRole("button", { name: "Đang theo dõi" })).toBeDisabled();
  expect(screen.getByText("Cần đối soát")).toBeInTheDocument();
});
