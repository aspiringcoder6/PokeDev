import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { getAdlcTaskLoop } from "@/controllers/API/adlc";
import type { AdlcTaskRun } from "@/types/adlc";
import { readKernelEvidence, summarizeKernelEvidence } from "./kernel-evidence";
import KernelResults from "./kernel-results";

jest.mock("@/controllers/API/adlc", () => ({ getAdlcTaskLoop: jest.fn() }));
jest.mock("@/stores/authStore", () => ({
  __esModule: true,
  default: (select) => select({ userData: { id: "owner-a" } }),
}));

const ids = {
  run: "11111111-1111-4111-8111-111111111111",
  task: "22222222-2222-4222-8222-222222222222",
  attempt: "33333333-3333-4333-8333-333333333333",
  candidate: "44444444-4444-4444-8444-444444444444",
  artifact: "55555555-5555-4555-8555-555555555555",
};
const digest = `sha256:${"a".repeat(64)}`;
function savedEvidence() {
  return readKernelEvidence(
    {
      schema_version: "0.1",
      workflow_run_id: ids.run,
      task_run_id: ids.task,
      mode: "COMMAND",
      history_source: "CHECKPOINT",
      history_complete: true,
      spec_digest: `sha256:${"b".repeat(64)}`,
      current_candidate_id: ids.candidate,
      current_candidate_digest: digest,
      iterations: [
        {
          iteration: 1,
          attempt_id: ids.attempt,
          phase: "FINISHED",
          status: "PASSED",
          candidate_id: ids.candidate,
          candidate_digest: digest,
          patch_artifact_id: ids.artifact,
          changed_paths: ["app.py"],
          duration_ms: 21116,
          checks: [
            {
              check_id: "acceptance",
              label: "Bộ kiểm thử cố định",
              kind: "BEHAVIORAL",
              passed: true,
              exit_code: 0,
              executed_tests: 9,
              timed_out: false,
            },
          ],
        },
      ],
    },
    ids.run,
    ids.task,
  );
}
function savedTask(): AdlcTaskRun {
  return {
    id: ids.task,
    name: "Triển khai ứng dụng",
    status: "WAITING_APPROVAL",
    current_attempt_id: ids.attempt,
    executor: { service: "agent-provider:task-loop-harness" },
    artifacts: [
      {
        artifact_id: ids.artifact,
        workflow_run_id: ids.run,
        task_run_id: ids.task,
        attempt_id: ids.attempt,
        kind: "SOURCE_PATCH",
        metadata: { candidate_id: ids.candidate, candidate_digest: digest },
      },
    ],
  } as unknown as AdlcTaskRun;
}

beforeEach(() => jest.clearAllMocks());

test("summarizes protected command checks tied to this attempt and patch", () => {
  expect(summarizeKernelEvidence(savedEvidence(), savedTask())).toMatchObject({
    bound: true,
    passed: true,
    tests: 9,
  });
});

test.each([
  [
    "mock mode",
    (view, _task) => {
      view.mode = "MOCK";
    },
  ],
  [
    "incomplete history",
    (view, _task) => {
      view.history_complete = false;
    },
  ],
  [
    "fallback metadata",
    (view, _task) => {
      view.history_source = "RUN_SNAPSHOT";
    },
  ],
  [
    "missing spec digest",
    (view, _task) => {
      view.spec_digest = null;
    },
  ],
  [
    "old attempt",
    (_view, task) => {
      task.current_attempt_id = ids.run;
    },
  ],
  [
    "different candidate",
    (view, _task) => {
      view.current_candidate_id = ids.run;
    },
  ],
  [
    "different digest",
    (view, _task) => {
      view.current_candidate_digest = `sha256:${"c".repeat(64)}`;
    },
  ],
  [
    "wrong patch scope",
    (_view, task) => {
      task.artifacts[0].task_run_id = ids.run;
    },
  ],
  [
    "wrong patch attempt",
    (_view, task) => {
      task.artifacts[0].attempt_id = ids.run;
    },
  ],
  [
    "wrong patch candidate",
    (_view, task) => {
      task.artifacts[0].metadata.candidate_digest = `sha256:${"c".repeat(64)}`;
    },
  ],
  [
    "missing patch",
    (_view, task) => {
      task.artifacts = [];
    },
  ],
  [
    "unfinished iteration",
    (view, _task) => {
      view.iterations[0].phase = "VERIFIED";
    },
  ],
  [
    "unknown executor",
    (_view, task) => {
      task.executor.service = "agent-provider:task-loop-mock";
    },
  ],
])("does not certify %s", (_name, mutate) => {
  const view = savedEvidence(),
    task = savedTask();
  mutate(view, task);
  expect(summarizeKernelEvidence(view, task).passed).toBe(false);
});

test.each([
  [
    "no checks",
    (view) => {
      view.iterations[0].checks = [];
    },
  ],
  [
    "zero tests",
    (view) => {
      view.iterations[0].checks[0].executed_tests = 0;
    },
  ],
  [
    "nonzero exit",
    (view) => {
      view.iterations[0].checks[0].exit_code = 1;
    },
  ],
  [
    "timeout",
    (view) => {
      view.iterations[0].checks[0].timed_out = true;
    },
  ],
  [
    "failed check",
    (view) => {
      view.iterations[0].checks[0].passed = false;
    },
  ],
  [
    "mock comparisons",
    (view) => {
      view.iterations[0].checks[0].kind = "MOCK";
    },
  ],
])("a PASSED label alone cannot override %s", (_name, mutate) => {
  const view = savedEvidence();
  mutate(view);
  expect(summarizeKernelEvidence(view, savedTask()).passed).toBe(false);
});

test("rejects evidence from another task/run or with malformed measurements", () => {
  expect(() =>
    readKernelEvidence(savedEvidence(), ids.task, ids.run),
  ).toThrow();
  const view = savedEvidence();
  view.iterations[0].checks[0].executed_tests = -1;
  expect(() => readKernelEvidence(view, ids.run, ids.task)).toThrow();
});

function show(task = savedTask(), runId = ids.run) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const onReview = jest.fn();
  render(
    <QueryClientProvider client={client}>
      <KernelResults
        deliveryId={ids.run}
        runId={runId}
        task={task}
        onReview={onReview}
      />
    </QueryClientProvider>,
  );
  return { onReview };
}

test("shows test evidence while review is pending, without accepting or releasing it", async () => {
  (getAdlcTaskLoop as jest.Mock).mockResolvedValue(savedEvidence());
  const { onReview } = show();
  expect(await screen.findByText("9 kiểm thử đã chạy")).toBeInTheDocument();
  expect(
    screen.getByText("Candidate đang chờ bạn duyệt, chưa được bàn giao."),
  ).toBeInTheDocument();
  expect(screen.getByText(/Không tự xác nhận giao diện/)).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Xem patch & bằng chứng" }),
  );
  expect(onReview).toHaveBeenCalledTimes(1);
  expect(getAdlcTaskLoop).toHaveBeenCalledWith(ids.run, ids.task);
  expect(getAdlcTaskLoop).toHaveBeenCalledTimes(1);
});

test("cannot turn an agent's self-reported success into system test evidence", async () => {
  const view = savedEvidence();
  view.history_source = "UNAVAILABLE";
  view.history_complete = false;
  (getAdlcTaskLoop as jest.Mock).mockResolvedValue(view);
  const task = savedTask();
  task.status = "SUCCEEDED";
  task.result = {
    output: { verification_report: { passed: true } },
  } as AdlcTaskRun["result"];
  show(task);
  expect(
    await screen.findByText(/Chưa đủ bằng chứng kernel/),
  ).toBeInTheDocument();
  expect(
    screen.queryByText("Đạt trong phạm vi kiểm thử"),
  ).not.toBeInTheDocument();
});

test("scope errors fail closed and are not retried or reflected as private error text", async () => {
  (getAdlcTaskLoop as jest.Mock).mockResolvedValue({
    ...savedEvidence(),
    task_run_id: ids.run,
  });
  show();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Chưa đọc được bằng chứng",
  );
  expect(
    screen.queryByText("Đạt trong phạm vi kiểm thử"),
  ).not.toBeInTheDocument();
  await waitFor(() => expect(getAdlcTaskLoop).toHaveBeenCalledTimes(1));
});
