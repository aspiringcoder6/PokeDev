import { fixture } from "../../../tests/delivery-workspace-preview/fixture";
import {
  boardTasks,
  column,
  currentStep,
  outputSummary,
  stages,
} from "./model";

test("five steps come from persisted workflow, plan and run, never elapsed timers", () => {
  expect(currentStep({ ...fixture(1), workflow: { nodes: [] } })).toBe(0);
  for (const i of [1, 2, 3, 4]) expect(currentStep(fixture(i))).toBe(i);
});
test("board uses runtime traceability rather than task index or a fake completion timer", () => {
  const row = fixture(3);
  row.run!.tasks.reverse();
  expect(boardTasks(row).map((t) => t.status)).toEqual([
    "SUCCEEDED",
    "SUCCEEDED",
    "RUNNING",
    "PENDING",
    "PENDING",
  ]);
  expect(
    boardTasks({ ...row, run: null }).every((t) => t.status === "PENDING"),
  ).toBe(true);
});
test("dependency Gantt keeps parallel tasks at the same ordinal and labels missing dates estimated", () => {
  const tasks = boardTasks(fixture(3));
  expect(tasks.map((t) => t.order)).toEqual([0, 1, 1, 2, 3]);
  expect(tasks.every((t) => t.estimated)).toBe(true);
});
test.each(["FAILED", "CANCELLED", "SKIPPED", "WAITING_APPROVAL"])(
  "%s is never counted as done",
  (status) => expect(column(status)).toBe("review"),
);
test("unknown graph or output is not invented", () => {
  expect(stages({ nodes: [null, {}], edges: [] })).toEqual([]);
  expect(outputSummary({ summary: "Agent report" })).toBe("Agent report");
  expect(outputSummary(null)).toContain("có cấu trúc");
});
test("a completed task without a completion timestamp never receives invented elapsed time", () => {
  const row = fixture(3);
  row.run!.tasks[0].started_at = "2026-10-18T02:00:00Z";
  expect(boardTasks(row)[0].estimated).toBe(true);
});

test.each([
  "run-plan",
  "run-flow",
  "plan-flow",
  "task-run",
  "task-plan",
  "duplicate-task",
])(
  "%s mismatch cannot leak a completed status into graph/list/board",
  (mismatch) => {
    const row = fixture(3);
    if (mismatch === "run-plan") row.run!.execution_plan_id = "other";
    if (mismatch === "run-flow") row.run!.flow_id = "other";
    if (mismatch === "plan-flow") row.plan!.workflow_definition_id = "other";
    if (mismatch === "task-run") row.run!.tasks[0].workflow_run_id = "other";
    if (mismatch === "task-plan")
      row.run!.tasks[0].plan_traceability!.execution_plan_id = "other";
    if (mismatch === "duplicate-task")
      row.run!.tasks.push({ ...row.run!.tasks[0], id: "duplicate" });
    expect(boardTasks(row)[0].status).toBe("UNKNOWN");
    expect(boardTasks(row)[0].runtime).toBeUndefined();
    expect(column(boardTasks(row)[0].status)).toBe("review");
  },
);

test("reversed timestamps do not become measured Gantt duration", () => {
  const row = fixture(3);
  row.run!.tasks[0].started_at = "2026-10-18T03:00:00Z";
  row.run!.tasks[0].completed_at = "2026-10-18T02:00:00Z";
  expect(boardTasks(row)[0].estimated).toBe(true);
});
