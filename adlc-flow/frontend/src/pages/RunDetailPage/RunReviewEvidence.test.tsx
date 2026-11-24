import { act, render, screen, waitFor } from "@testing-library/react";
import { getAdlcTaskLoop } from "@/controllers/API/adlc";
import type { AdlcTaskRun } from "@/types/adlc";
import {
  KernelReviewEvidence,
  QualityInterfaceSamples,
  useRunReviewEvidence,
} from "./RunReviewEvidence";

jest.mock("@/controllers/API/adlc", () => ({ getAdlcTaskLoop: jest.fn() }));
jest.mock("@/stores/authStore", () => ({
  __esModule: true,
  default: (select) => select({ userData: { id: "owner-a" } }),
}));

const runId = "11111111-1111-4111-8111-111111111111";
const taskId = "22222222-2222-4222-8222-222222222222";
const attempt = "33333333-3333-4333-8333-333333333333";
const candidate = "44444444-4444-4444-8444-444444444444";
const artifactId = "55555555-5555-4555-8555-555555555555";
const digest = `sha256:${"a".repeat(64)}`;
const task = {
  id: taskId,
  name: "Triển khai ứng dụng",
  status: "WAITING_APPROVAL",
  current_attempt_id: attempt,
  executor: { service: "agent-provider:task-loop-harness" },
  artifacts: [
    {
      artifact_id: artifactId,
      workflow_run_id: runId,
      task_run_id: taskId,
      attempt_id: attempt,
      kind: "SOURCE_PATCH",
      metadata: { candidate_id: candidate, candidate_digest: digest },
    },
  ],
} as unknown as AdlcTaskRun;
const inspection = {
  schema_version: "0.1",
  workflow_run_id: runId,
  task_run_id: taskId,
  mode: "COMMAND",
  history_source: "CHECKPOINT",
  history_complete: true,
  spec_digest: digest,
  current_candidate_id: candidate,
  current_candidate_digest: digest,
  iterations: [
    {
      iteration: 1,
      attempt_id: attempt,
      phase: "FINISHED",
      status: "PASSED",
      candidate_id: candidate,
      candidate_digest: digest,
      patch_artifact_id: artifactId,
      changed_paths: ["app.py"],
      duration_ms: 1000,
      checks: [
        {
          check_id: "fixed-suite",
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
};
function View({
  run = runId,
  current = task,
}: {
  run?: string;
  current?: AdlcTaskRun;
}) {
  return (
    <KernelReviewEvidence evidence={useRunReviewEvidence(run, [current])} />
  );
}
beforeEach(() => jest.clearAllMocks());

test("shows real count only from the candidate-bound command receipt", async () => {
  (getAdlcTaskLoop as jest.Mock).mockResolvedValue(inspection);
  const { rerender } = render(<View />);
  expect(await screen.findByText("9 test đã đạt")).toBeVisible();
  rerender(<View current={{ ...task }} />);
  expect(getAdlcTaskLoop).toHaveBeenCalledTimes(1);
});

test.each([
  { ...inspection, mode: "MOCK" },
  { ...inspection, history_complete: false },
  { ...inspection, workflow_run_id: taskId },
  { ...inspection, current_candidate_digest: `sha256:${"b".repeat(64)}` },
])(
  "does not turn mismatched, mock or incomplete evidence into a pass",
  async (value) => {
    (getAdlcTaskLoop as jest.Mock).mockResolvedValue(value);
    render(<View />);
    expect(await screen.findByText("Chưa đủ bằng chứng")).toBeVisible();
    expect(screen.queryByText("9 test đã đạt")).toBeNull();
  },
);

test("a late previous-run response cannot repopulate the current run", async () => {
  let finish: (value: unknown) => void = () => {};
  (getAdlcTaskLoop as jest.Mock)
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    )
    .mockRejectedValue(new Error("unavailable"));
  const { rerender } = render(<View />);
  rerender(<View run={taskId} />);
  await waitFor(() =>
    expect(screen.getByText("Chưa đủ bằng chứng")).toBeVisible(),
  );
  await act(async () => {
    finish(inspection);
  });
  expect(screen.queryByText("9 test đã đạt")).toBeNull();
});

test("sample views remain inert, labelled, and without invented verdicts or test counts", () => {
  render(<QualityInterfaceSamples />);
  expect(
    screen.getByText("Giao diện mẫu · không phải kết quả thật"),
  ).toBeVisible();
  expect(screen.getAllByText("Chưa thực thi · mẫu")).toHaveLength(2);
  expect(screen.getByText("Kết luận: —")).toBeVisible();
  expect(screen.queryByRole("button")).toBeNull();
  expect(getAdlcTaskLoop).not.toHaveBeenCalled();
});
