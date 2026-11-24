import { translateUi, useUiLocale, formatUiStatus } from "@/i18n/ui";
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  ChevronRight,
  Clock3,
  Code2,
  Database,
  Download,
  FileCode2,
  FileText,
  GitBranch,
  ListChecks,
  LoaderCircle,
  MessageSquare,
  Pause,
  Play,
  Plus,
  ShieldCheck,
  Sparkles,
  Target,
  Users,
  Workflow,
} from "lucide-react";
import { useEffect, useState } from "react";
import type { Dispatch, ReactNode } from "react";
import {
  canApprove,
  checkStatus,
  createPatch,
  formatElapsed,
  pageAvailable,
  REQUEST_EXAMPLES,
  REVIEW_AT,
  ROLE_INFO,
  RUN_LENGTH,
  runEvents,
  taskStatus,
} from "./model";
import type {
  StudioAction,
  StudioPage,
  StudioPlan,
  StudioRole,
  StudioState,
  StudioTask,
  TaskStatus,
} from "./model";
import { useStudio } from "./use-studio";
import { createVanguardReport } from "./vanguard";
import "./studio.css";

type ScreenProps = { state: StudioState; dispatch: Dispatch<StudioAction> };
const STEPS: { page: StudioPage; label: string; icon: typeof Target }[] = [
  {
    page: "request",
    get label() {
      return translateUi("Your request");
    },
    icon: MessageSquare,
  },
  {
    page: "workflow",
    get label() {
      return translateUi("Workflow");
    },
    icon: Workflow,
  },
  {
    page: "plan",
    get label() {
      return translateUi("Review plan");
    },
    icon: ListChecks,
  },
  {
    page: "run",
    get label() {
      return translateUi("Live run");
    },
    icon: Play,
  },
  {
    page: "results",
    get label() {
      return translateUi("Results");
    },
    icon: FileText,
  },
];
const roleName = (role: StudioTask["role"] | "team") =>
  role === "memory"
    ? translateUi("Project memory")
    : role === "team"
      ? translateUi("Team")
      : ROLE_INFO[role].label;
const taskLabel = (status: TaskStatus, paused = false) =>
  status === "completed"
    ? translateUi("Complete")
    : status === "running"
      ? paused
        ? translateUi("Paused")
        : translateUi("Working")
      : translateUi("Waiting");

function Status({
  status,
  children,
}: {
  status: TaskStatus | "review";
  children?: ReactNode;
}) {
  return (
    <span className={"pd-status pd-status-" + status}>
      {status === "completed" ? (
        <Check size={12} />
      ) : (
        <span className="pd-status-dot" />
      )}
      {children || taskLabel(status as TaskStatus)}
    </span>
  );
}
function Avatar({
  role,
  small = false,
}: {
  role: StudioTask["role"];
  small?: boolean;
}) {
  return (
    <span
      className={"pd-avatar" + (small ? " pd-avatar-small" : "")}
      aria-label={roleName(role)}
    >
      {role === "memory" ? (
        <Database size={small ? 13 : 18} />
      ) : (
        ROLE_INFO[role].short
      )}
    </span>
  );
}
function Button({
  children,
  onClick,
  secondary = false,
  disabled = false,
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  secondary?: boolean;
  disabled?: boolean;
  type?: "button" | "submit";
}) {
  return (
    <button
      type={type}
      className={
        "pd-button " + (secondary ? "pd-button-secondary" : "pd-button-primary")
      }
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  );
}
function Heading({
  eyebrow,
  title,
  children,
  action,
}: {
  eyebrow: string;
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="pd-heading-row">
      <div>
        <p className="pd-eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="pd-subtitle">{children}</p>
      </div>
      {action && <div className="pd-heading-action">{action}</div>}
    </div>
  );
}
function Panel({
  title,
  icon: Icon,
  children,
  className = "",
  aside,
}: {
  title: string;
  icon?: typeof Target;
  children: ReactNode;
  className?: string;
  aside?: ReactNode;
}) {
  return (
    <section className={"pd-panel " + className}>
      <div className="pd-panel-heading">
        <h2>
          {Icon && <Icon size={17} />}
          {title}
        </h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

export default function VAIPlatformStudioPage() {
  useUiLocale();
  const { state, dispatch } = useStudio();
  useEffect(() => {
    document.getElementById("pd-main")?.scrollTo(0, 0);
  }, [state.page]);
  useEffect(() => {
    const previous = document.title;
    document.title = "PokeDev · Your team workspace";
    return () => {
      document.title = previous;
    };
  }, []);
  const role = ROLE_INFO[state.role];
  const complete = state.run.status === "completed";
  const progress = Math.round((state.run.elapsed / RUN_LENGTH) * 100);
  return (
    <div className="pd-studio">
      <aside className="pd-sidebar">
        <a
          className="pd-brand"
          href={(import.meta.env.BASE_URL || "/") + "studio/"}
          aria-label={translateUi("PokeDev Studio")}
        >
          <img
            src={(import.meta.env.BASE_URL || "/") + "brand/vai-platform-logo.svg"}
            alt={translateUi("PokeDev")}
          />
          <span>dev team bỏ túi</span>
        </a>
        <button
          type="button"
          className="pd-new-request"
          onClick={() => dispatch({ type: "RESET" })}
        >
          <Plus size={17} /> {translateUi("New request")}
        </button>
        <p className="pd-nav-label">{translateUi("Workspace")}</p>
        <nav aria-label={translateUi("Request journey")} className="pd-nav">
          {STEPS.map(({ page, label, icon: Icon }, index) => {
            const available = pageAvailable(state, page);
            const done =
              page === "request"
                ? !!state.plan
                : page === "workflow"
                  ? !!state.plan && !state.generating
                  : page === "plan"
                    ? state.approved
                    : page === "run"
                      ? complete
                      : false;
            return (
              <button
                key={page}
                type="button"
                disabled={!available}
                className={state.page === page ? "active" : ""}
                aria-current={state.page === page ? "step" : undefined}
                aria-label={label}
                title={label}
                onClick={() => dispatch({ type: "PAGE", page })}
              >
                <Icon size={18} />
                <span>{label}</span>
                {done ? (
                  <Check size={14} className="pd-nav-check" />
                ) : (
                  <span className="pd-nav-number">{index + 1}</span>
                )}
              </button>
            );
          })}
        </nav>
        {state.plan && (
          <div className="pd-sidebar-run">
            <div className="pd-sidebar-run-label">
              <GitBranch size={14} /> {translateUi("Current work")}
            </div>
            <strong>{state.plan.title}</strong>
            {state.run.status !== "idle" && (
              <>
                <div className="pd-mini-progress">
                  <span style={{ width: progress + "%" }} />
                </div>
                <span className="pd-sidebar-progress">
                  {complete
                    ? translateUi("Ready to hand over")
                    : progress + "% · " + formatUiStatus(state.run.status)}
                </span>
              </>
            )}
          </div>
        )}
        <div className="pd-sidebar-bottom">
          <div className="pd-project-icon">
            <GitBranch size={18} />
          </div>
          <div>
            <strong>
              {/vanguard|list-paginated|r3xx/i.test(state.request)
                ? translateUi("Vanguard workspace")
                : translateUi("Commerce workspace")}
            </strong>
            <span>{translateUi("Project context connected")}</span>
          </div>
        </div>
      </aside>
      <div className="pd-workspace">
        <header className="pd-topbar">
          <div className="pd-breadcrumb">
            <span>{translateUi("Workspace")}</span>
            <ChevronRight size={14} />
            <strong>{STEPS.find((s) => s.page === state.page)?.label}</strong>
          </div>
          <div className="pd-role-picker">
            <Avatar role={state.role} />
            <div>
              <label htmlFor="pd-role">{translateUi("Your role")}</label>
              <select
                id="pd-role"
                aria-label={translateUi("Your role")}
                value={state.role}
                onChange={(e) =>
                  dispatch({ type: "ROLE", role: e.target.value as StudioRole })
                }
              >
                {Object.entries(ROLE_INFO).map(([key, value]) => (
                  <option key={key} value={key}>
                    {value.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </header>
        <main className="pd-main" id="pd-main">
          <div className="pd-role-context">
            <span className="pd-role-context-marker" />
            <strong>
              {translateUi("{{role}} view", { role: role.label })}
            </strong>
            <span>{role.description}</span>
          </div>
          {state.page === "request" && (
            <RequestScreen state={state} dispatch={dispatch} />
          )}
          {state.page === "workflow" && (
            <WorkflowScreen state={state} dispatch={dispatch} />
          )}
          {state.page === "plan" && (
            <PlanScreen state={state} dispatch={dispatch} />
          )}
          {state.page === "run" && (
            <RunScreen state={state} dispatch={dispatch} />
          )}
          {state.page === "results" && (
            <ResultsScreen key={state.role} state={state} />
          )}
        </main>
      </div>
    </div>
  );
}

function RequestScreen({ state, dispatch }: ScreenProps) {
  useUiLocale();
  const [error, setError] = useState("");
  const active = state.run.status !== "idle";
  return (
    <div className="pd-request-screen">
      <Heading
        eyebrow={translateUi("YOUR TEAM, ONE WORKSPACE")}
        title={translateUi("What do you want to build?")}
      >
        {translateUi(
          "Describe the outcome. Your team will turn it into a workflow you can review and follow.",
        )}
      </Heading>
      <section className="pd-request-card">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (state.request.trim().length < 12) {
              setError(
                translateUi(
                  "Add a little more detail so the team has a clear outcome.",
                ),
              );
              return;
            }
            dispatch({ type: "GENERATE" });
          }}
        >
          <label htmlFor="pd-request">
            {translateUi("Describe your request")}
          </label>
          <textarea
            id="pd-request"
            value={state.request}
            maxLength={1200}
            readOnly={active}
            placeholder={translateUi(
              "For example: build a Vanguard rule that detects list APIs without pagination, with reviewed criteria and a check report…",
            )}
            onChange={(e) => {
              setError("");
              dispatch({ type: "REQUEST", text: e.target.value });
            }}
            aria-describedby={error ? "pd-request-error" : "pd-request-hint"}
            aria-invalid={!!error}
          />
          {error ? (
            <p id="pd-request-error" className="pd-input-error" role="alert">
              {error}
            </p>
          ) : (
            <p id="pd-request-hint" className="pd-field-hint">
              {translateUi(
                "An outcome, who it is for, and any rules the team should follow.",
              )}
            </p>
          )}
          <div className="pd-examples">
            <span>{translateUi("Try a request")}</span>
            {REQUEST_EXAMPLES.map((example) => (
              <button
                type="button"
                key={example.label}
                disabled={active}
                onClick={() => {
                  setError("");
                  dispatch({ type: "REQUEST", text: example.text });
                }}
              >
                {example.label}
                <ArrowUpRight size={13} />
              </button>
            ))}
          </div>
          <div className="pd-request-footer">
            <span>
              <GitBranch size={16} />{" "}
              {/vanguard|list-paginated|r3xx/i.test(state.request)
                ? translateUi("Vanguard workspace")
                : translateUi("Commerce workspace")}{" "}
              <span className="pd-dot-separator">·</span>{" "}
              {translateUi("Changes stay in a separate workspace")}
            </span>
            <Button type="submit" disabled={active}>
              <Sparkles size={17} /> {translateUi("Generate workflow")}
            </Button>
          </div>
        </form>
      </section>
      <div className="pd-value-grid">
        <div>
          <span className="pd-value-icon">
            <Users size={21} />
          </span>
          <h2>{translateUi("A team with clear roles")}</h2>
          <p>
            {translateUi(
              "Analysis, development, and testing work towards one outcome.",
            )}
          </p>
        </div>
        <div>
          <span className="pd-value-icon">
            <ShieldCheck size={21} />
          </span>
          <h2>{translateUi("You keep the decisions")}</h2>
          <p>
            {translateUi(
              "Approve the plan, guide the team, and review the handoff.",
            )}
          </p>
        </div>
        <div>
          <span className="pd-value-icon">
            <FileText size={21} />
          </span>
          <h2>{translateUi("Results you can inspect")}</h2>
          <p>
            {translateUi(
              "Changes, checks, and project knowledge in one place.",
            )}
          </p>
        </div>
      </div>
    </div>
  );
}

function FlowGraph({
  state,
  selected,
  onSelect,
}: {
  state: StudioState;
  selected: string;
  onSelect: (id: string) => void;
}) {
  useUiLocale();
  const plan = state.plan!;
  const vanguard = plan.scenario === "vanguard";
  const positions = [
    {
      id: "scope",
      x: 0,
      y: 83,
      label: translateUi("Scope & criteria"),
      role: "analyst",
    },
    {
      id: "service",
      x: 176,
      y: 18,
      label: vanguard ? "Pagination rule" : "Feature logic",
      role: "developer",
    },
    {
      id: "interface",
      x: 176,
      y: 139,
      label: vanguard ? "Good/bad corpus" : "User experience",
      role: vanguard ? "tester" : "developer",
    },
    {
      id: "tests",
      x: 356,
      y: 83,
      label: translateUi("Testing"),
      role: "tester",
    },
    {
      id: "review",
      x: 535,
      y: 83,
      label: translateUi("Review"),
      role: "developer",
    },
    {
      id: "approval",
      x: 714,
      y: 83,
      label: translateUi("Your approval"),
      role: "analyst",
    },
    {
      id: "memory",
      x: 894,
      y: 83,
      label: translateUi("Project memory"),
      role: "memory",
    },
  ] as const;
  return (
    <div className="pd-flow" aria-label={translateUi("Workflow graph")}>
      <svg
        className="pd-flow-lines"
        viewBox="0 0 1040 260"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <defs>
          <marker
            id="pd-arrow"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="5"
            markerHeight="5"
            orient="auto"
          >
            <path d="M0 0L10 5L0 10Z" />
          </marker>
        </defs>
        {[
          "M146 130H162V65H174",
          "M162 130V186H174",
          "M322 65H341V130H354",
          "M322 186H341V130",
          "M502 130H533",
          "M681 130H712",
          "M860 130H892",
        ].map((d) => (
          <path key={d} d={d} markerEnd="url(#pd-arrow)" />
        ))}
      </svg>
      {positions.map((position) => {
        const task = plan.tasks.find((t) => t.id === position.id);
        const status =
          position.id === "approval"
            ? state.run.handoffApproved
              ? "completed"
              : state.run.status === "review"
                ? "review"
                : "queued"
            : taskStatus(task!, state.run);
        return (
          <button
            type="button"
            key={position.id}
            className={
              "pd-flow-node pd-flow-" +
              status +
              (selected === position.id ? " selected" : "")
            }
            style={{
              left: (position.x / 1040) * 100 + "%",
              top: (position.y / 260) * 100 + "%",
              width: (146 / 1040) * 100 + "%",
            }}
            onClick={() => onSelect(position.id)}
            aria-pressed={selected === position.id}
          >
            <div className="pd-flow-owner">
              {position.role === "memory" ? (
                <Database size={13} />
              ) : position.id === "approval" ? (
                <ShieldCheck size={13} />
              ) : (
                <Avatar role={position.role} small />
              )}
              <span>
                {position.id === "approval"
                  ? translateUi("Decision")
                  : position.role === "analyst"
                    ? translateUi("Analyst")
                    : position.role === "memory"
                      ? translateUi("Knowledge")
                      : roleName(position.role)}
              </span>
              {status === "completed" && <Check size={14} />}
            </div>
            <strong>{position.label}</strong>
            <span className="pd-flow-state">
              {status === "review"
                ? translateUi("Needs you")
                : state.run.status === "idle"
                  ? position.id === "approval"
                    ? translateUi("Approval gate")
                    : translateUi("Planned")
                  : taskLabel(
                      status as TaskStatus,
                      state.run.status === "paused",
                    )}
            </span>
          </button>
        );
      })}
      <span className="pd-flow-parallel">
        {translateUi("These tasks can run together")}
      </span>
    </div>
  );
}

function WorkflowScreen({ state, dispatch }: ScreenProps) {
  useUiLocale();
  const [selected, setSelected] = useState("scope");
  const plan = state.plan!;
  const task = plan.tasks.find((t) => t.id === selected);
  if (state.generating)
    return (
      <div className="pd-generation" role="status">
        <div className="pd-generation-symbol">
          <Workflow size={34} />
        </div>
        <p className="pd-eyebrow">{translateUi("BUILDING YOUR WORKFLOW")}</p>
        <h1>{translateUi("Turning your request into a team plan")}</h1>
        <p>
          {translateUi("Connecting the outcome, tasks, and review points.")}
        </p>
        <div className="pd-generation-steps">
          <span>
            <Check size={16} /> {translateUi("Reading your request")}
          </span>
          <span>
            <LoaderCircle size={16} className="pd-spin" />{" "}
            {translateUi("Mapping tasks and dependencies")}
          </span>
          <span>{translateUi("Assigning the right roles")}</span>
        </div>
      </div>
    );
  return (
    <>
      <Heading eyebrow={translateUi("01 / WORKFLOW")} title={plan.title}>
        {translateUi(
          "A connected path from your request to a reviewed handoff.",
        )}
      </Heading>
      <div className="pd-work-summary">
        <span>
          <ListChecks size={16} />
          {translateUi("6 proposed tasks")}
        </span>
        <span>
          <Users size={16} />
          {translateUi("3 specialist roles")}
        </span>
        <span>
          <ShieldCheck size={16} />
          {translateUi("2 approval points")}
        </span>
        <span>
          <GitBranch size={16} />
          {plan.scenario === "vanguard"
            ? translateUi("Rule + corpus in parallel")
            : translateUi("Parallel development")}
        </span>
      </div>
      <Panel
        title={translateUi("The proposed workflow")}
        icon={Workflow}
        aside={
          <span className="pd-panel-note">
            {translateUi("Select a step to explore it")}
          </span>
        }
      >
        <FlowGraph state={state} selected={selected} onSelect={setSelected} />
        <div className="pd-step-explainer">
          <span className="pd-explainer-icon">
            {selected === "approval" ? (
              <ShieldCheck size={22} />
            ) : (
              <Target size={22} />
            )}
          </span>
          <div>
            <h3>{task?.title || translateUi("You approve the handoff")}</h3>
            <p>
              {task?.description ||
                translateUi(
                  "Review the changes and check report before the team saves the handoff.",
                )}
            </p>
          </div>
          <span className="pd-output-label">
            {task?.output || translateUi("Approval decision")}
          </span>
        </div>
      </Panel>
      <div className="pd-two-column pd-workflow-context">
        <Panel
          title={translateUi("What the team will work from")}
          icon={MessageSquare}
        >
          <p className="pd-request-quote">{plan.requirement}</p>
        </Panel>
        <Panel title={translateUi("Your team")} icon={Users}>
          <div className="pd-team-list">
            {(["analyst", "developer", "tester"] as const).map((role) => (
              <div key={role}>
                <Avatar role={role} />
                <div>
                  <strong>{ROLE_INFO[role].label}</strong>
                  <span>
                    {role === "analyst"
                      ? translateUi("Scope and acceptance criteria")
                      : role === "developer"
                        ? translateUi("Implementation and review")
                        : translateUi("Behaviour and edge cases")}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </div>
      <div className="pd-bottom-actions">
        <p>
          <ShieldCheck size={16} />
          {translateUi("The team starts after you approve the plan.")}
        </p>
        <Button onClick={() => dispatch({ type: "PAGE", page: "plan" })}>
          {translateUi("Review proposed tasks")}
          <ArrowRight size={17} />
        </Button>
      </div>
    </>
  );
}

function Criteria({
  state,
  dispatch,
  editable = false,
}: ScreenProps & { editable?: boolean }) {
  return (
    <div className="pd-criteria">
      {state
        .plan!.criteria.filter((c) => editable || c.included)
        .map((criterion) =>
          editable ? (
            <label key={criterion.id} className="pd-criterion">
              <input
                type="checkbox"
                checked={criterion.included}
                onChange={() =>
                  dispatch({ type: "CRITERION", id: criterion.id })
                }
              />
              <span>{criterion.label}</span>
            </label>
          ) : (
            <div key={criterion.id} className="pd-criterion">
              <span
                className={
                  "pd-check-circle" +
                  (state.run.elapsed >= REVIEW_AT ? " done" : "")
                }
              >
                {state.run.elapsed >= REVIEW_AT ? (
                  <Check size={12} />
                ) : (
                  <span />
                )}
              </span>
              <span>{criterion.label}</span>
            </div>
          ),
        )}
    </div>
  );
}

function TaskList({
  state,
  filter,
}: {
  state: StudioState;
  filter?: StudioTask["role"];
}) {
  useUiLocale();
  const plan = state.plan!;
  return (
    <div className="pd-task-list">
      {plan.tasks
        .filter((task) => !filter || task.role === filter)
        .map((task, index) => {
          const status = taskStatus(task, state.run);
          return (
            <div className="pd-task-row" key={task.id}>
              <span
                className={
                  "pd-task-number " + (status === "completed" ? "done" : "")
                }
              >
                {status === "completed" ? (
                  <Check size={14} />
                ) : (
                  String(index + 1).padStart(2, "0")
                )}
              </span>
              <div className="pd-task-description">
                <strong>{task.title}</strong>
                <p>
                  {state.run.status === "idle"
                    ? task.output
                    : status === "completed"
                      ? task.output + " ready"
                      : status === "running"
                        ? task.description
                        : translateUi("After ") +
                          (task.dependencies
                            .map(
                              (id) =>
                                plan.tasks.find((t) => t.id === id)?.title,
                            )
                            .join(" + ") || translateUi("plan approval"))}
                </p>
                <span className="pd-task-owner">
                  <Avatar role={task.role} small />
                  {roleName(task.role)}
                </span>
              </div>
              {state.run.status !== "idle" && (
                <Status status={status}>
                  {taskLabel(status, state.run.status === "paused")}
                </Status>
              )}
            </div>
          );
        })}
    </div>
  );
}

function PlanScreen({ state, dispatch }: ScreenProps) {
  useUiLocale();
  const [criterion, setCriterion] = useState("");
  const owner = canApprove(state.role);
  const idle = state.run.status === "idle";
  return (
    <>
      <Heading
        eyebrow={translateUi("02 / REVIEW PLAN")}
        title={translateUi("A clear plan before the team starts")}
      >
        {translateUi(
          "Review the tasks, agree on the outcome, and give the team a defined scope.",
        )}
      </Heading>
      <div className="pd-plan-banner">
        <GitBranch size={18} />
        <div>
          <strong>{state.plan!.title}</strong>
          <span>
            {translateUi(
              "Plan v1 · 6 tasks · Separate workspace · Final approval required",
            )}
          </span>
        </div>
        {state.approved && (
          <Status status="completed">{translateUi("Plan approved")}</Status>
        )}
      </div>
      <div className="pd-plan-grid">
        <Panel title={translateUi("Proposed tasks")} icon={ListChecks}>
          <TaskList state={state} />
        </Panel>
        <div className="pd-stack">
          <Panel
            title={
              state.role === "tester"
                ? translateUi("Coverage to verify")
                : state.role === "developer"
                  ? translateUi("Implementation scope")
                  : translateUi("Acceptance criteria")
            }
            icon={
              state.role === "tester"
                ? ShieldCheck
                : state.role === "developer"
                  ? Code2
                  : Target
            }
          >
            {state.role === "developer" ? (
              <div className="pd-file-list">
                {state.plan!.files.map((file) => (
                  <div key={file.path}>
                    <FileCode2 size={16} />
                    <div>
                      <strong>{file.path}</strong>
                      <p>{file.purpose}</p>
                    </div>
                  </div>
                ))}
              </div>
            ) : state.role === "tester" ? (
              <CheckReport state={state} />
            ) : (
              <>
                <Criteria
                  state={state}
                  dispatch={dispatch}
                  editable={owner && idle}
                />
                {owner && idle && state.plan!.criteria.length < 8 && (
                  <form
                    className="pd-add-criterion"
                    onSubmit={(e) => {
                      e.preventDefault();
                      dispatch({ type: "ADD_CRITERION", text: criterion });
                      setCriterion("");
                    }}
                  >
                    <input
                      aria-label={translateUi("Add acceptance criterion")}
                      placeholder={translateUi("Add a criterion…")}
                      maxLength={180}
                      value={criterion}
                      onChange={(e) => setCriterion(e.target.value)}
                    />
                    <button
                      type="submit"
                      aria-label={translateUi("Add criterion")}
                      disabled={!criterion.trim()}
                    >
                      <Plus size={17} />
                    </button>
                  </form>
                )}
              </>
            )}
          </Panel>
          <Panel title={translateUi("The boundaries")} icon={ShieldCheck}>
            <ul className="pd-scope-list">
              {state.plan!.scope.map((scope) => (
                <li key={scope}>
                  <Check size={14} />
                  {scope}
                </li>
              ))}
              <li>
                <ShieldCheck size={14} />
                {translateUi("Review changes before merging")}
              </li>
            </ul>
          </Panel>
        </div>
      </div>
      <div className="pd-bottom-actions">
        <p>
          <ShieldCheck size={16} />
          {state.approved
            ? translateUi("Approved by ") +
              ROLE_INFO[state.approvedBy!].label +
              ". Ready for the team."
            : translateUi("Approval is required before execution.")}
        </p>
        {!idle ? (
          <Button onClick={() => dispatch({ type: "PAGE", page: "run" })}>
            {translateUi("Open run")}
            <ArrowRight size={17} />
          </Button>
        ) : !owner ? (
          <Button
            secondary
            onClick={() => dispatch({ type: "ROLE", role: "analyst" })}
          >
            {translateUi("Review as Business Analyst")}
            <ArrowRight size={16} />
          </Button>
        ) : state.approved ? (
          <Button onClick={() => dispatch({ type: "START" })}>
            <Play size={17} />
            {translateUi("Run workflow")}
          </Button>
        ) : (
          <Button
            onClick={() => dispatch({ type: "APPROVE_PLAN" })}
            disabled={!state.plan!.criteria.some((c) => c.included)}
          >
            <Check size={17} />
            {translateUi("Approve plan")}
          </Button>
        )}
      </div>
    </>
  );
}

function CheckReport({ state }: { state: StudioState }) {
  useUiLocale();
  return (
    <div className="pd-check-report">
      {state.plan!.checks.map((check, index) => {
        const status =
          state.run.status === "idle"
            ? "queued"
            : checkStatus(index, state.run.elapsed);
        return (
          <div key={check}>
            <span
              className={
                "pd-check-circle " + (status === "completed" ? "done" : "")
              }
            >
              {status === "completed" ? (
                <Check size={12} />
              ) : status === "running" ? (
                <LoaderCircle
                  size={12}
                  className={state.run.status === "paused" ? "" : "pd-spin"}
                />
              ) : (
                <span />
              )}
            </span>
            <span>{check}</span>
            <span className={"pd-check-word " + status}>
              {status === "completed"
                ? translateUi("Passed")
                : status === "running"
                  ? state.run.status === "paused"
                    ? translateUi("Paused")
                    : translateUi("Checking")
                  : translateUi("Not run")}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function DecisionCard({ state, dispatch }: ScreenProps) {
  useUiLocale();
  const [answer, setAnswer] = useState(state.plan!.question.options[0]);
  if (state.run.status === "waiting")
    return (
      <section
        className="pd-decision"
        aria-label={translateUi("Team question")}
      >
        <div className="pd-decision-icon">
          <MessageSquare size={22} />
        </div>
        <div className="pd-decision-body">
          <p className="pd-eyebrow">
            {translateUi("THE TEAM NEEDS YOUR INPUT")}
          </p>
          <h2>{state.plan!.question.title}</h2>
          <p>{state.plan!.question.detail}</p>
          <div className="pd-answer-options">
            {state.plan!.question.options.map((option) => (
              <label key={translateUi(option)}>
                <input
                  type="radio"
                  name="team-answer"
                  value={translateUi(option)}
                  checked={answer === option}
                  onChange={() => setAnswer(option)}
                />
                {translateUi(option)}
              </label>
            ))}
          </div>
        </div>
        <Button onClick={() => dispatch({ type: "ANSWER", answer })}>
          {translateUi("Confirm and continue")}
          <ArrowRight size={16} />
        </Button>
      </section>
    );
  if (state.run.status === "review")
    return (
      <section
        className="pd-decision"
        aria-label={translateUi("Handoff approval")}
      >
        <div className="pd-decision-icon">
          <ShieldCheck size={22} />
        </div>
        <div className="pd-decision-body">
          <p className="pd-eyebrow">{translateUi("READY FOR YOUR DECISION")}</p>
          <h2>{translateUi("The complete change is ready to review")}</h2>
          <p>
            {state.plan!.files.length} {translateUi("changed files ·")}{" "}
            {state.plan!.checks.length}{" "}
            {translateUi("checks passed · Acceptance criteria reviewed")}
          </p>
          <details className="pd-handoff-preview">
            <summary>
              {translateUi("Inspect the handoff before approving")}
            </summary>
            <div className="pd-handoff-files">
              {state.plan!.files.map((file) => (
                <div key={file.path}>
                  <FileCode2 size={14} />
                  <strong>{file.path}</strong>
                  <span>{file.purpose}</span>
                </div>
              ))}
            </div>
            <p>
              <strong>{translateUi("Team decision:")}</strong>{" "}
              {state.run.answer}
            </p>
            <p>
              <strong>{translateUi("Review:")}</strong>{" "}
              {translateUi(
                "The changes stay within the agreed scope. The handoff includes changes, check results, and notes.",
              )}
            </p>
            <Button
              secondary
              onClick={() =>
                download("changes.diff", createPatch(state.plan!), "text/plain")
              }
            >
              <Download size={15} />
              {translateUi("Download changes")}
            </Button>
          </details>
        </div>
        {canApprove(state.role) ? (
          <Button onClick={() => dispatch({ type: "APPROVE_HANDOFF" })}>
            <Check size={17} />
            {translateUi("Approve handoff")}
          </Button>
        ) : (
          <Button
            secondary
            onClick={() => dispatch({ type: "ROLE", role: "analyst" })}
          >
            {translateUi("Switch to Business Analyst")}
            <ArrowRight size={16} />
          </Button>
        )}
      </section>
    );
  return null;
}

function RoleRunPanel({ state, dispatch }: ScreenProps) {
  useUiLocale();
  if (state.role === "tester")
    return (
      <Panel
        title={translateUi("Live check results")}
        icon={ShieldCheck}
        aside={
          <span className="pd-panel-note">
            {
              state.plan!.checks.filter(
                (_, i) => checkStatus(i, state.run.elapsed) === "completed",
              ).length
            }{" "}
            / {state.plan!.checks.length} passed
          </span>
        }
      >
        <CheckReport state={state} />
        <div className="pd-panel-footer">
          {translateUi("Each result stays linked to the handoff.")}
        </div>
      </Panel>
    );
  if (state.role === "developer")
    return (
      <Panel title={translateUi("Your implementation tasks")} icon={Code2}>
        <TaskList state={state} filter="developer" />
        <div className="pd-panel-footer">
          <FileCode2 size={15} />
          {translateUi("Changes will be available with the handoff.")}
        </div>
      </Panel>
    );
  if (state.role === "lead")
    return (
      <Panel title={translateUi("Team tasks")} icon={Users}>
        <TaskList state={state} />
      </Panel>
    );
  return (
    <Panel title={translateUi("Outcome and acceptance")} icon={Target}>
      <Criteria state={state} dispatch={dispatch} />
      <div className="pd-outcome-decision">
        <h3>{translateUi("Decision shared with the team")}</h3>
        <p>
          {state.run.answer ||
            translateUi(
              "The team will ask for your input before implementation.",
            )}
        </p>
      </div>
      <div className="pd-panel-footer">
        {translateUi(
          "Criteria are confirmed during the complete-change review.",
        )}
      </div>
    </Panel>
  );
}

function RunScreen({ state, dispatch }: ScreenProps) {
  useUiLocale();
  const [selected, setSelected] = useState("");
  const [note, setNote] = useState("");
  const [mine, setMine] = useState(false);
  const plan = state.plan!;
  const completedTasks = plan.tasks.filter(
    (task) => taskStatus(task, state.run) === "completed",
  ).length;
  const progress = Math.round((state.run.elapsed / RUN_LENGTH) * 100);
  const complete = state.run.status === "completed";
  const paused = state.run.status === "paused";
  const events = runEvents(state).filter(
    (event) => !mine || event.role === state.role || event.role === "team",
  );
  const task = plan.tasks.find((t) => t.id === selected);
  const statusTitle = complete
    ? translateUi("The work is ready to hand over")
    : paused
      ? translateUi("The team is paused")
      : state.run.status === "waiting"
        ? translateUi("A quick decision, then the team continues")
        : state.run.status === "review"
          ? translateUi("The team is ready for your review")
          : translateUi("Your team is working");
  return (
    <>
      <Heading
        eyebrow={translateUi("03 / LIVE RUN")}
        title={statusTitle}
        action={
          complete ? (
            <Button onClick={() => dispatch({ type: "PAGE", page: "results" })}>
              {translateUi("View results")}
              <ArrowRight size={17} />
            </Button>
          ) : paused ? (
            <Button secondary onClick={() => dispatch({ type: "RESUME" })}>
              <Play size={16} />
              {translateUi("Resume run")}
            </Button>
          ) : state.run.status === "running" ? (
            <Button secondary onClick={() => dispatch({ type: "PAUSE" })}>
              <Pause size={16} />
              {translateUi("Pause run")}
            </Button>
          ) : undefined
        }
      >
        {plan.title}
      </Heading>
      <div className="pd-run-progress" aria-label={translateUi("Run progress")}>
        <div>
          <div className="pd-live-label">
            <span
              className={state.run.status === "running" ? "pd-live-dot" : ""}
            />
            {complete
              ? translateUi("Completed")
              : paused
                ? translateUi("Paused")
                : state.run.status === "waiting" ||
                    state.run.status === "review"
                  ? translateUi("Waiting for your decision")
                  : translateUi("Live updates")}
          </div>
          <span className="pd-run-progress-number">
            {progress}
            <small>%</small>
          </span>
        </div>
        <div className="pd-run-progress-main">
          <div
            className="pd-progress-track"
            role="progressbar"
            aria-label={translateUi("Workflow completion")}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={progress}
          >
            <span style={{ width: progress + "%" }} />
          </div>
          <div className="pd-progress-caption">
            <span>
              {completedTasks} {translateUi("of")} {plan.tasks.length}{" "}
              {translateUi("tasks complete")}
            </span>
            <span>
              <Clock3 size={13} />
              {formatElapsed(state.run.elapsed)} {translateUi("active time")}
            </span>
          </div>
        </div>
        <div className="pd-run-approval">
          <ShieldCheck size={19} />
          <div>
            <strong>{translateUi("Plan approved")}</strong>
            <span>{translateUi("You keep the final decision")}</span>
          </div>
        </div>
      </div>
      <DecisionCard state={state} dispatch={dispatch} />
      <div className="pd-run-flow">
        <FlowGraph state={state} selected={selected} onSelect={setSelected} />
      </div>
      {task && (
        <div className="pd-run-selected">
          <strong>{task.title}</strong>
          <span>{task.description}</span>
        </div>
      )}
      <div className="pd-run-grid">
        <div className="pd-stack">
          <RoleRunPanel state={state} dispatch={dispatch} />
          {!complete && (
            <Panel title={translateUi("Guide the team")} icon={MessageSquare}>
              <form
                className="pd-note-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  dispatch({ type: "NOTE", text: note });
                  setNote("");
                }}
              >
                <label htmlFor="pd-team-note">
                  {translateUi(
                    "Add context or a review note while the work continues.",
                  )}
                </label>
                <div>
                  <input
                    id="pd-team-note"
                    maxLength={500}
                    placeholder={translateUi(
                      "For example: include a short release note…",
                    )}
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                  />
                  <Button type="submit" secondary disabled={!note.trim()}>
                    {translateUi("Send")}
                    <ArrowRight size={15} />
                  </Button>
                </div>
              </form>
            </Panel>
          )}
        </div>
        <Panel
          title={translateUi("Team activity")}
          icon={Clock3}
          className="pd-activity-panel"
          aside={
            <button
              type="button"
              className="pd-text-button"
              aria-pressed={mine}
              onClick={() => setMine(!mine)}
            >
              {mine ? "Show all" : "My role"}
            </button>
          }
        >
          <div
            className="pd-activity-feed"
            role="log"
            aria-label={translateUi("Team activity")}
          >
            {events.length ? (
              events.map((event) => (
                <div key={event.id} className="pd-event">
                  <span className="pd-event-marker">
                    {event.role === "tester" ? (
                      <ShieldCheck size={14} />
                    ) : event.role === "developer" ? (
                      <Code2 size={14} />
                    ) : event.role === "memory" ? (
                      <Database size={14} />
                    ) : event.role === "analyst" ? (
                      <Target size={14} />
                    ) : (
                      <Users size={14} />
                    )}
                  </span>
                  <div>
                    <div className="pd-event-meta">
                      <span>{roleName(event.role)}</span>
                      <time>{formatElapsed(event.at)}</time>
                    </div>
                    <strong>{event.title}</strong>
                    <p>{event.detail}</p>
                  </div>
                </div>
              ))
            ) : (
              <p className="pd-empty-feed">
                {translateUi(
                  "Updates for your role appear here as the work progresses.",
                )}
              </p>
            )}
          </div>
        </Panel>
      </div>
      {complete && (
        <div className="pd-bottom-actions">
          <p>
            <Check size={16} />
            {translateUi(
              "Changes, check results, and project knowledge are ready.",
            )}
          </p>
          <Button onClick={() => dispatch({ type: "PAGE", page: "results" })}>
            {translateUi("Open the handoff")}
            <ArrowRight size={17} />
          </Button>
        </div>
      )}
    </>
  );
}

function download(name: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
const ORDERS = [
  ["ORD-1042", "Linh Nguyen", "12 Oct 2026", "$128.00"],
  ["ORD-1043", "Minh Tran", "12 Oct 2026", "$86.50"],
  ["ORD-1044", "Alex Chen", "13 Oct 2026", "$214.00"],
  ["ORD-1045", "Sam Taylor", "13 Oct 2026", "$42.00"],
];
function csvOutput() {
  return (
    "\uFEFF" +
    [["Order ID", "Customer", "Date", "Total"], ...ORDERS]
      .map((row) =>
        row.map((value) => '"' + value.replaceAll('"', '""') + '"').join(","),
      )
      .join("\r\n")
  );
}
function OutcomePreview({
  plan,
  answer,
}: {
  plan: StudioPlan;
  answer: string | null;
}) {
  useUiLocale();
  if (plan.scenario === "vanguard") {
    const report = createVanguardReport(answer);
    return (
      <section
        className="pd-output-preview pd-vanguard-result"
        aria-label={translateUi("Vanguard rule result")}
      >
        <div className="pd-output-heading">
          <div>
            <p className="pd-eyebrow">
              {translateUi("VANGUARD · API DESIGN LINTER")}
            </p>
            <h3>
              {translateUi("list-paginated: findings and reviewed cases")}
            </h3>
          </div>
          <Button
            secondary
            onClick={() =>
              download(
                "vanguard-pagination-report.json",
                JSON.stringify(report, null, 2),
                "application/json",
              )
            }
          >
            <Download size={15} /> {translateUi("Download rule report")}
          </Button>
        </div>
        <div className="pd-output-filters">
          <span>{translateUi("Rule R3xx-01")}</span>
          <span>
            {report.cases.length} {translateUi("reviewed cases")}
          </span>
          <span>
            {report.findings.length} {translateUi("WARN findings")}
          </span>
        </div>
        <p className="pd-vanguard-policy">
          <strong>{translateUi("Pagination policy:")}</strong> {report.policy}
        </p>
        <div className="pd-table-wrap">
          <table>
            <thead>
              <tr>
                <th>{translateUi("Endpoint")}</th>
                <th>{translateUi("Expected")}</th>
                <th>{translateUi("Finding")}</th>
                <th>{translateUi("Source location")}</th>
              </tr>
            </thead>
            <tbody>
              {report.cases.map((item) => (
                <tr key={item.id}>
                  <td>{item.endpoint}</td>
                  <td>{item.expectation}</td>
                  <td
                    className={
                      item.finding.startsWith("WARN") ? "pd-finding-warn" : ""
                    }
                  >
                    {item.finding}
                  </td>
                  <td>{item.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="pd-vanguard-followup">
          <strong>{translateUi("Next Product Loop:")}</strong> {report.followUp}
        </p>
      </section>
    );
  }
  if (plan.scenario === "export")
    return (
      <section
        className="pd-output-preview"
        aria-label={translateUi("Order export result")}
      >
        <div className="pd-output-heading">
          <div>
            <p className="pd-eyebrow">{translateUi("ORDERS DASHBOARD")}</p>
            <h3>{translateUi("Orders ready to export")}</h3>
          </div>
          <Button
            secondary
            onClick={() =>
              download("orders.csv", csvOutput(), "text/csv;charset=utf-8")
            }
          >
            <Download size={15} />
            {translateUi("Export CSV")}
          </Button>
        </div>
        <div className="pd-output-filters">
          <span>{translateUi("12–13 Oct 2026")}</span>
          <span>{translateUi("All statuses")}</span>
          <span>{translateUi("4 matching orders")}</span>
        </div>
        <div className="pd-table-wrap">
          <table>
            <thead>
              <tr>
                {[
                  translateUi("Order ID"),
                  translateUi("Customer"),
                  translateUi("Date"),
                  translateUi("Total"),
                ].map((column) => (
                  <th key={column}>{column}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ORDERS.map((row) => (
                <tr key={row[0]}>
                  {row.map((cell, index) => (
                    <td key={index}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    );
  if (plan.scenario === "reset")
    return (
      <section className="pd-output-preview">
        <p className="pd-eyebrow">{translateUi("PASSWORD RESET EXPERIENCE")}</p>
        <h3>{translateUi("A clear path back to the account")}</h3>
        <div className="pd-reset-path">
          {[
            translateUi("Request a link"),
            translateUi("Choose a new password"),
            translateUi("See confirmation"),
          ].map((step, index) => (
            <div key={step}>
              <span>{index + 1}</span>
              <strong>{step}</strong>
              <Check size={17} />
            </div>
          ))}
        </div>
        <p className="pd-field-hint">
          {translateUi(
            "Single-use links · 30-minute expiry · Consistent response for every email",
          )}
        </p>
      </section>
    );
  if (plan.scenario === "insights")
    return (
      <section className="pd-output-preview">
        <p className="pd-eyebrow">{translateUi("SALES INSIGHTS")}</p>
        <h3>{translateUi("Your selected period at a glance")}</h3>
        <div className="pd-metric-preview">
          {[
            [translateUi("Revenue"), "$12,480", "+12.4%"],
            [translateUi("Orders"), "146", "+8.1%"],
            [translateUi("Average order"), "$85.48", "+4.0%"],
          ].map(([label, value, change]) => (
            <div key={label}>
              <span>{label}</span>
              <strong>{value}</strong>
              <small>
                {change} {translateUi("vs. previous period")}
              </small>
            </div>
          ))}
        </div>
        <p className="pd-field-hint">
          {translateUi(
            "The current and previous periods use the same duration.",
          )}
        </p>
      </section>
    );
  return (
    <section className="pd-output-preview">
      <p className="pd-eyebrow">{translateUi("REQUESTED OUTCOME")}</p>
      <h3>{plan.title}</h3>
      <p className="pd-request-quote">{plan.requirement}</p>
      <p className="pd-field-hint">
        {translateUi(
          "Implementation, checks, and handoff notes are grouped below.",
        )}
      </p>
    </section>
  );
}

function ResultsScreen({ state }: { state: StudioState }) {
  useUiLocale();
  const [tab, setTab] = useState(
    state.role === "developer"
      ? "changes"
      : state.role === "tester"
        ? "checks"
        : "summary",
  );
  const plan = state.plan!;
  const tabs = [
    ["summary", "Summary", FileText],
    ["changes", "Changes", Code2],
    ["checks", "Checks", ShieldCheck],
    ["memory", "Project memory", Database],
  ] as const;
  return (
    <>
      <Heading
        eyebrow={translateUi("04 / RESULTS")}
        title={translateUi("One handoff. Everything connected.")}
        action={
          <Button
            secondary
            onClick={() =>
              download(
                "vaiplatform-handoff.json",
                JSON.stringify(
                  {
                    plan,
                    decision: state.run.answer,
                    notes: state.run.notes,
                    approvedBy: state.run.handoffBy,
                    checks: plan.checks.map((name) => ({
                      name,
                      status: "passed",
                    })),
                    changes: createPatch(plan),
                    ...(plan.scenario === "vanguard"
                      ? { ruleReport: createVanguardReport(state.run.answer) }
                      : {}),
                  },
                  null,
                  2,
                ),
                "application/json",
              )
            }
          >
            <Download size={17} />
            {translateUi("Download handoff")}
          </Button>
        }
      >
        {plan.title} {translateUi("· Approved by")}{" "}
        {ROLE_INFO[state.run.handoffBy!].label}
      </Heading>
      <div className="pd-result-stats">
        <div>
          <span className="pd-stat-icon">
            <FileCode2 size={20} />
          </span>
          <strong>{plan.files.length}</strong>
          <span>{translateUi("changed files")}</span>
        </div>
        <div>
          <span className="pd-stat-icon">
            <ShieldCheck size={20} />
          </span>
          <strong>
            {plan.checks.length}/{plan.checks.length}
          </strong>
          <span>{translateUi("checks passed")}</span>
        </div>
        <div>
          <span className="pd-stat-icon">
            <Check size={20} />
          </span>
          <strong>{plan.criteria.filter((c) => c.included).length}</strong>
          <span>{translateUi("criteria reviewed")}</span>
        </div>
        <div>
          <span className="pd-stat-icon">
            <Database size={20} />
          </span>
          <strong>{translateUi("Saved")}</strong>
          <span>{translateUi("project knowledge")}</span>
        </div>
      </div>
      <div
        className="pd-result-tabs"
        role="tablist"
        aria-label={translateUi("Handoff views")}
      >
        {tabs.map(([key, label, Icon], index) => (
          <button
            type="button"
            key={key}
            role="tab"
            id={"pd-tab-" + key}
            aria-selected={tab === key}
            tabIndex={tab === key ? 0 : -1}
            aria-controls={"pd-result-" + key}
            onClick={() => setTab(key)}
            onKeyDown={(e) => {
              if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key))
                return;
              e.preventDefault();
              const next =
                e.key === "Home"
                  ? 0
                  : e.key === "End"
                    ? tabs.length - 1
                    : (index +
                        (e.key === "ArrowRight" ? 1 : -1) +
                        tabs.length) %
                      tabs.length;
              setTab(tabs[next][0]);
              document.getElementById("pd-tab-" + tabs[next][0])?.focus();
            }}
          >
            <Icon size={16} />
            {translateUi(label)}
          </button>
        ))}
      </div>
      <div
        role="tabpanel"
        id={"pd-result-" + tab}
        aria-labelledby={"pd-tab-" + tab}
        className="pd-result-content"
      >
        {tab === "summary" && (
          <div className="pd-stack">
            <OutcomePreview plan={plan} answer={state.run.answer} />
            <div className="pd-two-column">
              <Panel
                title={translateUi("What is in the handoff")}
                icon={FileText}
              >
                <div className="pd-deliverable-list">
                  {[
                    plan.scenario === "vanguard"
                      ? translateUi(
                          "Pagination rule and independent fixture corpus",
                        )
                      : translateUi("Changes to the service and interface"),
                    translateUi("Check report and acceptance review"),
                    translateUi("Release notes and approval history"),
                    translateUi("Project decisions for the next request"),
                  ].map((item) => (
                    <p key={item}>
                      <Check size={15} />
                      {item}
                    </p>
                  ))}
                </div>
              </Panel>
              <Panel
                title={translateUi("Decisions that shaped the work")}
                icon={Target}
              >
                <div className="pd-memory-copy">
                  <strong>{state.run.answer}</strong>
                  <p>
                    {translateUi(
                      "The team used this decision to complete the agreed scope.",
                    )}
                  </p>
                  <p>
                    {translateUi("Final approval:")}{" "}
                    {ROLE_INFO[state.run.handoffBy!].label}
                  </p>
                </div>
              </Panel>
            </div>
          </div>
        )}
        {tab === "changes" && (
          <div className="pd-stack">
            <div className="pd-change-header">
              <p>
                {plan.files.length}{" "}
                {translateUi(
                  "files · Changes are ready for review before merging.",
                )}
              </p>
              <Button
                secondary
                onClick={() =>
                  download("changes.diff", createPatch(plan), "text/plain")
                }
              >
                <Download size={15} />
                {translateUi("Download patch")}
              </Button>
            </div>
            {plan.files.map((file) => (
              <section className="pd-diff" key={file.path}>
                <div className="pd-diff-heading">
                  <FileCode2 size={16} />
                  <strong>{file.path}</strong>
                  <span>+{file.additions.length} lines</span>
                </div>
                <p>{file.purpose}</p>
                <pre aria-label={translateUi("Changes in ") + file.path}>
                  {file.additions.map((line, index) => (
                    <span key={index}>
                      <span className="pd-line-number">{index + 1}</span>
                      <span className="pd-plus">+</span>
                      {line}
                    </span>
                  ))}
                </pre>
              </section>
            ))}
          </div>
        )}
        {tab === "checks" && (
          <div className="pd-two-column">
            <Panel
              title={translateUi("Completed check report")}
              icon={ShieldCheck}
            >
              <CheckReport state={state} />
              <div className="pd-panel-footer">
                {translateUi("All six checks are included in the handoff.")}
              </div>
            </Panel>
            <Panel title={translateUi("Acceptance review")} icon={Target}>
              <div className="pd-criteria">
                {plan.criteria
                  .filter((c) => c.included)
                  .map((c) => (
                    <div className="pd-criterion" key={c.id}>
                      <span className="pd-check-circle done">
                        <Check size={12} />
                      </span>
                      <span>{c.label}</span>
                    </div>
                  ))}
              </div>
              <div className="pd-panel-footer">
                {translateUi(
                  "Reviewed with the complete change before approval.",
                )}
              </div>
            </Panel>
          </div>
        )}
        {tab === "memory" && (
          <div className="pd-two-column">
            <Panel
              title={translateUi("Saved with this project")}
              icon={Database}
            >
              <div className="pd-memory-copy">
                <h3>{translateUi("Requested outcome")}</h3>
                <p>
                  {plan.scenario === "vanguard"
                    ? translateUi(
                        "Build list-paginated on frozen Java/Spring IR. Keep WARN findings with source locations, an independent corpus and human handoff approval.",
                      )
                    : plan.requirement}
                </p>
                <h3>{translateUi("Team decision")}</h3>
                <p>{state.run.answer}</p>
                <h3>{translateUi("Review and approval")}</h3>
                <p>
                  {translateUi("The handoff was approved by")}{" "}
                  {ROLE_INFO[state.run.handoffBy!].label}. Changes, check
                  results, and notes are kept together.
                </p>
              </div>
            </Panel>
            <Panel
              title={translateUi("Notes for the next request")}
              icon={MessageSquare}
            >
              <div className="pd-memory-copy">
                <p>
                  {translateUi(
                    "Keep the current project conventions and apply the recorded decision to related work.",
                  )}
                </p>
                {state.run.notes.length ? (
                  state.run.notes.map((note) => (
                    <blockquote key={note.id}>
                      <p>{note.text}</p>
                      <span>
                        {ROLE_INFO[note.role].label} · {formatElapsed(note.at)}
                      </span>
                    </blockquote>
                  ))
                ) : (
                  <p>
                    {translateUi(
                      "No extra guidance was needed for this request.",
                    )}
                  </p>
                )}
              </div>
            </Panel>
          </div>
        )}
      </div>
    </>
  );
}
