import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  ArrowLeft,
  CheckCircle2,
  CircleDot,
  ChevronRight,
  Download,
  ExternalLink,
  FileText,
  FolderGit2,
  GitBranch,
  History,
  Inbox,
  Layers,
  LoaderCircle,
  Plus,
  RefreshCw,
  Sparkles,
  Settings2,
  Terminal,
  Workflow,
  X,
} from "lucide-react";
import { type ReactNode, useContext, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { SanitizedMarkdown } from "@/components/core/sanitizedMarkdown";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { AuthContext } from "@/contexts/authContext";
import { deliveryApi } from "@/controllers/API/delivery";
import {
  liveError,
  liveCodeMessage,
  liveWorkflows,
  type LiveRun,
  type LiveTask,
  type ProjectWorkflow,
} from "@/controllers/API/live-workflows";
import ProjectWorkflows from "./project-workflows";
import ProjectWorkloop, { WorkspaceWorkloop } from "./project-workloop";
import ExecutionGraph, {
  WorkJourney,
  ExecutionTimeline,
} from "./execution-graph";
import {
  nativeExecution,
  nativeJourney,
  executionTime,
  nativeRunRefreshInterval,
} from "./execution-model";
import ProjectMetrics from "./project-metrics";
import ProjectIssues from "./project-issues";
import { workspaceLocation } from "./workspace-location";
import DocumentIntake, { DocumentInboxSummary } from "./document-intake";
import { documentUrl } from "@/controllers/API/document-intake";
import ProjectEnvironment from "./project-environment";
import RunHandover, { RunRecovery } from "./run-handover";
import { RunHumanInputs } from "./human-input";
import WorkspaceDashboard from "./workspace-dashboard";
import { workspaceDashboard } from "@/controllers/API/workspace-dashboard";
import { matchesDashboardHistory } from "./workspace-dashboard-model";
import "./live-workspace.css";
import "./cohesive-workspace.css";

export const liveState: Record<string, string> = {
  PLANNING: "Đang lập kế hoạch",
  PLAN_READY: "Chờ duyệt kế hoạch",
  RUNNING: "Đang thực hiện",
  SUCCEEDED: "Hoàn tất",
  FAILED: "Cần xử lý",
  UNCONFIRMED: "Cần đối soát",
  PENDING: "Chờ phụ thuộc",
  WAITING_SLOT: "Chờ Agent",
  WAITING_INPUT: "Chờ bạn phản hồi",
  DONE: "Hoàn tất",
  BLOCKED: "Bị chặn",
  SKIPPED: "Bỏ qua nhánh",
};
const pending = (r?: LiveRun) =>
  !!r && ["PLANNING", "RUNNING"].includes(r.state);
const date = (v: string) =>
  new Date(v).toLocaleString("vi-VN", {
    timeZone: "Asia/Ho_Chi_Minh",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
const clock = (v: number) =>
  new Date(v * 1000).toLocaleTimeString("vi-VN", {
    timeZone: "Asia/Ho_Chi_Minh",
  });

export function safeLivePreview(preview: LiveRun["preview"]) {
  if (!preview?.url || preview.state !== "LIVE") return false;
  const expires =
    typeof preview.expires_at === "number"
      ? preview.expires_at * 1000
      : Date.parse(preview.expires_at);
  try {
    const url = new URL(preview.url);
    return (
      expires > Date.now() &&
      url.hostname === "localhost" &&
      url.protocol === "http:" &&
      Number(url.port) > 1024 &&
      url.origin !== window.location.origin &&
      !url.username &&
      !url.password &&
      url.pathname === "/" &&
      !url.search &&
      !url.hash
    );
  } catch {
    return false;
  }
}

export function ProjectDag({
  tasks,
  run,
  selected,
  select,
}: {
  tasks: LiveTask[];
  run: LiveRun;
  selected: string;
  select: (id: string) => void;
}) {
  const graph = nativeExecution(tasks, run);
  return (
    <ExecutionGraph
      tasks={graph.tasks}
      edges={graph.edges}
      selected={selected}
      select={select}
    />
  );
}

export function LiveRunDetail({
  run,
  busy,
  action,
  reuse,
  retry,
  editPlan,
  saveWorkflow,
  humanInputs,
  initialTab,
  updatedAt,
  stale,
  initialTask,
  onTaskSelect,
  onTabSelect,
}: {
  run: LiveRun;
  busy: string;
  action: (name: string, op: () => Promise<unknown>) => void;
  reuse: () => void;
  retry?: () => void;
  editPlan?: () => void;
  saveWorkflow?: () => void;
  humanInputs?: ReactNode;
  initialTab?: string;
  updatedAt?: number;
  stale?: boolean;
  initialTask?: string;
  onTaskSelect?: (id: string) => void;
  onTabSelect?: (id: string) => void;
}) {
  const [tab, setTab] = useState("tasks"),
    [selected, setSelected] = useState(initialTask || ""),
    [doc, setDoc] = useState("SPEC");
  useEffect(() => setSelected(initialTask || ""), [initialTask]);
  useEffect(() => {
    if (
      initialTab &&
      [
        "tasks",
        "spec",
        "parallel",
        "tests",
        "preview",
        "changes",
        "handover",
      ].includes(initialTab)
    )
      setTab(initialTab);
  }, [initialTab]);
  const tasks: LiveTask[] = run.plan?.tasks?.length
    ? [
        ...run.plan.tasks,
        ...(run.phase === "execution"
          ? run.nodes.filter((n) => !run.plan!.tasks.some((t) => t.id === n.id))
          : []),
      ]
    : run.nodes;
  const selectTask = (id: string) => {
    setSelected(id);
    onTaskSelect?.(id);
  };
  const selectTab = (id: string) => {
    setTab(id);
    onTabSelect?.(id);
  };
  const task =
      tasks.find((t) => t.id === selected) ||
      tasks.find((t) =>
        run.nodes.some((n) => n.id === t.id && n.state === "WAITING_INPUT"),
      ) ||
      tasks.find((t) =>
        run.nodes.some(
          (n) => n.id === t.id && ["RUNNING", "BLOCKED"].includes(n.state),
        ),
      ) ||
      tasks[0],
    node = run.nodes.find((n) => n.id === task?.id);
  const document = run.documents.find((d) => d.id === doc) || run.documents[0];
  const tabs = [
    { id: "tasks", name: "Tiến trình & task" },
    { id: "spec", name: "Tài liệu & Memory" },
    { id: "parallel", name: "Chạy song song" },
    { id: "tests", name: "Test & Verify" },
    { id: "preview", name: "Ứng dụng" },
    { id: "changes", name: "Thay đổi source" },
    ...(!run.legacy ? [{ id: "handover", name: "Bàn giao Gitea" }] : []),
  ];
  return (
    <section className="lw-run">
      <header className="lw-run-header">
        <div>
          <div className="lw-eyebrow">
            {run.legacy ? "LƯỢT CHẠY TNQD ĐÃ LƯU" : "PokeDev · Harness"}{" "}
            <span>· {date(run.created_at)}</span>
          </div>
          <h2>{run.title}</h2>
          <p>
            <GitBranch size={14} /> {run.repository}{" "}
            {run.base_commit && <code>@{run.base_commit.slice(0, 8)}</code>}
          </p>
        </div>
        <span className={`lw-state ${run.state.toLowerCase()}`}>
          {pending(run) && <LoaderCircle size={13} className="animate-spin" />}
          {liveState[run.state] || run.state}
        </span>
      </header>
      <WorkJourney steps={nativeJourney(run)} select={selectTab} />
      <div className="ej-live" role="status">
        <span>
          <span className={`eg-dot ${pending(run) ? "running" : "done"}`} />
          {stale
            ? "Mất kết nối cập nhật · dữ liệu đang lưu"
            : pending(run)
              ? "Tự cập nhật mỗi 3 giây"
              : run.state === "PLAN_READY"
                ? "Chờ bạn duyệt kế hoạch"
                : run.state === "UNCONFIRMED"
                  ? "Cần đối soát trạng thái"
                  : run.state === "FAILED"
                    ? "Lượt cần xử lý"
                    : "Lượt đã hoàn tất"}
          {updatedAt ? ` · ${executionTime(updatedAt / 1000)} (UTC+7)` : ""}
        </span>
        <code>{run.run_id.slice(0, 8)}</code>
      </div>
      <div className="ej-next">
        <ArrowRight size={17} />
        <div>
          <strong>
            {run.state === "PLAN_READY"
              ? "Bước tiếp theo: xem và duyệt kế hoạch"
              : run.nodes.some((n) => n.state === "WAITING_INPUT")
                ? "Agent cần bạn phản hồi"
                : run.state === "SUCCEEDED"
                  ? "Kết quả đã kiểm chứng · tiếp tục bàn giao"
                  : run.state === "UNCONFIRMED"
                    ? "Cần đối soát trước khi tiếp tục"
                    : run.state === "FAILED"
                      ? "Xem task bị chặn và kết quả kiểm tra"
                      : pending(run)
                        ? "Theo dõi tiến trình · chọn task để xem chi tiết"
                        : "Xem lại tài liệu và kết quả của lượt này"}
          </strong>
          <p>
            {run.state === "SUCCEEDED"
              ? "Mở Bàn giao Gitea để xem nhánh, pull request và điều kiện hợp nhất."
              : "Các câu hỏi và quyết định phát sinh xuất hiện ngay trong lượt chạy."}
          </p>
        </div>
        <button
          onClick={() =>
            setTab(run.state === "SUCCEEDED" ? "handover" : "tasks")
          }
        >
          <ArrowRight size={16} />
        </button>
      </div>
      {humanInputs}
      {run.origin_document && (
        <div className="lw-workflow-binding">
          <FileText size={15} />
          <span>
            Từ Slack / Confluence · {run.origin_document.title} · v
            {run.origin_document.page_version}
            <small>
              {" "}
              · Duyệt cho project lúc {date(run.origin_document.approved_at)}
            </small>
          </span>
          <a
            href={documentUrl(
              run.origin_document.document_id,
              run.project_id || undefined,
            )}
          >
            Xem yêu cầu <ArrowRight size={12} />
          </a>
          {run.origin_document.confluence_url && (
            <a
              href={run.origin_document.confluence_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              Confluence <ExternalLink size={12} />
            </a>
          )}
          {run.origin_document.slack_url && (
            <a
              href={run.origin_document.slack_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              Slack <ExternalLink size={12} />
            </a>
          )}
        </div>
      )}
      {run.environment && (
        <div className="pl-binding">
          <Terminal size={15} />
          <span>
            Môi trường: <strong>{run.environment.profile.name}</strong> · v
            {run.environment.revision} · @{run.environment.digest?.slice(0, 10)}
          </span>
          <a href={`/work?view=environment&project=${run.project_id}`}>
            Xem cấu hình project
          </a>
        </div>
      )}
      {run.issue && (
        <div className="lw-workflow-binding">
          <CircleDot size={15} />
          <span>
            Từ issue{" "}
            <a href={run.issue.url} target="_blank" rel="noopener noreferrer">
              #{run.issue.number}
            </a>{" "}
            · bản {run.issue.revision}
            {run.approval_source === "project_issue_policy"
              ? ` · Đã duyệt theo cài đặt project${run.automation?.risk ? ` · ${run.automation.risk.tier}` : ""}`
              : ""}
          </span>
          <a
            href={`/work?view=issues&project=${run.project_id}&issue=${run.issue.proposal_id}`}
          >
            Xem đề xuất
            <ArrowRight size={12} />
          </a>
        </div>
      )}
      {run.auto_timing && (
        <p className="pi-note">
          Lượt tự động · Đã dùng{" "}
          {(run.auto_timing.active_seconds / 60).toFixed(1)}/
          {Math.round(run.auto_timing.limit_seconds / 60)} phút làm việc. Thời
          gian chờ phản hồi được tạm dừng.
        </p>
      )}
      <details className="lw-requirement">
        <summary>
          Yêu cầu của lượt chạy <ChevronRight size={14} />
        </summary>
        <p>
          {run.requirement ||
            "Yêu cầu và tài liệu của lượt TNQD trước đây được giữ trong các tab bên dưới."}
        </p>
        <code>Run {run.run_id}</code>
        {run.parent_run_id && (
          <p>
            Lượt thử tiếp từ{" "}
            <a
              href={`/work?project=${run.project_id || ""}&run=${run.parent_run_id}`}
            >
              {run.parent_run_id.slice(0, 8)}
            </a>
            ; dùng cùng commit và kế hoạch đã duyệt.
          </p>
        )}
      </details>
      {run.workflow && (
        <div className="lw-workflow-binding">
          <Workflow size={15} />
          <span>
            Workflow: <strong>{run.workflow.name}</strong> · v
            {run.workflow.revision}
          </span>
          <a
            href={`/work?view=workflows&project=${run.project_id}&workflow=${run.workflow.workflow_id}`}
          >
            Mở canvas
            <ArrowRight size={12} />
          </a>
        </div>
      )}
      {run.error_code && ["FAILED", "UNCONFIRMED"].includes(run.state) && (
        <div role="alert" className="lw-alert">
          {liveCodeMessage(run.error_code)} <code>{run.error_code}</code>
        </div>
      )}
      {run.state === "UNCONFIRMED" && !run.legacy && (
        <div className="lw-panel">
          <button
            disabled={!!busy}
            onClick={() =>
              action("Đang đối soát session và tiến trình", () =>
                liveWorkflows.reconcile(run.run_id),
              )
            }
          >
            <RefreshCw size={15} />
            Kiểm tra lại lượt chạy
          </button>
        </div>
      )}
      <RunRecovery key={run.run_id} run={run} busy={busy} action={action} />
      {run.state === "FAILED" &&
        run.phase === "execution" &&
        !run.legacy &&
        retry && (
          <div className="lw-panel">
            <button disabled={!!busy} onClick={retry}>
              <RefreshCw size={15} />
              Thử lại từ kế hoạch đã duyệt
            </button>
            <p className="lw-muted">
              Tạo lượt mới từ cùng commit và kế hoạch; giữ lại lượt lỗi để đối
              chiếu.
            </p>
          </div>
        )}
      {run.state === "PLAN_READY" && !run.legacy && (
        <div className="lw-approve">
          <div>
            <strong>Kế hoạch sẵn sàng để bạn duyệt</strong>
            <p>
              Xem tài liệu, phạm vi file, phụ thuộc và lệnh kiểm chứng trước khi
              thực hiện.
            </p>
          </div>
          <div className="lw-approval-actions">
            {editPlan && (
              <button disabled={!!busy} onClick={editPlan}>
                <GitBranch size={15} />
                Chỉnh kế hoạch trên canvas
              </button>
            )}
            <button
              className="lw-primary"
              disabled={!!busy}
              onClick={() =>
                action("Đang bắt đầu thực hiện", () =>
                  liveWorkflows.execute(run),
                )
              }
            >
              Duyệt & thực hiện <ArrowRight size={16} />
            </button>
          </div>
        </div>
      )}
      <nav className="lw-tabs" aria-label="Kết quả lượt chạy">
        {tabs.map((t) => (
          <button
            key={t.id}
            aria-selected={tab === t.id}
            onClick={() => selectTab(t.id)}
          >
            {t.name}
            {t.id === "tests" && !!run.checks?.length && (
              <span>{run.checks.length}</span>
            )}
          </button>
        ))}
      </nav>
      {tab === "tasks" && (
        <>
          <div className="lw-metrics">
            <span>
              <strong>{tasks.length}</strong> công việc
            </span>
            <span>
              <strong>
                {
                  run.nodes.filter(
                    (n) =>
                      n.state === "DONE" && tasks.some((t) => t.id === n.id),
                  ).length
                }
              </strong>{" "}
              hoàn tất
            </span>
            <span>
              <strong>
                {
                  run.nodes.filter(
                    (n) => n.state === "RUNNING" && !n.reused_from,
                  ).length
                }
              </strong>{" "}
              task đang chạy
            </span>
            <span>
              <strong>
                {
                  run.nodes.filter((n) =>
                    ["WAITING_INPUT", "BLOCKED"].includes(n.state),
                  ).length
                }
              </strong>{" "}
              cần xử lý
            </span>
          </div>
          <div className="lw-task-layout">
            <ProjectDag
              tasks={tasks}
              run={run}
              selected={task?.id || ""}
              select={selectTask}
            />
            <aside className="lw-task-detail">
              {task ? (
                <>
                  <small>
                    {task.id} · {task.role || task.kind}
                  </small>
                  <h3>{task.title}</h3>
                  <span
                    className={`lw-state ${(node?.state || "PENDING").toLowerCase()}`}
                  >
                    {liveState[node?.state || "PENDING"] || node?.state}
                  </span>
                  <p>
                    Phụ thuộc:{" "}
                    {task.depends_on?.join(", ") || "Có thể bắt đầu độc lập"}
                  </p>
                  {task.steps?.length && (
                    <>
                      <h4>Các bước thực hiện</h4>
                      <ol>
                        {task.steps.map((s, i) => (
                          <li key={i}>{s}</li>
                        ))}
                      </ol>
                    </>
                  )}
                  {task.acceptance?.length && (
                    <>
                      <h4>Tiêu chí nghiệm thu</h4>
                      <ul>
                        {task.acceptance.map((s, i) => (
                          <li key={i}>{s}</li>
                        ))}
                      </ul>
                    </>
                  )}
                  {!!task.write_paths?.length && (
                    <>
                      <h4>File được thay đổi</h4>
                      {task.write_paths.map((p) => (
                        <code className="lw-file" key={p}>
                          {p}
                        </code>
                      ))}
                    </>
                  )}
                  {node?.summary && <p className="lw-result">{node.summary}</p>}
                  {node?.error_code && (
                    <p>
                      {liveCodeMessage(node.error_code)}{" "}
                      <code>{node.error_code}</code>
                    </p>
                  )}
                  {node?.session_id && (
                    <small className="lw-file">Session {node.session_id}</small>
                  )}
                  {node?.reused_from && (
                    <p className="lw-muted">
                      Dùng lại artifact đã đối chiếu từ lượt{" "}
                      {node.reused_from.slice(0, 8)}.
                    </p>
                  )}
                </>
              ) : (
                <p>
                  Agent đang chuẩn bị công việc theo yêu cầu và source của
                  project.
                </p>
              )}
            </aside>
          </div>
          <ExecutionTimeline
            tasks={nativeExecution(tasks, run).tasks}
            select={selectTask}
          />
          {!!run.plan?.commands?.length && (
            <details className="lw-commands">
              <summary>
                Lệnh kiểm chứng trong Sandbox ({run.plan.commands.length})
              </summary>
              {run.plan.commands.map((c, i) => (
                <div key={i}>
                  <strong>{c.label}</strong>
                  <code>{c.argv.join(" ")}</code>
                </div>
              ))}
            </details>
          )}
        </>
      )}
      {tab === "spec" && (
        <div className="lw-documents">
          <div className="lw-document-nav">
            {run.documents.map((d) => (
              <button
                key={d.id}
                aria-pressed={document?.id === d.id}
                onClick={() => setDoc(d.id)}
              >
                <FileText size={16} />
                <span>
                  {d.title}
                  <small>{d.revision}</small>
                </span>
              </button>
            ))}
            <p>
              Memory theo project:{" "}
              {run.memory?.some((m) => m.mode === "COGNEE")
                ? "Harness / Cognee"
                : "Kho tài liệu PokeDev"}
            </p>
            <small>
              Tài liệu có phiên bản; nội dung được bổ sung sau khi kiểm chứng.
              Tài liệu của vòng trước là ngữ cảnh cho yêu cầu tiếp theo.
            </small>
          </div>
          <article>
            {document ? (
              <>
                <div className="lw-eyebrow">
                  {document.id} · {document.revision}
                </div>
                <SanitizedMarkdown
                  chatMessage={document.body}
                  isEmpty={false}
                />
                {document.previous_body && (
                  <details>
                    <summary>Xem phiên bản trước phát triển</summary>
                    <SanitizedMarkdown
                      chatMessage={document.previous_body}
                      isEmpty={false}
                    />
                  </details>
                )}
              </>
            ) : (
              <p>
                Tài liệu sẽ xuất hiện khi BA lấy ngữ cảnh và phân tích yêu cầu.
              </p>
            )}
          </article>
        </div>
      )}
      {tab === "parallel" && (
        <div className="lw-panel">
          <h3>Timeline các Agent</h3>
          <p>
            Thời điểm dưới đây lấy từ session thực trên Harness. Cạnh trên DAG
            quyết định task nào được bắt đầu.
          </p>
          {run.parallel?.verified ? (
            <div className="lw-positive">
              <CheckCircle2 size={18} />
              <span>
                {run.parallel.tasks.join(" + ")} cùng hoạt động khoảng{" "}
                {run.parallel.overlap_seconds.toFixed(1)} giây ·{" "}
                {run.parallel.samples || 1} lần quan sát.
              </span>
            </div>
          ) : (
            <p>Chưa ghi nhận hai session cùng hoạt động trong lượt này.</p>
          )}
          {run.nodes
            .filter((n) => n.session_id && !n.reused_from && n.native_start_at)
            .map((n) => (
              <div className="lw-timeline" key={n.id}>
                <strong>{n.id}</strong>
                <span>{n.title}</span>
                <code>
                  {clock(n.native_start_at || n.started_at!)} →{" "}
                  {n.native_end_at || n.completed_at
                    ? clock(n.native_end_at || n.completed_at!)
                    : "đang chạy"}
                </code>
              </div>
            ))}
          {run.nodes.some((n) => n.reused_from) && (
            <p className="lw-muted">
              {run.nodes
                .filter((n) => n.reused_from)
                .map((n) => n.id)
                .join(", ")}
              : dùng lại artifact đã đối chiếu của lượt trước; thời gian chạy cũ
              không tính vào bằng chứng song song của lượt này.
            </p>
          )}
        </div>
      )}
      {tab === "tests" && (
        <div className="lw-panel">
          {run.checks?.length ? (
            run.checks.map((group) => (
              <section className="lw-check-group" key={group.id}>
                <h3>
                  {group.title}{" "}
                  <small>
                    {
                      group.tests.filter(
                        (t) => t.passed === true || t.status === "PASS",
                      ).length
                    }
                    /{group.tests.length} đạt
                  </small>
                </h3>
                {group.tests.map((test, i) => (
                  <details className="lw-check" key={test.id || i}>
                    <summary>
                      <span
                        className={`lw-dot ${test.passed === true || test.status === "PASS" ? "ok" : "fail"}`}
                      />
                      <span>{test.label || test.id}</span>
                      <small>
                        {test.passed === true || test.status === "PASS"
                          ? "Đạt"
                          : "Cần xử lý"}
                      </small>
                    </summary>
                    {test.argv && <code>{test.argv.join(" ")}</code>}
                    <pre>
                      {test.stdout ||
                        test.stderr ||
                        test.error ||
                        "Không có log bổ sung."}
                      {test.stdout && test.stderr ? "\n" + test.stderr : ""}
                    </pre>
                  </details>
                ))}
              </section>
            ))
          ) : (
            <div className="lw-empty">
              <Layers size={30} />
              <h3>Chưa có kết quả kiểm chứng</h3>
              <p>
                Runner sẽ chạy lệnh đã duyệt và TestForge trong Sandbox sau khi
                các task hoàn tất.
              </p>
            </div>
          )}
        </div>
      )}
      {tab === "preview" && (
        <div className="lw-panel">
          {safeLivePreview(run.preview) ? (
            <>
              <div className="lw-preview-heading">
                <div>
                  <h3>Ứng dụng trong Sandbox</h3>
                  <p>Bản source của lượt chạy này · phiên chạy có thời hạn</p>
                </div>
                <a
                  href={run.preview!.url!}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Mở riêng <ExternalLink size={15} />
                </a>
              </div>
              <iframe
                className="lw-preview"
                title="Ứng dụng từ lượt Workloop"
                src={run.preview!.url!}
                sandbox="allow-scripts allow-forms allow-same-origin"
                referrerPolicy="no-referrer"
              />
            </>
          ) : (
            <div className="lw-empty">
              <FolderGit2 size={30} />
              <h3>
                {run.preview
                  ? "Phiên Sandbox đã hết hạn"
                  : "Chưa có bản ứng dụng để xem"}
              </h3>
              <p>
                Preview xuất hiện khi source đã build và ứng dụng khởi động
                được. Repo CLI có kết quả ở Test & Verify.
              </p>
            </div>
          )}
        </div>
      )}
      {tab === "changes" && (
        <div className="lw-panel">
          <div className="lw-preview-heading">
            <h3>{run.changed_files?.length || 0} file thay đổi</h3>
            {!run.legacy && run.diff && (
              <button
                onClick={() =>
                  action("Đang tải bản thay đổi", async () => {
                    const content = await liveWorkflows.patch(run.run_id),
                      url = URL.createObjectURL(
                        new Blob([content], {
                          type: "text/plain;charset=utf-8",
                        }),
                      );
                    const a = window.document.createElement("a");
                    a.href = url;
                    a.download = `vaiplatform-${run.run_id}.patch`;
                    a.click();
                    URL.revokeObjectURL(url);
                  })
                }
              >
                <Download size={15} />
                Tải patch
              </button>
            )}
          </div>
          {run.changed_files?.map((p) => (
            <code className="lw-file" key={p}>
              {p}
            </code>
          ))}
          {run.diff && <pre className="lw-diff">{run.diff}</pre>}
          {run.state === "SUCCEEDED" &&
            !run.legacy &&
            (run.published ? (
              <a
                className="lw-primary lw-link"
                target="_blank"
                rel="noopener noreferrer"
                href={run.published.url}
              >
                Xem nhánh {run.published.branch} <ExternalLink size={15} />
              </a>
            ) : (
              <button
                className="lw-primary"
                disabled={!!busy}
                onClick={() =>
                  action("Đang xuất nhánh lên Gitea", () =>
                    liveWorkflows.publish(run.run_id),
                  )
                }
              >
                <GitBranch size={15} />
                Xuất kết quả thành nhánh Gitea
              </button>
            ))}
          <p className="lw-muted">
            Lịch sử giữ lại tài liệu, log và bản thay đổi của từng lượt. Bạn có
            thể tiếp tục bằng một yêu cầu mới.
          </p>
        </div>
      )}
      {tab === "handover" && <RunHandover key={run.run_id} run={run} />}
      <footer className="lw-run-footer">
        <span>
          {busy ||
            (pending(run)
              ? "Đang cập nhật tự động…"
              : `Lưu theo project · ${run.run_id.slice(0, 8)}`)}
        </span>
        <div className="lw-approval-actions">
          {saveWorkflow && (
            <button onClick={saveWorkflow}>
              <Workflow size={14} />
              Lưu thành workflow
            </button>
          )}
          <button onClick={reuse}>
            Dùng yêu cầu này cho lượt mới <ArrowRight size={14} />
          </button>
        </div>
      </footer>
    </section>
  );
}

export default function LiveWorkspace({ tools }: { tools?: ReactNode } = {}) {
  const { userData } = useContext(AuthContext),
    identity = userData?.id || "pending",
    client = useQueryClient();
  const [params, setParams] = useSearchParams(),
    selectedId = params.get("run") || "",
    workloopJob = params.get("workloop_job") || "";
  const { projectId, section } = workspaceLocation(params);
  const filteredHistory = params.get("filtered") === "1";
  const dashboardDays = params.get("range") === "7" ? 7 : 28;
  const [historyLimit, setHistoryLimit] = useState(50);
  useEffect(
    () => setHistoryLimit(50),
    [projectId, params.get("from"), params.get("to"), params.get("status")],
  );
  const [showNew, setShowNew] = useState(
      !!projectId && !selectedId && !workloopJob && !params.get("view"),
    ),
    [repoDialog, setRepoDialog] = useState(false),
    [repoMode, setRepoMode] = useState("existing"),
    [repository, setRepository] = useState(""),
    [repoName, setRepoName] = useState(""),
    [search, setSearch] = useState("");
  const [formProject, setFormProject] = useState(projectId),
    [formWorkflow, setFormWorkflow] = useState(""),
    [title, setTitle] = useState(""),
    [requirement, setRequirement] = useState(""),
    [busy, setBusy] = useState(""),
    [error, setError] = useState("");
  const inFlight = useRef(false),
    retryIntent = useRef<{ parent: string; run: string } | null>(null),
    draft = useRef<
      { key: string; flow?: string; delivery?: string; run: string } | undefined
    >(undefined);
  const enabled = !!userData;
  useEffect(() => {
    if (selectedId || workloopJob) setShowNew(false);
  }, [selectedId, workloopJob]);
  const workflowOptions = useQuery({
    queryKey: ["project-workflows", identity, formProject],
    queryFn: () => liveWorkflows.workflows(formProject),
    enabled: enabled && !!formProject,
    retry: false,
  });
  const projects = useQuery({
    queryKey: ["live-projects", identity],
    queryFn: liveWorkflows.projects,
    enabled,
    retry: false,
  });
  const folders = useQuery({
    queryKey: ["delivery-folders", identity],
    queryFn: deliveryApi.folders,
    enabled,
    retry: false,
  });
  const readiness = useQuery({
    queryKey: ["live-ready", identity],
    queryFn: liveWorkflows.readiness,
    enabled,
    retry: false,
    staleTime: 30000,
    refetchInterval: (q) => (q.state.data?.ready ? 60000 : 15000),
  });
  const history = useQuery({
    queryKey: ["live-runs", identity, projectId],
    queryFn: () => liveWorkflows.runs(projectId || undefined),
    enabled:
      enabled &&
      !filteredHistory &&
      !["overview", "new-project", "requests"].includes(section),
    retry: false,
    refetchInterval: 4000,
  });
  const historySnapshot = useQuery({
    queryKey: ["workspace-dashboard", identity, projectId, dashboardDays],
    queryFn: () =>
      workspaceDashboard.read(dashboardDays, projectId || undefined),
    enabled:
      enabled && filteredHistory && ["work", "results"].includes(section),
    retry: false,
    refetchInterval: 10000,
    staleTime: 3000,
  });
  const detail = useQuery({
    queryKey: ["live-run", identity, selectedId],
    queryFn: () => liveWorkflows.read(selectedId),
    enabled: enabled && !!selectedId && ["work", "results"].includes(section),
    retry: false,
    refetchIntervalInBackground: true,
    refetchInterval: (q) => nativeRunRefreshInterval(q.state.data?.state),
  });
  const repos = useQuery({
    queryKey: ["gitea-repos", identity],
    queryFn: liveWorkflows.repositories,
    enabled: enabled && repoDialog && repoMode === "existing",
    retry: false,
  });
  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ["live-projects", identity] }),
      client.invalidateQueries({ queryKey: ["live-runs", identity] }),
      client.invalidateQueries({ queryKey: ["live-run", identity] }),
      client.invalidateQueries({ queryKey: ["live-ready", identity] }),
      client.invalidateQueries({ queryKey: ["project-issues", identity] }),
      client.invalidateQueries({ queryKey: ["workspace-dashboard", identity] }),
      client.invalidateQueries({ queryKey: ["document-intake", identity] }),
    ]);
  };
  const action = async (name: string, operation: () => Promise<unknown>) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(name);
    setError("");
    try {
      await operation();
    } catch (e) {
      setError(liveError(e));
    } finally {
      inFlight.current = false;
      setBusy("");
      await refresh();
    }
  };
  const selectRun = (r: Pick<LiveRun, "project_id" | "run_id">) => {
    setShowNew(false);
    setError("");
    setParams({
      ...(r.project_id ? { project: r.project_id } : {}),
      run: r.run_id,
    });
  };
  const useWorkflow = (workflow: ProjectWorkflow) => {
    setFormProject(workflow.project_id);
    setFormWorkflow(workflow.workflow_id);
    setShowNew(true);
    setError("");
    setParams({ project: workflow.project_id });
  };
  const changeView = (next: string) => {
    setParams((previous) => {
      if (next === "overview")
        return new URLSearchParams(
          previous.has("tools_project")
            ? { tools_project: previous.get("tools_project")! }
            : {},
        );
      const result = new URLSearchParams(previous);
      result.delete("workflow");
      result.delete("edit_run");
      result.delete("from_run");
      result.delete("project_id");
      result.delete("tools_project");
      result.delete("issue");
      result.delete("document");
      if (next === "work" && projectId) result.delete("view");
      else if (next === "work") result.set("view", "history");
      else result.set("view", next);
      if (projectId) {
        result.set("project", projectId);
      } else {
        result.delete("project");
      }
      return result;
    });
  };
  const createRun = () =>
    action("Đang lấy source và bắt đầu phân tích", async () => {
      const key = JSON.stringify([
        formProject,
        title.trim(),
        requirement.trim(),
        formWorkflow,
        workflowOptions.data?.items.find((w) => w.workflow_id === formWorkflow)
          ?.digest,
      ]);
      if (draft.current?.key !== key)
        draft.current = { key, run: crypto.randomUUID() };
      const intent = draft.current;
      if (!intent.flow)
        intent.flow = (
          await deliveryApi.createFlow(
            title.trim(),
            requirement.trim(),
            formProject,
          )
        ).id;
      if (!intent.delivery)
        intent.delivery = (
          await deliveryApi.create(
            intent.flow,
            title.trim(),
            requirement.trim(),
          )
        ).id;
      const run = await liveWorkflows.plan({
        project_id: formProject,
        delivery_id: intent.delivery,
        run_id: intent.run,
        ...(formWorkflow
          ? {
              workflow_id: formWorkflow,
              workflow_digest: workflowOptions.data?.items.find(
                (w) => w.workflow_id === formWorkflow,
              )?.digest,
            }
          : {}),
      });
      selectRun(run);
      draft.current = undefined;
    });
  const snapshotStatus = (
    historySnapshot.error as { response?: { status?: number } } | null
  )?.response?.status;
  const snapshotDenied =
    historySnapshot.isError && [401, 403, 404].includes(snapshotStatus || 0);
  const historyItems = filteredHistory
    ? snapshotDenied
      ? []
      : historySnapshot.data?.history || []
    : history.data?.items || [];
  const visible = historyItems.filter(
    (r) =>
      (!filteredHistory || matchesDashboardHistory(r, params)) &&
      (params.get("view") !== "review" || r.state === "PLAN_READY") &&
      (section !== "results" ||
        ["SUCCEEDED", "FAILED", "UNCONFIRMED"].includes(r.state)) &&
      `${r.title} ${r.repository} ${r.run_id}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  const unlinked = (folders.data || []).filter(
    (f) => !projects.data?.items.some((p) => p.project_id === f.id),
  );
  const run = [401, 403, 404].includes(
    (detail.error as { response?: { status?: number } })?.response?.status || 0,
  )
    ? undefined
    : detail.data;
  const project = projects.data?.items.find((p) => p.project_id === projectId);
  const allRuns = historyItems;
  const waiting = allRuns.filter((r) => r.state === "PLAN_READY").length;
  return (
    <div className="lw-page">
      <header className="lw-top">
        <div>
          <div className="lw-eyebrow">
            <span className="lw-brand-mark">
              <Workflow size={12} />
            </span>
            PokeDev / WORKSPACE
          </div>
          <h1>
            {project?.name ||
              (section === "new-project"
                ? "Project mới"
                : "Tổng quan workspace")}
          </h1>
          <p>
            {project ? (
              <>
                <GitBranch size={13} />
                {project.repository}
                <span className="lw-separator">/</span>
                {project.branch}
              </>
            ) : section === "new-project" ? (
              "Kết nối repo, xây dựng sản phẩm hoặc thiết kế quy trình cho workspace."
            ) : (
              "Từ ý tưởng đến sản phẩm. Cùng một nơi để thiết kế, thực hiện và kiểm chứng."
            )}
          </p>
        </div>
        <div className="lw-top-actions">
          {project && (
            <a
              href={project.repository_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              <ExternalLink size={14} />
              Repo
            </a>
          )}
          <button
            aria-label="Cập nhật trạng thái"
            onClick={() => void refresh()}
          >
            <RefreshCw size={16} />
          </button>
          {!!projectId && (
            <button
              className="lw-primary"
              onClick={() => {
                if (!projectId) {
                  setRepoDialog(true);
                  return;
                }
                changeView("work");
                setShowNew(true);
                setTitle("");
                setRequirement("");
                setFormWorkflow("");
                setFormProject(
                  projectId || projects.data?.items[0]?.project_id || "",
                );
                setError("");
              }}
            >
              <Plus size={16} />
              Yêu cầu mới
            </button>
          )}
        </div>
      </header>
      <div className="lw-body">
        <aside className="lw-sidebar">
          {(!!projectId || section === "new-project") && (
            <button
              className="lw-workspace-return"
              aria-label="Tổng quan workspace"
              onClick={() => {
                setParams({});
                setShowNew(false);
              }}
            >
              <ArrowLeft size={14} />
              Tổng quan workspace
            </button>
          )}
          <button
            className="lw-create-project"
            aria-current={section === "new-project" ? "page" : undefined}
            onClick={() => {
              setParams({ view: "new-project" });
              setShowNew(false);
              setError("");
            }}
          >
            <Plus size={16} /> Project mới
          </button>
          <div className="lw-sidebar-heading">
            <h2>PROJECT CỦA BẠN</h2>
            <button
              title="Kết nối hoặc tạo repo"
              aria-label="Kết nối hoặc tạo repo"
              onClick={() => setRepoDialog(true)}
            >
              <Plus size={16} />
            </button>
          </div>
          {projects.data?.items.map((p) => (
            <button
              className={`lw-project ${projectId === p.project_id ? "active" : ""}`}
              key={p.project_id}
              title={p.repository}
              onClick={() => {
                setParams({
                  project: p.project_id,
                  ...(projectId && section !== "work" ? { view: section } : {}),
                });
                setFormProject(p.project_id);
                setFormWorkflow("");
                setShowNew(false);
              }}
            >
              <FolderGit2 size={17} />
              <span>
                {p.name}
                <small>{p.repository}</small>
              </span>
            </button>
          ))}
          <button className="lw-connect" onClick={() => setRepoDialog(true)}>
            <GitBranch size={15} />
            Chọn / tạo repo Gitea
          </button>
          {!!unlinked.length && (
            <details className="lw-old-projects">
              <summary>Project khác ({unlinked.length})</summary>
              {unlinked.map((f) => (
                <a
                  key={f.id}
                  href={`/work?tools_project=${encodeURIComponent(f.id)}`}
                >
                  {f.name}
                  <ExternalLink size={12} />
                </a>
              ))}
            </details>
          )}
          <div
            className={`lw-connection ${readiness.data?.ready ? "ready" : ""}`}
          >
            <span
              className={`lw-dot ${readiness.data?.ready ? "ok" : "fail"}`}
            />
            <div>
              <strong>
                {readiness.isFetching
                  ? "Đang kiểm tra dịch vụ…"
                  : readiness.data?.ready
                    ? "Harness đã kết nối"
                    : "Kết nối cần kiểm tra"}
              </strong>
              <small>
                {readiness.data?.endpoint || "AI · Sandbox · TestForge"}
              </small>
            </div>
          </div>
        </aside>
        <main
          className={`lw-main ${section === "workflows" && params.get("workflow") ? "lw-main-canvas" : ""}`}
        >
          {section !== "new-project" && (
            <nav
              className="lw-workspace-tabs"
              aria-label={
                projectId ? "Khu vực của project" : "Khu vực của workspace"
              }
            >
              {(projectId
                ? [
                    { id: "work", name: "Công việc", icon: Layers },
                    { id: "requests", name: "Yêu cầu & tài liệu", icon: Inbox },
                    { id: "issues", name: "Issue Gitea", icon: CircleDot },
                    { id: "workflows", name: "Workflow", icon: Workflow },
                    { id: "results", name: "Kết quả", icon: CheckCircle2 },
                    { id: "metrics", name: "Thống kê", icon: GitBranch },
                    { id: "environment", name: "Môi trường", icon: Terminal },
                    { id: "settings", name: "Cài đặt", icon: Settings2 },
                  ]
                : [
                    { id: "overview", name: "Tổng quan", icon: Layers },
                    { id: "requests", name: "Yêu cầu & tài liệu", icon: Inbox },
                    { id: "work", name: "Lịch sử công việc", icon: History },
                    { id: "results", name: "Kết quả", icon: CheckCircle2 },
                  ]
              ).map((tab) => (
                <button
                  key={tab.id}
                  aria-current={section === tab.id ? "page" : undefined}
                  onClick={() => changeView(tab.id)}
                >
                  <tab.icon size={15} />
                  {tab.name}
                  {tab.id === "work" && waiting > 0 && <span>{waiting}</span>}
                </button>
              ))}
            </nav>
          )}
          {(error ||
            projects.error ||
            history.error ||
            historySnapshot.error ||
            detail.error) && (
            <div role="alert" className="lw-alert">
              {error ||
                liveError(
                  projects.error ||
                    history.error ||
                    historySnapshot.error ||
                    detail.error,
                )}
            </div>
          )}
          {section === "workflows" && (
            <ProjectWorkflows
              identity={identity}
              projectId={projectId}
              projects={projects.data?.items || []}
              onUse={useWorkflow}
              onApplied={(runId, project) => {
                setShowNew(false);
                setParams({ project, run: runId });
              }}
            />
          )}
          {section === "metrics" && (
            <ProjectMetrics
              key={`${identity}:${projectId}`}
              identity={identity}
              project={project}
            />
          )}
          {section === "requests" && (
            <DocumentIntake
              key={`${identity}:${projectId}`}
              identity={identity}
              projectId={projectId || undefined}
              projects={projects.data?.items || []}
              selectedId={params.get("document") || undefined}
              onSelect={(id) =>
                setParams((previous) => {
                  const next = new URLSearchParams(previous);
                  next.set("document", id);
                  return next;
                })
              }
              onOpenRun={selectRun}
              onConnectProject={() => setRepoDialog(true)}
            />
          )}
          {section === "environment" && (
            <ProjectEnvironment
              key={`${identity}:${projectId}`}
              identity={identity}
              project={project}
            />
          )}
          {(section === "issues" || section === "settings") && (
            <ProjectIssues
              key={`${identity}:${projectId}`}
              project={project}
              identity={identity}
              section={section}
              selectedProposal={params.get("issue") || undefined}
              onSettings={() => changeView("settings")}
              onOpenRun={(runId) => {
                setShowNew(false);
                setParams({ project: projectId, run: runId });
              }}
            />
          )}
          {section === "overview" && (
            <>
              <WorkspaceDashboard key={identity} identity={identity} />
              <DocumentInboxSummary />
              <WorkspaceWorkloop />
            </>
          )}
          {section === "new-project" && (
            <section
              className="lw-project-start"
              aria-label="Bắt đầu project mới"
            >
              <div>
                <FolderGit2 size={23} />
                <h2>Bắt đầu từ repo Gitea</h2>
                <p>
                  Chọn repo sẵn có hoặc tạo repo mới, rồi giao yêu cầu và chỉnh
                  workflow riêng cho project.
                </p>
              </div>
              <button
                className="lw-primary"
                onClick={() => setRepoDialog(true)}
              >
                <Plus size={15} /> Chọn / tạo repo Gitea
              </button>
            </section>
          )}
          {section === "new-project" && (
            <div className="lw-tools" id="workspace-tools">
              <header>
                <span className="lw-eyebrow">ĐIỀU PHỐI TOÀN WORKSPACE</span>
                <h2>Workflow gói & chu kỳ phát triển</h2>
                <p>
                  Soạn workflow, duyệt hợp đồng, theo dõi dịch vụ và các chu kỳ
                  hiện có.
                </p>
                <div>
                  <a href="/flows">
                    <Workflow size={15} />
                    Canvas gói
                  </a>
                  <a href="/projects">
                    <FolderGit2 size={15} />
                    Mở project từ thư mục
                  </a>
                  <a href="/library">
                    <Layers size={15} />
                    Thư viện
                  </a>
                </div>
              </header>
              {tools}
            </div>
          )}
          {(section === "work" || section === "results") && (
            <>
              {!run && !selectedId && !workloopJob && (
                <div className="lw-overview">
                  <div>
                    <span className="lw-eyebrow">MỘT QUY TRÌNH LIỀN MẠCH</span>
                    <h2>
                      {section === "results"
                        ? "Kết quả có thể kiểm chứng"
                        : "Ý tưởng của bạn, từng bước thành sản phẩm."}
                    </h2>
                    <p>
                      Chọn repo, dùng workflow của bạn hoặc để AI lập kế hoạch.
                      Theo dõi mọi thay đổi từ cùng một project.
                    </p>
                  </div>
                  <div className="lw-overview-stats">
                    <div>
                      <strong>
                        {allRuns.length.toString().padStart(2, "0")}
                      </strong>
                      <span>Lượt đã lưu</span>
                    </div>
                    <div>
                      <strong>{waiting.toString().padStart(2, "0")}</strong>
                      <span>Chờ bạn duyệt</span>
                    </div>
                    <div>
                      <strong>
                        {allRuns
                          .filter((r) => r.state === "SUCCEEDED")
                          .length.toString()
                          .padStart(2, "0")}
                      </strong>
                      <span>Hoàn tất</span>
                    </div>
                  </div>
                </div>
              )}
              {section === "work" && showNew && (
                <section className="lw-new">
                  <div className="lw-new-heading">
                    <div>
                      <span className="lw-eyebrow">
                        01 REPO → 02 YÊU CẦU → 03 KẾ HOẠCH → 04 THỰC HIỆN
                      </span>
                      <h2>Bạn muốn cải thiện hoặc tạo sản phẩm gì?</h2>
                    </div>
                    <button
                      aria-label="Đóng yêu cầu mới"
                      onClick={() => setShowNew(false)}
                    >
                      <X size={18} />
                    </button>
                  </div>
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      void createRun();
                    }}
                  >
                    <label>
                      Project / repo
                      <select
                        required
                        value={formProject}
                        onChange={(e) => {
                          setFormProject(e.target.value);
                          setFormWorkflow("");
                        }}
                      >
                        <option value="">Chọn project đã kết nối…</option>
                        {projects.data?.items.map((p) => (
                          <option key={p.project_id} value={p.project_id}>
                            {p.repository}
                          </option>
                        ))}
                      </select>
                    </label>
                    <button
                      type="button"
                      className="lw-inline"
                      onClick={() => setRepoDialog(true)}
                    >
                      <Plus size={14} />
                      Chọn repo khác hoặc tạo repo mới
                    </button>
                    <label>
                      Workflow sử dụng
                      <select
                        aria-label="Workflow sử dụng"
                        value={formWorkflow}
                        onChange={(e) => setFormWorkflow(e.target.value)}
                      >
                        <option value="">AI lập kế hoạch từ yêu cầu</option>
                        {workflowOptions.data?.items
                          .filter((workflow) => workflow.ready)
                          .map((workflow) => (
                            <option
                              value={workflow.workflow_id}
                              key={workflow.workflow_id}
                            >
                              {workflow.name} · v{workflow.revision}
                            </option>
                          ))}
                      </select>
                    </label>
                    <div className="lw-workflow-hint">
                      <Workflow size={15} />
                      <p>
                        {formWorkflow
                          ? "Lượt chạy sẽ giữ nguyên task, phụ thuộc, phạm vi file và kiểm tra của canvas đã chọn."
                          : "AI phân tích repo và đề xuất kế hoạch để bạn duyệt. Bạn có thể chỉnh kế hoạch trên canvas trước khi chạy."}
                      </p>
                      <button
                        type="button"
                        className="lw-inline"
                        onClick={() => {
                          setParams({
                            ...(formProject ? { project: formProject } : {}),
                            view: "workflows",
                          });
                        }}
                      >
                        Thiết kế workflow
                        <ArrowRight size={13} />
                      </button>
                    </div>
                    <label>
                      Tên yêu cầu
                      <input
                        required
                        maxLength={120}
                        placeholder="Ví dụ: Thêm bộ lọc công việc theo trạng thái"
                        value={title}
                        onChange={(e) => setTitle(e.target.value)}
                      />
                    </label>
                    <label>
                      Mô tả và tiêu chí mong muốn
                      <textarea
                        required
                        minLength={20}
                        maxLength={30000}
                        rows={6}
                        placeholder="Nêu hành vi cần có, dữ liệu đầu vào, giao diện và cách bạn muốn kiểm tra kết quả. Agent sẽ đọc source của repo để tạo spec và chia task cụ thể."
                        value={requirement}
                        onChange={(e) => setRequirement(e.target.value)}
                      />
                    </label>
                    <div className="lw-form-footer">
                      <p>
                        Mỗi yêu cầu tạo một lượt riêng. Bạn duyệt kế hoạch trước
                        khi Agent sửa source.
                      </p>
                      <button
                        className="lw-primary"
                        type="submit"
                        disabled={
                          !!busy ||
                          !formProject ||
                          !readiness.data?.ready ||
                          (!!formWorkflow &&
                            !workflowOptions.data?.items.some(
                              (w) => w.workflow_id === formWorkflow && w.ready,
                            ))
                        }
                      >
                        {busy ? (
                          <LoaderCircle size={16} className="animate-spin" />
                        ) : (
                          <Sparkles size={16} />
                        )}
                        {busy || "Phân tích & lập kế hoạch"}
                      </button>
                    </div>
                    {!readiness.isFetching && !readiness.data?.ready && (
                      <p className="lw-alert">
                        Chưa sẵn sàng gọi AI / Sandbox. Bấm cập nhật trạng thái
                        sau khi Harness hoặc VPN hoạt động.
                      </p>
                    )}
                  </form>
                </section>
              )}
              {!showNew && !workloopJob && run ? (
                <LiveRunDetail
                  key={run.run_id}
                  run={run}
                  initialTab={params.get("tab") || undefined}
                  updatedAt={detail.dataUpdatedAt}
                  stale={detail.isError}
                  initialTask={params.get("task") || undefined}
                  onTaskSelect={(id) =>
                    setParams(
                      (old) => {
                        const next = new URLSearchParams(old);
                        next.set("task", id);
                        return next;
                      },
                      { replace: true },
                    )
                  }
                  onTabSelect={(id) =>
                    setParams(
                      (old) => {
                        const next = new URLSearchParams(old);
                        next.set("tab", id);
                        return next;
                      },
                      { replace: true },
                    )
                  }
                  humanInputs={<RunHumanInputs runId={run.run_id} />}
                  busy={busy}
                  action={(n, op) => {
                    void action(n, op);
                  }}
                  editPlan={
                    run.state === "PLAN_READY"
                      ? () =>
                          setParams({
                            project: run.project_id || "",
                            view: "workflows",
                            workflow: "new",
                            edit_run: run.run_id,
                          })
                      : undefined
                  }
                  saveWorkflow={
                    run.plan && !run.legacy && run.project_id
                      ? () =>
                          setParams({
                            project: run.project_id!,
                            view: "workflows",
                            workflow: "new",
                            from_run: run.run_id,
                          })
                      : undefined
                  }
                  retry={() => {
                    void action(
                      "Đang tạo lượt thử tiếp từ kế hoạch đã duyệt",
                      async () => {
                        if (retryIntent.current?.parent !== run.run_id)
                          retryIntent.current = {
                            parent: run.run_id,
                            run: crypto.randomUUID(),
                          };
                        selectRun(
                          await liveWorkflows.retry(
                            run.run_id,
                            retryIntent.current.run,
                          ),
                        );
                      },
                    );
                  }}
                  reuse={() => {
                    setTitle(run.title);
                    setRequirement(run.requirement || "");
                    setFormProject(run.project_id || "");
                    setFormWorkflow("");
                    setShowNew(true);
                  }}
                />
              ) : !showNew && selectedId && detail.isFetching ? (
                <div className="lw-empty">
                  <LoaderCircle className="animate-spin" />
                  Đang mở lượt chạy…
                </div>
              ) : null}
              {!showNew &&
                projectId &&
                projects.data?.items.find(
                  (p) => p.project_id === projectId,
                ) && (
                  <ProjectWorkloop
                    key={projectId}
                    project={
                      projects.data.items.find(
                        (p) => p.project_id === projectId,
                      )!
                    }
                  />
                )}
              <section className="lw-history">
                <div className="lw-history-heading">
                  <div>
                    <h2>
                      <History size={18} />
                      Lịch sử lượt chạy
                    </h2>
                    <p>
                      {projectId
                        ? projects.data?.items.find(
                            (p) => p.project_id === projectId,
                          )?.repository
                        : "Tất cả project, gồm các lượt TNQD đã thực hiện"}
                    </p>
                  </div>
                  <input
                    aria-label="Tìm lịch sử"
                    placeholder="Tìm yêu cầu, repo, mã lượt…"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                </div>
                {filteredHistory && (
                  <div className="lw-history-filter">
                    <span>
                      Đang lọc từ dashboard
                      {params.get("from")
                        ? ` · ${params.get("from")} – ${params.get("to")}`
                        : " · mọi thời điểm"}
                      {params.get("status")
                        ? ` · ${liveState[params.get("status")!] || ({ active: "Đang thực hiện", running: "Đang thực hiện", waiting: "Chờ phản hồi / duyệt", other: "Trạng thái khác" } as Record<string, string>)[params.get("status")!] || params.get("status")}`
                        : ""}{" "}
                      · {visible.length} lượt
                    </span>
                    <button
                      onClick={() =>
                        setParams((previous) => {
                          const next = new URLSearchParams(previous);
                          for (const key of [
                            "filtered",
                            "from",
                            "to",
                            "status",
                            "range",
                          ])
                            next.delete(key);
                          return next;
                        })
                      }
                    >
                      Bỏ bộ lọc
                    </button>
                  </div>
                )}
                {visible.length ? (
                  <div className="lw-history-list">
                    {visible.slice(0, historyLimit).map((r) => (
                      <button
                        className={selectedId === r.run_id ? "selected" : ""}
                        key={r.run_id}
                        onClick={() => selectRun(r)}
                      >
                        <span
                          className={`lw-dot ${r.state === "SUCCEEDED" ? "ok" : r.state === "FAILED" || r.state === "UNCONFIRMED" ? "fail" : ""}`}
                        />
                        <div>
                          <strong>{r.title}</strong>
                          <small>
                            {r.repository} · {date(r.created_at)} ·{" "}
                            {r.run_id.slice(0, 8)}
                          </small>
                        </div>
                        <span className={`lw-state ${r.state.toLowerCase()}`}>
                          {liveState[r.state] || r.state}
                        </span>
                        <ChevronRight size={15} />
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="lw-empty">
                    <History size={28} />
                    <h3>
                      {(
                        filteredHistory
                          ? historySnapshot.isFetching
                          : history.isFetching
                      )
                        ? "Đang tải lịch sử…"
                        : "Chưa có lượt chạy trong project này"}
                    </h3>
                    <p>
                      Kết nối repo, nhập yêu cầu và bắt đầu tạo kế hoạch. Kết
                      quả sẽ được lưu tại đây.
                    </p>
                  </div>
                )}
                {visible.length > historyLimit && (
                  <button
                    className="wd-more"
                    onClick={() => setHistoryLimit((value) => value + 50)}
                  >
                    Xem thêm · đang hiện {historyLimit}/{visible.length} lượt
                  </button>
                )}
              </section>
            </>
          )}
        </main>
      </div>
      <Dialog open={repoDialog} onOpenChange={setRepoDialog}>
        <DialogContent className="lw-repo-dialog">
          <DialogTitle>Kết nối project với Gitea</DialogTitle>
          <DialogDescription>
            Chọn source hiện có hoặc tạo repo riêng cho sản phẩm mới.
          </DialogDescription>
          <div className="lw-tabs">
            <button
              aria-selected={repoMode === "existing"}
              onClick={() => setRepoMode("existing")}
            >
              Repo hiện có
            </button>
            <button
              aria-selected={repoMode === "new"}
              onClick={() => setRepoMode("new")}
            >
              Tạo repo mới
            </button>
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void action("Đang kết nối repo", async () => {
                const p = await liveWorkflows.connect(
                  repoMode === "existing"
                    ? { repository_id: Number(repository) }
                    : { new_repository_name: repoName.trim() },
                );
                setFormProject(p.project_id);
                if (section !== "requests")
                  setParams({ project: p.project_id });
                setRepoDialog(false);
                setShowNew(section !== "requests");
              });
            }}
          >
            {repoMode === "existing" ? (
              <label>
                Repo
                <select
                  aria-label="Repo"
                  required
                  value={repository}
                  onChange={(e) => setRepository(e.target.value)}
                >
                  <option value="">
                    {repos.isFetching
                      ? "Đang lấy danh sách…"
                      : "Chọn repo Gitea…"}
                  </option>
                  {repos.data?.items.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.full_name}
                      {r.private ? " · riêng tư" : ""}
                    </option>
                  ))}
                </select>
                {repos.error && (
                  <p role="alert" className="lw-alert">
                    {liveError(repos.error)}
                  </p>
                )}
              </label>
            ) : (
              <label>
                Tên repo mới
                <input
                  required
                  pattern="[A-Za-z0-9][A-Za-z0-9_.-]{1,79}"
                  maxLength={80}
                  placeholder="ten-san-pham"
                  value={repoName}
                  onChange={(e) => setRepoName(e.target.value)}
                />
                <small>
                  Repo riêng tư, nhánh main. Yêu cầu tiếp theo sẽ quyết định nội
                  dung sản phẩm.
                </small>
              </label>
            )}
            {error && (
              <p role="alert" className="lw-alert">
                {error}
              </p>
            )}
            <button className="lw-primary" disabled={!!busy} type="submit">
              {busy ||
                (repoMode === "existing"
                  ? "Kết nối repo"
                  : "Tạo & kết nối repo")}
              <ArrowRight size={16} />
            </button>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
