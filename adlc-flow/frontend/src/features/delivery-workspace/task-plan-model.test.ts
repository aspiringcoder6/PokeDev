import { fixture } from "../../../tests/delivery-workspace-preview/fixture";
import {
  isStageLevelPlan,
  planSelectionScope,
  taskAcceptance,
  taskPlanGroups,
  taskStage,
} from "./task-plan-model";

test("stage groups follow explicit identifiers, never a task's index or similar name", () => {
  const row = fixture(2);
  const task = row.plan!.tasks[0];
  row.plan!.tasks.reverse();
  expect(taskStage(row, task).name).toBe("Làm rõ yêu cầu & tiêu chí");
  expect(taskPlanGroups(row)).toHaveLength(5);
  expect(isStageLevelPlan(row)).toBe(true);
  task.source_workflow_stage_id = "unknown";
  expect(taskStage(row, task)).toMatchObject({ id: "unmapped" });
  expect(isStageLevelPlan(row)).toBe(false);
});

test("an expanded task retains original stage lineage and many-task grouping", () => {
  const row = fixture(2);
  const first = row.plan!.tasks[0];
  first.source_workflow_stage_id = "expanded-stage";
  first.metadata = { source_workflow_stage_id: "stage-0" };
  row.plan!.tasks.push({ ...first, plan_task_id: "child" });
  expect(taskStage(row, first).id).toBe("stage-0");
  expect(
    taskPlanGroups(row).find((group) => group.id === "stage-0")?.count,
  ).toBe(2);
  expect(isStageLevelPlan(row)).toBe(false);
});

test.each([false, true])(
  "reads only declared criteria from a JSON spec; string=%s",
  (serialized) => {
    const task = fixture(2).plan!.tasks[0];
    const spec = {
      acceptance_criteria: [
        {
          criterion_id: "create",
          description: "Create a task.",
          check_refs: ["suite"],
        },
      ],
      verification_commands: [
        { check_id: "suite", test_path: "test_acceptance.py" },
      ],
      writable_paths: ["app.py"],
      max_iterations: 3,
    };
    task.inputs = { task_loop_spec: serialized ? JSON.stringify(spec) : spec };
    expect(taskAcceptance(task)).toEqual({
      criteria: [
        { id: "create", description: "Create a task.", checks: ["suite"] },
      ],
      checks: [{ id: "suite", path: "test_acceptance.py" }],
      writablePaths: ["app.py"],
      maxIterations: 3,
    });
  },
);

test.each([
  undefined,
  "broken json",
  { acceptance_criteria: [{ criterion_id: "no-description" }] },
])("missing acceptance text is not invented: %s", (value) => {
  const task = fixture(2).plan!.tasks[0];
  task.inputs = { task_loop_spec: value };
  expect(taskAcceptance(task).criteria).toEqual([]);
  expect(taskAcceptance(undefined).criteria).toEqual([]);
});

test("task drawer scope changes with product, plan, digest or run", () => {
  const row = fixture(3);
  const original = planSelectionScope(row);
  expect(planSelectionScope({ ...row, id: "other" })).not.toBe(original);
  expect(planSelectionScope({ ...row, plan_digest: "different" })).not.toBe(
    original,
  );
  expect(
    planSelectionScope({
      ...row,
      plan: { ...row.plan!, execution_plan_id: "other" },
    }),
  ).not.toBe(original);
  expect(
    planSelectionScope({ ...row, run: { ...row.run!, id: "other" } }),
  ).not.toBe(original);
  expect(planSelectionScope({ ...row, revision: row.revision + 1 })).toBe(
    original,
  );
});
