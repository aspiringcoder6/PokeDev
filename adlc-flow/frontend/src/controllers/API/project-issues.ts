import { getBaseUrl } from "@/customization/utils/urls";
import { api } from "./api";
import { liveError } from "./live-workflows";

export type ProjectIssueSettings = {
  project_id: string;
  watch_issues: boolean;
  mode: "review" | "auto" | "risk";
  labels: string[];
  workflow_id: string | null;
  revision: number;
  updated_at: string;
  last_scan_at: string | null;
  scan_error: string | null;
  scan_truncated: boolean;
  poll_seconds: number;
  auto_allowed_paths?: string[];
  auto_max_runs_per_day?: number;
  auto_max_active_minutes?: number;
};
export type IssueTriage = {
  version: string;
  action: "ready" | "needs_spec" | "needs_human";
  confidence: number;
  reasons: string[];
  questions: { id: string; question: string }[];
  input_digest: string;
  planning_style: string;
};
export type IssueRisk = {
  tier: string;
  level: number;
  preliminary: boolean;
  paths: string[];
  factors: { factor: string; level: number; reason: string }[];
};
export type IssueProposal = {
  proposal_id: string;
  project_id: string;
  repository: string;
  source_digest: string;
  revision: number;
  state: string;
  issue: {
    number: number;
    title: string;
    body: string;
    state: string;
    url: string;
    author: string;
    labels: string[];
    updated_at: string | null;
  };
  run_id: string | null;
  previous_runs: { run_id: string; revision: number }[];
  error_code: string | null;
  review_reason: string | null;
  run_state?: string;
  run_error?: string | null;
  triage?: IssueTriage;
  risk?: IssueRisk;
  auto_decision?: {
    allowed: boolean;
    code: string | null;
    policy_revision: number;
    risk_tier: string;
  };
  clarification?: {
    source_digest: string;
    answers: Record<string, string>;
    approach: "implement" | "spec_first";
    by: string;
    at: string;
  };
};
export type IssuePage = {
  items: IssueProposal[];
  settings: ProjectIssueSettings;
  automation_usage?: {
    used: number;
    limit: number;
    window_hours: number;
    next_available_at: number | null;
  };
};
export type IssueAudit = {
  id: number;
  event: string;
  at: string;
  details: {
    actor?: string;
    revision?: number;
    policy_revision?: number;
    run_id?: string;
    risk?: IssueRisk;
    triage?: IssueTriage;
    native_cancel_confirmed?: boolean;
  };
};
export type IssueSettingsCommand = Pick<
  ProjectIssueSettings,
  | "watch_issues"
  | "mode"
  | "labels"
  | "workflow_id"
  | "auto_allowed_paths"
  | "auto_max_runs_per_day"
  | "auto_max_active_minutes"
> & { expected_revision: number; auto_confirmed: boolean };
const base = (project: string) =>
  `${getBaseUrl().replace(/\/?$/, "/")}adlc/live/projects/${encodeURIComponent(project)}`;
export const projectIssues = {
  settings: async (project: string): Promise<ProjectIssueSettings> =>
    (await api.get(base(project) + "/settings")).data,
  save: async (
    project: string,
    command: IssueSettingsCommand,
  ): Promise<ProjectIssueSettings> =>
    (await api.put(base(project) + "/settings", command)).data,
  list: async (project: string): Promise<IssuePage> =>
    (await api.get(base(project) + "/issues")).data,
  scan: async (project: string): Promise<IssuePage> =>
    (await api.post(base(project) + "/issues/scan")).data,
  act: async (
    project: string,
    proposal: IssueProposal,
    action: "plan" | "ignore" | "restore",
  ): Promise<IssueProposal> =>
    (
      await api.post(
        `${base(project)}/issues/${encodeURIComponent(proposal.proposal_id)}/${action}`,
        { source_digest: proposal.source_digest },
      )
    ).data,
  clarify: async (
    project: string,
    proposal: IssueProposal,
    answers: Record<string, string>,
    approach: string,
  ): Promise<IssueProposal> =>
    (
      await api.post(
        `${base(project)}/issues/${proposal.proposal_id}/clarification`,
        { source_digest: proposal.source_digest, answers, approach },
      )
    ).data,
  audit: async (
    project: string,
    proposal: string,
  ): Promise<{ items: IssueAudit[] }> =>
    (await api.get(`${base(project)}/issues/${proposal}/audit`)).data,
};

const messages: Record<string, string> = {
  ISSUE_CLARIFICATION_REQUIRED:
    "Cần bạn bổ sung mục tiêu, phạm vi và tiêu chí nghiệm thu trước khi lập kế hoạch.",
  ISSUE_SPEC_REQUIRED:
    "Cần chốt đặc tả cho yêu cầu này trước khi bắt đầu. Bổ sung thông tin bên dưới.",
  ISSUE_CLARIFICATION_INVALID:
    "Điền đủ ba câu trả lời, mỗi câu từ 8 đến 4.000 ký tự.",
  ISSUE_RISK_REVIEW_REQUIRED:
    "Yêu cầu hoặc kế hoạch có rủi ro từ R2 trở lên. Cần bạn xem và duyệt thực hiện.",
  ISSUE_PATH_REVIEW_REQUIRED:
    "Kế hoạch có file ngoài phạm vi được tự sửa. Cần bạn xem và duyệt lượt này.",
  ISSUE_COMMAND_REVIEW_REQUIRED:
    "Lệnh thực hiện cần bạn kiểm tra trước khi duyệt.",
  ISSUE_AUTO_BUDGET_EXHAUSTED:
    "Đã dùng hết số lượt tự động trong 24 giờ. Bạn có thể tự lập kế hoạch hoặc chờ lượt mới.",
  ISSUE_AUTO_TIME_LIMIT_EXHAUSTED:
    "Lượt tự động đã dùng hết thời gian làm việc cho phép. Cần bạn xem lại trước khi chạy tiếp.",
  ISSUE_TRIAGE_CHANGED:
    "Thông tin phân loại đã thay đổi so với lúc lập kế hoạch. Cần bạn xem lại lượt này.",
  ISSUE_MANUAL_PLAN_REVIEW:
    "Bạn đã chủ động lập kế hoạch cho lượt này. Kế hoạch chờ bạn duyệt thực hiện.",
  ISSUE_ALLOWED_PATHS_INVALID:
    "Nhập đường dẫn tương đối chính xác hoặc thư mục kết thúc bằng /**; tối đa 20 mục.",
  ISSUE_ALLOWED_PATHS_REQUIRED:
    "Chọn ít nhất một file hoặc thư mục được tự sửa cho chế độ ít rủi ro.",
  ISSUE_AUTO_LIMITS_INVALID:
    "Giới hạn từ 1–50 lượt mỗi 24 giờ và 5–60 phút làm việc mỗi lượt.",
  ISSUE_CHANGED:
    "Issue đã thay đổi. Hãy xem lại nội dung mới trước khi lập kế hoạch.",
  ISSUE_SETTINGS_CHANGED:
    "Cài đặt đã được thay đổi ở nơi khác. Tải lại cài đặt rồi lưu lại lựa chọn của bạn.",
  ISSUE_AUTO_CONFIRMATION_REQUIRED:
    "Xác nhận cho phép project tự duyệt và thực hiện trước khi lưu.",
  ISSUE_SETTINGS_INVALID:
    "Kiểm tra danh sách nhãn: tối đa 20 nhãn, mỗi nhãn không quá 100 ký tự.",
  ISSUE_NOT_ELIGIBLE:
    "Issue đã đóng hoặc không còn khớp bộ lọc nhãn của project.",
  ISSUE_PREPARING: "Đề xuất này đang được chuẩn bị. Chờ một lát rồi tải lại.",
  ISSUE_PROPOSAL_NOT_READY:
    "Trạng thái đề xuất đã thay đổi. Hãy tải lại danh sách.",
  ISSUE_REQUIRES_MANUAL_SUMMARY:
    "Issue quá dài hoặc thiếu tiêu đề. Hãy tạo yêu cầu mới với phần mô tả đã tóm tắt.",
  ISSUE_AUTO_POLICY_CHANGED:
    "Cài đặt đã đổi sau khi lập kế hoạch. Cần bạn xem và duyệt lượt này.",
  ISSUE_WORKFLOW_CHANGED:
    "Workflow đã thay đổi sau khi lập kế hoạch. Cần bạn xem và duyệt lượt này.",
  ISSUE_REPOSITORY_CHANGED:
    "Repo đã thay đổi định danh. Kiểm tra lại kết nối Gitea của project.",
  ISSUE_OWNER_UNAVAILABLE: "Tài khoản quản lý project hiện không khả dụng.",
  ISSUE_PREPARATION_FAILED:
    "Chưa chuẩn bị được công việc. Kiểm tra kết nối và thử lại.",
  LIVE_PROJECT_RUN_ACTIVE:
    "Project đang có công việc chạy. Hãy chờ lượt đó hoàn tất.",
};
export const issueCodeMessage = (code: string) => messages[code] || code;
export function issueError(error: unknown) {
  const code = (
    error as { response?: { data?: { detail?: { code?: string } } } }
  )?.response?.data?.detail?.code;
  return (code && messages[code]) || liveError(error);
}
