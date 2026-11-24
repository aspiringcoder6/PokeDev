import type { Delivery } from "@/controllers/API/delivery";
import type { AdlcPlanTask } from "@/types/adlc";
import { asObject, objects, stages, strings, text } from "./model";

export function planSelectionScope(row: Delivery) {
  return JSON.stringify([
    row.id,
    row.cycle?.id,
    row.cycle?.spec_digest,
    row.plan_id,
    row.plan?.execution_plan_id,
    row.plan_digest,
    row.run?.id,
  ]);
}

export function taskStage(row: Delivery, task: AdlcPlanTask) {
  const available = stages(row.workflow);
  const index = available.findIndex(
    (stage) => stage.id === task.source_workflow_stage_id,
  );
  const originalId = text(task.metadata?.source_workflow_stage_id);
  const original = originalId
    ? available.findIndex((stage) => stage.id === originalId)
    : -1;
  const match = original >= 0 ? original : index;
  return match < 0
    ? { id: "unmapped", name: "Chưa gắn giai đoạn", color: 6 }
    : {
        id: available[match].id,
        name: available[match].name || "Giai đoạn chưa có tên",
        color: match % 6,
      };
}

export function taskPlanGroups(row: Delivery) {
  const groups = new Map<
    string,
    ReturnType<typeof taskStage> & { count: number }
  >();
  for (const task of row.plan?.tasks ?? []) {
    const group = taskStage(row, task);
    groups.set(group.id, {
      ...group,
      count: (groups.get(group.id)?.count ?? 0) + 1,
    });
  }
  return [...groups.values()];
}

export function isStageLevelPlan(row: Delivery) {
  const workflowStages = stages(row.workflow);
  const groups = taskPlanGroups(row);
  return (
    workflowStages.length > 0 &&
    groups.length === workflowStages.length &&
    groups.every((group) => group.id !== "unmapped" && group.count === 1)
  );
}

// Read declared acceptance requirements, never manufacture a verification result.
export function taskAcceptance(task: AdlcPlanTask | undefined) {
  let value: unknown = task?.inputs?.task_loop_spec;
  if (typeof value === "string") {
    try {
      value = JSON.parse(value);
    } catch {
      value = undefined;
    }
  }
  const spec = asObject(value);
  return {
    criteria: objects(spec.acceptance_criteria)
      .map((item) => ({
        id: text(item.criterion_id),
        description: text(item.description),
        checks: strings(item.check_refs),
      }))
      .filter((item) => item.description),
    writablePaths: strings(spec.writable_paths),
    maxIterations:
      typeof spec.max_iterations === "number" ? spec.max_iterations : null,
    checks: objects(spec.verification_commands)
      .map((item) => ({ id: text(item.check_id), path: text(item.test_path) }))
      .filter((item) => item.id),
  };
}
