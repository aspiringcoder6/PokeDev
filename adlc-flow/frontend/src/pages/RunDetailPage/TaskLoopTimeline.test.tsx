import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import {
  getAdlcSourcePatch,
  getAdlcTaskLoop,
  getAdlcTaskLoopRuntime,
} from "@/controllers/API/adlc";
import type {
  AdlcLoopIteration,
  AdlcTaskLoopInspection,
  AdlcTaskRun,
} from "@/types/adlc";
import TaskLoopTimeline from "./TaskLoopTimeline";

jest.mock("@/controllers/API/adlc", () => ({
  getAdlcTaskLoop: jest.fn(),
  getAdlcTaskLoopRuntime: jest.fn(),
  getAdlcSourcePatch: jest.fn(),
}));
jest.mock("@/components/common/genericIconComponent", () => () => null);

const task: AdlcTaskRun = {
  id: "task-1",
  workflow_run_id: "run-1",
  key: "coding",
  name: "Coding Agent",
  task_type: "IMPLEMENTATION",
  status: "WAITING_APPROVAL",
  dependency_task_run_ids: [],
  retry_count: 1,
  executor: {
    service: "agent-provider:coding-agent-contract-loop",
    operation: "coding-task-loop",
  },
};
const iteration: AdlcLoopIteration = {
  iteration: 2,
  attempt_id: "attempt-2",
  session_id: "fresh-session-2",
  phase: "FINISHED",
  status: "PASSED",
  started_at: "2026-10-10T01:00:00Z",
  completed_at: "2026-10-10T01:00:01Z",
  duration_ms: 1000,
  candidate_id: "candidate-2",
  candidate_digest: "sha256:verified",
  parent_candidate_id: "candidate-1",
  changed_paths: ["app.py"],
  patch_artifact_id: "patch-2",
  total_tokens: 18,
  cost: 0.1,
  stop_reason: "CHECKS_PASSED",
  checks: [
    {
      check_id: "behavior",
      label: "Addition works",
      kind: "BEHAVIORAL",
      passed: true,
      exit_code: 0,
      executed_tests: 3,
      timed_out: false,
    },
    {
      check_id: "contract:0",
      label: "Patch contains changes",
      kind: "CONTRACT",
      passed: true,
      exit_code: null,
      executed_tests: null,
      timed_out: null,
    },
  ],
};
const view: AdlcTaskLoopInspection = {
  schema_version: "0.1",
  workflow_run_id: "run-1",
  task_run_id: "task-1",
  mode: "COMMAND",
  history_source: "CHECKPOINT",
  history_complete: true,
  unavailable_reason: null,
  spec_digest: "sha256:spec",
  max_iterations: 3,
  max_duration_ms: 60000,
  max_total_tokens: 1000,
  max_total_cost: 1,
  elapsed_ms: 2000,
  total_tokens: 36,
  total_cost: 0.2,
  current_candidate_id: "candidate-2",
  current_candidate_digest: "sha256:verified",
  stopped: true,
  stop_reason: "CHECKS_PASSED",
  can_retry: false,
  recovery_available: false,
  iterations: [
    {
      ...iteration,
      iteration: 1,
      attempt_id: "attempt-1",
      session_id: "fresh-session-1",
      status: "CHECKS_FAILED",
      candidate_id: "candidate-1",
      candidate_digest: "sha256:first",
      parent_candidate_id: "initial",
      patch_artifact_id: "patch-1",
      stop_reason: "TASK_LOOP_CHECKS_FAILED",
      checks: [{ ...iteration.checks[0], passed: false, exit_code: 1 }],
    },
    iteration,
  ],
  failure_patterns: [],
};

const renderTimeline = (
  data: AdlcTaskLoopInspection = view,
  overrides: Partial<AdlcTaskRun> = {},
) => {
  (getAdlcTaskLoop as jest.Mock).mockResolvedValue(data);
  const onRetry = jest.fn();
  const result = render(
    <TaskLoopTimeline
      runId="run-1"
      task={{ ...task, ...overrides }}
      runStatus="WAITING_APPROVAL"
      acting={false}
      onRetry={onRetry}
    />,
  );
  return { ...result, onRetry };
};

beforeEach(() => {
  jest.clearAllMocks();
  (getAdlcTaskLoopRuntime as jest.Mock).mockResolvedValue(null);
});

it.each([
  "agent-provider:task-loop-harness",
  "agent-provider:coding-agent-harness-contract-loop",
])(
  "shows recorded Harness proposal runtime and retained history for %s",
  async (service) => {
    (getAdlcTaskLoopRuntime as jest.Mock).mockResolvedValue({
      schema_version: "0.2",
      workflow_run_id: "run-1",
      task_run_id: "task-1",
      binding_source: "CHECKPOINT",
      protocol_ref: "task-loop-runtime:iteration/0.2.0",
      execution_unified_with_harness: false,
      runtime: {
        protocol_ref: "task-loop-runtime:iteration/0.2.0",
        runtime_ref: "runtime:deepseek-harness-iteration/0.1.0",
        family: "HARNESS",
        provider_id: "my-codex",
        model_id: "cx/gpt-5.6-luna",
        agent: null,
        modes: ["FILE_PROPOSAL"],
        fresh_sessions: true,
        reported_usage: true,
        cancellation: true,
        cost_reporting: "UNAVAILABLE",
      },
    });
    renderTimeline(
      {
        ...view,
        total_cost: null,
        max_total_cost: null,
        iterations: view.iterations.map((i) => ({ ...i, cost: null })),
      },
      { executor: { service, operation: "coding-task-loop" } },
    );
    expect(await screen.findByText(/Runtime: Harness adapter/)).toBeVisible();
    expect(
      screen.getByText(/monetary cost is unavailable, not zero/),
    ).toBeVisible();
    expect(screen.getByText("Task loop · 2 / 3 iterations")).toBeVisible();
    expect(screen.queryByText(/Reported cost/)).not.toBeInTheDocument();
  },
);

it("loads passive runtime disclosure alongside history", async () => {
  (getAdlcTaskLoopRuntime as jest.Mock).mockResolvedValue({
    schema_version: "0.1",
    workflow_run_id: "run-1",
    task_run_id: "task-1",
    binding_source: "LEGACY",
    protocol_ref: null,
    runtime: null,
    execution_unified_with_harness: false,
  });
  renderTimeline();
  expect(
    await screen.findByText(
      /legacy checkpoint; no standardized runtime binding/,
    ),
  ).toBeVisible();
  expect(getAdlcTaskLoopRuntime).toHaveBeenCalledWith("run-1", "task-1");
});

it("runtime read outage does not hide existing iteration history", async () => {
  (getAdlcTaskLoopRuntime as jest.Mock).mockRejectedValue(new Error("offline"));
  renderTimeline();
  expect(await screen.findByText("Task loop · 2 / 3 iterations")).toBeVisible();
  expect(screen.getByText(/Runtime identity unavailable/)).toBeVisible();
});

it("a pending runtime identity request does not delay the timeline", async () => {
  (getAdlcTaskLoopRuntime as jest.Mock).mockReturnValue(new Promise(() => {}));
  renderTimeline();
  expect(await screen.findByText("Task loop · 2 / 3 iterations")).toBeVisible();
  expect(screen.getByText(/Runtime identity unavailable/)).toBeVisible();
});

it("shows candidate lineage, both kinds of checks, usage, and the final review instruction", async () => {
  renderTimeline();
  expect(await screen.findByText("Task loop · 2 / 3 iterations")).toBeVisible();
  expect(
    screen.getByText(
      "Checks passed. Review and approve the exact candidate below.",
    ),
  ).toBeVisible();
  expect(screen.getByText("Current candidate candidate-2")).toBeVisible();
  expect(screen.getByText("Based on candidate-1")).toBeVisible();
  expect(screen.getByText(/Contract: Patch contains changes/)).toBeVisible();
  expect(screen.getAllByText(/Addition works/)[1]).toBeVisible();
  expect(screen.getByText("Tokens 36 / 1,000")).toBeVisible();
  expect(screen.getByText("Reported cost 0.2 / 1")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: /Retry iteration/i }),
  ).not.toBeInTheDocument();
});

it("reads earlier patches from the owner-scoped endpoint without enabling approval", async () => {
  (getAdlcSourcePatch as jest.Mock).mockResolvedValue({
    artifact: {
      artifact_id: "patch-1",
      workflow_run_id: "run-1",
      task_run_id: "task-1",
      metadata: { candidate_digest: "sha256:first" },
    },
    files: [
      {
        file: "app.py",
        patch: "+first candidate\n",
        additions: 1,
        deletions: 0,
      },
    ],
  });
  renderTimeline();
  await screen.findByText("Task loop · 2 / 3 iterations");
  fireEvent.click(screen.getByText(/Iteration 1 · checks failed/));
  fireEvent.click(
    screen.getByRole("button", { name: "View iteration 1 patch" }),
  );
  expect(await screen.findByText("+first candidate")).toBeInTheDocument();
  expect(getAdlcSourcePatch).toHaveBeenCalledWith("run-1", "patch-1");
  expect(
    screen.queryByRole("button", { name: "Approve" }),
  ).not.toBeInTheDocument();
});

it("rejects a patch that belongs to a different candidate", async () => {
  (getAdlcSourcePatch as jest.Mock).mockResolvedValue({
    artifact: {
      artifact_id: "patch-2",
      workflow_run_id: "other-run",
      task_run_id: "task-1",
      metadata: { candidate_digest: "sha256:verified" },
    },
    files: [{ file: "private.py", patch: "PRIVATE WRONG PATCH" }],
  });
  renderTimeline();
  await screen.findByText("Task loop · 2 / 3 iterations");
  fireEvent.click(
    screen.getByRole("button", { name: "View iteration 2 patch" }),
  );
  expect(
    await screen.findByText(
      "This patch does not match the recorded candidate.",
    ),
  ).toBeVisible();
  expect(screen.queryByText("PRIVATE WRONG PATCH")).not.toBeInTheDocument();
});

it("shows a stopped loop and recurring findings with no retry", async () => {
  renderTimeline(
    {
      ...view,
      stopped: true,
      stop_reason: "TASK_LOOP_STALLED",
      failure_patterns: [
        {
          check_id: "behavior",
          kind: "BEHAVIORAL",
          label: "Addition works",
          iterations: [1, 2],
        },
      ],
    },
    { status: "FAILED" },
  );
  expect(
    await screen.findByText("Stopped after repeated unchanged candidates"),
  ).toBeVisible();
  expect(
    screen.getByText(/Address the stopping reason in a new run/),
  ).toBeVisible();
  expect(
    screen.getByText(/Addition works failed in iterations 1, 2/),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: /Retry iteration/i }),
  ).not.toBeInTheDocument();
});

it("offers recovery only when a saved result can be adopted", async () => {
  (getAdlcTaskLoop as jest.Mock).mockResolvedValue({
    ...view,
    can_retry: true,
    recovery_available: true,
  });
  const onRetry = jest.fn();
  render(
    <TaskLoopTimeline
      runId="run-1"
      task={{ ...task, status: "FAILED" }}
      runStatus="PAUSED"
      acting={false}
      onRetry={onRetry}
    />,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: /Recover saved result/i }),
  );
  expect(onRetry).toHaveBeenCalledTimes(1);
});

it("does not offer retry from a partial snapshot", async () => {
  (getAdlcTaskLoop as jest.Mock).mockResolvedValue({
    ...view,
    history_complete: false,
    history_source: "RUN_SNAPSHOT",
    can_retry: true,
  });
  render(
    <TaskLoopTimeline
      runId="run-1"
      task={{ ...task, status: "FAILED" }}
      runStatus="PAUSED"
      acting={false}
      onRetry={jest.fn()}
    />,
  );
  expect(
    await screen.findByText(/Full checkpoint history is unavailable/),
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: /Retry iteration/i }),
  ).not.toBeInTheDocument();
});

it("labels mock comparisons and avoids inventing provider usage", async () => {
  renderTimeline({
    ...view,
    mode: "MOCK",
    total_tokens: null,
    total_cost: null,
    elapsed_ms: null,
    iterations: [],
  });
  expect(await screen.findByText("Mock checks")).toBeVisible();
  expect(
    screen.getByText(/behavioral tests and provider usage were not measured/),
  ).toBeVisible();
  expect(screen.queryByText(/Tokens 0/)).not.toBeInTheDocument();
});

it("ignores an old run response after navigation", async () => {
  let resolveOld: (value: AdlcTaskLoopInspection) => void = () => undefined;
  (getAdlcTaskLoop as jest.Mock).mockReturnValueOnce(
    new Promise((resolve) => {
      resolveOld = resolve;
    }),
  );
  const { rerender } = render(
    <TaskLoopTimeline
      runId="run-1"
      task={task}
      runStatus="SUCCEEDED"
      acting={false}
      onRetry={jest.fn()}
    />,
  );
  (getAdlcTaskLoop as jest.Mock).mockResolvedValue({
    ...view,
    workflow_run_id: "run-2",
    task_run_id: "task-2",
    current_candidate_id: "candidate-new",
    iterations: [],
  });
  rerender(
    <TaskLoopTimeline
      runId="run-2"
      task={{ ...task, id: "task-2", workflow_run_id: "run-2" }}
      runStatus="SUCCEEDED"
      acting={false}
      onRetry={jest.fn()}
    />,
  );
  await screen.findByText("Current candidate candidate-new");
  await act(async () => resolveOld(view));
  await waitFor(() =>
    expect(screen.getByText("Current candidate candidate-new")).toBeVisible(),
  );
  expect(
    screen.queryByText("Current candidate candidate-2"),
  ).not.toBeInTheDocument();
});
