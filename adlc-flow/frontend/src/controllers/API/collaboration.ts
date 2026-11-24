import { z } from "zod";
import { getBaseUrl } from "@/customization/utils/urls";
import { api } from "./api";

const uuid = z.string().uuid();
const digest = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const kind = z.enum([
  "CONTRACT",
  "WORKFLOW",
  "PLAN",
  "RUN",
  "ARTIFACT",
  "CANDIDATE",
  "VERIFICATION",
  "TEST_SUITE",
]);
const reference = z.object({
  resource_id: uuid,
  revision: z.number().int().positive(),
  content_digest: digest,
});
const permission = z.object({
  allowed: z.boolean(),
  reason: z.string(),
  granted: z.boolean(),
  phase: z.string(),
});
const resource = z.object({
  id: uuid,
  project_id: uuid,
  kind,
  title: z.string(),
  created_by: uuid,
  origin_owner_id: z.string(),
  responsible_ids: z.array(uuid),
  revision: z.number().int().positive(),
  content_digest: digest,
  status: z.string(),
  dependencies: z.record(reference),
  parent_id: uuid.nullable(),
  updated_at: z.string(),
  created_at: z.string(),
});
const decision = z.object({
  id: uuid,
  decided_by: uuid,
  decision: z.enum(["APPROVE", "REQUEST_CHANGES"]),
  comment: z.string(),
  resource_revision: z.number().int().positive(),
  content_digest: digest,
  policy_revision: z.number().int().positive(),
  created_at: z.string(),
  expires_at: z.string(),
});
export const sharedResourceSchema = resource.extend({
  payload: z.record(z.unknown()),
  selected_revision: z.number().int().positive(),
  policy_revision: z.number().int().positive(),
  stale_dependencies: z.boolean(),
  can_decide: z.boolean(),
  reviewers: z.array(z.object({ user_id: uuid, username: z.string() })),
  required_action: z.string().nullable(),
  decisions: z.array(decision),
});
export type SharedResource = z.infer<typeof sharedResourceSchema>;
export const workspaceSchema = z.object({
  project_id: uuid,
  name: z.string(),
  mode: z.literal("COLLABORATION"),
  policy_revision: z.number().int().positive(),
  execution_enabled: z.literal(false),
  effective: z.object({
    user_id: uuid,
    revision: z.number().int().positive(),
    roles: z.array(z.string()),
    permissions: z.record(permission),
  }),
  resources: z.array(resource),
  total: z.number().int().nonnegative(),
  limit: z.number().int().positive(),
  offset: z.number().int().nonnegative(),
  inbox: z.array(reference.extend({ title: z.string(), kind })),
});
export type TeamWorkspace = z.infer<typeof workspaceSchema>;
export const importPreviewSchema = z.object({
  run_id: uuid,
  name: z.string(),
  status: z.string(),
  origin_owner_id: z.string(),
  content_digest: digest,
  policy_revision: z.number().int().positive(),
  task_count: z.number(),
  artifact_count: z.number(),
  contract_count: z.number().int().nonnegative(),
  plan_count: z.number().int().nonnegative(),
  verification_count: z.number().int().nonnegative(),
  manifest: z.object({
    run: digest,
    plan: digest.nullable(),
    contracts: z.array(
      z.object({
        contract_id: uuid,
        revision: z.number().int().positive(),
        content_digest: digest,
      }),
    ),
    verifications: z.array(digest),
  }),
  warning: z.string(),
});
const root = `${getBaseUrl().replace(/\/?$/, "/")}adlc/collaboration/projects`;
const path = (project: string) => `${root}/${encodeURIComponent(project)}`;
export const workspace = async (project: string, offset = 0) =>
  workspaceSchema.parse(
    (await api.get(`${path(project)}?limit=50&offset=${offset}`)).data,
  );
export const sharedResource = async (
  project: string,
  id: string,
  revision?: number,
) =>
  sharedResourceSchema.parse(
    (
      await api.get(
        `${path(project)}/resources/${encodeURIComponent(id)}${revision ? `?revision=${revision}` : ""}`,
      )
    ).data,
  );
export const enableCollaboration = async (project: string, revision: number) =>
  z
    .object({
      mode: z.literal("COLLABORATION"),
      revision: z.number().int().positive(),
    })
    .parse(
      (await api.post(`${path(project)}/enable`, { policy_revision: revision }))
        .data,
    );
export const exactResource = (item: SharedResource) => ({
  policy_revision: item.policy_revision,
  expected_revision: item.revision,
  content_digest: item.content_digest,
});
export const contractTool = async (
  project: string,
  policyRevision: number,
  tool: string,
  args: Record<string, unknown>,
) =>
  sharedResourceSchema.parse(
    (
      await api.post(`${path(project)}/contracts/tools`, {
        policy_revision: policyRevision,
        tool,
        arguments: args,
      })
    ).data,
  );
export const submitShared = async (item: SharedResource) =>
  sharedResourceSchema.parse(
    (
      await api.post(
        `${path(item.project_id)}/resources/${item.id}/submit`,
        exactResource(item),
      )
    ).data,
  );
export const reviseShared = async (item: SharedResource) =>
  sharedResourceSchema.parse(
    (
      await api.post(
        `${path(item.project_id)}/resources/${item.id}/revise`,
        exactResource(item),
      )
    ).data,
  );
export const decideShared = async (
  item: SharedResource,
  result: "APPROVE" | "REQUEST_CHANGES",
  comment: string,
) =>
  decision.parse(
    (
      await api.post(
        `${path(item.project_id)}/resources/${item.id}/decisions`,
        { ...exactResource(item), decision: result, comment },
      )
    ).data,
  );
export const saveSharedWorkflow = async (
  project: string,
  body: Record<string, unknown>,
  existing?: SharedResource,
) =>
  sharedResourceSchema.parse(
    (existing
      ? await api.put(`${path(project)}/workflows/${existing.id}`, {
          ...body,
          ...exactResource(existing),
        })
      : await api.post(`${path(project)}/workflows`, body)
    ).data,
  );
export const compileShared = async (item: SharedResource) =>
  z
    .discriminatedUnion("valid", [
      z.object({ valid: z.literal(true), resource: sharedResourceSchema }),
      z.object({
        valid: z.literal(false),
        plan: z
          .object({
            validation_errors: z.array(
              z.object({ code: z.string(), message: z.string() }),
            ),
          })
          .passthrough(),
      }),
    ])
    .parse(
      (
        await api.post(
          `${path(item.project_id)}/workflows/${item.id}/compile`,
          exactResource(item),
        )
      ).data,
    );
export const prepareSharedRun = async (item: SharedResource) =>
  sharedResourceSchema.parse(
    (
      await api.post(
        `${path(item.project_id)}/plans/${item.id}/prepare`,
        exactResource(item),
      )
    ).data,
  );
export const createSharedSuite = async (
  project: string,
  body: Record<string, unknown>,
  existing?: SharedResource,
) =>
  sharedResourceSchema.parse(
    (existing
      ? await api.put(`${path(project)}/suites/${existing.id}`, {
          ...body,
          ...exactResource(existing),
        })
      : await api.post(`${path(project)}/suites`, body)
    ).data,
  );
export const previewSharedImport = async (project: string, run: string) =>
  importPreviewSchema.parse(
    (await api.get(`${path(project)}/imports/runs/${encodeURIComponent(run)}`))
      .data,
  );
export const importSharedRun = async (
  project: string,
  preview: z.infer<typeof importPreviewSchema>,
) =>
  sharedResourceSchema.parse(
    (
      await api.post(`${path(project)}/imports/runs`, {
        run_id: preview.run_id,
        policy_revision: preview.policy_revision,
        content_digest: preview.content_digest,
        confirm_share: true,
      })
    ).data,
  );

export function collaborationError(error: unknown): string {
  const code = (
    error as { response?: { data?: { detail?: { code?: string } } } }
  )?.response?.data?.detail?.code;
  const messages: Record<string, string> = {
    TEAM_INDEPENDENT_REVIEWER_REQUIRED:
      "Cần một người khác đủ quyền duyệt. Một người nhiều role vẫn không được tự duyệt.",
    TEAM_CURRENT_APPROVAL_REQUIRED:
      "Phê duyệt không còn hiệu lực. Kiểm tra quyền, revision và thời hạn rồi tạo phiên bản duyệt mới.",
    TEAM_RESOURCE_REVISION_CONFLICT:
      "Tài liệu đã đổi. Bản đang xem không còn là phiên bản hiện tại; hãy tải lại và quyết định lại.",
    TEAM_POLICY_REVISION_CONFLICT:
      "Quyền project đã đổi. Hãy tải lại trước khi tiếp tục.",
    TEAM_RESOURCE_LOCKED:
      "Phiên bản đã khóa. Tạo revision mới để chỉnh sửa, không ghi đè bản cũ.",
    TEAM_DECISION_ALREADY_RESOLVED:
      "Cổng duyệt đã được xử lý. Không ghi thêm quyết định cho cùng revision.",
    TEAM_DEPENDENCY_CHANGED:
      "Contract hoặc workflow nguồn đã đổi. Cần lập và duyệt lại kế hoạch.",
    TEAM_VERIFIED_PASS_REQUIRED:
      "Chưa có bằng chứng Verify PASS hợp lệ. Không thể nghiệm thu bằng lời xác nhận.",
    TEAM_IMPORT_ORIGINAL_OWNER_REQUIRED:
      "Chỉ người tạo dữ liệu gốc đồng thời có quyền quản trị project mới được chia sẻ snapshot này.",
    TEAM_IMPORT_TERMINAL_RUN_REQUIRED:
      "Chỉ chia sẻ run đã kết thúc; không chuyển run đang chạy.",
    TEAM_COLLABORATION_REQUIRES_EMPTY_PROJECT:
      "Project phải rỗng trước khi mở cộng tác. Dữ liệu cũ cần chuyển có chọn lọc.",
    TEAM_COLLABORATION_NOT_ENABLED: "Project chưa được mở cộng tác.",
    TEAM_COLLABORATION_PROVIDER_REQUIRED:
      "Backend chưa hỗ trợ quyền cộng tác H7B. Cần cập nhật dịch vụ trước khi tiếp tục.",
    CONTRACT_VALIDATION_REQUIRED:
      "Contract cần có task và tiêu chí nghiệm thu hợp lệ trước khi gửi duyệt.",
    TEAM_PERMISSION_DENIED:
      "Bạn không có quyền thực hiện hành động này trong project.",
    TEAM_MEMBERSHIP_REQUIRED: "Bạn không còn quyền truy cập project này.",
  };
  return (
    (code && messages[code]) ||
    "Không thể xác minh dữ liệu hoặc quyền. Thao tác đang khóa; hãy tải lại và thử lại."
  );
}
