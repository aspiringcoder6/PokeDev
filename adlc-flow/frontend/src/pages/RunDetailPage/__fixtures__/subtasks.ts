import type {
  AdlcSubtaskRun,
  AdlcSubtaskSummary,
  AdlcTaskSubtasks,
} from "@/types/adlc";

/**
 * Test fixtures for subtask components.
 */

export function makeSubtask(
  id: string,
  overrides: Partial<AdlcSubtaskRun> = {},
): AdlcSubtaskRun {
  return {
    id,
    task_run_id: "task-1",
    name: id,
    description: "",
    status: "pending",
    dependencies: [],
    trigger: "on_success",
    started_at: null,
    completed_at: null,
    duration_ms: null,
    result: null,
    error: null,
    attempt_id: null,
    ...overrides,
  };
}

export function makeSummary(
  overrides: Partial<AdlcSubtaskSummary> = {},
): AdlcSubtaskSummary {
  return {
    total: 0,
    succeeded: 0,
    failed: 0,
    running: 0,
    pending: 0,
    skipped: 0,
    ...overrides,
  };
}

export function makeTaskSubtasks(
  subtasks: AdlcSubtaskRun[],
): AdlcTaskSubtasks {
  const summary: AdlcSubtaskSummary = {
    total: subtasks.length,
    succeeded: subtasks.filter((s) => s.status === "succeeded").length,
    failed: subtasks.filter((s) => s.status === "failed").length,
    running: subtasks.filter((s) => s.status === "running").length,
    pending: subtasks.filter(
      (s) => s.status === "pending" || s.status === "ready",
    ).length,
    skipped: subtasks.filter((s) => s.status === "skipped").length,
  };
  return {
    task_run_id: "task-1",
    subtasks,
    summary,
  };
}

export const linearSubtasks: AdlcSubtaskRun[] = [
  makeSubtask("task-1.sub-1", { status: "succeeded", duration_ms: 1200 }),
  makeSubtask("task-1.sub-2", {
    status: "succeeded",
    duration_ms: 800,
    dependencies: ["task-1.sub-1"],
  }),
  makeSubtask("task-1.sub-3", {
    status: "running",
    duration_ms: null,
    dependencies: ["task-1.sub-2"],
  }),
];

export const parallelSubtasks: AdlcSubtaskRun[] = [
  makeSubtask("task-1.sub-1", { status: "succeeded", duration_ms: 500 }),
  makeSubtask("task-1.sub-2", { status: "succeeded", duration_ms: 600 }),
  makeSubtask("task-1.sub-3", { status: "failed", duration_ms: 300 }),
];

export const diamondSubtasks: AdlcSubtaskRun[] = [
  makeSubtask("task-1.sub-1", { status: "succeeded" }),
  makeSubtask("task-1.sub-2", {
    status: "succeeded",
    dependencies: ["task-1.sub-1"],
  }),
  makeSubtask("task-1.sub-3", {
    status: "running",
    dependencies: ["task-1.sub-1"],
  }),
  makeSubtask("task-1.sub-4", {
    status: "pending",
    dependencies: ["task-1.sub-2", "task-1.sub-3"],
  }),
];
