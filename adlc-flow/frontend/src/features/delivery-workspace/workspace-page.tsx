import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronRight,
  Circle,
  Clock3,
  Code2,
  FileCheck2,
  FileText,
  GitBranch,
  LayoutGrid,
  ListChecks,
  LoaderCircle,
  MessageSquare,
  MoreHorizontal,
  Plus,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  WandSparkles,
} from "lucide-react";
import { useContext, useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { AuthContext } from "@/contexts/authContext";
import {
  generateAdlcBlueprint,
  getAdlcHarnessResults,
  getAdlcHarnessSessions,
  respondToAdlcHarnessInteraction,
  submitAdlcHarnessSession,
} from "@/controllers/API/adlc";
import {
  type Delivery,
  deliveryApi,
  deliveryError,
} from "@/controllers/API/delivery";
import { teamProjects } from "@/controllers/API/team-access";
import { listVerifications } from "@/controllers/API/verification";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import ProjectSelector from "@/features/adlc-workspace/project-selector";
import HarnessResults from "@/pages/RunDetailPage/HarnessResults";
import HarnessSessions from "@/pages/RunDetailPage/HarnessSessions";
import { isLiveLoop } from "./kernel-evidence";
import KernelResults from "./kernel-results";
import CyclePanel, { type CycleActions, DraftCycle } from "./cycle-panel";
import CyclePlanning from "./cycle-planning";
import TaskDetails from "./task-details";
import ServiceChecksPanel from "./service-checks";
import ProductLoopPanel from "./product-loop";
import WorkloopPanel from "./workloop";
import LiveWorkspace from "./live-workspace";
import { liveWorkflows } from "@/controllers/API/live-workflows";
import { planSelectionScope } from "./task-plan-model";
import TaskPlanView from "./task-plan-view";
import {
  type BoardTask,
  boardTasks,
  column,
  currentStep,
  label,
  outputSummary,
  ROLE_NAMES,
  STEPS,
  stageName,
  stages,
  time,
} from "./model";
import "./workspace.css";

type Action =
  | "reconcile"
  | "generate"
  | "approve-workflow"
  | "compile"
  | "approve-plan"
  | "start";
type Project = { id: string; name: string };
type ViewProps = {
  embedded?: boolean;
  row: Delivery | null;
  items: Delivery[];
  projects: Project[];
  projectPicker?: (
    selected: string,
    onSelected: (id: string) => void,
  ) => React.ReactNode;
  roles: string[];
  busy?: string;
  error?: string;
  refreshing?: boolean;
  loading?: boolean;
  filter?: "all" | "review" | "results";
  more?: boolean;
  loadingMore?: boolean;
  onMore?: () => void;
  onCreate: (
    title: string,
    requirement: string,
    project: string,
  ) => Promise<void>;
  onAction: (action: Action, frozen: Delivery) => Promise<void>;
  onOpen: (id: string) => void;
  onNew: () => void;
  onRefresh: () => void;
  onNote: (
    kind: Delivery["notes"][number]["kind"],
    value: string,
    command: string,
  ) => Promise<void>;
  onAdvanced: (path: string) => void;
} & CycleActions;
const examples = [
  "Xây ứng dụng quản lý công việc cho nhóm",
  "Thêm đăng nhập và phân quyền cho ứng dụng",
  "Tạo trang quản lý đơn hàng và báo cáo",
];
const icons = [MessageSquare, GitBranch, ListChecks, LayoutGrid, ShieldCheck];

export function DeliveryExperience({
  embedded = false,
  row,
  items,
  projects,
  projectPicker,
  roles,
  busy,
  error,
  refreshing,
  loading,
  filter = "all",
  more,
  loadingMore,
  onMore,
  onCreate,
  onAction,
  onOpen,
  onNew,
  onRefresh,
  onNote,
  onAdvanced,
  onSelectCycle,
  onPrepareCycle,
  onUpdateCycle,
}: ViewProps) {
  const Heading = embedded ? "h2" : "h1";
  const [page, setPage] = useState<number | null>(null);
  const [section, setSection] = useState<"all" | "review" | "results">(filter);
  useEffect(() => setSection(filter), [filter]);
  const [review, setReview] = useState<{
    action: Action;
    row: Delivery;
  } | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [taskSelection, setTaskSelection] = useState<{
    scope: string;
    id: string;
  } | null>(null);
  const [role, setRole] = useState("");
  const availableRoles = roles.filter((key) => key in ROLE_NAMES);
  useEffect(() => {
    setPage(null);
    setTaskSelection(null);
    setReview(null);
  }, [row?.id, row?.cycle?.id]);
  const active = page ?? (row ? (filter === "results" ? 4 : currentStep(row)) : 0);
  const tasks = row ? boardTasks(row) : [];
  const taskScope = row ? planSelectionScope(row) : "";
  const selectedTask =
    taskSelection?.scope === taskScope
      ? tasks.find((task) => task.id === taskSelection.id)
      : undefined;
  const setSelectedTask = (task: BoardTask | null) =>
    setTaskSelection(task ? { scope: taskScope, id: task.id } : null);
  useEffect(() => setTaskSelection(null), [taskScope]);
  const completed = tasks.filter((task) => task.status === "SUCCEEDED").length;
  const disabled = !!busy || !!refreshing || !!error;
  const writable = !!row?.permissions.write && !disabled;
  const configurable =
    writable &&
    !row?.dispatch_plan_id &&
    !row?.run &&
    row?.cycle_capabilities?.edit_workflow !== false;
  const draftCycle =
    !!row?.cycle &&
    !row.cycle.is_initial &&
    (row.cycle.state === "DRAFT" || row.cycle_capabilities?.plan_detailed);
  const staleReview =
    !!review &&
    (!row ||
      review.row.id !== row.id ||
      review.row.cycle?.id !== row.cycle?.id ||
      review.row.revision !== row.revision ||
      review.row.workflow_digest !== row.workflow_digest ||
      review.row.plan_digest !== row.plan_digest);
  const ask = (action: Action) => {
    if (row) {
      setReview({ action, row });
      setConfirmed(false);
    }
  };
  const showItems = items.filter((item) =>
    section === "review"
      ? !item.run && stages(item.workflow).length > 0
      : section === "results"
        ? !!item.run &&
          ["SUCCEEDED", "FAILED", "CANCELLED"].includes(item.run.status)
        : true,
  );
  return (
    <main className="delivery">
      <div className="dw-topline">
        <span>
          <span className="dw-online-dot" /> WORKSPACE
        </span>
        <div className="dw-context">
          <span className="dw-avatar">
            {availableRoles.length
              ? (ROLE_NAMES[role] || ROLE_NAMES[availableRoles[0]])
                  .slice(0, 2)
                  .toUpperCase()
              : "CN"}
          </span>
          <label className="dw-sr" htmlFor="dw-role">
            Vai trò được cấp
          </label>
          <select
            id="dw-role"
            value={
              availableRoles.includes(role)
                ? role
                : availableRoles[0] || "personal"
            }
            onChange={(event) => setRole(event.target.value)}
          >
            {availableRoles.length ? (
              availableRoles.map((key) => (
                <option key={key} value={key}>
                  {ROLE_NAMES[key]}
                </option>
              ))
            ) : (
              <option value="personal">Cá nhân</option>
            )}
          </select>
          <span className="dw-muted dw-role-note">
            Quyền do quản trị viên cấp
          </span>
        </div>
      </div>
      <div className="dw-body">
        <header className="dw-heading">
          <div>
            {row && (
              <button className="dw-link dw-back" onClick={onNew}>
                <ArrowLeft size={14} /> Tất cả công việc
              </button>
            )}
            <p className="dw-eyebrow">
              {row
                ? "CÙNG XÂY DỰNG, TỪNG BƯỚC RÕ RÀNG"
                : "PokeDev / WORKSPACE"}
            </p>
            <Heading>{row?.title || "Bạn muốn xây dựng điều gì?"}</Heading>
            <p className="dw-subtitle">
              {row
                ? "Một nơi để duyệt, theo dõi và kiểm chứng kết quả."
                : "Bắt đầu bằng yêu cầu của team bạn. Cùng PokeDev biến ý tưởng của bạn thành hiện thực, với những vai trò khác nhau ở các chốt chặn quan trọng"}
            </p>
          </div>
          <div className="dw-heading-actions">
            <button
              className="dw-icon-button"
              title="Tải lại dữ liệu"
              aria-label="Tải lại dữ liệu"
              onClick={onRefresh}
              disabled={!!busy}
            >
              <RefreshCw size={16} className={refreshing ? "dw-spin" : ""} />
            </button>
            {row && (
              <span
                className={`dw-pill ${row.run?.status === "SUCCEEDED" ? "dw-success" : ""}`}
              >
                {row.run
                  ? label(row.run.status)
                  : row.plan_approved
                    ? "Sẵn sàng thực hiện"
                    : "Đang chuẩn bị"}
              </span>
            )}
            <button className="dw-button dw-primary" onClick={onNew}>
              <Plus size={16} /> Công việc mới
            </button>
          </div>
        </header>
        {row && (
          <CyclePanel
            row={row}
            disabled={disabled}
            onSelectCycle={onSelectCycle}
            onPrepareCycle={onPrepareCycle}
            onUpdateCycle={onUpdateCycle}
            onAdvanced={onAdvanced}
          />
        )}
        {error && (
          <div role="alert" className="dw-error">
            <ShieldCheck size={17} />
            <div>
              <strong>Thao tác chưa được xác nhận</strong>
              <p>{error}</p>
            </div>
          </div>
        )}
        {busy && (
          <div role="status" className="dw-notice">
            <LoaderCircle size={16} className="dw-spin" />
            {busy}
            <span>Chỉ cập nhật khi backend trả kết quả.</span>
          </div>
        )}
        {row?.dispatch_plan_id && !row.run && !busy && (
          <div role="alert" className="dw-notice">
            Kế hoạch đã được gửi tới bộ điều phối, nhưng chưa có xác nhận lượt
            chạy. Không khởi chạy thêm agent.
            <button
              className="dw-button"
              disabled={!!refreshing || !row.permissions.write}
              onClick={() => void onAction("reconcile", row).catch(() => {})}
            >
              Đối soát lượt chạy
            </button>
          </div>
        )}
        {row?.run?.approval_requests
          ?.filter((item) => item.status === "PENDING")
          .map((approval) => (
            <div
              className="dw-panel dw-notice"
              key={approval.approval_request_id}
            >
              <MessageSquare size={18} />
              <div>
                <strong>{approval.title}</strong>
                <p>{approval.context.summary}</p>
                <button
                  className="dw-button"
                  onClick={() => onAdvanced(`/runs/${row.run!.id}`)}
                >
                  Xem thay đổi & duyệt <ArrowRight size={14} />
                </button>
              </div>
            </div>
          ))}
        {loading ? (
          <div className="dw-empty">
            <LoaderCircle size={25} className="dw-spin" />
            <h2>Đang mở workspace...</h2>
          </div>
        ) : draftCycle && row ? (
          <div className="dw-cycle-draft-layout">
            {row.cycle_capabilities?.plan_detailed ? (
              <CyclePlanning
                row={row}
                disabled={disabled}
                onRefresh={onRefresh}
                onAdvanced={onAdvanced}
              />
            ) : (
              <DraftCycle row={row} />
            )}
            <Notes
              key={row.cycle!.id}
              row={row}
              disabled={!writable}
              onNote={onNote}
            />
          </div>
        ) : (
          <>
            <nav className="dw-steps" aria-label="Các bước phát triển">
              {STEPS.map((name, index) => {
                const Icon = icons[index];
                return (
                  <button
                    key={name}
                    aria-current={active === index ? "step" : undefined}
                    disabled={!row && index > 0}
                    onClick={() => setPage(index)}
                    className={`${active === index ? "is-active" : ""} ${row && currentStep(row) > index ? "is-past" : ""}`}
                  >
                    <span className="dw-step-icon">
                      {row && currentStep(row) > index ? (
                        <Check size={16} />
                      ) : (
                        <Icon size={16} />
                      )}
                    </span>
                    <span>
                      <small>BƯỚC {index + 1}</small>
                      <strong>{name}</strong>
                    </span>
                    {index < 4 && (
                      <ChevronRight className="dw-step-arrow" size={16} />
                    )}
                  </button>
                );
              })}
            </nav>
            {active === 0 && (
              <RequirementForm
                key={`${row?.id || "new"}:${row?.cycle?.id || "initial"}`}
                row={row}
                projects={projects}
                projectPicker={projectPicker}
                disabled={disabled}
                onCreate={onCreate}
                onContinue={() => setPage(1)}
              />
            )}
            {active === 1 && row && (
              <div className="dw-two-col">
                <section className="dw-panel">
                  <PanelHeading
                    icon={GitBranch}
                    eyebrow="LỘ TRÌNH THỰC HIỆN"
                    title="Các giai đoạn của workflow"
                    description="Xem AI sẽ làm gì, theo thứ tự nào và tạo ra đầu ra gì."
                  />
                  <div className="dw-stage-list">
                    {stages(row.workflow).map((stage, index) => (
                      <article key={stage.id} className="dw-stage">
                        <div className="dw-stage-number">
                          {String(index + 1).padStart(2, "0")}
                        </div>
                        <div>
                          <span className="dw-small-tag">
                            {stageName(stage.kind)}
                          </span>
                          <h3>{stage.name}</h3>
                          <p>{stage.objective}</p>
                          <div className="dw-output">
                            <FileCheck2 size={13} /> Đầu ra:{" "}
                            {stage.outputs.join(", ") || "Xem mô tả giai đoạn"}
                          </div>
                        </div>
                      </article>
                    ))}
                    {!stages(row.workflow).length && (
                      <Empty
                        title="Chưa có workflow"
                        description="Chọn tạo workflow từ yêu cầu. Nếu kết nối AI lỗi, dữ liệu sẽ không được thay bằng kết quả mô phỏng."
                        action={
                          <button
                            className="dw-button dw-primary"
                            disabled={!configurable}
                            onClick={() =>
                              void onAction("generate", row).catch(() => {})
                            }
                          >
                            Tạo workflow từ yêu cầu <Sparkles size={15} />
                          </button>
                        }
                      />
                    )}
                  </div>
                  <div className="dw-panel-footer">
                    <span>
                      <ShieldCheck size={14} /> Duyệt workflow chưa khởi chạy
                      agent
                    </span>
                    {row.workflow_approved ? (
                      <button
                        className="dw-button dw-primary"
                        disabled={!configurable}
                        onClick={() =>
                          void onAction("compile", row).catch(() => {})
                        }
                      >
                        Tạo kế hoạch chi tiết <ArrowRight size={15} />
                      </button>
                    ) : (
                      <button
                        className="dw-button dw-primary"
                        disabled={!configurable || !stages(row.workflow).length}
                        onClick={() => ask("approve-workflow")}
                      >
                        Duyệt các giai đoạn <Check size={15} />
                      </button>
                    )}
                  </div>
                </section>
                <aside className="dw-panel dw-side-panel">
                  <span className="dw-eyebrow">ĐẦU VÀO ĐÃ GỬI</span>
                  <h3>Yêu cầu của bạn</h3>
                  <p className="dw-prewrap">{row.requirement}</p>
                  <div className="dw-divider" />
                  <h3>Bạn vẫn là người quyết định</h3>
                  <p>
                    Workflow chỉ mô tả các giai đoạn. Bạn sẽ duyệt danh sách
                    task ở bước tiếp theo, rồi mới cho phép thực thi.
                  </p>
                  <button
                    className="dw-link"
                    onClick={() => onAdvanced(`/flow/${row.flow_id}`)}
                  >
                    Chỉnh sửa workflow nâng cao <ArrowRight size={13} />
                  </button>
                </aside>
              </div>
            )}
            {active === 2 && row && (
              <section className="dw-panel">
                <PanelHeading
                  icon={ListChecks}
                  eyebrow="CHỐT PHẠM VI TRƯỚC KHI CHẠY"
                  title="Kế hoạch công việc"
                  description="Mỗi task có mục tiêu, đầu ra và quan hệ phụ thuộc cụ thể."
                />
                {!row.plan ? (
                  <Empty
                    title="Workflow cần được duyệt trước"
                    description="Sau khi chốt các giai đoạn, hệ thống biên dịch thành task có thể thực thi."
                    action={
                      <button className="dw-button" onClick={() => setPage(1)}>
                        Xem workflow <ArrowRight size={15} />
                      </button>
                    }
                  />
                ) : (
                  <>
                    <div className="dw-plan-summary">
                      <span>
                        <ListChecks size={16} />
                        <strong>{tasks.length}</strong> công việc
                      </span>
                      <span>
                        <GitBranch size={16} />
                        <strong>{stages(row.workflow).length}</strong> giai đoạn
                      </span>
                      <span>
                        <ShieldCheck size={16} />
                        {row.plan_approved
                          ? "Đã được bạn duyệt"
                          : "Chưa được phép thực thi"}
                      </span>
                    </div>
                    {row.plan.validation_errors.length > 0 && (
                      <div className="dw-error">
                        <div>
                          <strong>Kế hoạch chưa thể chạy</strong>
                          {row.plan.validation_errors.map((issue, index) => (
                            <p key={`${issue.code}-${index}`}>
                              {issue.message}
                            </p>
                          ))}
                        </div>
                      </div>
                    )}
                    <TaskPlanView
                      key={taskScope}
                      row={row}
                      tasks={tasks}
                      selectedTaskId={selectedTask?.id}
                      onSelect={setSelectedTask}
                    />
                    <div className="dw-panel-footer">
                      <span>
                        <ShieldCheck size={14} /> Sửa workflow sẽ yêu cầu duyệt
                        lại
                      </span>
                      {row.plan_approved ? (
                        <button
                          className="dw-button dw-primary"
                          disabled={
                            !configurable ||
                            !row.permissions.execute ||
                            !!row.run ||
                            !row.workflow_approved
                          }
                          onClick={() => ask("start")}
                        >
                          Bắt đầu thực hiện <ArrowRight size={15} />
                        </button>
                      ) : (
                        <button
                          className="dw-button dw-primary"
                          disabled={
                            !configurable ||
                            row.plan.validation_status !== "VALID" ||
                            !row.workflow_approved
                          }
                          onClick={() => ask("approve-plan")}
                        >
                          Duyệt kế hoạch này <Check size={15} />
                        </button>
                      )}
                    </div>
                  </>
                )}
                {more && (
                  <button
                    className="dw-button"
                    disabled={loadingMore}
                    onClick={onMore}
                  >
                    {loadingMore ? "Đang tải…" : "Xem thêm công việc"}
                  </button>
                )}
              </section>
            )}
            {active === 3 && row && (
              <>
                <div className="dw-metrics">
                  <Metric
                    title="Công việc hoàn tất"
                    value={`${completed}/${tasks.length}`}
                    icon={CheckCircle2}
                  />
                  <Metric
                    title="Đang thực hiện"
                    value={String(
                      tasks.filter((task) => task.status === "RUNNING").length,
                    )}
                    icon={Activity}
                  />
                  <Metric
                    title="Cần bạn xử lý"
                    value={String(
                      tasks.filter((task) =>
                        ["WAITING_APPROVAL", "FAILED"].includes(task.status),
                      ).length,
                    )}
                    icon={MessageSquare}
                  />
                  <Metric
                    title="Yêu cầu phát sinh"
                    value={String(row.notes.length)}
                    icon={FileText}
                  />
                </div>
                <Timeline tasks={tasks} onSelect={setSelectedTask} />
                <div className="dw-board-layout">
                  <section>
                    <div className="dw-section-heading">
                      <h2>Bảng công việc</h2>
                      <span>
                        <span className="dw-online-dot" /> Trạng thái từ lượt
                        chạy thật
                      </span>
                    </div>
                    <div className="dw-board">
                      {[
                        { key: "todo", title: "Chưa bắt đầu" },
                        { key: "active", title: "Đang thực hiện" },
                        { key: "review", title: "Cần xử lý" },
                        { key: "done", title: "Hoàn tất" },
                      ].map((lane) => (
                        <section
                          key={lane.key}
                          className={`dw-lane dw-lane-${lane.key}`}
                        >
                          <h3>
                            <span className="dw-lane-dot" />
                            {lane.title}
                            <span>
                              {
                                tasks.filter(
                                  (task) => column(task.status) === lane.key,
                                ).length
                              }
                            </span>
                          </h3>
                          {tasks
                            .filter((task) => column(task.status) === lane.key)
                            .map((task) => (
                              <button
                                className="dw-task-card"
                                key={task.id}
                                onClick={() => setSelectedTask(task)}
                              >
                                <span className="dw-small-tag">
                                  {stageName(task.plan?.task_type || "")}
                                </span>
                                <strong>{task.name}</strong>
                                <p>{task.objective}</p>
                                <footer>
                                  <span className="dw-avatar dw-avatar-agent">
                                    <Sparkles size={12} />
                                  </span>
                                  <span>Agent · {label(task.status)}</span>
                                  <MoreHorizontal size={15} />
                                </footer>
                              </button>
                            ))}
                          {!tasks.some(
                            (task) => column(task.status) === lane.key,
                          ) && (
                            <p className="dw-lane-empty">Chưa có công việc</p>
                          )}
                        </section>
                      ))}
                    </div>
                  </section>
                  <Notes row={row} disabled={!writable} onNote={onNote} />
                </div>
                {!row.run && (
                  <div className="dw-notice">
                    <Clock3 size={16} />
                    Bảng đang hiển thị kế hoạch, chưa có lượt chạy.
                    <button className="dw-link" onClick={() => setPage(2)}>
                      Đến bước duyệt kế hoạch <ArrowRight size={14} />
                    </button>
                  </div>
                )}
              </>
            )}
            {active === 4 && row && (
              <Results row={row} onAdvanced={onAdvanced} />
            )}
            {!row && (
              <section className="dw-recent">
                <div className="dw-section-heading">
                  <h2>Tiếp tục công việc</h2>
                  <div
                    className="dw-tabs"
                    role="tablist"
                    aria-label="Lọc công việc"
                  >
                    {[
                      ["all", "Tất cả"],
                      ["review", "Cần duyệt"],
                      ["results", "Có kết quả"],
                    ].map(([value, name]) => (
                      <button
                        key={value}
                        role="tab"
                        aria-selected={section === value}
                        onClick={() => setSection(value as typeof section)}
                      >
                        {name}
                      </button>
                    ))}
                  </div>
                </div>
                {showItems.length ? (
                  <div className="dw-recent-grid">
                    {showItems.map((item) => (
                      <button
                        className="dw-work-card"
                        key={item.id}
                        onClick={() => onOpen(item.id)}
                      >
                        <div>
                          <span className="dw-work-icon">
                            <GitBranch size={19} />
                          </span>
                          <span className="dw-small-tag">
                            {item.run
                              ? label(item.run.status)
                              : item.plan
                                ? "Kế hoạch cần duyệt"
                                : "Đang chuẩn bị"}
                          </span>
                        </div>
                        <h3>{item.title}</h3>
                        <p>{item.requirement}</p>
                        <footer>
                          <span>{time(item.updated_at)}</span>
                          <ArrowRight size={16} />
                        </footer>
                      </button>
                    ))}
                  </div>
                ) : (
                  <p className="dw-recent-empty">
                    {items.length
                      ? "Không có công việc trong mục này."
                      : "Công việc đầu tiên của bạn sẽ xuất hiện ở đây. Mọi tiến độ và kết quả đều được lưu lại."}
                  </p>
                )}
              </section>
            )}
            {row && (
              <details className="dw-advanced">
                <summary>
                  <Code2 size={15} /> Thông tin nâng cao
                </summary>
                <div className="dw-advanced-links">
                  <button
                    className="dw-link"
                    onClick={() => onAdvanced(`/flow/${row.flow_id}`)}
                  >
                    Mở trình chỉnh sửa workflow
                  </button>
                  {row.run && (
                    <button
                      className="dw-link"
                      onClick={() => onAdvanced(`/runs/${row.run!.id}`)}
                    >
                      Xem nhật ký và điều khiển chi tiết
                    </button>
                  )}
                </div>
                <p className="dw-muted">
                  Phạm vi hiện tại: cá nhân. Project dùng chung tiếp tục kiểm
                  tra quyền và duyệt độc lập, không mượn quyền người tạo.
                </p>
                <pre>
                  {JSON.stringify(
                    {
                      workflow_digest: row.workflow_digest,
                      plan_digest: row.plan_digest,
                      revision: row.revision,
                    },
                    null,
                    2,
                  )}
                </pre>
              </details>
            )}
          </>
        )}
      </div>
      <Dialog
        open={!!review}
        onOpenChange={(open) => {
          if (!open && !busy) setReview(null);
        }}
      >
        <DialogContent className="delivery dw-modal">
          <DialogTitle>
            {review?.action === "start"
              ? "Bắt đầu thực hiện kế hoạch?"
              : review?.action === "approve-workflow"
                ? "Duyệt các giai đoạn này?"
                : "Duyệt kế hoạch công việc?"}
          </DialogTitle>
          <DialogDescription>
            {review?.action === "start"
              ? "Agent sẽ thực thi trong phạm vi đã duyệt. Mọi yêu cầu xác nhận và kết quả kiểm thử vẫn phải được xử lý; thao tác này không tự cấp quyền merge/push."
              : "Quyết định chỉ có hiệu lực với đúng nội dung đang xem. Duyệt không đồng nghĩa với đã chạy hoặc đã Verify."}
          </DialogDescription>
          <p className="dw-prewrap">{review?.row.title}</p>
          <label className="dw-consent">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            Tôi đã đọc nội dung và đồng ý với quyết định này.
          </label>
          {staleReview && (
            <p role="alert">
              Nội dung đã đổi. Đóng cửa sổ và kiểm tra lại phiên bản mới.
            </p>
          )}
          {error && <p role="alert">{error}</p>}
          <button
            className="dw-button dw-primary"
            disabled={disabled || !confirmed || staleReview}
            onClick={async () => {
              if (!review) return;
              try {
                await onAction(review.action, review.row);
                setReview(null);
              } catch {
                /* Error remains visible; never assume the action succeeded. */
              }
            }}
          >
            Xác nhận {review?.action === "start" ? "thực hiện" : "phê duyệt"}
            <ArrowRight size={15} />
          </button>
        </DialogContent>
      </Dialog>
      {row && (
        <TaskDetails
          row={row}
          task={selectedTask}
          tasks={tasks}
          onClose={() => setSelectedTask(null)}
          onSelect={setSelectedTask}
          onAdvanced={onAdvanced}
        />
      )}
    </main>
  );
}

function RequirementForm({
  row,
  projects,
  projectPicker,
  disabled,
  onCreate,
  onContinue,
}: {
  row: Delivery | null;
  projects: Project[];
  projectPicker?: ViewProps["projectPicker"];
  disabled: boolean;
  onCreate: ViewProps["onCreate"];
  onContinue: () => void;
}) {
  const [title, setTitle] = useState(row?.title || "");
  const [requirement, setRequirement] = useState(row?.requirement || "");
  const [project, setProject] = useState("");
  return (
    <div className="dw-two-col dw-request-layout">
      <form
        className="dw-panel dw-request"
        onSubmit={(event) => {
          event.preventDefault();
          if (event.target !== event.currentTarget || disabled) return;
          if (!row && (!title.trim() || !requirement.trim())) return;
          if (!row) void onCreate(title, requirement, project);
          else onContinue();
        }}
      >
        <PanelHeading
          icon={WandSparkles}
          eyebrow="BẮT ĐẦU TỪ MỤC TIÊU"
          title={row ? "Yêu cầu đã gửi" : "Mô tả ứng dụng của bạn"}
          description="Mô tả dự án của bạn và những mục tiêu cần đạt được trong dự án đó."
        />
        <label>
          Tên công việc
          <input
            required
            maxLength={200}
            placeholder="Ví dụ: Ứng dụng quản lý công việc"
            value={title}
            readOnly={!!row}
            onChange={(event) => setTitle(event.target.value)}
          />
        </label>
        <label>
          Bạn cần ứng dụng làm được gì?
          <textarea
            required
            rows={7}
            maxLength={20000}
            placeholder={
              "Mô tả người sử dụng, các chức năng cần có và điều kiện để bạn thấy ứng dụng đã đạt yêu cầu.\n\nVí dụ: Một ứng dụng để nhóm 5 người tạo, phân công và theo dõi công việc. Có đăng nhập, lọc theo trạng thái, hạn hoàn thành và một trang báo cáo đơn giản."
            }
            value={requirement}
            readOnly={!!row}
            onChange={(event) => setRequirement(event.target.value)}
          />
        </label>
        {!row && (
          <>
            <div className="dw-example-row">
              Gợi ý bắt đầu
              {examples.map((example) => (
                <button
                  type="button"
                  key={example}
                  onClick={() => {
                    setRequirement(example);
                    if (!title) setTitle(example);
                  }}
                >
                  {example}
                  <Plus size={12} />
                </button>
              ))}
            </div>
            <label>
              Dự án lưu workflow
              <select
                value={project}
                onChange={(event) => setProject(event.target.value)}
              >
                <option value="">Không gian cá nhân mặc định</option>
                {projects.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            {projectPicker?.(project, setProject)}
            <p className="dw-muted">
              Chọn dự án đã liên kết mã nguồn trước khi thực thi. Agent làm việc
              trên bản sao riêng; duyệt kế hoạch không tự cấp quyền push.
            </p>
          </>
        )}
        <div className="dw-request-footer">
          <span>
            <ShieldCheck size={14} /> Bạn duyệt trước khi agent thực thi
          </span>
          <button
            className="dw-button dw-primary"
            type="submit"
            disabled={disabled || !title.trim() || !requirement.trim()}
          >
            {row ? "Xem workflow" : "Tạo workflow từ yêu cầu"}
            <ArrowRight size={16} />
          </button>
        </div>
      </form>
      <aside className="dw-intro">
        <div className="dw-intro-art">
          <div className="dw-art-orbit" />
          <span className="dw-art-center">
            <Sparkles size={31} />
          </span>
          <span className="dw-art-node dw-art-node-a">
            <GitBranch size={21} />
          </span>
          <span className="dw-art-node dw-art-node-b">
            <Code2 size={21} />
          </span>
          <span className="dw-art-node dw-art-node-c">
            <ShieldCheck size={21} />
          </span>
        </div>
        <span className="dw-eyebrow">TỪ Ý TƯỞNG ĐẾN KẾT QUẢ</span>
        <h2>
          Rõ việc cần làm.
          <br />
          Biết kết quả đến đâu.
        </h2>
        <p>AI giúp thực hiện. Bạn và nhóm cùng nắm quyền quyết định.</p>
        <ol>
          {[
            "Xem và duyệt từng giai đoạn",
            "Chốt kế hoạch với task rõ ràng",
            "Theo dõi tiến độ, xử lý phát sinh",
            "Đọc kết quả kèm bằng chứng Verify",
          ].map((line, index) => (
            <li key={line}>
              <span>{index + 1}</span>
              {line}
            </li>
          ))}
        </ol>
        <div className="dw-intro-note">
          <UsersIcon />
          <span>Dành cho cả BA, Developer, Tester và Admin.</span>
        </div>
      </aside>
    </div>
  );
}
function UsersIcon() {
  return (
    <span className="dw-mini-avatars">
      <i>BA</i>
      <i>DEV</i>
      <i>QA</i>
    </span>
  );
}
function PanelHeading({
  icon: Icon,
  eyebrow,
  title,
  description,
}: {
  icon: typeof GitBranch;
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <header className="dw-panel-heading">
      <span className="dw-panel-icon">
        <Icon size={19} />
      </span>
      <div>
        <p className="dw-eyebrow">{eyebrow}</p>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
    </header>
  );
}
function Empty({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="dw-empty">
      <Circle size={26} />
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}
function Metric({
  title,
  value,
  icon: Icon,
}: {
  title: string;
  value: string;
  icon: typeof Activity;
}) {
  return (
    <div className="dw-metric">
      <span>
        {title}
        <Icon size={16} />
      </span>
      <strong>{value}</strong>
    </div>
  );
}
export function Timeline({
  tasks,
  onSelect,
}: {
  tasks: BoardTask[];
  onSelect: (task: BoardTask) => void;
}) {
  const real = tasks.filter((task) => !task.estimated);
  const allReal = tasks.length > 0 && real.length === tasks.length;
  const min = allReal ? Math.min(...real.map((task) => task.start)) : 0;
  const max = allReal
    ? Math.max(min + 1000, ...real.map((task) => task.end))
    : Math.max(4, ...tasks.map((task) => task.order + 1));
  return (
    <section className="dw-panel dw-timeline">
      <div className="dw-section-heading">
        <div>
          <h2>Lịch trình công việc</h2>
          <p>
            {allReal
              ? "Thời gian thực tế từ lượt chạy"
              : "Gantt theo phụ thuộc · mỗi mốc là một lớp công việc, chưa phải cam kết thời gian"}
          </p>
        </div>
        <span className="dw-small-tag">{allReal ? "THỰC TẾ" : "DỰ KIẾN"}</span>
      </div>
      <div className="dw-timeline-scroll">
        <div className="dw-timeline-axis">
          <span>CÔNG VIỆC</span>
          <div>
            {Array.from({ length: 5 }, (_, i) => (
              <span key={i}>
                {allReal
                  ? new Date(min + ((max - min) * i) / 4).toLocaleTimeString(
                      "vi-VN",
                      { hour: "2-digit", minute: "2-digit" },
                    )
                  : `Mốc ${i + 1}`}
              </span>
            ))}
          </div>
        </div>
        {tasks.map((task) => (
          <button
            key={task.id}
            className="dw-timeline-row"
            onClick={() => onSelect(task)}
          >
            <span title={task.name}>
              {task.status === "SUCCEEDED" ? (
                <CheckCircle2 size={13} />
              ) : (
                <Circle size={13} />
              )}
              {task.name}
            </span>
            <div className="dw-timeline-track">
              <span
                className={`dw-gantt-bar dw-gantt-${column(task.status)}`}
                style={{
                  left: `${(allReal ? (task.start - min) / (max - min) : task.order / max) * 100}%`,
                  width: `${Math.max(3, (allReal ? (task.end - task.start) / (max - min) : 1 / max) * 100)}%`,
                }}
              >
                {label(task.status)}
              </span>
            </div>
          </button>
        ))}
      </div>
      {!tasks.length && (
        <p className="dw-muted">
          Task sẽ xuất hiện khi có kế hoạch đã biên dịch.
        </p>
      )}
    </section>
  );
}
function Notes({
  row,
  disabled,
  onNote,
}: {
  row: Delivery;
  disabled: boolean;
  onNote: ViewProps["onNote"];
}) {
  const [value, setValue] = useState("");
  const [kind, setKind] =
    useState<Delivery["notes"][number]["kind"]>("CHANGE_REQUEST");
  const command = useRef<string | null>(null);
  return (
    <aside className="dw-panel dw-notes">
      <div className="dw-section-heading">
        <h2>Trao đổi & phát sinh</h2>
        <MessageSquare size={16} />
      </div>
      <p className="dw-muted">
        Ghi lại để xem xét ở lượt tiếp theo. Không tự sửa phạm vi đang chạy.
      </p>
      <div className="dw-note-list">
        {row.notes.length ? (
          row.notes.map((note) => (
            <article key={note.id}>
              <div>
                <span className="dw-small-tag">
                  {note.kind === "CHANGE_REQUEST"
                    ? "Yêu cầu thay đổi"
                    : note.kind === "QUESTION"
                      ? "Câu hỏi"
                      : "Ghi chú"}
                </span>
                <time>{time(note.created_at)}</time>
              </div>
              <p>{note.text}</p>
              <small>{note.actor_name} · Chưa đưa vào kế hoạch</small>
            </article>
          ))
        ) : (
          <p className="dw-lane-empty">Chưa có yêu cầu phát sinh.</p>
        )}
      </div>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          command.current ||= crypto.randomUUID();
          try {
            await onNote(kind, value, command.current);
            setValue("");
            command.current = null;
          } catch {
            /* Retain text and idempotency key for an explicit retry. */
          }
        }}
      >
        <label className="dw-sr" htmlFor="dw-note-kind">
          Loại trao đổi
        </label>
        <select
          id="dw-note-kind"
          value={kind}
          onChange={(event) => {
            setKind(event.target.value as typeof kind);
            command.current = null;
          }}
        >
          <option value="CHANGE_REQUEST">Yêu cầu thay đổi</option>
          <option value="QUESTION">Câu hỏi</option>
          <option value="NOTE">Ghi chú</option>
        </select>
        <label className="dw-sr" htmlFor="dw-note">
          Nội dung trao đổi
        </label>
        <textarea
          id="dw-note"
          rows={3}
          maxLength={4000}
          placeholder="Việc gì cần được bổ sung hoặc làm rõ?"
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
            command.current = null;
          }}
        />
        <button className="dw-button" disabled={disabled || !value.trim()}>
          Ghi nhận <Plus size={14} />
        </button>
      </form>
    </aside>
  );
}

function Results({
  row,
  onAdvanced,
}: {
  row: Delivery;
  onAdvanced: ViewProps["onAdvanced"];
}) {
  const runId = row.run?.id;
  const reports = useQuery({
    queryKey: ["delivery-verification", row.id, runId],
    queryFn: () => listVerifications({ runId: runId! }),
    enabled: !!runId,
    retry: false,
  });
  const captured = useQuery({
    queryKey: ["delivery-captured-results", row.id, runId],
    queryFn: () => getAdlcHarnessResults(runId!),
    enabled: !!runId,
    retry: false,
  });
  const verified = (reports.isError ? [] : reports.data || []).filter(
    (report) => report.receipt && report.report && report.evidence_digest,
  );
  const passed = verified.filter((report) => report.report?.verdict === "PASS");
  return (
    <div className="dw-results">
      <section className="dw-panel">
        <div
          className={`dw-result-hero ${verified.length && passed.length === verified.length ? "is-verified" : ""}`}
        >
          <span>
            <ShieldCheck size={27} />
          </span>
          <div>
            <p className="dw-eyebrow">BẰNG CHỨNG, KHÔNG CHỈ LÀ BÁO CÁO</p>
            <h2>
              {!runId
                ? "Chưa có kết quả thực thi"
                : reports.isError
                  ? "Chưa đọc được bằng chứng"
                  : !verified.length
                    ? "Chưa có Verify độc lập"
                    : `${passed.length}/${verified.length} báo cáo Verify đạt`}
            </h2>
            <p>
              {!verified.length
                ? "Kiểm thử hệ thống, báo cáo của agent và Verify độc lập được trình bày riêng. Một task hoàn tất không tự chứng nhận toàn bộ ứng dụng."
                : "Kết luận chỉ áp dụng cho phạm vi và candidate của từng báo cáo; không tự chứng nhận toàn bộ ứng dụng."}
            </p>
          </div>
        </div>
        <div className="dw-result-summary">
          <span>
            Lượt chạy
            <strong>{row.run ? label(row.run.status) : "Chưa bắt đầu"}</strong>
          </span>
          <span>
            Task hoàn tất
            <strong>
              {row.run?.tasks.filter((task) => task.status === "SUCCEEDED")
                .length || 0}
              /{row.plan?.tasks.length || 0}
            </strong>
          </span>
          <span>
            Bằng chứng độc lập<strong>{verified.length} báo cáo</strong>
          </span>
        </div>
      </section>
      <WorkloopPanel key={`workloop:${row.id}:${row.cycle?.id}`} deliveryId={row.id} cycleId={row.cycle?.id} canWrite={row.permissions.write && row.permissions.execute} />
      <ServiceChecksPanel key={`${row.id}:${row.cycle?.id}`} deliveryId={row.id} cycleId={row.cycle?.id} canWrite={row.permissions.write} />
      <ProductLoopPanel key={`loop:${row.id}:${row.cycle?.id}`} deliveryId={row.id} cycleId={row.cycle?.id} canWrite={row.permissions.write && row.permissions.execute} />
      {runId &&
        row.run?.tasks
          .filter(isLiveLoop)
          .map((task) => (
            <KernelResults
              key={task.id}
              deliveryId={row.id}
              runId={runId}
              task={task}
              onReview={() => onAdvanced(`/runs/${runId}`)}
            />
          ))}
      {!captured.isError &&
        (captured.data || []).map((entry) => (
          <article className="dw-panel" key={entry.attempt_id}>
            <h3>
              {row.run?.tasks.find((task) => task.id === entry.task_run_id)
                ?.name || "Kết quả công việc"}
            </h3>
            <p className="dw-prewrap">{outputSummary(entry.result.output)}</p>
            {entry.result.error && (
              <p className="dw-error">{entry.result.error.message}</p>
            )}
            <p className="dw-muted">
              Đây là báo cáo của agent, không thay thế Verify độc lập.
            </p>
          </article>
        ))}
      {captured.isError && (
        <p role="alert">
          Chưa đọc được kết quả của agent. Thử tải lại hoặc mở nhật ký chi tiết.
        </p>
      )}
      {!!captured.data?.length && !captured.isError && (
        <details className="dw-panel">
          <summary>Kết quả kỹ thuật nâng cao</summary>
          <HarnessResults
            results={captured.data}
            sessions={[]}
            tasks={row.run?.tasks || []}
          />
        </details>
      )}
      {verified.map((report) => (
        <article className="dw-panel dw-report" key={report.plan.plan_id}>
          <div>
            <span
              className={`dw-pill ${report.report!.verdict === "PASS" ? "dw-success" : "dw-danger"}`}
            >
              {report.report!.verdict === "PASS" ? "Đạt" : "Không đạt"}
            </span>
            <h3>{report.plan.profile_ref}</h3>
          </div>
          <p>Candidate và bộ tiêu chí được khóa theo digest.</p>
          <details>
            <summary>Xem bằng chứng nâng cao</summary>
            <pre className="dw-json">{JSON.stringify(report, null, 2)}</pre>
          </details>
        </article>
      ))}
      {runId && (
        <button
          className="dw-button"
          onClick={() => onAdvanced(`/runs/${runId}`)}
        >
          Mở kết quả, source diff và công cụ Verify <ArrowRight size={15} />
        </button>
      )}
    </div>
  );
}

export default function DeliveryWorkspacePage() {
  const { deliveryId } = useParams();
  return deliveryId ? <LegacyDeliveryWorkspacePage /> : <LiveWorkspace tools={<LegacyDeliveryWorkspacePage embedded />} />;
}

function LegacyDeliveryWorkspacePage({ embedded = false }: { embedded?: boolean }) {
  const { deliveryId } = useParams();
  const navigate = useCustomNavigate();
  const client = useQueryClient();
  const { userData } = useContext(AuthContext);
  const identity = userData?.id || "pending";
  const liveHistory = useQuery({ queryKey: ["live-runs", identity, ""], queryFn: () => liveWorkflows.runs(), enabled: !!userData && embedded, retry: false });
  const liveDeliveries = new Set(liveHistory.data?.items.map((run) => run.delivery_id));
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  const [params, setParams] = useSearchParams();
  const selectedCycle = params.get("cycle_id");
  const toolsProject = params.get("tools_project") || (params.get("view") === "advanced" ? params.get("project_id") || params.get("project") : null);
  const flowDraft = useRef<{ id: string; signature: string } | null>(null);
  const list = useInfiniteQuery({
    queryKey: ["deliveries", identity],
    queryFn: ({ pageParam }) => deliveryApi.list(pageParam),
    initialPageParam: 0,
    getNextPageParam: (last) =>
      last.offset + last.items.length < last.total
        ? last.offset + last.items.length
        : undefined,
    enabled: !!userData,
    retry: false,
  });
  const query = useQuery({
    queryKey: ["delivery", identity, deliveryId, selectedCycle],
    queryFn: () => deliveryApi.get(deliveryId!, selectedCycle),
    enabled: !!userData && !!deliveryId,
    retry: false,
    refetchInterval: 3000,
  });
  const folders = useQuery({
    queryKey: ["delivery-folders", identity],
    queryFn: deliveryApi.folders,
    enabled: !!userData,
    retry: false,
  });
  const team = useQuery({
    queryKey: ["delivery-roles", identity],
    queryFn: teamProjects,
    enabled: !!userData,
    retry: false,
  });
  const row = deliveryId ? query.data || null : null;
  const runId = row?.run?.id;
  const sessions = useQuery({
    queryKey: ["delivery-sessions", identity, runId],
    queryFn: () => getAdlcHarnessSessions(runId!),
    enabled: !!runId,
    retry: false,
    refetchInterval: 4000,
  });
  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ["delivery", identity] }),
      client.invalidateQueries({ queryKey: ["deliveries", identity] }),
      client.invalidateQueries({ queryKey: ["delivery-sessions", identity] }),
      client.invalidateQueries({ queryKey: ["delivery-verification"] }),
      client.invalidateQueries({ queryKey: ["delivery-captured-results"] }),
      client.invalidateQueries({ queryKey: ["delivery-loop-evidence"] }),
    ]);
  };
  const perform = async (
    message: string,
    operation: () => Promise<unknown>,
  ) => {
    if (inFlight.current)
      throw new Error("Another command is awaiting acknowledgement.");
    inFlight.current = true;
    setBusy(message);
    setError("");
    try {
      await operation();
      await refresh();
    } catch (failure) {
      setError(deliveryError(failure));
      await refresh();
      throw failure;
    } finally {
      inFlight.current = false;
      setBusy("");
    }
  };
  const pending = (sessions.data || []).filter(
    (entry) =>
      entry.session.interactions.some(
        (interaction) => interaction.status === "PENDING",
      ) || entry.session.status === "READY_FOR_SUBMISSION",
  );
  return (
    <div className={`dw-route ${embedded ? "dw-embedded" : ""}`}>
      {!embedded && <a className="dw-workspace-back" href={`/work?view=new-project${row?.folder_id ? `&tools_project=${encodeURIComponent(row.folder_id)}` : ""}`}><ArrowLeft size={14} />Về Project mới</a>}
      <DeliveryExperience
        embedded={embedded}
        key={`${deliveryId || "new"}:${selectedCycle || "initial"}`}
        row={row}
        items={(list.data?.pages.flatMap((page) => page.items) || []).filter(item => (!embedded || !liveDeliveries.has(item.id)) && (!toolsProject || item.folder_id === toolsProject))}
        more={!!list.hasNextPage}
        loadingMore={list.isFetchingNextPage}
        onMore={() => void list.fetchNextPage()}
        filter={
          params.get("view") === "review"
            ? "review"
            : params.get("view") === "results"
              ? "results"
              : "all"
        }
        projects={(folders.data || []).filter(
          (folder) =>
            folder.is_owner &&
            team.isSuccess &&
            !team.data?.projects.some(
              (project) => project.project_id === folder.id,
            ),
        )}
        projectPicker={(selected, choose) => (
          <ProjectSelector
            projectId={selected}
            disabled={!!busy}
            label="Chọn thư mục mã nguồn"
            onSelected={async (project) => {
              choose(project.project_id);
              await client.invalidateQueries({
                queryKey: ["delivery-folders", identity],
              });
            }}
          />
        )}
        roles={
          team.data?.projects.find(
            (project) => project.project_id === row?.folder_id,
          )?.roles || []
        }
        busy={busy}
        error={
          error ||
          (query.isError || list.isError
            ? deliveryError(query.error || list.error)
            : undefined)
        }
        refreshing={query.isFetching && !!row}
        loading={deliveryId ? query.isLoading : list.isLoading}
        onRefresh={() => {
          setError("");
          void refresh();
        }}
        onOpen={(id) => navigate(`/work/${id}`)}
        onNew={() => {
          setError("");
          navigate(`/work?view=new-project${toolsProject ? `&tools_project=${encodeURIComponent(toolsProject)}` : ""}`);
        }}
        onAdvanced={navigate}
        onSelectCycle={(id) => {
          setError("");
          setParams((previous) => {
            const next = new URLSearchParams(previous);
            next.set("cycle_id", id);
            return next;
          });
        }}
        onPrepareCycle={async (frozen, goal, command) => {
          await perform("Đang lưu bản nháp chu kỳ mới…", async () => {
            const saved = await deliveryApi.prepareCycle(frozen, goal, command);
            setParams((previous) => {
              const next = new URLSearchParams(previous);
              next.set("cycle_id", saved.cycle_id);
              return next;
            });
          });
        }}
        onUpdateCycle={async (frozen, goal, command) => {
          await perform("Đang lưu phiên bản mục tiêu…", () =>
            deliveryApi.updateCycle(frozen, goal, command),
          );
        }}
        onCreate={async (title, requirement, folder) => {
          try {
            await perform(
              "AI đang xây dựng các giai đoạn từ yêu cầu…",
              async () => {
                const signature = JSON.stringify([title, requirement, folder]);
                if (
                  !flowDraft.current ||
                  flowDraft.current.signature !== signature
                )
                  flowDraft.current = {
                    ...(await deliveryApi.createFlow(
                      title,
                      requirement,
                      folder || null,
                    )),
                    signature,
                  };
                const saved = await deliveryApi.create(
                  flowDraft.current.id,
                  title,
                  requirement,
                );
                navigate(`/work/${saved.id}`);
                await generateAdlcBlueprint(
                  saved.flow_id,
                  requirement,
                  "Trả về workflow thực thi cho yêu cầu này. Tách các giai đoạn rõ ràng; không dùng package MOCK. Có bước kiểm thử, Verify độc lập và chốt phê duyệt trước hành động phát hành. Không tự mở quyền GitHub hoặc dùng repository ngoài phạm vi cấu hình.",
                );
              },
            );
          } catch {
            /* Error shown; retain the saved draft, never generate simulated output. */
          }
        }}
        onAction={async (action, frozen) => {
          await perform(
            action === "generate"
              ? "AI đang xây dựng các giai đoạn…"
              : action === "compile"
                ? "Đang biên dịch kế hoạch công việc…"
                : action === "start"
                  ? "Đang gửi kế hoạch đã duyệt tới bộ điều phối…"
                  : "Đang lưu quyết định của bạn…",
            () =>
              action === "reconcile"
                ? deliveryApi.reconcile(frozen)
                : action === "generate"
                  ? generateAdlcBlueprint(
                      frozen.flow_id,
                      frozen.requirement,
                      "Chỉ dùng package thực thi thật, không MOCK. Bao gồm kiểm thử, Verify và duyệt trước phát hành; không tự mở quyền hoặc đổi repository.",
                    )
                  : action === "approve-workflow"
                    ? deliveryApi.approveWorkflow(frozen)
                    : action === "compile"
                      ? deliveryApi.compile(frozen)
                      : action === "approve-plan"
                        ? deliveryApi.approvePlan(frozen)
                        : deliveryApi.start(frozen),
          );
        }}
        onNote={async (kind, value, command) => {
          if (row)
            await perform("Đang ghi nhận yêu cầu…", () =>
              deliveryApi.note(row, kind, value, command),
            );
        }}
      />
      {row?.run && pending.length > 0 && (
        <fieldset
          className="dw-inline-interactions"
          disabled={
            !!busy ||
            sessions.isFetching ||
            sessions.isError ||
            query.isError ||
            !row.permissions.write
          }
        >
          <h2>Agent cần bạn xác nhận</h2>
          <HarnessSessions
            sessions={pending}
            tasks={row.run.tasks}
            actingOn={busy || undefined}
            canSubmit={() => !busy && !sessions.isError && !sessions.isFetching}
            onRespond={(session, interaction, response) => {
              void perform("Đang gửi câu trả lời…", () =>
                respondToAdlcHarnessInteraction(
                  row.run!.id,
                  session,
                  interaction,
                  response,
                ),
              ).catch(() => {});
            }}
            onSubmit={(session) => {
              void perform("Đang gửi kết quả đã xác nhận…", () =>
                submitAdlcHarnessSession(row.run!.id, session),
              ).catch(() => {});
            }}
          />
        </fieldset>
      )}
    </div>
  );
}
