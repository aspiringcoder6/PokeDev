import type { Delivery } from "@/controllers/API/delivery";
import type { AdlcPlanTask, AdlcTaskRun } from "@/types/adlc";

export const STEPS = ["Yêu cầu", "Workflow", "Kế hoạch", "Theo dõi", "Kết quả"];
export const ROLE_NAMES: Record<string, string> = {
  admin: "Admin",
  business_analyst: "Business Analyst",
  developer: "Developer",
  tester: "Tester",
};
export const asObject = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
export const text = (value: unknown) =>
  typeof value === "string" ? value : "";
export const outputSummary = (output: unknown) =>
  text(output) ||
  text(asObject(output).summary) ||
  "Đã lưu kết quả có cấu trúc; mở phần nâng cao để đọc chi tiết.";
export const objects = (value: unknown) =>
  Array.isArray(value) ? value.map(asObject) : [];
export const strings = (value: unknown) =>
  Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
export const STATUS: Record<string, string> = {
  PENDING: "Chưa bắt đầu",
  READY: "Sẵn sàng",
  RUNNING: "Đang thực hiện",
  WAITING_APPROVAL: "Cần bạn xác nhận",
  SUCCEEDED: "Hoàn tất",
  FAILED: "Cần xử lý lỗi",
  CANCELLED: "Đã dừng",
  SKIPPED: "Đã bỏ qua",
  UNKNOWN: "Chưa đối soát",
  PAUSED: "Tạm dừng",
  CREATED: "Đã chuẩn bị",
  QUEUED: "Đang xếp lịch",
};
export const label = (status: string) => STATUS[status] || "Chưa xác nhận";
export const stageName = (kind: string) =>
  ({
    REQUIREMENT: "Làm rõ yêu cầu",
    IMPLEMENTATION: "Phát triển",
    TESTING: "Kiểm thử",
    VERIFICATION: "Xác minh",
    REVIEW: "Đánh giá",
    APPROVAL: "Phê duyệt",
  })[kind] || "Giai đoạn";

export function stages(graph: Record<string, unknown>) {
  const edges = objects(graph.edges);
  return objects(graph.nodes).flatMap((node) => {
    const stage = asObject(asObject(node.data).adlc);
    if (stage.document_type !== "WORKFLOW_STAGE") return [];
    return [
      {
        id: text(stage.stage_id) || text(node.id),
        name: text(stage.name),
        objective: text(stage.objective),
        kind: text(stage.stage_type),
        outputs: strings(stage.expected_outputs),
        package: text(asObject(stage.package_ref).package_id),
        dependencies: edges
          .filter((edge) => edge.target === node.id)
          .map((edge) => text(edge.source)),
      },
    ];
  });
}

export function currentStep(row: Delivery): number {
  if (row.run)
    return ["SUCCEEDED", "FAILED", "CANCELLED"].includes(row.run.status)
      ? 4
      : 3;
  if (row.plan) return 2;
  return stages(row.workflow).length ? 1 : 0;
}
export type BoardTask = {
  id: string;
  name: string;
  objective: string;
  status: string;
  dependencies: string[];
  outputs: string[];
  plan?: AdlcPlanTask;
  runtime?: AdlcTaskRun;
  start: number;
  end: number;
  estimated: boolean;
  order: number;
};
export function boardTasks(row: Delivery): BoardTask[] {
  const tasks = row.plan?.tasks || [];
  const boundRun =
    row.plan &&
    row.plan_id === row.plan.execution_plan_id &&
    row.plan.workflow_definition_id === row.flow_id &&
    row.run?.execution_plan_id === row.plan.execution_plan_id &&
    row.run.flow_id === row.flow_id
      ? row.run
      : null;
  const byId = new Map(tasks.map((task) => [task.plan_task_id, task]));
  const offsets = new Map<string, number>();
  const depth = (id: string, path = new Set<string>()): number => {
    if (offsets.has(id)) return offsets.get(id)!;
    if (path.has(id) || path.size > 128) return 0;
    const task = byId.get(id);
    const next = new Set(path).add(id);
    const value = Math.max(
      0,
      ...(task?.dependency_task_ids || []).map(
        (parent) => depth(parent, next) + 1,
      ),
    );
    offsets.set(id, value);
    return value;
  };
  return tasks.map((task) => {
    const matches = boundRun?.tasks.filter(
      (item) =>
        item.workflow_run_id === boundRun.id &&
        item.plan_traceability?.execution_plan_id ===
          row.plan!.execution_plan_id &&
        item.plan_traceability?.plan_task_id === task.plan_task_id,
    );
    const runtime = matches?.length === 1 ? matches[0] : undefined;
    const started = runtime?.started_at ? Date.parse(runtime.started_at) : NaN;
    const completed = runtime?.completed_at
      ? Date.parse(runtime.completed_at)
      : NaN;
    const factual =
      Number.isFinite(started) &&
      (!Number.isFinite(completed) || completed >= started) &&
      (Number.isFinite(completed) || runtime?.status === "RUNNING");
    return {
      id: task.plan_task_id,
      name: task.name,
      objective: task.objective,
      dependencies: task.dependency_task_ids,
      outputs: task.expected_artifacts,
      status: runtime?.status || (row.run ? "UNKNOWN" : "PENDING"),
      runtime,
      plan: task,
      order: depth(task.plan_task_id),
      estimated: !factual,
      start: factual ? started : depth(task.plan_task_id),
      end:
        factual && Number.isFinite(completed)
          ? completed
          : factual
            ? Math.max(started + 1000, Date.now())
            : depth(task.plan_task_id) + 1,
    };
  });
}
export const column = (status: string) =>
  status === "SUCCEEDED"
    ? "done"
    : status === "RUNNING"
      ? "active"
      : [
            "WAITING_APPROVAL",
            "FAILED",
            "CANCELLED",
            "SKIPPED",
            "UNKNOWN",
          ].includes(status)
        ? "review"
        : "todo";
export const time = (value: string) =>
  new Date(value).toLocaleString("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
    day: "2-digit",
    month: "2-digit",
  });
