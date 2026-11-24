import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  BellRing,
  ChevronRight,
  FileText,
  Link2,
  Pause,
  Play,
  RefreshCw,
  Square,
  Workflow,
  X,
} from "lucide-react";
import { useContext, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { AuthContext } from "@/contexts/authContext";
import { SanitizedMarkdown } from "@/components/core/sanitizedMarkdown";
import {
  projectWorkloop,
  type WorkloopJob,
} from "@/controllers/API/project-workloop";
import { liveError, type LiveProject } from "@/controllers/API/live-workflows";
import ExecutionGraph, { WorkJourney } from "./execution-graph";
import { executionState, executionTime } from "./execution-model";
import { HumanInputCard } from "./human-input";
import "./project-workloop.css";

export const workloopState: Record<string, string> = {
  RUNNING: "Đang chạy",
  COMPLETED: "Đã chạy xong",
  FAILED: "Lỗi",
  INTERRUPTED: "Đã ngắt",
  SUSPENDED: "Đã tạm dừng",
  UNKNOWN: "Chưa rõ trạng thái",
};
const eventNames: Record<string, string> = {
  node_started: "Bắt đầu task",
  node_terminal: "Task kết thúc",
  node_done: "Kết quả task",
  node_review_pending: "Cổng duyệt cần quyết định",
  node_review_rejected: "Yêu cầu sửa sau review",
  node_review_exhausted: "Đã hết vòng sửa · cần xem lại",
  approval_requested: "Cần bạn phản hồi",
  approval_answered: "Đã nhận phản hồi",
  run_start: "Bắt đầu lượt chạy",
  run_end: "Kết thúc lượt chạy",
  run_completed: "Chạy xong",
  run_failed: "Lượt chạy lỗi",
  signal_consumed: "Đã nhận lệnh điều khiển",
  run_suspended: "Đã tạm dừng",
  run_interrupted: "Đã ngắt",
};
const actionNames: Record<string, string> = {
  PAUSE: "Tạm dừng",
  STOP: "Dừng",
  RESUME: "Tiếp tục",
  ANSWER: "Phản hồi",
};
const commandNames: Record<string, string> = {
  SENDING: "Đang gửi",
  REQUESTED: "Đã gửi · chờ Workloop xác nhận",
  CONFIRMED: "Đã xác nhận",
  REJECTED: "Không được chấp nhận",
  UNCERTAIN: "Chưa xác nhận · không tự gửi lại",
};
export function workloopHref(project: string, job: string) {
  return "/work?" + new URLSearchParams({ project, workloop_job: job });
}
const forbidden = (error: unknown) =>
  [401, 403, 404].includes(
    (error as { response?: { status?: number } })?.response?.status || 0,
  );

export function WorkspaceWorkloop() {
  const { userData } = useContext(AuthContext);
  const query = useQuery({
    queryKey: ["workloop-attention", userData?.id],
    queryFn: projectWorkloop.attention,
    enabled: !!userData,
    retry: false,
    refetchInterval: 10000,
  });
  const rows = forbidden(query.error) ? [] : query.data?.items || [];
  if (!rows.length && !query.isError) return null;
  return (
    <section className="pw-project">
      <header>
        <div>
          <h3>
            <Workflow size={17} />
            Workloop đã liên kết
          </h3>
          <p>
            {rows.filter((r) => r.state === "RUNNING").length} đang chạy ·{" "}
            {rows.filter((r) => r.state === "COMPLETED").length} đã chạy xong ·{" "}
            {rows.reduce((n, r) => n + r.requests.length, 0)} cần phản hồi
          </p>
        </div>
      </header>
      {(query.isError || query.data?.partial) && (
        <p className="lw-alert">
          Chưa cập nhật được toàn bộ Workloop; trạng thái đã lưu có thể đã cũ.
        </p>
      )}
      <div className="pw-jobs">
        {rows.map((r) => (
          <Link key={r.job_id} to={workloopHref(r.project_id, r.job_id)}>
            <strong>{r.title}</strong>
            <span>{workloopState[r.state]}</span>
            <ChevronRight size={14} />
          </Link>
        ))}
      </div>
    </section>
  );
}

export function WorkloopRunDetail({
  project,
  jobId,
}: {
  project: LiveProject;
  jobId: string;
}) {
  const { userData } = useContext(AuthContext),
    client = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [selected, setSelected] = useState(params.get("task") || ""),
    [tab, setTab] = useState(
      ["reports", "context", "attention"].includes(params.get("tab") || "")
        ? params.get("tab")!
        : "tasks",
    );
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [stopConfirm, setStopConfirm] = useState(false);
  useEffect(() => {
    setSelected(params.get("task") || "");
    const value = params.get("tab") || "tasks";
    setTab(
      ["reports", "context", "attention"].includes(value) ? value : "tasks",
    );
  }, [params.get("tab"), params.get("task")]);
  const intent = useRef<{ key: string; id: string } | null>(null);
  const query = useQuery({
    queryKey: ["project-workloop-job", userData?.id, project.project_id, jobId],
    queryFn: () => projectWorkloop.read(project.project_id, jobId),
    enabled: !!userData,
    retry: false,
    refetchInterval: 3000,
    refetchIntervalInBackground: true,
  });
  const run = forbidden(query.error) ? undefined : query.data;
  const reports = useQuery({
    queryKey: [
      "project-workloop-reports",
      userData?.id,
      project.project_id,
      jobId,
    ],
    queryFn: () => projectWorkloop.reports(project.project_id, jobId),
    enabled: !!run && tab === "reports",
    retry: false,
    staleTime: 30000,
  });
  const selectTask = (id: string) => {
    setSelected(id);
    setParams(
      (old) => {
        const next = new URLSearchParams(old);
        next.set("task", id);
        return next;
      },
      { replace: true },
    );
  };
  const selectTab = (value: string) => {
    setTab(value);
    setParams(
      (old) => {
        const next = new URLSearchParams(old);
        next.set("tab", value);
        return next;
      },
      { replace: true },
    );
  };
  const command = async (
    action: string,
    commandId?: string,
    request?: WorkloopJob["requests"][number],
    response?: Record<string, unknown>,
  ) => {
    if (busy || !run) return;
    const key = `${jobId}:${action}:${request?.request_id || ""}`;
    if (!intent.current || intent.current.key !== key)
      intent.current = { key, id: crypto.randomUUID() };
    setBusy(true);
    setError("");
    try {
      const result = await projectWorkloop.command(project.project_id, jobId, {
        command_id: commandId || intent.current.id,
        action,
        ...(request
          ? {
              request_id: request.request_id,
              source_digest: request.source_digest,
              response,
            }
          : {}),
      });
      if (result.state === "REJECTED") {
        intent.current = null;
        throw new Error(
          "Workloop chưa chấp nhận thao tác. Hãy cập nhật trạng thái và xem lại yêu cầu.",
        );
      }
      if (result.state === "UNCERTAIN" || result.state === "SENDING")
        throw new Error(
          "Chưa xác nhận được thao tác. Hệ thống giữ lệnh để đối soát, không tự gửi lại.",
        );
      intent.current = null;
    } catch (e) {
      setError(
        e instanceof Error && !("response" in e) ? e.message : liveError(e),
      );
      throw e;
    } finally {
      setBusy(false);
      await client.invalidateQueries({
        queryKey: [
          "project-workloop-job",
          userData?.id,
          project.project_id,
          jobId,
        ],
      });
      await client.invalidateQueries({
        queryKey: ["project-workloop", userData?.id, project.project_id],
      });
    }
  };
  if (!run)
    return (
      <section className="lw-panel">
        <p role={query.isError ? "alert" : "status"}>
          {query.isError ? liveError(query.error) : "Đang mở lượt Workloop…"}
        </p>
        <button onClick={() => void query.refetch()}>
          <RefreshCw size={14} />
          Thử lại
        </button>
      </section>
    );
  const tasks = run.tasks || [],
    task =
      tasks.find((t) => t.id === selected) ||
      tasks.find((t) => t.state === "WAITING_INPUT") ||
      tasks.find((t) => t.state === "IN_PROGRESS") ||
      tasks[0];
  const awaiting = run.commands?.some(
    (c) =>
      ["SENDING", "REQUESTED", "UNCERTAIN"].includes(c.state) &&
      c.action !== "ANSWER",
  );
  const stale = run.stale || query.isError;
  return (
    <section className="lw-run pw-run">
      <header className="lw-run-header">
        <div>
          <div className="lw-eyebrow">
            WORKLOOP · {run.workflow} · v{run.version || "?"}
          </div>
          <h2>{run.title}</h2>
          <p>
            {run.repository} · <code>{run.job_id}</code>
          </p>
        </div>
        <span className={`pw-state pw-${run.state.toLowerCase()}`}>
          {workloopState[run.state] || run.state}
        </span>
      </header>
      <WorkJourney
        steps={[
          {
            id: "scope",
            title: "Project",
            detail: "Đã liên kết thủ công",
            state: "done",
            tab: "context",
          },
          {
            id: "workflow",
            title: "Workflow",
            detail: run.topology?.commit
              ? `@${run.topology.commit.slice(0, 8)}`
              : "Thiếu bản nguồn",
            state: run.topology?.state === "pinned" ? "done" : "attention",
            tab: "context",
          },
          {
            id: "execute",
            title: "Thực hiện",
            detail: `${tasks.filter((t) => ["DONE", "DONE_WITH_CONCERNS"].includes(t.state)).length}/${tasks.length} task`,
            state:
              run.state === "COMPLETED"
                ? "done"
                : ["FAILED", "INTERRUPTED"].includes(run.state)
                  ? "attention"
                  : "current",
            tab: "tasks",
          },
          {
            id: "human",
            title: "Phản hồi",
            detail: run.requests.length
              ? `${run.requests.length} yêu cầu đang chờ`
              : "Không có yêu cầu chờ",
            state: run.requests.length ? "attention" : "done",
            tab: "attention",
          },
          {
            id: "reports",
            title: "Báo cáo",
            detail: "Sản phẩm từng task",
            state: run.state === "COMPLETED" ? "current" : "waiting",
            tab: "reports",
          },
          {
            id: "handover",
            title: "Kiểm chứng & bàn giao",
            detail: "Cần đối chiếu bằng chứng",
            state: "waiting",
            tab: "context",
          },
        ]}
        select={selectTab}
      />
      <div className="ej-live" role="status">
        <span>
          <span className={`eg-dot ${stale ? "waiting" : "running"}`} />
          {stale
            ? "Mất kết nối · đang xem dữ liệu đã lưu; điều khiển bị khóa"
            : "Tự cập nhật mỗi 3 giây"}{" "}
          · {executionTime(run.checked_at)} (UTC+7)
        </span>
        <button onClick={() => void query.refetch()}>
          <RefreshCw size={13} />
          Cập nhật
        </button>
      </div>
      <div className="pw-controls">
        <p>
          {run.requests.length
            ? "Agent đang cần bạn phản hồi để tiếp tục."
            : run.state === "COMPLETED"
              ? "Workloop đã chạy xong. Xem báo cáo trước khi xác nhận chất lượng và bàn giao."
              : run.state === "INTERRUPTED"
                ? "Lượt đã ngắt. API hiện chỉ hỗ trợ tiếp tục các lượt đã tạm dừng."
                : "Lệnh tạm dừng và dừng có hiệu lực khi Workloop xử lý tín hiệu."}
        </p>
        <div>
          {run.state === "RUNNING" && (
            <>
              <button
                disabled={busy || stale || awaiting}
                onClick={() => void command("PAUSE").catch(() => {})}
              >
                <Pause size={14} />
                Tạm dừng
              </button>
              <button
                disabled={busy || stale || awaiting}
                onClick={() => setStopConfirm(true)}
              >
                <Square size={14} />
                Dừng
              </button>
            </>
          )}
          {run.state === "SUSPENDED" && (
            <button
              disabled={busy || stale || awaiting}
              onClick={() => void command("RESUME").catch(() => {})}
            >
              <Play size={14} />
              Tiếp tục
            </button>
          )}
        </div>
      </div>
      {stopConfirm && (
        <div className="lw-alert">
          <p>
            Dừng lượt {run.job_id}? Workloop sẽ xử lý tín hiệu; thao tác này
            không tạo lượt mới.
          </p>
          <button
            disabled={busy}
            onClick={() => {
              setStopConfirm(false);
              void command("STOP").catch(() => {});
            }}
          >
            Gửi lệnh dừng
          </button>
          <button onClick={() => setStopConfirm(false)}>Quay lại</button>
        </div>
      )}
      {error && (
        <p role="alert" className="lw-alert">
          {error}
        </p>
      )}
      {run.commands?.slice(0, 3).map((c) => (
        <div className="pw-command" key={c.command_id}>
          {actionNames[c.action]} · {commandNames[c.state]}{" "}
          <small>{executionTime(c.created_at)}</small>
        </div>
      ))}
      {!!run.requests.length && (
        <section className="pw-attention" id="workloop-attention">
          <h3>
            <BellRing size={17} />
            Cần bạn xử lý ({run.requests.length})
          </h3>
          {run.requests.map((request) =>
            request.supported ? (
              <HumanInputCard
                key={request.request_id}
                request={{
                  ...request,
                  can_respond:
                    request.can_respond &&
                    !stale &&
                    !busy &&
                    !run.commands?.some(
                      (c) =>
                        c.request_id === request.request_id &&
                        [
                          "UNCERTAIN",
                          "SENDING",
                          "REQUESTED",
                          "CONFIRMED",
                        ].includes(c.state),
                    ),
                }}
                onAnswer={(response, commandId) =>
                  command("ANSWER", commandId, request, response)
                }
              />
            ) : (
              <p key={request.request_id} className="lw-alert">
                {request.title}. Dạng yêu cầu này chưa có hợp đồng trả lời trên
                web.
              </p>
            ),
          )}
        </section>
      )}
      <nav className="lw-tabs" aria-label="Chi tiết Workloop">
        {[
          ["tasks", "Tiến trình & task"],
          ["reports", "Báo cáo"],
          ["context", "Nguồn & bàn giao"],
        ].map(([id, label]) => (
          <button
            key={id}
            aria-selected={tab === id}
            onClick={() => selectTab(id)}
          >
            {label}
          </button>
        ))}
      </nav>
      {tab === "attention" && !run.requests.length && (
        <p className="lw-panel">Không có yêu cầu đang chờ.</p>
      )}
      {(tab === "tasks" || tab === "attention") && (
        <>
          <div className="lw-task-layout">
            <ExecutionGraph
              tasks={tasks.map((t) => ({
                ...t,
                started_at: t.started_at
                  ? Date.parse(t.started_at) / 1000
                  : undefined,
                completed_at: t.completed_at
                  ? Date.parse(t.completed_at) / 1000
                  : undefined,
              }))}
              edges={run.topology?.edges || []}
              selected={task?.id || ""}
              select={selectTask}
            />
            <aside className="lw-task-detail">
              {task ? (
                <>
                  <small>
                    {task.id} · {task.role}
                  </small>
                  <h3>{task.title}</h3>
                  <p>{executionState[task.state] || task.state}</p>
                  <h4>Thời gian</h4>
                  <p>Bắt đầu: {executionTime(task.started_at)}</p>
                  <p>Kết thúc: {executionTime(task.completed_at)}</p>
                  {task.summary && <p className="lw-alert">{task.summary}</p>}
                  {!!task.attempts?.length && (
                    <p>Vòng thực hiện: {task.attempts.join(", ")}</p>
                  )}
                  {task.brief && (
                    <>
                      <h4>Hướng dẫn task</h4>
                      <p className="pw-pre">{task.brief}</p>
                    </>
                  )}
                  {task.session_id && <small>Session: {task.session_id}</small>}
                  <button onClick={() => selectTab("reports")}>
                    <FileText size={14} />
                    Xem báo cáo task
                  </button>
                </>
              ) : (
                <p>Chưa có task được ghi nhận.</p>
              )}
            </aside>
          </div>
          {run.topology?.state !== "pinned" && (
            <p className="lw-alert">
              Chưa đọc được sơ đồ tại đúng commit của lượt chạy. Các task dưới
              đây lấy từ sự kiện; chưa hiển thị cạnh phụ thuộc để tránh dùng
              nhầm workflow mới hơn.
            </p>
          )}
          <section className="eg-timeline">
            <header>
              <h3>Diễn biến thực hiện</h3>
              <small>Giờ Việt Nam · UTC+7</small>
            </header>
            <ol>
              {[...(run.events || [])].reverse().map((e) => (
                <li key={e.id}>
                  <time>{executionTime(e.at)}</time>
                  <button onClick={() => e.node_id && selectTask(e.node_id)}>
                    <strong>{e.node_id || run.workflow}</strong>
                    <span>
                      {eventNames[e.kind] || e.kind}
                      {e.state
                        ? ` · ${executionState[e.state] || e.state}`
                        : ""}
                    </span>
                  </button>
                </li>
              ))}
            </ol>
          </section>
        </>
      )}
      {tab === "reports" && (
        <div className="pw-reports">
          <p className="lw-muted">
            Báo cáo do agent cung cấp. Trạng thái chạy xong chưa xác nhận kiểm
            thử, PR hoặc triển khai.
          </p>
          <button
            onClick={() => void reports.refetch()}
            disabled={reports.isFetching}
          >
            <RefreshCw size={14} />
            {reports.isFetching ? "Đang đọc báo cáo…" : "Đọc lại báo cáo"}
          </button>
          {reports.isError && (
            <p role="alert" className="lw-alert">
              {liveError(reports.error)}
            </p>
          )}
          {!reports.isFetching &&
            !reports.data?.nodes.length &&
            !reports.isError && (
              <p>Workloop chưa cung cấp báo cáo cho lượt này.</p>
            )}
          {reports.data?.nodes.map((r) => (
            <article key={r.id} className={task?.id === r.id ? "selected" : ""}>
              <h3>
                {r.id} <small>{executionState[r.state] || r.state}</small>
              </h3>
              <SanitizedMarkdown
                chatMessage={r.message || "Chưa có nội dung báo cáo."}
                isEmpty={false}
              />
            </article>
          ))}
        </div>
      )}
      {tab === "context" && (
        <div className="lw-panel">
          <h3>Nguồn thực thi</h3>
          <dl className="pw-context">
            <dt>Project / repo</dt>
            <dd>{run.repository}</dd>
            <dt>Lượt Workloop</dt>
            <dd>{run.job_id}</dd>
            <dt>Workflow</dt>
            <dd>
              {run.workflow} · v{run.version}
            </dd>
            <dt>Commit Factory</dt>
            <dd>
              <code>{run.topology?.commit || "Chưa có"}</code>
            </dd>
          </dl>
          <p>
            Liên kết project do quản trị viên xác nhận. Các job cũ của Workloop
            chưa lưu đủ thông tin repo, tài liệu, nguồn Slack hoặc PR để tự động
            đối chiếu.
          </p>
          <div className="ej-next">
            <ArrowRight size={17} />
            <div>
              <strong>Kiểm chứng và bàn giao có bằng chứng</strong>
              <p>
                Xem báo cáo task để đối chiếu commit, kiểm thử và PR. Có thể tạo
                yêu cầu kế tiếp trong project với workflow hiện tại để đi qua
                luồng kiểm chứng và bàn giao Gitea của PokeDev.
              </p>
            </div>
          </div>
          {run.error && <p className="lw-alert">{run.error}</p>}
        </div>
      )}
    </section>
  );
}

export default function ProjectWorkloop({ project }: { project: LiveProject }) {
  const { userData } = useContext(AuthContext),
    client = useQueryClient();
  const [params, setParams] = useSearchParams(),
    selected = params.get("workloop_job") || "";
  const [linking, setLinking] = useState(false),
    [job, setJob] = useState(""),
    [title, setTitle] = useState(""),
    [confirm, setConfirm] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const jobs = useQuery({
    queryKey: ["project-workloop", userData?.id, project.project_id],
    queryFn: () => projectWorkloop.jobs(project.project_id),
    enabled: !!userData,
    retry: false,
    refetchInterval: selected ? false : 5000,
    refetchIntervalInBackground: true,
  });
  const candidates = useQuery({
    queryKey: ["workloop-candidates", userData?.id, project.project_id],
    queryFn: () => projectWorkloop.candidates(project.project_id),
    enabled: !!userData && linking && !!userData.is_superuser,
    retry: false,
  });
  const rows = forbidden(jobs.error) ? [] : jobs.data?.items || [];
  const count = rows.reduce((n, r) => n + r.requests.length, 0);
  const select = (id: string) =>
    setParams({ project: project.project_id, workloop_job: id });
  const bind = async () => {
    if (busy || !confirm || !job || !title.trim()) return;
    setBusy(true);
    setError("");
    try {
      await projectWorkloop.link(
        project.project_id,
        job,
        title.trim(),
        project.repository,
      );
      await client.invalidateQueries({
        queryKey: ["project-workloop", userData?.id, project.project_id],
      });
      setLinking(false);
      select(job);
    } catch (e) {
      setError(liveError(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="pw-project">
      <header>
        <div>
          <h3>
            <Workflow size={17} />
            Workloop trong project{" "}
            {count > 0 && (
              <span className="pw-count">
                <BellRing size={13} />
                {count} cần phản hồi
              </span>
            )}
          </h3>
          <p>
            Theo dõi lượt từ Workloop cùng công việc của {project.repository}.
          </p>
        </div>
        {userData?.is_superuser && (
          <button onClick={() => setLinking(!linking)}>
            <Link2 size={14} />
            Liên kết lượt Workloop
          </button>
        )}
      </header>
      {jobs.isError && (
        <p role="alert" className="lw-alert">
          {liveError(jobs.error)}
          <button onClick={() => void jobs.refetch()}>Thử lại</button>
        </p>
      )}
      {linking && (
        <div className="pw-link">
          <header>
            <strong>Liên kết lượt đã có</strong>
            <button
              aria-label="Đóng liên kết Workloop"
              onClick={() => setLinking(false)}
            >
              <X size={16} />
            </button>
          </header>
          <p>
            Workloop dùng chung chưa ghi project nguồn. Hãy xác nhận đúng repo
            trước khi liên kết; lượt này sẽ chỉ hiện trong project đã chọn.
          </p>
          {candidates.isError && (
            <p role="alert" className="lw-alert">
              {liveError(candidates.error)}
            </p>
          )}
          <label>
            Lượt Workloop
            <select
              value={job}
              onChange={(e) => {
                setJob(e.target.value);
                const row = candidates.data?.items.find(
                  (r) => r.job_id === e.target.value,
                );
                setTitle(row?.workflow || "");
                setConfirm(false);
              }}
            >
              <option value="">
                {candidates.isFetching ? "Đang tải…" : "Chọn lượt…"}
              </option>
              {candidates.data?.items.map((r) => (
                <option key={r.job_id} value={r.job_id}>
                  {r.workflow} · {r.job_id} · {workloopState[r.state]}
                </option>
              ))}
            </select>
          </label>
          <small>
            Tối đa 100 lượt gần nhất. Nếu không thấy, nhập mã lượt bên dưới.
          </small>
          <label>
            Mã lượt
            <input
              value={job}
              onChange={(e) => {
                setJob(e.target.value);
                setConfirm(false);
              }}
              placeholder="job-…"
            />
          </label>
          <label>
            Tên công việc
            <input
              value={title}
              maxLength={200}
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          <label className="pw-confirm">
            <input
              type="checkbox"
              checked={confirm}
              onChange={(e) => setConfirm(e.target.checked)}
            />
            Tôi xác nhận lượt này thuộc repo {project.repository}.
          </label>
          {error && (
            <p role="alert" className="lw-alert">
              {error}
            </p>
          )}
          <button
            className="lw-primary"
            disabled={busy || !confirm || !job || !title.trim()}
            onClick={() => void bind()}
          >
            {busy ? "Đang liên kết…" : "Liên kết vào project"}
            <ArrowRight size={14} />
          </button>
        </div>
      )}
      {!!rows.length && (
        <div className="pw-jobs">
          {rows.map((r) => (
            <button
              key={r.job_id}
              aria-pressed={selected === r.job_id}
              onClick={() => select(r.job_id)}
            >
              <div>
                <strong>{r.title}</strong>
                <small>
                  {r.workflow} · {r.job_id}
                  {r.stale ? " · dữ liệu cũ" : ""}
                </small>
              </div>
              <span className={`pw-state pw-${r.state.toLowerCase()}`}>
                {workloopState[r.state]}
              </span>
              {!!r.requests.length && (
                <span className="pw-count">
                  {r.requests.length} cần phản hồi
                </span>
              )}
              <ChevronRight size={14} />
            </button>
          ))}
        </div>
      )}
      {!rows.length && !jobs.isFetching && !jobs.isError && (
        <p className="pw-empty">
          Chưa liên kết lượt Workloop. Các yêu cầu tạo tại PokeDev vẫn được
          theo dõi ở lịch sử bên dưới.
        </p>
      )}
      {selected && (
        <WorkloopRunDetail
          key={`${project.project_id}:${selected}`}
          project={project}
          jobId={selected}
        />
      )}
    </section>
  );
}
