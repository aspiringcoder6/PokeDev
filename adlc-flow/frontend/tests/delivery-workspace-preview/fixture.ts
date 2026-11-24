// Isolated visual/test fixture. Never imported by the application router.
import type { Delivery } from "../../src/controllers/API/delivery";
import graphPlan from "./task-graph-plan.json";
export const ids = {
  row: "11111111-1111-4111-8111-111111111111",
  flow: "22222222-2222-4222-8222-222222222222",
  plan: "33333333-3333-4333-8333-333333333333",
  run: "44444444-4444-4444-8444-444444444444",
};
export const cycleIds = {
  first: "a1111111-1111-4111-8111-111111111111",
  next: "a2222222-2222-4222-8222-222222222222",
};

export function cyclePlanningFixture(
  phase: "VALIDATED" | "RUNNING" | "ACCEPTED" = "VALIDATED",
): Delivery {
  const row = cycleFixture("draft");
  const graph = taskGraphFixture();
  row.flow_id = graph.flow_id;
  row.workflow = graph.workflow;
  row.workflow_approved = true;
  row.cycle!.spec.workflow_id = graph.flow_id;
  row.cycle!.spec.planning_ready = true;
  row.cycle!.spec.baseline = {
    repository_key: "project:todo-app",
    base_commit: "a".repeat(40),
  };
  row.cycle!.spec.acceptance_criteria = [
    {
      criterion_id: "csv_export",
      description: "Xuất CSV đúng dữ liệu trong phạm vi đã chọn.",
    },
  ];
  row.cycle_capabilities!.plan_detailed = true;
  const operationId = "c3333333-3333-4333-8333-333333333333";
  const plan = {
    ...graph.plan!,
    metadata: {
      ...graph.plan!.metadata,
      cycle_id: row.cycle!.id,
      cycle_spec_digest: row.cycle!.spec_digest,
      planning_operation_id: operationId,
    },
  };
  // UI-only sample, not execution evidence. Split one branch to exercise a real join visually.
  const baseTask = plan.tasks.find((task) => task.name === "Implement A")!;
  const extraId = "c4444444-4444-4444-8444-444444444444";
  const extra = {
    ...baseTask,
    plan_task_id: extraId,
    name: "Tích hợp CSV",
    objective: "Nối dữ liệu CSV với API đã có.",
    source_workflow_stage_id: extraId,
    metadata: {
      ...baseTask.metadata,
      source_workflow_stage_id: baseTask.source_workflow_stage_id,
      criterion_ids: ["csv_export"],
    },
  };
  plan.tasks = plan.tasks.map((task) => ({
    ...task,
    metadata: { ...task.metadata, criterion_ids: ["csv_export"] },
    dependency_task_ids:
      task.name === "Verify"
        ? [...task.dependency_task_ids, extraId]
        : task.dependency_task_ids,
  }));
  plan.tasks.splice(
    plan.tasks.findIndex((task) => task.name === "Verify"),
    0,
    extra,
  );
  row.cycle!.planning_operations = [
    {
      id: operationId,
      cycle_id: row.cycle!.id,
      spec_digest: row.cycle!.spec_digest,
      input_digest: `sha256:${"e".repeat(64)}`,
      status: phase === "RUNNING" ? "RESERVED" : "SUCCEEDED",
      phase,
      created_at: row.created_at,
      updated_at: row.updated_at,
      ...(phase === "RUNNING"
        ? {}
        : {
            preview_plan: plan,
            plan_digest: `sha256:${"b".repeat(64)}`,
            validation_errors: [],
            diff: {
              added: [
                "scope",
                "backend",
                "frontend",
                "csv_integration",
                "verify",
              ],
              removed: [],
              changed: [],
              unchanged: [],
            },
          }),
    },
  ];
  if (phase === "ACCEPTED") {
    row.plan = { ...plan, status: "APPROVED" };
    row.plan_id = plan.execution_plan_id;
    row.plan_digest = `sha256:${"b".repeat(64)}`;
    row.plan_approved = true;
    row.cycle!.state = "PLANNING";
    row.cycle!.plan_id = row.plan_id;
  }
  return row;
}

export function cycleFixture(
  selected: "initial" | "draft" = "initial",
  withDraft = false,
): Delivery {
  const row = fixture(3);
  const first = {
    id: cycleIds.first,
    delivery_id: row.id,
    number: 1,
    predecessor_id: null,
    revision: 4,
    spec_revision: 1,
    state: "LINKED" as const,
    goal: row.requirement,
    plan_id: row.plan_id,
    plan_version: 1,
    run_id: row.run!.id,
    dispatch_plan_id: row.plan_id,
    run_status: "RUNNING",
    is_initial: true,
    is_latest: !withDraft && selected !== "draft",
    is_execution_cycle: true,
    created_at: row.created_at,
    updated_at: row.updated_at,
  };
  const next = {
    ...first,
    id: cycleIds.next,
    number: 2,
    predecessor_id: first.id,
    revision: 1,
    spec_revision: 1,
    state: "DRAFT" as const,
    goal: "Thêm xuất báo cáo CSV, giữ nguyên các chức năng đã được chấp nhận.",
    plan_id: null,
    plan_version: null,
    run_id: null,
    dispatch_plan_id: null,
    run_status: null,
    is_initial: false,
    is_latest: true,
    is_execution_cycle: false,
  };
  const current = selected === "draft" ? next : first;
  const spec = {
    schema_version: "0.1",
    goal: current.goal,
    workflow_id: row.flow_id,
    workflow_version: 1,
    workflow_digest: row.workflow_digest,
    workflow_snapshot: row.workflow,
    baseline: null,
    acceptance_criteria: [],
    selected_feedback_ids: [],
    execution_ready: false,
    source: selected === "draft" ? "USER_DRAFT" : "LEGACY_IMPORT",
  };
  return {
    ...row,
    requirement: current.goal,
    plan_id: current.plan_id,
    plan: selected === "draft" ? null : row.plan,
    plan_digest: selected === "draft" ? null : row.plan_digest,
    plan_approved: selected === "draft" ? false : row.plan_approved,
    workflow_approved: selected === "draft" ? false : row.workflow_approved,
    run: selected === "draft" ? null : row.run,
    dispatch_plan_id: current.dispatch_plan_id,
    notes: [],
    cycles: selected === "draft" || withDraft ? [next, first] : [first],
    cycle: {
      ...current,
      spec,
      spec_digest: `sha256:${"d".repeat(64)}`,
      plan_revisions:
        selected === "draft"
          ? []
          : [
              {
                plan_id: row.plan_id!,
                ordinal: 1,
                plan_version: 1,
                plan_digest: row.plan_digest!,
                created_at: row.created_at,
                approval: {},
              },
            ],
    },
    cycle_capabilities: {
      prepare: true,
      execute: selected === "initial",
      edit_workflow: selected === "initial",
    },
  };
}
export const names = [
  "Làm rõ yêu cầu & tiêu chí",
  "Xây dựng giao diện",
  "Phát triển chức năng",
  "Kiểm thử tự động",
  "Verify & bàn giao",
];
const objectives = [
  "Chốt chức năng quản lý công việc và các tiêu chí chấp nhận.",
  "Tạo giao diện danh sách, bảng công việc và trang báo cáo.",
  "Xây API, phân công công việc và xử lý hạn hoàn thành.",
  "Chạy bộ kiểm thử đã khóa trên bản thay đổi.",
  "Đối chiếu bằng chứng với tiêu chí, duyệt trước khi phát hành.",
];
const types = [
  "REQUIREMENT",
  "IMPLEMENTATION",
  "IMPLEMENTATION",
  "TESTING",
  "VERIFICATION",
];
export function fixture(step = 3): Delivery {
  const graph = {
    nodes: names.map((name, i) => ({
      id: `stage-${i}`,
      data: {
        adlc: {
          document_type: "WORKFLOW_STAGE",
          stage_id: `stage-${i}`,
          name,
          objective: objectives[i],
          stage_type: types[i],
          expected_outputs: [
            i < 3 ? "Bản thay đổi mã nguồn" : "Báo cáo kèm bằng chứng",
          ],
          package_ref: { package_id: "coding-agent" },
        },
      },
    })),
    edges: [
      [0, 1],
      [0, 2],
      [1, 3],
      [2, 3],
      [3, 4],
    ].map(([source, target]) => ({
      source: `stage-${source}`,
      target: `stage-${target}`,
    })),
  };
  const tasks = names.map((name, i) => ({
    plan_task_id: `task-${i}`,
    source_workflow_stage_id: `stage-${i}`,
    resolved_node_spec_id: `spec-${i}`,
    resolved_node_digest: `sha256:${"c".repeat(64)}`,
    task_type: types[i],
    name,
    objective: objectives[i],
    expected_artifacts: [i < 3 ? "source_patch" : "verification_report"],
    inputs: {},
    input_bindings: [],
    effective_policies: { retry: { max_attempts: 2 } },
    metadata: {},
    dependency_task_ids:
      i === 0
        ? []
        : i < 3
          ? ["task-0"]
          : i === 3
            ? ["task-1", "task-2"]
            : ["task-3"],
  }));
  return {
    id: ids.row,
    flow_id: ids.flow,
    title: "Ứng dụng quản lý công việc nhóm",
    requirement:
      "Xây dựng ứng dụng cho nhóm 5 người tạo và phân công công việc. Có đăng nhập, bộ lọc trạng thái, hạn hoàn thành và báo cáo tiến độ. Giao diện đơn giản, dễ sử dụng; có kiểm thử và bằng chứng Verify trước bàn giao.",
    revision: 4,
    folder_id: null,
    dispatch_plan_id: null,
    scope: "PRIVATE",
    updated_at: "2026-10-18T03:00:00Z",
    created_at: "2026-10-18T02:00:00Z",
    workflow: graph,
    workflow_digest: `sha256:${"a".repeat(64)}`,
    workflow_approved: step > 1,
    workflow_approved_by: null,
    workflow_approved_at: null,
    plan_id: step > 1 ? ids.plan : null,
    plan_digest: step > 1 ? `sha256:${"b".repeat(64)}` : null,
    plan_approved: step > 2,
    plan:
      step > 1
        ? {
            execution_plan_id: ids.plan,
            workflow_definition_id: ids.flow,
            workflow_definition_version: 1,
            plan_version: 1,
            resolved_node_specs: [],
            tasks,
            status: step > 2 ? "APPROVED" : "VALIDATED",
            validation_status: "VALID",
            validation_errors: [],
            warnings: [],
            assumptions: [],
            approval_required: true,
          }
        : null,
    run:
      step > 2
        ? {
            id: ids.run,
            flow_id: ids.flow,
            execution_plan_id: ids.plan,
            status: step === 4 ? "SUCCEEDED" : "RUNNING",
            tasks: tasks.map((task, i) => ({
              id: `runtime-${i}`,
              workflow_run_id: ids.run,
              name: task.name,
              status:
                step === 4 || i < 2
                  ? "SUCCEEDED"
                  : i === 2
                    ? "RUNNING"
                    : "PENDING",
              plan_traceability: {
                execution_plan_id: ids.plan,
                plan_task_id: task.plan_task_id,
              },
              result: null,
            })),
            events: [],
          }
        : null,
    permissions: { write: true, execute: true },
    notes: [
      {
        id: "55555555-5555-4555-8555-555555555555",
        kind: "CHANGE_REQUEST",
        text: "Bổ sung chế độ xem theo thành viên ở lượt tiếp theo.",
        actor_name: "Minh Anh · BA",
        created_at: "2026-10-18T03:00:00Z",
        status: "OPEN",
      },
    ],
  } as unknown as Delivery;
}

// Produced by the real compiler and revalidated in the backend fixture test.
// It has never been executed and must stay outside the application router.
export function taskGraphFixture(): Delivery {
  return {
    ...fixture(2),
    flow_id: graphPlan.plan.workflow_definition_id,
    title: "Kế hoạch có nhánh song song",
    workflow: graphPlan.workflow,
    plan_id: graphPlan.plan.execution_plan_id,
    plan: graphPlan.plan,
    run: null,
    notes: [],
  } as unknown as Delivery;
}
