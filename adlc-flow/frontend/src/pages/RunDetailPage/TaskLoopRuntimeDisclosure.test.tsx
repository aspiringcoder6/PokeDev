import { render, screen } from "@testing-library/react";
import type { AdlcLoopRuntimeView } from "@/types/adlc";
import TaskLoopRuntimeDisclosure, {
  supportedLoopRuntime,
} from "./TaskLoopRuntimeDisclosure";

const view: AdlcLoopRuntimeView = {
  schema_version: "0.1",
  workflow_run_id: "run-1",
  task_run_id: "task-1",
  binding_source: "CHECKPOINT",
  protocol_ref: "task-loop-runtime:iteration/0.1.0",
  execution_unified_with_harness: false,
  runtime: {
    protocol_ref: "task-loop-runtime:iteration/0.1.0",
    runtime_ref: "runtime:opencode-task-loop/0.1.0",
    family: "OPENCODE",
    provider_id: "fixture",
    model_id: "no-model",
    agent: null,
    modes: ["WORKSPACE_EDIT", "FILE_PROPOSAL"],
    fresh_sessions: true,
    reported_usage: true,
    cancellation: true,
  },
};

test("discloses the recorded adapter/model and does not claim a fully unified Harness", () => {
  render(
    <TaskLoopRuntimeDisclosure
      value={view}
      runId="run-1"
      taskId="task-1"
      mock={false}
    />,
  );
  expect(
    screen.getByText("Runtime: OpenCode · fixture/no-model"),
  ).toBeVisible();
  expect(screen.getByText(/Iteration protocol 0.1/)).toBeVisible();
  expect(
    screen.getByText(/not one fully unified Harness runtime/),
  ).toBeVisible();
});

test.each(["LEGACY", "NOT_STARTED", "UNAVAILABLE"] as const)(
  "%s does not invent a binding",
  (binding_source) => {
    render(
      <TaskLoopRuntimeDisclosure
        value={{ ...view, binding_source, runtime: null, protocol_ref: null }}
        runId="run-1"
        taskId="task-1"
        mock={false}
      />,
    );
    expect(screen.queryByText(/Runtime: OpenCode/)).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Iteration protocol 0.1/),
    ).not.toBeInTheDocument();
  },
);

test.each([
  { ...view, task_run_id: "foreign" },
  { ...view, workflow_run_id: "foreign" },
  { ...view, schema_version: "future" },
  { ...view, execution_unified_with_harness: true },
  { ...view, runtime: { ...view.runtime, runtime_ref: "<script>" } },
  { ...view, runtime: { ...view.runtime, fresh_sessions: false } },
  {
    ...view,
    runtime: { ...view.runtime, modes: ["FILE_PROPOSAL", "FILE_PROPOSAL"] },
  },
])("unknown or misbound payload cannot make a runtime claim", (data) => {
  expect(
    supportedLoopRuntime(data as AdlcLoopRuntimeView, "run-1", "task-1"),
  ).toBe(false);
  render(
    <TaskLoopRuntimeDisclosure
      value={data as AdlcLoopRuntimeView}
      runId="run-1"
      taskId="task-1"
      mock={false}
    />,
  );
  expect(screen.getByText(/Runtime identity unavailable/)).toBeVisible();
});

test("custom adapter is distinguished from Harness", () => {
  render(
    <TaskLoopRuntimeDisclosure
      value={{ ...view, runtime: { ...view.runtime!, family: "CUSTOM" } }}
      runId="run-1"
      taskId="task-1"
      mock={false}
    />,
  );
  expect(screen.getByText(/Runtime: Custom adapter/)).toBeVisible();
});

test("mock is never presented as a live runtime", () => {
  render(
    <TaskLoopRuntimeDisclosure
      value={null}
      runId="run-1"
      taskId="task-1"
      mock
    />,
  );
  expect(
    screen.getByText(/deterministic mock; not a Harness execution/),
  ).toBeVisible();
});

const harness: AdlcLoopRuntimeView = {
  ...view,
  schema_version: "0.2",
  protocol_ref: "task-loop-runtime:iteration/0.2.0",
  runtime: {
    ...view.runtime!,
    protocol_ref: "task-loop-runtime:iteration/0.2.0",
    runtime_ref: "runtime:deepseek-harness-iteration/0.1.0",
    family: "HARNESS",
    provider_id: "my-codex",
    model_id: "cx/gpt-5.6-luna",
    modes: ["FILE_PROPOSAL"],
    cost_reporting: "UNAVAILABLE",
  },
};

test("Harness v0.2 is disclosed as proposals, with missing price and ADLC-owned Verify", () => {
  render(
    <TaskLoopRuntimeDisclosure
      value={harness}
      runId="run-1"
      taskId="task-1"
      mock={false}
    />,
  );
  expect(
    screen.getByText("Runtime: Harness adapter · my-codex/cx/gpt-5.6-luna"),
  ).toBeVisible();
  expect(screen.getByText(/Iteration protocol 0.2/)).toBeVisible();
  expect(
    screen.getByText(/monetary cost is unavailable, not zero/),
  ).toBeVisible();
  expect(
    screen.getByText(
      /ADLC still owns candidate capture, Verify and human approval/,
    ),
  ).toBeVisible();
});

test.each([
  { ...harness, protocol_ref: view.protocol_ref },
  {
    ...harness,
    runtime: { ...harness.runtime!, protocol_ref: view.protocol_ref },
  },
  { ...harness, runtime: { ...harness.runtime!, cost_reporting: undefined } },
])("unknown price/protocol semantics cannot make a Harness claim", (data) => {
  expect(
    supportedLoopRuntime(data as AdlcLoopRuntimeView, "run-1", "task-1"),
  ).toBe(false);
});
