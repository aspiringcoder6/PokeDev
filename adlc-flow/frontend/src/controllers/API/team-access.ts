import { z } from "zod";
import { getBaseUrl } from "@/customization/utils/urls";
import { api } from "./api";

export const roleIds = [
  "admin",
  "developer",
  "business_analyst",
  "tester",
] as const;
export type TeamRoleId = (typeof roleIds)[number];
const role = z.enum(roleIds);
const rule = z.object({
  allow: z.array(z.string()),
  deny: z.array(z.string()),
});
export const policySchema = z.object({
  roles: z.object({
    admin: rule,
    developer: rule,
    business_analyst: rule,
    tester: rule,
  }),
});
export type TeamPolicy = z.infer<typeof policySchema>;
const permission = z.object({
  allowed: z.boolean(),
  reason: z.string(),
  granted: z.boolean(),
  phase: z.string(),
});
const effectiveSchema = z.object({
  user_id: z.string().uuid(),
  revision: z.number().int().positive(),
  roles: z.array(role),
  permissions: z.record(permission),
});
export type TeamEffective = z.infer<typeof effectiveSchema>;
const member = z.object({
  user_id: z.string().uuid(),
  username: z.string(),
  is_active: z.boolean(),
  roles: z.array(role),
});
export const accessSchema = z.object({
  project_id: z.string().uuid(),
  name: z.string(),
  revision: z.number().int().positive(),
  mode: z.enum(["CONFIGURATION_ONLY", "COLLABORATION"]),
  can_manage: z.boolean(),
  effective: effectiveSchema,
  policy: policySchema.nullable(),
  members: z.array(member),
  catalog: z.array(
    z.object({
      key: z.string(),
      label: z.string(),
      area: z.string(),
      phase: z.enum(["H7A", "H7B", "H7C"]),
    }),
  ),
  roles: z.array(z.object({ id: role, name: z.string() })),
});
export type TeamAccessView = z.infer<typeof accessSchema>;
const projectsSchema = z.object({
  phase: z.literal("H7A"),
  can_create: z.boolean(),
  projects: z.array(
    z.object({
      project_id: z.string().uuid(),
      name: z.string(),
      revision: z.number().int().positive(),
      roles: z.array(role),
      mode: z.enum(["CONFIGURATION_ONLY", "COLLABORATION"]),
    }),
  ),
});
const auditSchema = z.array(
  z.object({
    id: z.string().uuid(),
    actor_id: z.string().uuid().nullable(),
    actor_username: z.string().nullable().optional(),
    action: z.string(),
    details: z.record(z.unknown()).nullable(),
    occurred_at: z.string(),
  }),
);
const revisionSchema = z.object({ revision: z.number().int().positive() });
const root = `${getBaseUrl().replace(/\/?$/, "/")}adlc/team-access`;
const projectPath = (id: string) =>
  `${root}/projects/${encodeURIComponent(id)}`;
export const teamProjects = async () =>
  projectsSchema.parse((await api.get(`${root}/projects`)).data);
export const teamProject = async (id: string) =>
  accessSchema.parse((await api.get(projectPath(id))).data);
export const createTeamProject = async (name: string) =>
  accessSchema.parse((await api.post(`${root}/projects`, { name })).data);
export const saveTeamPolicy = async (
  id: string,
  revision: number,
  policy: TeamPolicy,
) => {
  return revisionSchema.parse(
    (
      await api.put(`${projectPath(id)}/policy`, {
        expected_revision: revision,
        policy,
      })
    ).data,
  );
};
export const setTeamMember = async (
  id: string,
  revision: number,
  username: string,
  roles: TeamRoleId[],
) => {
  return revisionSchema.parse(
    (
      await api.put(`${projectPath(id)}/members`, {
        expected_revision: revision,
        username,
        roles,
      })
    ).data,
  );
};
export const revokeTeamMember = async (
  id: string,
  revision: number,
  subject: string,
) => {
  return revisionSchema
    .extend({ revoked: z.literal(true) })
    .parse(
      (
        await api.post(
          `${projectPath(id)}/members/${encodeURIComponent(subject)}/revoke`,
          { expected_revision: revision },
        )
      ).data,
    );
};
export const teamEffective = async (id: string, subject: string) =>
  effectiveSchema.parse(
    (
      await api.get(
        `${projectPath(id)}/effective/${encodeURIComponent(subject)}`,
      )
    ).data,
  );
export const teamAudit = async (id: string) =>
  auditSchema.parse((await api.get(`${projectPath(id)}/audit`)).data);

export function teamError(error: unknown): string {
  const value = error as {
    response?: { data?: { detail?: { code?: string } } };
  };
  const code = value?.response?.data?.detail?.code;
  const messages: Record<string, string> = {
    TEAM_EXPLICIT_LOGIN_REQUIRED:
      "Cần đăng nhập bằng tài khoản cá nhân; chế độ tự đăng nhập không được quản trị quyền.",
    TEAM_ENFORCEMENT_PROVIDER_REQUIRED:
      "Dịch vụ phân quyền chưa sẵn sàng. Các thao tác được khóa an toàn.",
    TEAM_PRESETS_NOT_READY:
      "Chưa cài migration của H7A. Hãy kiểm tra dịch vụ trước khi phân quyền.",
    TEAM_POLICY_REVISION_CONFLICT:
      "Chính sách đã thay đổi. Tải lại và xem phiên bản mới trước khi lưu.",
    TEAM_LAST_ADMIN_PROTECTED:
      "Không thể loại bỏ Admin có hiệu lực cuối cùng của project.",
    TEAM_ACTIVE_USER_NOT_FOUND:
      "Không tìm thấy tài khoản đang hoạt động với username này.",
    TEAM_WRITE_CONFLICT:
      "Tên project đã tồn tại hoặc dữ liệu vừa thay đổi. Hãy tải lại trước khi thử tiếp.",
    TEAM_BOOTSTRAP_OPERATOR_REQUIRED:
      "Chỉ quản trị viên nền tảng được khởi tạo project phân quyền.",
    TEAM_PROJECT_NOT_FOUND:
      "Project không tồn tại hoặc bạn không còn quyền truy cập.",
    TEAM_MEMBERSHIP_REQUIRED: "Bạn không còn là thành viên của project này.",
    TEAM_USER_TOKEN_REQUIRED: "Hãy đăng nhập để sử dụng quản trị quyền.",
  };
  return (
    (code && messages[code]) ||
    "Không thể xác minh hoặc lưu quyền. Không có thao tác nào được mở thêm; hãy thử tải lại."
  );
}
