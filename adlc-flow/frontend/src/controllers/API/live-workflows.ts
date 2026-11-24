import { getBaseUrl } from "@/customization/utils/urls";
import { api } from "./api";
import type { ProjectEnvironment, Handover } from "./project-lifecycle";

export type LiveProject = {
  project_id: string;
  name: string;
  repository: string;
  repository_id: number;
  repository_url: string;
  branch: string;
  base_commit: string;
};
export type GiteaRepository = {
  id: number;
  name: string;
  full_name: string;
  description: string;
  html_url: string;
  default_branch: string;
  private: boolean;
};
export type LiveTask = {
  id: string;
  title: string;
  kind?: string;
  role?: string;
  depends_on: string[];
  steps?: string[];
  acceptance?: string[];
  write_paths?: string[];
  join?: "all" | "any";
  control?: WorkflowControl;
};
export type WorkflowControl =
  | {
      type: "condition";
      predicate: "status_done" | "verification_passed" | "review_approved";
    }
  | { type: "verify" }
  | { type: "gate"; reviewer: "human" | "agent"; max_rounds: number };
export type WorkflowEdge = {
  source: string;
  target: string;
  port?: "done" | "match" | "no_match" | "approved" | "changes_requested";
  feedback?: boolean;
};
export type LivePlan = {
  title?: string;
  summary?: string;
  digest: string;
  tasks: LiveTask[];
  commands: { label: string; argv: string[]; timeout?: number }[];
  preview?: { path?: string; argv?: string[] } | null;
  browser_checks?: { label: string; steps: Record<string, string>[] }[];
  control_flow?: {
    version: 1;
    edges: WorkflowEdge[];
    loops: {
      gate: string;
      target: string;
      nodes: string[];
      max_rounds: number;
    }[];
    max_repairs: 0;
  };
};
export type WorkflowGraph = {
  version: 1 | 2;
  title: string;
  summary: string;
  nodes: { id: string; position: { x: number; y: number }; task: LiveTask }[];
  edges: WorkflowEdge[];
  commands: LivePlan["commands"];
  preview: LivePlan["preview"];
  browser_checks: NonNullable<LivePlan["browser_checks"]>;
};
export type ProjectWorkflow = {
  workflow_id: string;
  project_id: string;
  name: string;
  revision: number;
  digest: string;
  graph: WorkflowGraph;
  ready: boolean;
  error_code?: string | null;
  updated_at?: string;
};
export type ProjectFileIndex = {
  project_id: string;
  commit: string;
  paths: string[];
  truncated: boolean;
};
export type LiveNode = LiveTask & {
  state: string;
  session_id?: string;
  started_at?: number;
  completed_at?: number;
  native_start_at?: number;
  native_end_at?: number;
  reused_from?: string;
  summary?: string;
  error_code?: string;
  original_id?: string;
  iteration?: number;
  outcome?: string;
  port?: string;
};
export type HumanInput = {
  request_id: string;
  run_id: string;
  project_id: string;
  run_title: string;
  node_id: string;
  node_title: string;
  kind: "question" | "permission";
  title: string;
  status: "PENDING" | "SENDING" | "UNCERTAIN" | "ANSWERED";
  can_respond: boolean;
  created_at: string;
  questions?: {
    id: string;
    question: string;
    header: string;
    multi_select: boolean;
    options: { label: string; description: string }[];
  }[];
  tool_name?: string;
  prompt?: string;
  details?: Record<string, unknown>;
  origin?: "workflow_gate";
  source_digest?: string;
  gate_round?: number;
};
export type HumanAttention = {
  connected: boolean;
  active_runs: number;
  requests: HumanInput[];
  reviews: {
    request_id: string;
    run_id: string;
    project_id: string;
    run_title: string;
    kind: "plan" | "advanced" | "issue" | "recovery" | "workloop" | "document";
    proposal_id?: string;
    document_id?: string;
    href?: string;
    title: string;
  }[];
};
export type LiveRun = {
  run_id: string;
  delivery_id: string;
  project_id: string | null;
  title: string;
  requirement: string;
  repository: string;
  base_commit?: string;
  created_at: string;
  state: string;
  phase: string;
  legacy?: boolean;
  parent_run_id?: string;
  nodes: LiveNode[];
  documents: {
    id: string;
    title: string;
    body: string;
    revision: string;
    sha256: string;
    previous_body?: string;
  }[];
  plan?: LivePlan & { title: string; summary: string };
  memory?: {
    document_id: string;
    revision: string;
    mode: string;
    content_verified: boolean;
    retrieved_at: string;
    caller_context_id?: string;
    source_ref?: string;
  }[];
  checks?: {
    id: string;
    title: string;
    passed?: number;
    total?: number;
    tests: {
      id: string;
      label: string;
      passed?: boolean;
      status?: string;
      stdout?: string;
      stderr?: string;
      error?: string;
      argv?: string[];
    }[];
  }[];
  preview?: { state: string; url: string | null; expires_at: string | number };
  changed_files?: string[];
  diff?: string;
  error_code?: string;
  parallel?: {
    verified: boolean;
    tasks: string[];
    overlap_seconds: number;
    samples?: number;
  };
  published?: { branch: string; url: string; commit: string };
  workflow?: Pick<
    ProjectWorkflow,
    "workflow_id" | "project_id" | "name" | "revision" | "digest"
  >;
  issue?: {
    proposal_id: string;
    number: number;
    url: string;
    title: string;
    source_digest: string;
    revision: number;
  };
  approval_source?: string;
  origin_document?: {
    document_id: string;
    title: string;
    confluence_url?: string;
    slack_url?: string;
    page_version: number;
    lifecycle_id: string;
    digest: string;
    approved_at: string;
  };
  automation?: { settings_revision: number; risk?: { tier: string } };
  auto_timing?: { limit_seconds: number; active_seconds: number };
  environment?: ProjectEnvironment;
  approved_plan_digest?: string;
  recovery?: { generation: number; requested_at: string };
  recovery_status?: {
    available: boolean;
    stopping?: boolean;
    generation?: number;
    saved_at?: number;
    completed_tasks?: number;
    waiting_tasks?: string[];
    error_code?: string;
  };
  handover?: Handover;
};

const base = () => `${getBaseUrl().replace(/\/?$/, "/")}adlc/live`;
export const liveWorkflows = {
  attention: async (): Promise<HumanAttention> =>
    (await api.get(base() + "/attention")).data,
  answer: async (
    request: HumanInput,
    commandId: string,
    response: Record<string, unknown>,
  ): Promise<HumanInput> =>
    (
      await api.post(
        base() +
          "/runs/" +
          request.run_id +
          "/human-input/" +
          request.request_id,
        { command_id: commandId, response },
      )
    ).data,
  packageWorkflows: async (
    projectId?: string,
  ): Promise<
    { id: string; name: string; folder_id?: string; description?: string }[]
  > => {
    const response = await api.get(
      `${getBaseUrl().replace(/\/?$/, "/")}flows/`,
      {
        params: {
          get_all: true,
          ...(projectId ? { folder_id: projectId } : {}),
        },
      },
    );
    const items = Array.isArray(response.data)
      ? response.data
      : response.data.items || [];
    return items.filter(
      (flow: { data?: { adlc?: unknown; nodes?: unknown[] } }) =>
        flow.data?.adlc && flow.data.nodes?.length,
    );
  },
  readiness: async (): Promise<{
    ready: boolean;
    endpoint?: string;
    error_code?: string;
  }> => (await api.get(base() + "/readiness")).data,
  repositories: async (): Promise<{ items: GiteaRepository[] }> =>
    (await api.get(base() + "/repositories")).data,
  projects: async (): Promise<{ items: LiveProject[] }> =>
    (await api.get(base() + "/projects")).data,
  files: async (projectId: string): Promise<ProjectFileIndex> =>
    (await api.get(base() + "/projects/" + projectId + "/files")).data,
  connect: async (body: {
    repository_id?: number;
    new_repository_name?: string;
    description?: string;
  }): Promise<LiveProject> => (await api.post(base() + "/projects", body)).data,
  runs: async (projectId?: string): Promise<{ items: LiveRun[] }> =>
    (
      await api.get(base() + "/runs", {
        params: projectId ? { project_id: projectId } : {},
      })
    ).data,
  read: async (id: string): Promise<LiveRun> =>
    (await api.get(base() + "/runs/" + id)).data,
  workflows: async (
    projectId?: string,
  ): Promise<{ items: ProjectWorkflow[] }> =>
    (
      await api.get(base() + "/workflows", {
        params: projectId ? { project_id: projectId } : {},
      })
    ).data,
  workflow: async (id: string): Promise<ProjectWorkflow> =>
    (await api.get(base() + "/workflows/" + id)).data,
  saveWorkflow: async (body: {
    workflow_id: string;
    project_id: string;
    name: string;
    graph: WorkflowGraph;
    expected_digest?: string;
  }): Promise<ProjectWorkflow> =>
    (await api.put(base() + "/workflows/" + body.workflow_id, body)).data,
  applyWorkflow: async (
    run: LiveRun,
    workflow: ProjectWorkflow,
  ): Promise<LiveRun> =>
    (
      await api.post(base() + "/runs/" + run.run_id + "/workflow", {
        workflow_id: workflow.workflow_id,
        workflow_digest: workflow.digest,
        plan_digest: run.plan?.digest,
      })
    ).data,
  plan: async (body: {
    run_id: string;
    delivery_id: string;
    project_id: string;
    workflow_id?: string;
    workflow_digest?: string;
  }): Promise<LiveRun> => (await api.post(base() + "/runs", body)).data,
  execute: async (run: LiveRun): Promise<LiveRun> =>
    (
      await api.post(base() + "/runs/" + run.run_id + "/execute", {
        plan_digest: run.plan?.digest,
      })
    ).data,
  reconcile: async (id: string): Promise<LiveRun> =>
    (await api.post(base() + "/runs/" + id + "/reconcile")).data,
  retry: async (id: string, runId: string): Promise<LiveRun> =>
    (await api.post(base() + "/runs/" + id + "/retry", { run_id: runId })).data,
  publish: async (
    id: string,
  ): Promise<{ branch: string; url: string; commit: string }> =>
    (await api.post(base() + "/runs/" + id + "/publish")).data,
  patch: async (id: string): Promise<string> =>
    (await api.get(base() + "/runs/" + id + "/patch", { responseType: "text" }))
      .data,
};

const messages: Record<string, string> = {
  WORKLOOP_UNAVAILABLE:
    "Chưa kết nối được Workloop. Kiểm tra VPN và dịch vụ; dữ liệu đã lưu được giữ để đối chiếu.",
  WORKLOOP_JOB_NOT_FOUND:
    "Không tìm thấy lượt Workloop đã liên kết trong project này.",
  WORKLOOP_JOB_ALREADY_LINKED:
    "Lượt này đã liên kết với một project khác. Hãy kiểm tra lại mã lượt.",
  WORKLOOP_LINK_ADMIN_REQUIRED:
    "Cần quản trị viên xác nhận project cho các lượt Workloop dùng chung.",
  WORKLOOP_PROJECT_CONFIRMATION_REQUIRED:
    "Xác nhận đúng repo của project trước khi liên kết lượt.",
  WORKLOOP_ACTION_NOT_AVAILABLE:
    "Thao tác không phù hợp với trạng thái hiện tại của lượt Workloop.",
  WORKLOOP_ACTION_REJECTED:
    "Workloop chưa chấp nhận thao tác. Cập nhật trạng thái và kiểm tra lại.",
  WORKLOOP_REFRESH_REQUIRED:
    "Cần kết nối và cập nhật Workloop trước khi gửi lệnh.",
  WORKLOOP_REQUEST_CHANGED:
    "Yêu cầu đã thay đổi hoặc được xử lý. Cập nhật trước khi phản hồi.",
  WORKLOOP_COMMAND_PENDING:
    "Lệnh trước đang chờ xác nhận. Hãy cập nhật trạng thái để đối soát.",
  WORKLOOP_COMMAND_CONFLICT:
    "Mã thao tác đã được dùng cho một yêu cầu khác. Cập nhật lượt trước khi thử lại.",
  LIVE_ENVIRONMENT_INVALID:
    "Kiểm tra tên môi trường và thư mục làm việc tương đối trong workspace.",
  LIVE_ENVIRONMENT_COMMAND_INVALID:
    "Mỗi lệnh cần đối số hợp lệ và thời gian chờ 5–600 giây; tổng cộng tối đa 8 lệnh.",
  LIVE_ENVIRONMENT_TESTS_REQUIRED:
    "Thêm ít nhất một lệnh kiểm thử; tổng cài đặt, test và build tối đa 8 lệnh.",
  LIVE_ENVIRONMENT_BASE_INVALID:
    "Chọn repo khung và commit có thật trên repo đó. Commit để trống sẽ cố định bản hiện tại khi lưu.",
  LIVE_ENVIRONMENT_MAPPING_INVALID:
    "Đường dẫn ghép module phải tương đối, không chồng nhau và có repo khung.",
  LIVE_ENVIRONMENT_MAPPING_COLLISION:
    "Hai file nguồn đang được ghép vào cùng một vị trí. Kiểm tra lại các đường dẫn module.",
  LIVE_ENVIRONMENT_SOURCE_MISSING:
    "Không tìm thấy thư mục module trong commit của repo chính.",
  LIVE_ENVIRONMENT_DIRECTORY_MISSING:
    "Thư mục làm việc chưa có trong workspace được ghép.",
  LIVE_ENVIRONMENT_CHANGED:
    "Môi trường đã thay đổi. Tải lại bản mới trước khi lưu hoặc kiểm tra.",
  LIVE_ENVIRONMENT_CHECK_FAILED:
    "Chưa hoàn tất kiểm tra môi trường. Xem cấu hình và thử lại kết nối Harness/Gitea.",
  LIVE_RECOVERY_CHANGED:
    "Trạng thái lượt chạy đã thay đổi. Cập nhật lại trước khi tiếp tục.",
  LIVE_RECOVERY_CHECKPOINT_INVALID:
    "Chưa có tiến trình đã lưu hợp lệ để tiếp tục lượt này. Bằng chứng cũ vẫn được giữ.",
  LIVE_RECOVERY_WORKER_ACTIVE:
    "Tiến trình cũ vẫn đang hoạt động; PokeDev đã tiếp tục theo dõi và không tạo thêm Agent.",
  LIVE_RECOVERY_NATIVE_ACCEPTANCE_UNKNOWN:
    "Lượt bị ngắt khi đang mở phiên Agent. Chưa xác nhận được việc nhận yêu cầu; cần đối soát phiên thay vì gửi lặp.",
  LIVE_RECOVERY_NATIVE_NOT_FINISHED:
    "Phiên Agent cũ chưa hoàn tất. Kiểm tra kết nối hoặc trả lời câu hỏi đang chờ rồi tiếp tục lại.",
  LIVE_RECOVERY_NATIVE_BINDING_CHANGED:
    "Phiên làm việc hoặc đầu vào đã khác với tiến trình được lưu. Chưa thể tiếp tục tự động.",
  LIVE_RECOVERY_VERIFICATION_UNCONFIRMED:
    "Sandbox đang cần đối soát kết quả đã gửi. Tiến trình và mã kiểm thử được giữ; PokeDev chưa tạo lượt kiểm thử thay thế.",
  LIVE_RECOVERY_STOP_UNCONFIRMED:
    "Đã ghi yêu cầu dừng nhưng chưa xác nhận mọi phiên Agent đã dừng. Kết nối lại Harness và đối soát dừng trước khi chạy tiếp.",
  LIVE_INTERRUPTED_RUN_CLOSED:
    "Lượt gián đoạn đã dừng. Source, log và kết quả được giữ để xem lại hoặc dùng cho một lượt mới.",
  LIVE_RECOVERY_SOURCE_INVALID:
    "Source trong tiến trình đã lưu không khớp phạm vi được duyệt. Giữ lượt này để đối soát trước khi thử lại.",
  LIVE_RECOVERY_VERIFICATION_CHANGED:
    "Source đã khác với lần kiểm chứng đang chờ. Cần kiểm tra lại bằng chứng trước khi tiếp tục.",
  LIVE_ENVIRONMENT_PREVIEW_INVALID:
    "Preview cần một thư mục tương đối hoặc một lệnh khởi động với đối số hợp lệ.",
  LIVE_PR_VERIFIED_BRANCH_REQUIRED:
    "Xuất đúng nhánh của kết quả đã kiểm thử trước khi tạo Pull Request.",
  LIVE_PR_HEAD_CHANGED:
    "Nhánh hoặc commit của PR đã thay đổi. Cần kiểm chứng lại phiên bản mới trước khi merge.",
  LIVE_PR_BASE_CHANGED:
    "Nhánh đích đã thay đổi từ khi kiểm thử. Tạo lượt mới trên bản mới nhất và kiểm chứng lại.",
  LIVE_PR_NOT_MERGEABLE:
    "PR đang đóng, là bản nháp hoặc có xung đột. Mở Gitea để xử lý rồi cập nhật lại.",
  LIVE_PR_CHECKS_NOT_PASSED:
    "CI của commit hiện tại còn đang chạy hoặc có kiểm tra chưa đạt.",
  LIVE_PR_REQUIRED_CHECK_MISSING:
    "Chưa có đủ kiểm tra bắt buộc của nhánh đích cho commit hiện tại.",
  LIVE_PR_REVIEW_REQUIRED:
    "PR còn chờ review hoặc có yêu cầu sửa chưa được xử lý.",
  LIVE_PR_STATUS_UNCONFIRMED:
    "Chưa đọc được đầy đủ CI và review. Cập nhật trạng thái trước khi merge.",
  LIVE_PR_NO_CI_CONFIRMATION_REQUIRED:
    "Repo chưa có CI trên commit này. Xác nhận đã xem bằng chứng Sandbox trước khi merge.",
  LIVE_PR_MERGE_DENIED:
    "Tài khoản Gitea hiện tại chưa được phép merge vào nhánh đích.",
  LIVE_PR_CREATE_UNCONFIRMED:
    "Chưa xác nhận được việc tạo PR. Cập nhật/đối soát trước khi thử lại; PokeDev giữ yêu cầu để tránh tạo trùng.",
  LIVE_PR_CREATE_REJECTED:
    "Gitea chưa chấp nhận PR. Kiểm tra quyền, khác biệt giữa hai nhánh và PR hiện có rồi thử lại.",
  LIVE_PR_MERGE_REJECTED:
    "Gitea từ chối merge theo trạng thái hoặc quy tắc hiện tại. Cập nhật CI/review và xử lý trên Gitea trước khi thử lại.",
  LIVE_PR_MERGE_UNCONFIRMED:
    "Chưa xác nhận merge hoàn tất. Cập nhật trạng thái Gitea; yêu cầu merge không được tự gửi lặp.",
  LIVE_GATE_FEEDBACK_REQUIRED:
    "Ghi ít nhất 5 ký tự mô tả phần cần sửa trong thông tin bổ sung.",
  LIVE_REVIEW_STOPPED:
    "Bạn đã dừng lượt chạy tại cổng duyệt. Kết quả hiện có được giữ để xem lại.",
  LIVE_REVIEW_SOURCE_CHANGED:
    "Kết quả đã thay đổi sau khi mở cổng duyệt. Cần kiểm chứng và duyệt lại.",
  LIVE_CONDITION_BRANCHES_REQUIRED:
    "Điều kiện cần một đầu vào và đủ hai nhánh Đúng / Không khớp.",
  LIVE_CONDITION_SOURCE_INVALID:
    "Điều kiện Kiểm thử đạt phải nhận kết quả từ node Kiểm chứng.",
  LIVE_CONTROL_INVALID: "Kiểm tra loại node điều khiển và cách chờ đầu vào.",
  LIVE_CONTROL_PORT_INVALID:
    "Nối đúng nhánh đầu ra. Nhánh Yêu cầu sửa phải quay về Developer.",
  LIVE_CONTROL_TESTS_REQUIRED:
    "Node Kiểm chứng phải chờ tất cả Tester hoàn tất.",
  LIVE_REVIEW_VERIFICATION_REQUIRED:
    "Thêm node Kiểm chứng trước cổng duyệt và bên trong vòng sửa.",
  LIVE_REVIEW_LIMIT_INVALID:
    "Cổng duyệt cần người duyệt và giới hạn từ 0 đến 3 vòng sửa.",
  LIVE_REVIEW_LOOP_INVALID:
    "Nối Yêu cầu sửa về Developer phía trước, với giới hạn 1–3 vòng; đặt 0 nếu không có vòng sửa.",
  LIVE_REVIEW_LOOP_OVERLAP:
    "Các vòng sửa phải tách riêng và không lồng cổng duyệt.",
  LIVE_REVIEW_LOOP_SCOPE:
    "Mỗi vòng sửa chỉ có một Developer để giữ phạm vi thay đổi rõ ràng.",
  LIVE_REVIEW_LOOP_EXIT:
    "Các node trong vòng sửa phải đi qua cổng duyệt trước khi chuyển ra ngoài.",
  LIVE_REVIEW_BARRIER_REQUIRED:
    "Cổng duyệt cần chờ mọi task ghi file phía trước để kết quả không đổi khi đang duyệt.",
  LIVE_TESTER_BRANCH_UNSUPPORTED:
    "Tester phải chạy trước các nhánh điều kiện và cổng duyệt để giữ nguyên bộ test.",
  LIVE_CONTROL_VISIT_LIMIT:
    "Sơ đồ vượt giới hạn 100 lượt thực hiện task; giảm số node hoặc số vòng sửa.",
  LIVE_PRICING_CHANGED:
    "Bảng giá đã được sửa ở nơi khác. Tải lại trước khi lưu.",
  LIVE_PRICING_INVALID:
    "Điền đủ nhà cung cấp, model, nguồn giá và bốn đơn giá hợp lệ.",
  LIVE_AUTO_TIME_LIMIT:
    "Lượt tự động đã hết thời gian làm việc được cho phép và đã dừng. Hãy xem lại kết quả trước khi thử tiếp.",
  LIVE_AUTO_TIME_LIMIT_UNCONFIRMED:
    "Lượt tự động đã hết thời gian làm việc. Đã dừng worker; cần đối soát trạng thái dừng trên Harness trước khi chạy tiếp.",
  LIVE_HUMAN_INPUT_UNAVAILABLE:
    "Chưa kết nối được kênh câu hỏi của Harness. Kiểm tra VPN; PokeDev sẽ tự kết nối lại.",
  LIVE_HUMAN_INPUT_CHANGED:
    "Câu hỏi này đã thay đổi hoặc được xử lý ở nơi khác. Cập nhật danh sách trước khi trả lời.",
  LIVE_HUMAN_RESPONSE_INVALID:
    "Trả lời đủ các câu hỏi và chọn đúng những phương án được cung cấp.",
  LIVE_HUMAN_RESPONSE_UNCONFIRMED:
    "Chưa xác nhận được câu trả lời đã đến Agent. Đang kiểm tra lại; câu trả lời của bạn được giữ ở đây.",
  LIVE_HUMAN_INPUT_NOT_FOUND: "Không tìm thấy câu hỏi trong lượt chạy này.",
  LIVE_WORKFLOW_CHANGED:
    "Workflow đã được sửa ở nơi khác. Tải lại bản mới trước khi lưu hoặc sử dụng.",
  LIVE_WORKFLOW_PROJECT_MISMATCH:
    "Workflow và yêu cầu phải thuộc cùng project.",
  LIVE_WORKFLOW_NOT_FOUND: "Không tìm thấy workflow trong tài khoản này.",
  LIVE_WORKFLOW_INVALID:
    "Canvas chưa hợp lệ. Kiểm tra task và cấu hình kiểm chứng.",
  LIVE_PLAN_TASK_LIMIT: "Workflow cần từ 2 đến 20 task.",
  LIVE_PLAN_TASK_ID: "Mã task bị trùng hoặc không hợp lệ.",
  LIVE_PLAN_TASK_KIND:
    "Chọn vai trò Developer, Tester hoặc Reviewer cho mỗi task.",
  LIVE_PLAN_TASK_DETAIL:
    "Mỗi task cần tên đủ rõ (ít nhất 12 ký tự), các bước và tiêu chí nghiệm thu (mỗi dòng ít nhất 5 ký tự).",
  LIVE_PLAN_DAG_INVALID:
    "Phụ thuộc phải nối các task có thật và không tạo vòng lặp.",
  LIVE_PLAN_WRITE_PATH:
    "Developer và Tester cần danh sách file cụ thể được phép sửa, tính từ thư mục gốc của repo.",
  LIVE_PLAN_PARALLEL_WRITE_CONFLICT:
    "Hai task cùng sửa một file cần có phụ thuộc để chạy theo thứ tự.",
  LIVE_PLAN_IMPLEMENTATION_AND_TEST_REQUIRED:
    "Thêm ít nhất một task Developer và một task Tester.",
  LIVE_REVIEW_READ_ONLY:
    "Reviewer chỉ đọc; xóa danh sách file được phép sửa của task này.",
  LIVE_PLAN_TEST_COMMAND_REQUIRED:
    "Thêm ít nhất một lệnh kiểm thử trong tab Kiểm chứng.",
  LIVE_PLAN_COMMAND_INVALID:
    "Kiểm tra đối số và thời gian chờ của lệnh kiểm thử (5–600 giây).",
  LIVE_PLAN_PREVIEW_INVALID:
    "Preview cần một thư mục tĩnh hoặc một lệnh khởi chạy.",
  LIVE_PLAN_BROWSER_CHECK_INVALID:
    "Kiểm tra cấu hình browser: cần preview và các hành động goto, text, visible, fill hoặc click.",
  LIVE_AI_OR_SANDBOX_UNAVAILABLE:
    "Chưa kết nối được AI hoặc Sandbox. Kiểm tra Harness và VPN, rồi cập nhật lại trạng thái.",
  LIVE_PROJECT_RUN_ACTIVE:
    "Project này có lượt đang chạy hoặc cần đối soát. Mở lượt đó trong lịch sử trước khi gửi thêm yêu cầu.",
  LIVE_PLAN_NOT_READY_OR_CHANGED:
    "Kế hoạch chưa sẵn sàng hoặc đã thay đổi. Cập nhật và xem lại trước khi thực hiện.",
  LIVE_PLANNING_FINISHING:
    "Planner đang lưu kết quả cuối. Chờ một chút rồi bấm thực hiện lại.",
  GITEA_UNAVAILABLE: "Chưa kết nối được Gitea. Kiểm tra VPN và dịch vụ Gitea.",
  GITEA_REPOSITORY_NAME_UNAVAILABLE:
    "Tên repo đã tồn tại hoặc không dùng được. Chọn repo hiện có hoặc đổi tên mới.",
  LIVE_WORKER_INTERRUPTED:
    "Mất tín hiệu của tiến trình. Kết quả và session đã được giữ để đối soát; chưa xác nhận thành công.",
  GITEA_ACCESS_DENIED:
    "Gitea chưa chấp nhận thông tin kết nối. Kiểm tra quyền của tài khoản và token đã cấu hình.",
  PROJECT_GIT_OPERATION_FAILED:
    "Chưa lấy được source từ repo. Kiểm tra quyền truy cập, nhánh mặc định và kết nối Gitea.",
  LIVE_OWNED_AGENT_STILL_RUNNING:
    "Một Agent của lượt trước vẫn đang chạy. Chờ session dừng rồi thử lại để tránh tạo trùng công việc.",
  LIVE_MODEL_ROUTE_UNCONFIRMED:
    "Harness chưa xác nhận đúng model AI đã chọn. Cần kiểm tra cấu hình model trước khi thực hiện lại.",
  LIVE_DAG_INCOMPLETE:
    "Một số task chưa hoàn tất. Mở task cần xử lý để xem nguyên nhân; những kết quả đã có vẫn được giữ.",
  LIVE_NATIVE_TASK_INCOMPLETE:
    "Agent chưa hoàn tất đầu ra theo hợp đồng của task. Kết quả này chưa được coi là thành công.",
  PROJECT_CHECKS_FAILED:
    "Kiểm chứng trong Sandbox còn lỗi. Xem log của từng lệnh và các lượt sửa đã thực hiện.",
  PROJECT_BROWSER_CHECKS_FAILED:
    "Browser test còn hành vi chưa đạt tiêu chí. Xem ca kiểm thử lỗi và log tương ứng.",
  LIVE_REVIEW_CHANGES_REQUIRED:
    "Review phát hiện vấn đề cần xử lý trong source trước khi tiếp tục kiểm chứng.",
  PROJECT_PREVIEW_START_FAILED:
    "Ứng dụng chưa khởi động được trong Sandbox. Kiểm tra lệnh chạy và các dependency của repo.",
  LIVE_SOURCE_CONTEXT_MISSING:
    "File cần sửa chưa có đủ nội dung trong ngữ cảnh nguồn. Cần bổ sung phạm vi source trước khi chạy lại.",
};
export const liveCodeMessage = (code: string) =>
  messages[code] ||
  "Bước này chưa hoàn tất; xem mã lỗi và task tương ứng để xử lý.";
export function liveError(error: unknown) {
  const value = error as {
    response?: { data?: { detail?: { code?: string }; error_code?: string } };
    code?: string;
  };
  const code =
    value?.response?.data?.detail?.code ||
    value?.response?.data?.error_code ||
    value?.code ||
    "LIVE_REQUEST_FAILED";
  return (
    messages[code] ||
    `Chưa hoàn tất yêu cầu (${code}). Mở chi tiết lượt chạy để xem bước cần xử lý.`
  );
}
