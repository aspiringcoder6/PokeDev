import { z } from "zod";
import { getBaseUrl } from "@/customization/utils/urls";
import type { AdlcExecutionPlan, AdlcWorkflowRun } from "@/types/adlc";
import { api } from "./api";

const uuid = z.string().uuid();
const digest = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const planSnapshot = z
  .object({
    execution_plan_id: uuid,
    tasks: z.array(z.unknown()),
    status: z.string(),
    validation_status: z.string(),
    metadata: z.record(z.unknown()),
  })
  .passthrough();
const planningOperation = z.object({
  id: uuid,
  cycle_id: uuid,
  status: z.enum(["RESERVED", "UNCONFIRMED", "SUCCEEDED", "FAILED"]),
  spec_digest: digest,
  input_digest: digest,
  created_at: z.string(),
  updated_at: z.string(),
  phase: z.string(),
  error_code: z.string().nullable().optional(),
  preview_plan: planSnapshot.optional(),
  plan_digest: digest.optional(),
  proposal: z.record(z.unknown()).optional(),
  validation_errors: z
    .array(z.object({ code: z.string(), message: z.string() }))
    .optional(),
  diff: z
    .object({
      added: z.array(z.string()),
      removed: z.array(z.string()),
      changed: z.array(z.string()),
      unchanged: z.array(z.string()),
    })
    .optional(),
  usage: z
    .object({ total_tokens: z.number(), cost: z.null() })
    .passthrough()
    .nullable()
    .optional(),
  accepted_at: z.string().optional(),
});
export type CyclePlanningOperation = Omit<
  z.infer<typeof planningOperation>,
  "preview_plan"
> & { preview_plan?: AdlcExecutionPlan };
const planningContext = z.object({
  cycle_id: uuid,
  spec_digest: digest,
  workflow_digest: digest,
  repository_key: z.string(),
  base_commit: z.string().regex(/^[a-f0-9]{40}$/),
  paths: z.array(z.string()),
  acceptance_criteria: z.array(
    z.object({
      criterion_id: z.string(),
      stage_id: uuid,
      description: z.string(),
      check_refs: z.array(z.string()),
      kind: z.string(),
    }),
  ),
  limits: z.object({
    max_tasks: z.number(),
    max_tasks_per_stage: z.number(),
    max_depth: z.number(),
  }),
});
export type CyclePlanningContext = z.infer<typeof planningContext>;
const cycleSummary = z.object({
  id: uuid,
  delivery_id: uuid,
  number: z.number().int().positive(),
  predecessor_id: uuid.nullable(),
  revision: z.number().int().positive(),
  spec_revision: z.number().int().positive(),
  state: z.enum(["PLANNING", "DRAFT", "DISPATCH_RESERVED", "LINKED"]),
  goal: z.string(),
  plan_id: uuid.nullable(),
  plan_version: z.number().int().positive().nullable(),
  run_id: uuid.nullable(),
  dispatch_plan_id: uuid.nullable(),
  run_status: z.string().nullable(),
  is_initial: z.boolean(),
  is_latest: z.boolean(),
  is_execution_cycle: z.boolean(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type ProductCycle = z.infer<typeof cycleSummary>;
const rowSchema = z.object({
  id: uuid,
  flow_id: uuid,
  title: z.string(),
  requirement: z.string(),
  revision: z.number().int().positive(),
});
const schema = rowSchema.extend({
  folder_id: uuid.nullable(),
  scope: z.literal("PRIVATE"),
  updated_at: z.string(),
  created_at: z.string(),
  workflow: z.record(z.unknown()),
  workflow_digest: digest,
  workflow_approved: z.boolean(),
  workflow_approved_by: uuid.nullable(),
  workflow_approved_at: z.string().nullable(),
  plan_id: uuid.nullable(),
  dispatch_plan_id: uuid.nullable(),
  plan_digest: digest.nullable(),
  plan_approved: z.boolean(),
  plan: z
    .object({
      execution_plan_id: uuid,
      tasks: z.array(z.unknown()),
      status: z.string(),
      validation_status: z.string(),
    })
    .passthrough()
    .nullable(),
  run: z
    .object({
      id: uuid,
      status: z.string(),
      tasks: z.array(z.unknown()),
      events: z.array(z.unknown()),
    })
    .passthrough()
    .nullable(),
  permissions: z.object({ write: z.boolean(), execute: z.boolean() }),
  notes: z.array(
    z.object({
      id: uuid,
      kind: z.enum(["CHANGE_REQUEST", "QUESTION", "NOTE"]),
      text: z.string(),
      actor_name: z.string(),
      created_at: z.string(),
      status: z.literal("OPEN"),
    }),
  ),
  cycles: z.array(cycleSummary).optional(),
  cycle: cycleSummary
    .extend({
      spec_digest: digest,
      spec: z
        .object({
          goal: z.string(),
          workflow_id: uuid,
          workflow_version: z.number().int().positive().nullable(),
          workflow_digest: digest,
          baseline: z.unknown().nullable(),
          acceptance_criteria: z.array(z.unknown()),
          selected_feedback_ids: z.array(uuid),
          execution_ready: z.boolean(),
          source: z.string(),
        })
        .passthrough(),
      plan_revisions: z.array(
        z.object({
          plan_id: uuid,
          ordinal: z.number().int().positive(),
          plan_version: z.number().int().positive().nullable(),
          plan_digest: digest,
          created_at: z.string(),
          approval: z.record(z.unknown()),
        }),
      ),
      planning_operations: z.array(planningOperation).optional(),
    })
    .optional(),
  cycle_capabilities: z
    .object({
      prepare: z.boolean(),
      execute: z.boolean(),
      edit_workflow: z.boolean(),
      plan_detailed: z.boolean().optional(),
    })
    .optional(),
});
export type Delivery = Omit<z.infer<typeof schema>, "plan" | "run"> & {
  plan: AdlcExecutionPlan | null;
  run: AdlcWorkflowRun | null;
};
const read = (value: unknown) => {
  const row = schema.parse(value) as Delivery;
  if (row.cycle) {
    const cycle = row.cycle;
    if (
      !row.cycles ||
      cycle.delivery_id !== row.id ||
      cycle.spec.workflow_id !== row.flow_id ||
      cycle.plan_id !== row.plan_id ||
      cycle.run_id !== (row.run?.id ?? null) ||
      new Set(row.cycles.map((item) => item.id)).size !== row.cycles.length ||
      !row.cycles.some(
        (item) => item.id === cycle.id && item.delivery_id === row.id,
      ) ||
      row.cycles.some((item) => item.delivery_id !== row.id) ||
      (!cycle.is_initial &&
        cycle.state === "DRAFT" &&
        (row.plan ||
          row.run ||
          row.plan_approved ||
          (row.workflow_approved && !cycle.spec.planning_ready) ||
          row.cycle_capabilities?.execute))
    ) {
      throw new Error("Cycle snapshot binding mismatch");
    }
    for (const operation of cycle.planning_operations ?? []) {
      if (
        operation.cycle_id !== cycle.id ||
        (operation.preview_plan &&
          (operation.preview_plan.metadata.cycle_id !== cycle.id ||
            operation.preview_plan.metadata.cycle_spec_digest !==
              operation.spec_digest ||
            operation.preview_plan.metadata.planning_operation_id !==
              operation.id))
      )
        throw new Error("Planning snapshot binding mismatch");
    }
  }
  return row;
};
const base = getBaseUrl().replace(/\/?$/, "/");
const root = `${base}adlc/deliveries`;
const path = (id: string) => `${root}/${encodeURIComponent(id)}`;
const proof = (row: Delivery) => ({
  expected_revision: row.revision,
  workflow_digest: row.workflow_digest,
  ...(row.cycle ? { cycle_id: row.cycle.id } : {}),
});
const planningPath = (row: Delivery) => {
  if (!row.cycle || row.cycle.is_initial)
    throw new Error("Successor cycle required");
  return `${path(row.id)}/cycles/${encodeURIComponent(row.cycle.id)}/planning`;
};
const planningProof = (row: Delivery, commandId: string) => ({
  ...proof(row),
  command_id: commandId,
  spec_digest: row.cycle!.spec_digest,
});
const readPlanningOperation = (value: unknown, row: Delivery) => {
  const operation = planningOperation.parse(value) as CyclePlanningOperation;
  if (
    operation.cycle_id !== row.cycle?.id ||
    operation.spec_digest !== row.cycle?.spec_digest ||
    (operation.preview_plan &&
      (operation.preview_plan.metadata.cycle_id !== row.cycle.id ||
        operation.preview_plan.metadata.cycle_spec_digest !==
          operation.spec_digest ||
        operation.preview_plan.metadata.planning_operation_id !== operation.id))
  )
    throw new Error("Planning response binding mismatch");
  return operation;
};

export const deliveryApi = {
  planningContext: async (row: Delivery) => {
    const context = planningContext.parse(
      (await api.get(`${planningPath(row)}/context`)).data,
    );
    if (
      context.cycle_id !== row.cycle?.id ||
      context.spec_digest !== row.cycle.spec_digest ||
      context.workflow_digest !== row.workflow_digest
    )
      throw new Error("Planning context binding mismatch");
    return context;
  },
  freezePlanning: async (
    row: Delivery,
    baseCommit: string,
    commandId: string,
  ) =>
    z.object({ revision: z.number().int().positive(), cycle_id: uuid }).parse(
      (
        await api.post(`${planningPath(row)}/freeze`, {
          ...planningProof(row, commandId),
          base_commit: baseCommit,
        })
      ).data,
    ),
  generateDetailed: async (row: Delivery, commandId: string) =>
    readPlanningOperation(
      (
        await api.post(
          `${planningPath(row)}/generate`,
          planningProof(row, commandId),
        )
      ).data,
      row,
    ),
  reconcilePlanning: async (row: Delivery, generationId: string) => {
    const operation = readPlanningOperation(
      (
        await api.post(
          `${planningPath(row)}/generations/${encodeURIComponent(generationId)}/reconcile`,
        )
      ).data,
      row,
    );
    if (operation.id !== generationId)
      throw new Error("Generation identity mismatch");
    return operation;
  },
  acceptGraph: async (
    row: Delivery,
    generation: CyclePlanningOperation,
    commandId: string,
  ) =>
    z
      .object({
        revision: z.number().int().positive(),
        approved: z.literal(true),
      })
      .parse(
        (
          await api.post(`${planningPath(row)}/accept`, {
            ...planningProof(row, commandId),
            generation_id: generation.id,
            plan_digest: generation.plan_digest,
          })
        ).data,
      ),
  folders: async () =>
    z
      .array(z.object({ id: uuid, name: z.string(), is_owner: z.boolean() }))
      .parse((await api.get(`${base}projects/`)).data),
  list: async (offset = 0) => {
    const page = z
      .object({
        items: z.array(z.unknown()),
        total: z.number().int(),
        offset: z.number().int(),
      })
      .parse((await api.get(root, { params: { offset, limit: 30 } })).data);
    return { ...page, items: page.items.map(read) };
  },
  get: async (id: string, cycleId?: string | null) => {
    const row = read(
      (
        await api.get(
          path(id),
          cycleId ? { params: { cycle_id: cycleId } } : undefined,
        )
      ).data,
    );
    if (
      row.id !== id ||
      (cycleId && row.cycle?.id !== cycleId) ||
      (!cycleId && row.cycle && !row.cycle.is_initial)
    ) {
      throw new Error("Unexpected selected cycle");
    }
    return row;
  },
  prepareCycle: async (row: Delivery, goal: string, commandId: string) => {
    if (!row.cycle) throw new Error("Cycle snapshot required");
    return z
      .object({ revision: z.number().int().positive(), cycle_id: uuid })
      .parse(
        (
          await api.post(`${path(row.id)}/cycles`, {
            ...proof(row),
            command_id: commandId,
            predecessor_id: row.cycle.id,
            goal,
          })
        ).data,
      );
  },
  updateCycle: async (row: Delivery, goal: string, commandId: string) => {
    if (!row.cycle) throw new Error("Cycle snapshot required");
    return z
      .object({ revision: z.number().int().positive(), cycle_id: uuid })
      .parse(
        (
          await api.post(
            `${path(row.id)}/cycles/${encodeURIComponent(row.cycle.id)}/spec`,
            {
              ...proof(row),
              command_id: commandId,
              spec_digest: row.cycle.spec_digest,
              goal,
            },
          )
        ).data,
      );
  },
  create: async (flow: string, title: string, requirement: string) =>
    rowSchema.parse(
      (await api.post(root, { flow_id: flow, title, requirement })).data,
    ),
  createFromCanvas: async (flowId: string, project: string, title: string, requirement: string) => {
    const original = (await api.get(`${base}flows/${flowId}`)).data;
    const data = structuredClone(original.data);
    if (data.adlc) data.adlc.workflow_definition_id = "";
    for (const node of data.nodes || []) {
      if (node.data?.adlcDraft?.kind === "REQUIREMENT") node.data.adlcDraft.requirement = requirement;
      if (node.data?.adlc?.inputs && "requirement" in node.data.adlc.inputs) node.data.adlc.inputs.requirement = requirement;
    }
    const copy = (await api.post(`${base}flows/`, { name: title, description: requirement, folder_id: project, is_component: false, mcp_enabled: false, data })).data;
    return deliveryApi.create(copy.id, title, requirement);
  },
  createFlow: async (
    title: string,
    requirement: string,
    folder: string | null,
  ) =>
    z.object({ id: uuid }).parse(
      (
        await api.post(`${base}flows/`, {
          name: title,
          description: requirement,
          folder_id: folder,
          is_component: false,
          mcp_enabled: false,
          data: {
            nodes: [],
            edges: [],
            viewport: { x: 0, y: 0, zoom: 1 },
            adlc: {
              document_type: "WORKFLOW_DEFINITION",
              schema_version: "0.1",
              workflow_definition_id: "",
              version: 1,
              status: "DRAFT",
              default_policies: {},
              metadata: {},
            },
          },
        })
      ).data,
    ),
  approveWorkflow: async (row: Delivery) =>
    z
      .object({
        approved: z.literal(true),
        revision: z.number().int().positive(),
      })
      .parse(
        (await api.post(`${path(row.id)}/approve-workflow`, proof(row))).data,
      ),
  compile: async (row: Delivery) =>
    z
      .object({
        revision: z.number().int().positive(),
        plan: z
          .object({ execution_plan_id: uuid, tasks: z.array(z.unknown()) })
          .passthrough(),
      })
      .parse((await api.post(`${path(row.id)}/compile`, proof(row))).data),
  approvePlan: async (row: Delivery) =>
    z
      .object({
        approved: z.literal(true),
        revision: z.number().int().positive(),
      })
      .parse(
        (
          await api.post(`${path(row.id)}/approve-plan`, {
            ...proof(row),
            plan_digest: row.plan_digest,
          })
        ).data,
      ),
  start: async (row: Delivery) =>
    z.object({ run_id: uuid }).parse(
      (
        await api.post(`${path(row.id)}/start`, {
          ...proof(row),
          plan_digest: row.plan_digest,
        })
      ).data,
    ),
  reconcile: async (row: Delivery) =>
    z.object({ run_id: uuid }).parse(
      (
        await api.post(`${path(row.id)}/reconcile`, {
          ...proof(row),
          plan_digest: row.plan_digest,
        })
      ).data,
    ),
  note: async (
    row: Delivery,
    kind: Delivery["notes"][number]["kind"],
    text: string,
    commandId: string,
  ) =>
    z.object({ revision: z.number().int().positive() }).parse(
      (
        await api.post(`${path(row.id)}/notes`, {
          expected_revision: row.revision,
          command_id: commandId,
          ...(row.cycle ? { cycle_id: row.cycle.id } : {}),
          kind,
          text,
        })
      ).data,
    ),
};

export function deliveryError(error: unknown): string {
  const detail = (
    error as {
      response?: { data?: { detail?: { code?: string; message?: string } } };
    }
  )?.response?.data?.detail;
  const messages: Record<string, string> = {
    CYCLE_PLANNER_DISABLED:
      "Chưa bật dịch vụ lập kế hoạch chi tiết qua Harness.",
    CYCLE_PLANNER_NOT_CONFIGURED:
      "Cần cấu hình kết nối Harness và token cho phiên lập kế hoạch.",
    CYCLE_PLANNER_UNAVAILABLE:
      "Chưa kết nối được Harness. Đối soát lượt đã gửi trước khi tạo lượt mới.",
    CYCLE_PLANNER_RELEASE_MISMATCH:
      "Harness chưa nạp đúng plugin lập kế hoạch đã khóa phiên bản.",
    CYCLE_BASELINE_CHANGED:
      "Mã nguồn nền không còn khớp bản đã chốt. Cần xem và chốt lại đầu vào.",
    CYCLE_BASELINE_UNAVAILABLE:
      "Không đọc được commit đã chọn trong repository được cấu hình.",
    CYCLE_REPOSITORY_NOT_CONFIGURED:
      "Chọn project có mã nguồn local hoặc cấu hình repository Task Loop trước.",
    CYCLE_CONTEXT_LIMIT:
      "Ngữ cảnh vượt giới hạn lập kế hoạch. Cần thu hẹp phạm vi trước khi gọi AI.",
    CYCLE_GENERATION_UNCONFIRMED:
      "Lượt tạo kế hoạch chưa đối soát xong; chưa được gửi thêm lượt gọi AI.",
    CYCLE_GENERATION_BUDGET_EXHAUSTED:
      "Đã hết giới hạn 3 lượt lập kế hoạch cho chu kỳ này.",
    CYCLE_EXECUTOR_UNSUPPORTED:
      "Workflow có bộ chạy chưa được hỗ trợ. Cần chỉnh quy trình trước khi lập kế hoạch.",
    CYCLE_SOURCE_PLAN_INVALID:
      "Đầu vào hoặc chính sách workflow chưa thể thực thi. Cần kiểm tra cấu hình nâng cao.",
    CYCLE_HUMAN_GATE_REQUIRED:
      "Workflow cần một giai đoạn phê duyệt rõ ràng trước khi lập kế hoạch chi tiết.",
    CYCLE_GRAPH_CHANGED:
      "Đã có đề xuất mới hơn hoặc đang chờ đối soát. Hãy tải lại trước khi duyệt.",
    CYCLE_GRAPH_NOT_ACCEPTABLE:
      "Chỉ duyệt được graph đã kiểm tra và gắn đúng đặc tả của chu kỳ đang xem.",
    DELIVERY_USE_WORKSPACE:
      "Kế hoạch thuộc một công việc. Hãy thao tác trong Công việc để giữ đúng chu kỳ và phê duyệt.",
    DELIVERY_CYCLE_NOT_FOUND: "Không tìm thấy chu kỳ trong công việc này.",
    DELIVERY_CYCLE_HEAD_CHANGED:
      "Đã có chu kỳ mới hơn. Hãy mở chu kỳ mới nhất trước khi tiếp tục.",
    DELIVERY_CYCLE_DRAFT_EXISTS:
      "Đã có bản nháp cho chu kỳ tiếp theo. Hãy tiếp tục chỉnh mục tiêu của bản nháp đó.",
    DELIVERY_CYCLE_SPEC_CHANGED:
      "Mục tiêu của chu kỳ vừa thay đổi. Hãy tải lại trước khi sửa tiếp.",
    DELIVERY_CYCLE_SPEC_FROZEN:
      "Chu kỳ này không còn là bản nháp có thể sửa. Kết quả và phê duyệt cũ được giữ nguyên.",
    DELIVERY_CYCLE_PLANNING_NOT_READY:
      "Chu kỳ mới chỉ là bản nháp. Chưa mở lập kế hoạch và thực thi; không dùng lại phê duyệt của chu kỳ trước.",
    DELIVERY_CYCLE_ARCHIVE_UNAVAILABLE:
      "Chưa đọc được lịch sử chu kỳ. Cần kiểm tra migration và kho lưu; hệ thống không tự tạo lại lịch sử.",
    DELIVERY_ACTIVE_CYCLE_EXISTS:
      "Công việc đang có một chu kỳ thực thi hoặc chưa đối soát. Không khởi chạy thêm chu kỳ.",
    DELIVERY_GENERATION_UNCONFIRMED:
      "Lượt lập kế hoạch chưa được xác nhận. Hãy đối soát trước; không tự gửi thêm một lượt tạo kế hoạch.",
    DELIVERY_COMMAND_CONFLICT:
      "Mã thao tác đã được dùng cho nội dung khác. Hãy tải lại và kiểm tra trước khi gửi.",
    DELIVERY_REVISION_CONFLICT:
      "Dữ liệu vừa thay đổi. Hãy tải lại và xem đúng phiên bản trước khi tiếp tục.",
    DELIVERY_WORKFLOW_CHANGED:
      "Các giai đoạn đã thay đổi. Bạn cần xem và duyệt lại workflow.",
    DELIVERY_WORKFLOW_APPROVAL_REQUIRED:
      "Cần duyệt các giai đoạn của workflow trước khi tạo kế hoạch.",
    DELIVERY_PLAN_APPROVAL_REQUIRED:
      "Cần duyệt đúng kế hoạch trước khi bắt đầu chạy.",
    DELIVERY_PLAN_CHANGED:
      "Kế hoạch đã thay đổi. Hãy tải lại và duyệt phiên bản mới.",
    DELIVERY_RUN_START_UNCONFIRMED:
      "Kế hoạch đã được gửi chạy nhưng chưa nhận được xác nhận. Mở nhật ký để đối soát; không gửi lại hoặc tạo agent thứ hai.",
    DELIVERY_WORKFLOW_EMPTY:
      "Chưa có giai đoạn nào. Hãy tạo workflow từ yêu cầu trước.",
    DELIVERY_TEAM_ADAPTER_REQUIRED:
      "Project nhóm cần phê duyệt độc lập. Mở Không gian nhóm để làm việc với BA, Developer và Tester.",
    DELIVERY_MOCK_EXECUTION_NOT_ALLOWED:
      "Workflow đang dùng bộ chạy mô phỏng. Hãy đổi sang package thực thi thật trong phần chỉnh sửa nâng cao.",
    DELIVERY_HARNESS_LOOP_NOT_READY:
      "Bộ thực thi Task Loop chưa sẵn sàng. Cần kiểm tra kết nối, credential và phiên bản plugin. Chưa tạo lượt chạy hay gọi agent; có thể thử lại sau khi dịch vụ sẵn sàng.",
    TEAM_USE_COLLABORATION_API:
      "Project này dùng phê duyệt độc lập của team. Mở Không gian nhóm; chưa bật thực thi chung.",
    TEAM_SHARED_EXECUTION_NOT_ENABLED:
      "Project này chưa được cấp quyền chạy agent dùng chung.",
    BLUEPRINT_GENERATION_NOT_CONFIGURED:
      "Chưa cấu hình dịch vụ lập workflow. Kiểm tra kết nối AI trong Cài đặt.",
    CONTRACT_EXPLICIT_LOGIN_REQUIRED:
      "Hãy đăng nhập bằng tài khoản cá nhân để duyệt hoặc thực thi.",
  };
  return (
    (detail?.code && messages[detail.code]) ||
    "Chưa xác nhận được thao tác. Hãy tải lại để kiểm tra; hệ thống không tự chạy lại hay báo thành công."
  );
}
