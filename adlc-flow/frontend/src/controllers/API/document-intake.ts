import { getBaseUrl } from "@/customization/utils/urls";
import { api } from "./api";
import { liveError, type LiveRun } from "./live-workflows";

export type IntakeDocument = {
  document_id: string;
  title: string;
  doc_type: string;
  lifecycle_id: string;
  page_id: string;
  confluence_url?: string;
  slack_url?: string;
  slack_channel: string;
  slack_thread: string;
  source_status: string;
  created_at: string;
  synced_at?: string;
  project_id?: string;
  repository?: string;
  instructions?: string;
  state: string;
  archived_at?: string;
  page_version?: number;
  page_checked_at_iso?: string;
  page_digest?: string;
  digest?: string;
  body?: string;
  stale?: boolean;
  error_code?: string;
  approval?: {
    at: string;
    digest: string;
    decision: string;
    page_version: number;
  };
  run_id?: string;
  run_state?: string;
  run_started_at?: string;
  previous_runs?: { run_id: string; page_version: number }[];
  progress?: {
    enabled: boolean;
    state?: string;
    page_id?: string;
    link?: string;
    synced_at?: string;
    error_code?: string;
  };
  notifications?: {
    enabled: boolean;
    state?: string;
    error_code?: string;
    last_message_url?: string;
    last_sent_at?: string;
  };
  revision_request?: {
    id: string;
    digest: string;
    at: string;
    page_version: number;
    state: string;
    feedback: string;
    error_code?: string;
    transport?: string;
    invocation_id?: string;
    agent_state?: string;
  };
  plan_command?: {
    id: string;
    workflow_id?: string;
    workflow_digest?: string;
    state: string;
    digest: string;
    error_code?: string;
  };
};
export type DocumentInbox = {
  items: IntakeDocument[];
  rules: { channel: string; project_id: string; repository: string }[];
  can_manage: boolean;
  stale: boolean;
  checked_at?: string;
  error_code?: string;
  limit_reached?: boolean;
  bot_url?: string;
};
const base = () => `${getBaseUrl().replace(/\/?$/, "/")}adlc/live/intake`;
export const documentIntake = {
  list: async (
    projectId?: string,
    includeArchived = false,
  ): Promise<DocumentInbox> =>
    (
      await api.get(base(), {
        params: {
          ...(projectId ? { project_id: projectId } : {}),
          ...(includeArchived ? { include_archived: true } : {}),
        },
      })
    ).data,
  read: async (id: string): Promise<IntakeDocument> =>
    (await api.get(`${base()}/${encodeURIComponent(id)}`)).data,
  archive: async (id: string): Promise<IntakeDocument> =>
    (await api.delete(`${base()}/${encodeURIComponent(id)}`)).data,
  restore: async (id: string): Promise<IntakeDocument> =>
    (await api.post(`${base()}/${encodeURIComponent(id)}/restore`)).data,
  assign: async (
    id: string,
    projectId: string,
    instructions: string,
    automatic: boolean,
    shareProgress?: boolean,
  ): Promise<IntakeDocument> =>
    (
      await api.put(`${base()}/${encodeURIComponent(id)}/project`, {
        project_id: projectId,
        instructions,
        automatic_channel: automatic,
        share_progress: shareProgress,
      })
    ).data,
  progress: async (id: string, enabled: boolean): Promise<IntakeDocument> =>
    (
      await api.post(`${base()}/${encodeURIComponent(id)}/progress`, {
        enabled,
      })
    ).data,
  notifications: async (
    id: string,
    enabled: boolean,
  ): Promise<IntakeDocument> =>
    (
      await api.post(`${base()}/${encodeURIComponent(id)}/notifications`, {
        enabled,
      })
    ).data,
  revise: async (
    id: string,
    command: { digest: string; request_id: string; feedback: string },
  ): Promise<IntakeDocument> =>
    (await api.post(`${base()}/${encodeURIComponent(id)}/revision`, command))
      .data,
  checkRevision: async (
    id: string,
    command: { request_id: string; invocation_id?: string },
  ): Promise<IntakeDocument> =>
    (
      await api.post(
        `${base()}/${encodeURIComponent(id)}/revision/check`,
        command,
      )
    ).data,
  decide: async (
    id: string,
    digest: string,
    decision: "approve" | "reject",
  ): Promise<IntakeDocument> =>
    (
      await api.post(`${base()}/${encodeURIComponent(id)}/decision`, {
        digest,
        decision,
      })
    ).data,
  plan: async (
    id: string,
    command: {
      digest: string;
      command_id: string;
      workflow_id?: string;
      workflow_digest?: string;
    },
  ): Promise<LiveRun> =>
    (await api.post(`${base()}/${encodeURIComponent(id)}/plan`, command)).data,
  clearPlan: async (id: string) =>
    (await api.delete(`${base()}/${encodeURIComponent(id)}/plan`)).data,
  removeRule: async (channel: string) =>
    (await api.delete(`${base()}/channels/${encodeURIComponent(channel)}`))
      .data,
};
export function documentUrl(id?: string, project?: string) {
  const params = new URLSearchParams({ view: "requests" });
  if (id) params.set("document", id);
  if (project) params.set("project", project);
  return `/work?${params}`;
}
export const documentState: Record<string, string> = {
  SOURCE_UNAVAILABLE: "Tài liệu nguồn chưa khả dụng",
  ARCHIVED: "Đã lưu trữ",
  NEEDS_CHANGES: "Chờ sửa tài liệu",
  NEEDS_PROJECT: "Chọn project",
  NEEDS_REVIEW: "Chờ duyệt",
  CHANGED: "Tài liệu đã đổi",
  APPROVED: "Đã duyệt cho project",
  REJECTED: "Đã từ chối",
};
export function intakeError(error: unknown) {
  const code = (
    error as { response?: { data?: { detail?: { code?: string } } } }
  )?.response?.data?.detail?.code;
  const messages: Record<string, string> = {
    INTAKE_PAGE_NOT_CURRENT:
      "Trang không còn trong danh mục Confluence đã xuất bản, có thể đã được đưa vào Thùng rác. Nếu vừa tạo trang mới, chờ Confluence cập nhật chỉ mục rồi đồng bộ lại. Chưa thể duyệt hoặc lập kế hoạch từ bản lưu.",
    CONFLUENCE_PAGE_NOT_CURRENT:
      "Trang Confluence không còn được xuất bản hoặc đang ở Thùng rác. Kiểm tra trang nguồn trước khi đồng bộ lại.",
    INTAKE_DOCUMENT_ARCHIVED:
      "Yêu cầu đã được lưu trữ. Khôi phục trước khi tiếp tục xử lý.",
    INTAKE_ARCHIVE_ACTIVE:
      "Hoàn tất hoặc đối soát lượt đang xử lý trước khi lưu trữ yêu cầu.",
    INTAKE_REVISION_PENDING:
      "Đã có yêu cầu sửa đang chờ. Đợi tài liệu có phiên bản mới trước khi duyệt hoặc gửi thêm.",
    INTAKE_REVISION_UNCONFIRMED:
      "Chưa xác nhận được Workloop đã nhận yêu cầu. Kiểm tra lại; ứng dụng sẽ không tự gửi lặp.",
    INTAKE_REVISION_AWAITING_INVOCATION:
      "Bot chưa đăng ký bản tài liệu sửa tiếp theo. Mở hội thoại Slack để kiểm tra trước khi gửi thêm.",
    INTAKE_REVISION_REJECTED:
      "Workloop chưa nhận yêu cầu sửa. Kiểm tra kết nối và thử lại.",
    INTAKE_REVISION_FEEDBACK_REQUIRED:
      "Nhập nội dung cần sửa từ 10 đến 6.000 ký tự.",
    SLACK_BOT_TOKEN_REQUIRED: "Cần Bot User OAuth Token bắt đầu bằng xoxb-.",
    SLACK_WORKSPACE_MISMATCH:
      "Mã bot thuộc workspace Slack khác. Dùng bot trong ADLC Factory.",
    SLACK_INVALID_AUTH:
      "Mã bot Slack không hợp lệ. Kiểm tra lại trong OAuth & Permissions.",
    SLACK_TOKEN_REVOKED: "Mã bot đã bị thu hồi. Cập nhật lại kết nối.",
    SLACK_MISSING_SCOPE: "Bot chưa được cấp quyền chat:write để gửi thông báo.",
    SLACK_NOT_IN_CHANNEL:
      "Bot chưa tham gia kênh của yêu cầu. Mời bot vào kênh rồi thử lại.",
    SLACK_SECRET_STORAGE_UNAVAILABLE:
      "Chưa lưu được mã kết nối an toàn. Mã chưa được ghi vào cấu hình.",
    SLACK_DELIVERY_UNCONFIRMED:
      "Chưa xác nhận được tin đã gửi. Kiểm tra thread Slack; hệ thống không tự gửi lặp.",
    SLACK_CONNECTION_UNAVAILABLE:
      "Chưa kết nối được Slack. Thông báo sẽ thử lại khi đường truyền hoạt động.",
    SLACK_RATE_LIMITED:
      "Slack đang giới hạn tốc độ. Thông báo sẽ tự thử lại sau thời gian chờ.",
    INTAKE_REVISION_AGENT_FAILED:
      "Bot chưa cập nhật được tài liệu. Bản gốc vẫn được giữ; bạn có thể bổ sung góp ý rồi gửi lượt sửa mới.",
    INTAKE_REVISION_NO_UPDATE:
      "Lượt bot đã kết thúc nhưng chưa có phiên bản mới trên trang tài liệu này. Cần xem lại kết quả trước khi duyệt.",
    INTAKE_REVISION_AGENT_UNAVAILABLE:
      "Chưa đọc được tiến độ của bot. Giữ lượt hiện tại và kiểm tra lại khi kết nối hoạt động.",
    INTAKE_REVISION_INVOCATION_MISMATCH:
      "Mã lượt bot không khớp tài liệu hoặc hội thoại này. Kiểm tra mã trong đúng thread Slack.",
    PROGRESS_CONFLUENCE_UNAVAILABLE:
      "Chưa kết nối được Confluence để cập nhật tiến độ. Báo cáo gần nhất vẫn được giữ.",
    PROGRESS_CREATE_UNCONFIRMED:
      "Đang xác nhận việc tạo báo cáo. Nền tảng sẽ tìm trang đã tạo trước khi gửi thêm.",
    PROGRESS_REPORT_MODIFIED:
      "Trang báo cáo đã được chỉnh sửa bên ngoài. Mở báo cáo để kiểm tra trước khi tiếp tục đồng bộ.",
    PROGRESS_REPORT_BINDING_CHANGED:
      "Trang tìm thấy không khớp báo cáo của yêu cầu này. Chưa ghi đè nội dung trang.",
    PROGRESS_SPACE_REQUIRED:
      "Chưa xác định được không gian Confluence từ liên kết tài liệu nguồn.",
    INTAKE_EXECUTION_APPROVAL_FIXED:
      "Phiên bản này đã được dùng để lập kế hoạch. Mở lượt chạy để phản hồi hoặc điều khiển; thay đổi nội dung cần một quyết định mới.",
    INTAKE_PLAN_TOO_LARGE:
      "Tài liệu và chỉ dẫn bổ sung vượt 80.000 ký tự. Chia nhỏ yêu cầu trước khi lập kế hoạch; nội dung đã duyệt được giữ nguyên.",
    INTAKE_SOURCE_MISSING:
      "Yêu cầu không còn trong lifecycle Workloop. Kiểm tra cuộc trao đổi với bot trước khi tiếp tục.",
    INTAKE_DOCUMENT_CHANGED:
      "Tài liệu hoặc phạm vi đã thay đổi. Đọc lại phiên bản mới rồi duyệt lại.",
    INTAKE_APPROVAL_REQUIRED:
      "Cần duyệt đúng phiên bản tài liệu và phạm vi trước khi lập kế hoạch.",
    INTAKE_SOURCE_REJECTED:
      "Yêu cầu đã bị từ chối hoặc hủy tại Workloop. Kiểm tra lại cuộc trao đổi trên Slack.",
    INTAKE_CONFLUENCE_UNAVAILABLE:
      "Chưa đọc được Confluence. Kiểm tra kết nối rồi thử lại; nội dung đã lưu được giữ lại.",
    INTAKE_SYNC_UNAVAILABLE:
      "Chưa đồng bộ được Workloop. Kết nối lại trước khi duyệt hoặc lập kế hoạch.",
    INTAKE_PAGE_MISSING:
      "Yêu cầu chưa có tài liệu Confluence để duyệt. Tiếp tục cuộc trao đổi với bot trên Slack.",
    INTAKE_EXECUTION_BINDING_FIXED:
      "Tài liệu đã có lượt chạy. Giữ project này để bảo toàn lịch sử.",
    INTAKE_START_PENDING:
      "Đang xác nhận việc lập kế hoạch. Kiểm tra lượt chạy trước khi thay đổi phạm vi.",
    INTAKE_RUN_ALREADY_EXISTS:
      "Đã có lượt chạy cho phiên bản này. Mở lượt chạy để theo dõi hoặc thực hiện lại.",
    INTAKE_COMMAND_CONFLICT:
      "Lệnh này đã gắn với một phiên bản khác. Làm mới để kiểm tra trạng thái.",
    INTAKE_DOCUMENT_TOO_LARGE:
      "Tài liệu vượt giới hạn đọc. Chia nhỏ yêu cầu trên Confluence trước khi duyệt.",
  };
  return messages[code || ""] || liveError(error);
}
