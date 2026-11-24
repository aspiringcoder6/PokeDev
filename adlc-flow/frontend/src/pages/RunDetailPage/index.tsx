import {
  translateUi,
  useUiLocale,
  formatUiStatus,
  getUiLanguage,
} from "@/i18n/ui";
import axios from "axios";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import i18n from "@/i18n";
import ContractExecutionPanel from "@/components/adlc/ContractExecutionPanel";
import ContractPanel from "@/components/adlc/ContractPanel";
import MemoryPanel from "@/components/adlc/MemoryPanel";
import ReplayPanel from "@/components/adlc/ReplayPanel";
import VerificationPanel from "@/components/adlc/VerificationPanel";
import WorkflowPluginsPanel, {
  pluginRecordFromOutput,
} from "@/components/adlc/WorkflowPluginsPanel";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import Loading from "@/components/ui/loading";
import {
  approveAdlcRun,
  cancelAdlcRun,
  getAdlcHarnessResults,
  getAdlcHarnessSessions,
  getAdlcRun,
  getAdlcRunControls,
  getAdlcRunEvents,
  getAdlcRunTasks,
  getAdlcTaskSubtasks,
  pauseAdlcRun,
  reconcileAdlcContractVerification,
  reconcileAdlcHarnessRun,
  rejectAdlcRun,
  respondToAdlcHarnessInteraction,
  resumeAdlcRun,
  retryAdlcTask,
  submitAdlcHarnessSession,
} from "@/controllers/API/adlc";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import type {
  AdlcHarnessRunResult,
  AdlcHarnessRunSession,
  AdlcRunEvent,
  AdlcRunOperatorControls,
  AdlcTaskRun,
  AdlcTaskSubtasks,
  AdlcWorkflowRun,
  TaskRunStatus,
  WorkflowRunStatus,
} from "@/types/adlc";
import AttemptList, { buildTaskAttempts } from "./AttemptList";
import HarnessResults from "./HarnessResults";
import HarnessSessions from "./HarnessSessions";
import HarnessWorkflowResults from "./HarnessWorkflowResults";
import SourcePatchReview, {
  capturedSourcePatches,
  sourcePatchReviewKey,
} from "./SourcePatchReview";
import TaskActivityPanel from "./TaskActivityPanel";
import TaskArtifacts from "./TaskArtifacts";
import TaskArtifactsList from "./TaskArtifactsList";
import SubtaskProgress from "./SubtaskProgress";
import TaskSubtaskPanel from "./TaskSubtaskPanel";
import HarnessWorkflowReview, {
  workflowHarnessReview,
} from "./HarnessWorkflowReview";
import TaskLoopTimeline, { isTaskLoop } from "./TaskLoopTimeline";
import {
  KernelReviewEvidence,
  QualityInterfaceSamples,
  useRunReviewEvidence,
} from "./RunReviewEvidence";
import "./review.css";

function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail?.message === "string") return detail.message;
    if (typeof detail === "string") return detail;
  }
  return error instanceof Error
    ? error.message
    : translateUi("Unable to load this run.");
}

function statusVariant(status: string): BadgeProps["variant"] {
  if (status === "SUCCEEDED" || status === "APPROVED") return "successStatic";
  if (status === "FAILED" || status === "REJECTED" || status === "CANCELLED") {
    return "errorStatic";
  }
  if (status === "WAITING_APPROVAL" || status === "PAUSED")
    return "purpleStatic";
  if (status === "RUNNING" || status === "READY" || status === "QUEUED")
    return "emerald";
  return "secondaryStatic";
}

function StatusBadge({ status }: { status: string }) {
  return (
    <Badge variant={statusVariant(status)} size="tag">
      {formatUiStatus(status, true)}
    </Badge>
  );
}

function executionModeLabel(run: AdlcWorkflowRun): string {
  if (run.execution_mode === "EXECUTION_PLAN")
    return translateUi("Blueprint plan");
  if (run.execution_mode === "MOCK_WORKFLOW")
    return translateUi("Fixed mock workflow");
  return translateUi("Legacy flow");
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat(getUiLanguage(), {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));
}

function taskMaxAttempts(task: AdlcTaskRun): number {
  const configured = task.request?.constraints?.max_attempts;
  return typeof configured === "number" && Number.isInteger(configured)
    ? configured
    : 2;
}

function isTerminalRunStatus(status: WorkflowRunStatus | undefined): boolean {
  return (
    status === "SUCCEEDED" || status === "FAILED" || status === "CANCELLED"
  );
}

function isTerminalTaskStatus(status: TaskRunStatus | undefined): boolean {
  return (
    status === "SUCCEEDED" ||
    status === "FAILED" ||
    status === "CANCELLED" ||
    status === "SKIPPED"
  );
}

export default function RunDetailPage() {
  const { t } = useTranslation();
  useUiLocale();
  const { runId } = useParams();
  const navigate = useCustomNavigate();
  const [run, setRun] = useState<AdlcWorkflowRun>();
  const [tasks, setTasks] = useState<AdlcTaskRun[]>([]);
  const [events, setEvents] = useState<AdlcRunEvent[]>([]);
  const [controls, setControls] = useState<AdlcRunOperatorControls>();
  const [controlsError, setControlsError] = useState(false);
  const [harnessSessions, setHarnessSessions] = useState<
    AdlcHarnessRunSession[]
  >([]);
  const [harnessResults, setHarnessResults] = useState<AdlcHarnessRunResult[]>(
    [],
  );
  const [harnessError, setHarnessError] = useState<string>();
  const [resultsError, setResultsError] = useState<string>();
  const currentRunId = useRef(runId);
  currentRunId.current = runId;
  const [loading, setLoading] = useState(true);
  const [actingOn, setActingOn] = useState<string>();
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const [patchReviewReadyKey, setPatchReviewReadyKey] = useState<string>();
  const [expandedTaskId, setExpandedTaskId] = useState<string>();
  const [previewReadySessions, setPreviewReadySessions] = useState<string[]>(
    [],
  );
  const [reviewComment, setReviewComment] = useState("");
  const [showRejectForm, setShowRejectForm] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [subtasksByTask, setSubtasksByTask] = useState<
    Record<string, AdlcTaskSubtasks>
  >({});
  const [subtasksLoading, setSubtasksLoading] = useState<
    Record<string, boolean>
  >({});
  const [harnessReviewConfirmed, setHarnessReviewConfirmed] = useState(false);
  const [reviewTab, setReviewTab] = useState<
    "changes" | "quality" | "activity"
  >("changes");
  const reviewEvidence = useRunReviewEvidence(runId ?? "", tasks);
  useEffect(() => {
    setHarnessReviewConfirmed(false);
    setShowRejectForm(false);
    setRejectReason("");
  }, [
    runId,
    run?.approval_requests.find((a) => a.status === "PENDING")
      ?.approval_request_id,
  ]);

  const loadRun = useCallback(async () => {
    if (!runId) return;
    const isCurrentRun = () => currentRunId.current === runId;
    const loadLiveSessions = async () => {
      try {
        const snapshot = await getAdlcHarnessSessions(runId);
        if (!isCurrentRun()) return;
        setHarnessSessions(snapshot);
        setHarnessError(undefined);
      } catch (loadError) {
        if (!isCurrentRun()) return;
        // Do not offer stale approval/submit actions when live control is unavailable.
        setHarnessSessions([]);
        setHarnessError(errorMessage(loadError));
      }
    };
    const loadControls = async () => {
      try {
        const snapshot = await getAdlcRunControls(runId);
        if (!isCurrentRun()) return;
        if (snapshot.workflow_run_id !== runId)
          throw new Error(i18n.t("adlc.run.scopeMismatch"));
        setControls(snapshot);
        setControlsError(false);
      } catch {
        if (!isCurrentRun()) return;
        setControls(undefined);
        setControlsError(true);
      }
    };
    const loadAdlcState = async () => {
      try {
        const [runSnapshot, taskSnapshot, eventSnapshot] = await Promise.all([
          getAdlcRun(runId),
          getAdlcRunTasks(runId),
          getAdlcRunEvents(runId),
        ]);
        if (!isCurrentRun()) return;
        setRun(runSnapshot);
        setTasks(taskSnapshot);
        setEvents(eventSnapshot.events);
        setError(undefined);
        // Read the archive after the run snapshot so a terminal run cannot race
        // a pre-callback archive read and permanently hide its final result.
        try {
          const snapshot = await getAdlcHarnessResults(runId);
          if (!isCurrentRun()) return;
          // Accepted attempt results are immutable. A slower, older poll must
          // not erase an accepted result that a newer poll has already shown.
          setHarnessResults((current) => {
            const retained = new Map(
              current.map((entry) => [entry.attempt_id, entry]),
            );
            for (const entry of snapshot) retained.set(entry.attempt_id, entry);
            return [...retained.values()];
          });
          setResultsError(undefined);
        } catch (loadError) {
          if (isCurrentRun()) setResultsError(errorMessage(loadError));
        }
      } catch (loadError) {
        if (isCurrentRun()) setError(errorMessage(loadError));
      } finally {
        if (isCurrentRun()) setLoading(false);
      }
    };
    await Promise.all([loadAdlcState(), loadLiveSessions(), loadControls()]);
  }, [runId]);

  const subtasksInFlightRef = useRef<Set<string>>(new Set());
  const loadSubtasks = useCallback(
    async (taskRunId: string) => {
      if (!runId || subtasksInFlightRef.current.has(taskRunId)) return;
      const task = tasks.find((item) => item.id === taskRunId);
      if (!task || isTaskLoop(task) || task.task_type === "APPROVAL") return;
      subtasksInFlightRef.current.add(taskRunId);
      setSubtasksLoading((prev) => ({ ...prev, [taskRunId]: true }));
      try {
        const data = await getAdlcTaskSubtasks(runId, taskRunId);
        if (currentRunId.current !== runId || data.task_run_id !== taskRunId)
          return;
        setSubtasksByTask((prev) => ({ ...prev, [taskRunId]: data }));
      } catch {
        // Leave any previous data in place; the poller retries shortly.
        // Never fall back to fake progress — it misleads during live runs.
      } finally {
        subtasksInFlightRef.current.delete(taskRunId);
        if (currentRunId.current === runId)
          setSubtasksLoading((prev) => ({ ...prev, [taskRunId]: false }));
      }
    },
    [runId, tasks],
  );

  // Fetch subtasks when a task is expanded.
  useEffect(() => {
    if (expandedTaskId && !subtasksByTask[expandedTaskId]) {
      void loadSubtasks(expandedTaskId);
    }
  }, [expandedTaskId, subtasksByTask, loadSubtasks]);

  // Load subtask summaries for every task up front so the collapsed task
  // rows show their progress bars immediately, without requiring a click.
  useEffect(() => {
    for (const task of tasks) {
      if (!subtasksByTask[task.id]) {
        void loadSubtasks(task.id);
      }
    }
  }, [tasks, subtasksByTask, loadSubtasks]);

  // Poll subtask progress while the run is active so progress bars update
  // as soon as a subtask finishes (statuses are mirrored server-side).
  useEffect(() => {
    if (!runId) return;
    if (run && isTerminalRunStatus(run.status)) return;
    const interval = window.setInterval(() => {
      for (const task of tasks) {
        if (isTerminalTaskStatus(task.status)) continue;
        void loadSubtasks(task.id);
      }
      if (expandedTaskId) void loadSubtasks(expandedTaskId);
    }, 4000);
    return () => window.clearInterval(interval);
  }, [runId, run, tasks, expandedTaskId, loadSubtasks]);

  // Fetch one final snapshot when a task transitions to a terminal status so
  // its progress bar reflects the completed subtasks immediately.
  const prevTaskStatusesRef = useRef<Record<string, string>>({});
  useEffect(() => {
    for (const task of tasks) {
      const previous = prevTaskStatusesRef.current[task.id];
      if (
        previous &&
        previous !== task.status &&
        isTerminalTaskStatus(task.status)
      ) {
        void loadSubtasks(task.id);
      }
      prevTaskStatusesRef.current[task.id] = task.status;
    }
  }, [tasks, loadSubtasks]);

  useEffect(() => {
    setRun(undefined);
    setReviewTab("changes");
    setReviewComment("");
    setSubtasksByTask({});
    setSubtasksLoading({});
    setControls(undefined);
    setControlsError(false);
    setHarnessSessions([]);
    setHarnessResults([]);
    setPreviewReadySessions([]);
    setHarnessError(undefined);
    setResultsError(undefined);
    setLoading(true);
    void loadRun();
  }, [loadRun]);

  useEffect(() => {
    if (
      !run ||
      !["CREATED", "QUEUED", "RUNNING", "PAUSED", "WAITING_APPROVAL"].includes(
        run.status,
      )
    ) {
      return;
    }
    const timer = window.setInterval(() => void loadRun(), 1500);
    return () => window.clearInterval(timer);
  }, [loadRun, run]);

  const runAction = async (key: string, action: () => Promise<unknown>) => {
    setActingOn(key);
    setNotice(undefined);
    try {
      await action();
      await loadRun();
    } catch (actionError) {
      setError(errorMessage(actionError));
    } finally {
      setActingOn(undefined);
    }
  };

  const taskNamesById = useMemo(
    () => new Map(tasks.map((task) => [task.id, task.name])),
    [tasks],
  );
  const attemptNumbersById = useMemo(() => {
    const numbers = new Map<string, number>();
    for (const task of tasks) {
      for (const attempt of buildTaskAttempts(task, events)) {
        numbers.set(attempt.attemptId, attempt.number);
      }
    }
    return numbers;
  }, [tasks, events]);

  // Plan-orchestrated tasks produce results on subtask attempts whose
  // task_run_id is generated per subtask — attribute them to the owning
  // task through the subtask registry's attempt ids.
  const subtaskAttemptsByTask = useMemo(() => {
    const map = new Map<string, Map<string, string>>();
    for (const [taskRunId, data] of Object.entries(subtasksByTask)) {
      const attempts = new Map<string, string>();
      for (const sub of data.subtasks ?? []) {
        if (sub.attempt_id) attempts.set(sub.attempt_id, sub.name);
      }
      if (attempts.size > 0) map.set(taskRunId, attempts);
    }
    return map;
  }, [subtasksByTask]);

  const harnessResultsForTask = useCallback(
    (taskId: string) =>
      harnessResults.filter(
        (entry) =>
          entry.task_run_id === taskId ||
          subtaskAttemptsByTask.get(taskId)?.has(entry.attempt_id),
      ),
    [harnessResults, subtaskAttemptsByTask],
  );

  const harnessSessionsForTask = useCallback(
    (taskId: string) =>
      harnessSessions.filter(
        (entry) =>
          entry.task_run_id === taskId ||
          subtaskAttemptsByTask.get(taskId)?.has(entry.attempt_id),
      ),
    [harnessSessions, subtaskAttemptsByTask],
  );

  if (loading) {
    return (
      <div className="flex h-full w-full items-center justify-center">
        <Loading
          aria-label={translateUi("Loading ADLC run")}
          className="h-7 w-7 text-primary"
        />
      </div>
    );
  }

  if (!run) {
    return (
      <div className="flex h-full w-full flex-col items-center justify-center gap-4 p-6">
        <p className="text-sm text-destructive">
          {error ?? translateUi("Run not found.")}
        </p>
        <Button variant="outline" onClick={() => navigate("/flows")}>
          {translateUi("Back to flows")}
        </Button>
      </div>
    );
  }

  const pendingApproval = run.approval_requests.find(
    (approval) => approval.status === "PENDING",
  );

  // Only show approval if the task's dependencies are completed.
  // This prevents asking the user to approve work that hasn't finished yet.
  const approvalTask = pendingApproval
    ? tasks.find((t) => t.id === pendingApproval.task_run_id)
    : undefined;
  const approvalDependenciesMet = approvalTask
    ? approvalTask.dependency_task_run_ids.every((depId) => {
        const dep = tasks.find((t) => t.id === depId);
        return dep?.status === "SUCCEEDED";
      })
    : true;
  const showApproval = pendingApproval && approvalDependenciesMet;

  const capturedPatches = capturedSourcePatches(tasks);
  const allReviewPatches = capturedSourcePatches(
    tasks,
    harnessResults,
    harnessSessions,
  );
  const hasCapturedPatches = capturedPatches.length > 0;
  const patchReviewAvailable =
    !hasCapturedPatches ||
    patchReviewReadyKey === sourcePatchReviewKey(run.id, capturedPatches);

  return (
    <main className="rr-page h-full w-full overflow-y-auto bg-background">
      <div className="rr-shell mx-auto flex max-w-6xl flex-col gap-6 p-6 lg:p-8">
        <header className="rr-header flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-2">
            <Button
              variant="ghost"
              size="xs"
              className="-ml-3 text-muted-foreground"
              onClick={() =>
                navigate(run.flow_id ? `/flow/${run.flow_id}` : "/flows")
              }
            >
              <ForwardedIconComponent name="ArrowLeft" className="h-4 w-4" />
              {translateUi("Back to flow")}
            </Button>
            <Button
              variant="ghost"
              size="xs"
              className="-ml-3 text-muted-foreground"
              onClick={() =>
                navigate(
                  run.flow_id ? `/runs/?flowId=${run.flow_id}` : "/runs/",
                )
              }
            >
              <ForwardedIconComponent name="History" className="h-4 w-4" />
              {translateUi("All runs")}
            </Button>
            <p className="rr-kicker">Kết quả thực hiện</p>
            <div className="rr-header-info">
              <h1 className="text-2xl font-semibold">{run.name}</h1>
              {typeof run.run_number === "number" && (
                <Badge variant="secondaryStatic" size="tag">
                  {translateUi("Run #")}
                  {run.run_number}
                </Badge>
              )}
              <StatusBadge status={run.status} />
            </div>
            <details className="rr-technical">
              <summary>Thông tin lượt chạy</summary>
              <p className="font-mono text-xs text-muted-foreground">
                {translateUi("Run")} {run.id}
              </p>
              <p>{executionModeLabel(run)}</p>
              {run.execution_plan_id && (
                <button
                  type="button"
                  className="font-mono text-xs text-muted-foreground underline-offset-2 hover:underline"
                  onClick={() => navigate(`/plans/${run.execution_plan_id}`)}
                >
                  {translateUi("Execution plan")} {run.execution_plan_id}
                </button>
              )}
            </details>
          </div>
          <div className="flex flex-wrap gap-2">
            {controls?.can_pause &&
              ["QUEUED", "RUNNING"].includes(run.status) && (
                <Button
                  variant="outline"
                  size="md"
                  disabled={!!actingOn}
                  loading={actingOn === "pause"}
                  onClick={() =>
                    void runAction("pause", async () => {
                      await pauseAdlcRun(run.id);
                      setNotice(
                        translateUi(
                          "Pause requested. The current iteration finishes before the run pauses.",
                        ),
                      );
                    })
                  }
                >
                  {translateUi("Pause")}
                </Button>
              )}
            {controls?.can_resume &&
              run.status === "PAUSED" &&
              !tasks.some((task) => task.status === "FAILED") && (
                <Button
                  variant="outline"
                  size="md"
                  disabled={!!actingOn}
                  loading={actingOn === "resume"}
                  onClick={() =>
                    void runAction("resume", () => resumeAdlcRun(run.id))
                  }
                >
                  {translateUi("Resume")}
                </Button>
              )}
            {controls?.can_cancel &&
              !["SUCCEEDED", "FAILED", "CANCELLED"].includes(run.status) && (
                <Button
                  variant="outline"
                  size="md"
                  disabled={!!actingOn}
                  loading={actingOn === "cancel"}
                  onClick={() =>
                    void runAction("cancel", () => cancelAdlcRun(run.id))
                  }
                >
                  {translateUi("Cancel run")}
                </Button>
              )}
            {(harnessSessions.length > 0 ||
              harnessResults.length > 0 ||
              harnessError) && (
              <Button
                variant="outline"
                size="md"
                loading={actingOn === "harness-reconcile"}
                onClick={() =>
                  void runAction("harness-reconcile", async () => {
                    const report = await reconcileAdlcHarnessRun(run.id);
                    setNotice(
                      translateUi(
                        "Harness recovery checked {{value0}} attempt(s): {{value1}} result(s) recovered, {{value2}} automatic submission(s), {{value3}} unavailable.",
                        {
                          value0: report.inspected,
                          value1: report.recovered_results,
                          value2: report.submitted_sessions,
                          value3: report.unavailable_sessions,
                        },
                      ),
                    );
                  })
                }
              >
                <ForwardedIconComponent name="RefreshCcw" className="h-4 w-4" />
                {translateUi("Recover Harness state")}
              </Button>
            )}
            <Button variant="outline" size="md" onClick={() => void loadRun()}>
              <ForwardedIconComponent name="RefreshCw" className="h-4 w-4" />
              {translateUi("Refresh")}
            </Button>
          </div>
        </header>

        {controls?.pause_requested && run.status === "RUNNING" && (
          <p role="status" className="text-sm text-muted-foreground">
            {translateUi(
              "Pause requested. Waiting for the current iteration to finish.",
            )}
          </p>
        )}
        {controlsError &&
          !["SUCCEEDED", "FAILED", "CANCELLED"].includes(run.status) && (
            <p role="status" className="text-xs text-muted-foreground">
              {translateUi(
                "Run controls are unavailable. Refresh to reconnect.",
              )}
            </p>
          )}

        {error && (
          <div
            role="alert"
            className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm"
          >
            {error}
          </div>
        )}

        {notice && (
          <div
            role="status"
            className="rounded-md border border-accent-emerald/40 bg-accent-emerald/20 p-3 text-sm"
          >
            {notice}
          </div>
        )}

        {harnessError && (
          <div
            role="status"
            className="rounded-md border border-warning bg-warning/20 p-3 text-sm"
          >
            {translateUi(
              "Live Harness control is unavailable. Saved ADLC results remain accessible.",
            )}
            <p className="mt-1 text-xs text-muted-foreground">{harnessError}</p>
          </div>
        )}

        {resultsError && (
          <div
            role="alert"
            className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm"
          >
            {translateUi("Unable to refresh saved agent results:")}{" "}
            {resultsError}
          </div>
        )}

        <section className="rr-metrics" aria-label="Tóm tắt lượt chạy">
          <div>
            <strong>{allReviewPatches.length}</strong>
            <span>bản thay đổi</span>
          </div>
          <div>
            <strong>
              {reviewEvidence.loading
                ? "…"
                : reviewEvidence.rows.some((row) => row.summary?.passed)
                  ? reviewEvidence.rows.reduce(
                      (sum, row) =>
                        sum + (row.summary?.passed ? row.summary.tests : 0),
                      0,
                    )
                  : "—"}
            </strong>
            <span>
              test đã đạt
              {reviewEvidence.rows.some((row) => !row.summary?.passed)
                ? " · còn task chưa xác minh"
                : ""}
            </span>
          </div>
          <div>
            <strong>
              {tasks.filter((task) => task.status === "SUCCEEDED").length}/
              {tasks.length}
            </strong>
            <span>task hoàn tất</span>
          </div>
          {pendingApproval && (
            <div>
              <span>Chờ bạn xem thay đổi và phê duyệt</span>
            </div>
          )}
        </section>
        {tasks
          .filter((task) => task.result?.error)
          .map((task) => (
            <p role="alert" key={task.id} className="text-sm text-destructive">
              {task.name}: {task.result!.error!.code}:{" "}
              {task.result!.error!.message}
            </p>
          ))}
        <div
          className="rr-tabs"
          role="tablist"
          aria-label="Xem kết quả lượt chạy"
        >
          {(
            [
              ["changes", "Thay đổi"],
              ["quality", "Kiểm thử & Verify"],
              ["activity", "Hoạt động & nâng cao"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              id={`review-tab-${id}`}
              aria-selected={reviewTab === id}
              tabIndex={reviewTab === id ? 0 : -1}
              aria-controls={`review-panel-${id}`}
              onClick={() => setReviewTab(id)}
              onKeyDown={(event) => {
                const tabs = ["changes", "quality", "activity"] as const;
                const index = tabs.indexOf(id);
                const next =
                  event.key === "ArrowRight"
                    ? (index + 1) % 3
                    : event.key === "ArrowLeft"
                      ? (index + 2) % 3
                      : event.key === "Home"
                        ? 0
                        : event.key === "End"
                          ? 2
                          : -1;
                if (next < 0) return;
                event.preventDefault();
                setReviewTab(tabs[next]);
                document.getElementById(`review-tab-${tabs[next]}`)?.focus();
              }}
            >
              {label}
            </button>
          ))}
        </div>

        <HarnessSessions
          sessions={harnessSessions}
          tasks={tasks}
          actingOn={actingOn}
          canSubmit={(sessionId) => {
            const preview = harnessSessions.find(
              (entry) => entry.session.session_id === sessionId,
            );
            const hasPatch = preview?.session.result?.artifacts?.some(
              (item) => item.metadata?.capture === "harness-git-diff",
            );
            return !hasPatch || previewReadySessions.includes(sessionId);
          }}
          onRespond={(sessionId, interactionId, response) =>
            void runAction(`harness-interaction-${interactionId}`, () =>
              respondToAdlcHarnessInteraction(
                run.id,
                sessionId,
                interactionId,
                response,
              ),
            )
          }
          onSubmit={(sessionId) =>
            void runAction(`harness-submit-${sessionId}`, () =>
              submitAdlcHarnessSession(run.id, sessionId),
            )
          }
          onReconcileVerification={(sessionId) =>
            void runAction(`harness-recovery-${sessionId}`, () =>
              reconcileAdlcContractVerification(run.id, sessionId),
            )
          }
        />

        <div
          className="rr-panel"
          role="tabpanel"
          id="review-panel-changes"
          aria-labelledby="review-tab-changes"
          hidden={reviewTab !== "changes"}
        >
          {allReviewPatches.length === 0 && (
            <section className="rr-quality-card">
              <strong>Chưa có bản thay đổi để so sánh</strong>
              <p>Chọn Hoạt động để xem tiến độ và các lần thực hiện.</p>
            </section>
          )}
          <SourcePatchReview
            runId={run.id}
            tasks={tasks}
            results={harnessResults}
            sessions={harnessSessions}
            onAvailabilityChange={setPatchReviewReadyKey}
            onPreviewAvailabilityChange={setPreviewReadySessions}
          />
        </div>
        <div
          className="rr-panel"
          role="tabpanel"
          id="review-panel-quality"
          aria-labelledby="review-tab-quality"
          hidden={reviewTab !== "quality"}
        >
          {reviewTab === "quality" && (
            <>
              <KernelReviewEvidence evidence={reviewEvidence} />
              <WorkflowPluginsPanel
                runId={run.id}
                taskResults={tasks.flatMap((task) => {
                  const record = pluginRecordFromOutput(task.result?.output);
                  return record ? [record] : [];
                })}
              />
              <QualityInterfaceSamples />
              <details className="rr-advanced">
                <summary>Dữ liệu & thao tác Verify / TestForge thật</summary>
                <div className="rr-panel">
                  <VerificationPanel
                    key={`verify-${run.id}`}
                    scope={{ runId: run.id }}
                  />
                  <ReplayPanel
                    key={`replay-${run.id}`}
                    scope={{ runId: run.id }}
                  />
                </div>
              </details>
            </>
          )}
        </div>

        {pendingApproval && (
          <Card className="rr-approval bg-background">
            <CardHeader>
              <div className="flex items-center justify-between gap-3">
                <CardTitle>
                  {pendingApproval.title.replace(/^Approve\s+/i, "Duyệt · ")}
                </CardTitle>
                <StatusBadge status={pendingApproval.status} />
              </div>
              <CardDescription>
                {pendingApproval.context.summary ===
                "Review the completed work before the workflow continues."
                  ? "Xem kết quả trước khi cho workflow tiếp tục."
                  : pendingApproval.context.summary}
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              {workflowHarnessReview(
                pendingApproval.context.payload?.harness_workflow_review,
              ) && (
                <>
                  <HarnessWorkflowReview
                    review={
                      workflowHarnessReview(
                        pendingApproval.context.payload
                          ?.harness_workflow_review,
                      )!
                    }
                  />
                  <label className="flex w-full items-start gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={harnessReviewConfirmed}
                      onChange={(e) =>
                        setHarnessReviewConfirmed(e.target.checked)
                      }
                    />
                    Tôi đã đọc kế hoạch hoặc diff/bằng chứng và đồng ý với đúng
                    digest, repository và nhánh nêu trên.
                  </label>
                </>
              )}
              {pendingApproval.context.payload?.reviewed_candidates?.length ? (
                <details className="rr-technical w-full">
                  <summary>Candidate được duyệt · xem mã đối chiếu</summary>
                  {pendingApproval.context.payload.reviewed_candidates.map(
                    (candidate) => (
                      <div
                        key={candidate.artifact_id}
                        className="w-full space-y-1 rounded border p-2"
                      >
                        <p className="text-xs font-medium">
                          {translateUi("Approve candidate from iteration")}{" "}
                          {candidate.iteration ?? "unknown"}
                        </p>
                        <p className="break-all font-mono text-xs">
                          {candidate.candidate_id ?? candidate.artifact_id}
                        </p>
                        <p className="break-all font-mono text-[11px] text-muted-foreground">
                          {candidate.candidate_digest}
                        </p>
                      </div>
                    ),
                  )}
                </details>
              ) : null}
              <details className="rr-technical w-full">
                <summary>Thêm nhận xét (không bắt buộc)</summary>
                <label className="w-full space-y-1 text-xs text-muted-foreground">
                  {translateUi("Review feedback (optional)")}
                  <textarea
                    aria-label={translateUi("Review feedback")}
                    className="w-full rounded-md border bg-background p-2 text-sm text-foreground"
                    rows={2}
                    maxLength={4096}
                    value={reviewComment}
                    onChange={(event) => setReviewComment(event.target.value)}
                    placeholder={translateUi(
                      "Keep findings for an explicit successor run.",
                    )}
                  />
                </label>
              </details>
              {hasCapturedPatches && !patchReviewAvailable && (
                <p className="w-full text-sm text-destructive">
                  {translateUi(
                    "Approval is unavailable until every source patch can be loaded for review.",
                  )}
                </p>
              )}
              <Button
                size="md"
                disabled={
                  (hasCapturedPatches && !patchReviewAvailable) ||
                  (Boolean(
                    workflowHarnessReview(
                      pendingApproval.context.payload?.harness_workflow_review,
                    ),
                  ) &&
                    !harnessReviewConfirmed)
                }
                loading={
                  actingOn === `approve-${pendingApproval.approval_request_id}`
                }
                onClick={() =>
                  void runAction(
                    `approve-${pendingApproval.approval_request_id}`,
                    () =>
                      approveAdlcRun(
                        pendingApproval.approval_request_id,
                        reviewComment.trim() || undefined,
                      ),
                  )
                }
              >
                {workflowHarnessReview(
                  pendingApproval.context.payload?.harness_workflow_review,
                )
                  ? "Duyệt bước này"
                  : translateUi("Approve")}
              </Button>
              <Button
                variant="outline"
                size="md"
                disabled={hasCapturedPatches && !patchReviewAvailable}
                loading={
                  actingOn === `reject-${pendingApproval.approval_request_id}`
                }
                onClick={() => {
                  setRejectReason(reviewComment);
                  setShowRejectForm(true);
                }}
              >
                {translateUi("Reject")}
              </Button>
              {showRejectForm && (
                <div
                  className="w-full space-y-3 rounded-md border border-destructive/30 p-3"
                  data-testid="approval-reject-form"
                >
                  <label className="block space-y-1 text-sm">
                    {t("adlc.run.reasonRequired")}
                    <textarea
                      aria-label={t("adlc.run.ariaRejectionReason")}
                      className="w-full rounded border bg-background p-2"
                      maxLength={4096}
                      rows={3}
                      value={rejectReason}
                      onChange={(event) => setRejectReason(event.target.value)}
                    />
                  </label>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setShowRejectForm(false)}
                  >
                    {translateUi("Cancel")}
                  </Button>
                  <Button
                    size="sm"
                    disabled={
                      !rejectReason.trim() ||
                      Boolean(actingOn) ||
                      (hasCapturedPatches && !patchReviewAvailable)
                    }
                    onClick={() =>
                      void runAction(
                        `reject-${pendingApproval.approval_request_id}`,
                        () =>
                          rejectAdlcRun(
                            pendingApproval.approval_request_id,
                            rejectReason.trim(),
                          ),
                      )
                    }
                  >
                    {t("adlc.run.rejectAnd")} {t("adlc.run.sendFeedback")}
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {run.approval_requests
          .filter(
            (approval) =>
              approval.status !== "PENDING" && approval.decision?.comment,
          )
          .map((approval) => (
            <section
              key={approval.approval_request_id}
              aria-label={translateUi("Saved review feedback")}
              className="space-y-2 rounded-md border p-4"
            >
              <h3 className="text-sm font-medium">
                {translateUi("Review feedback ·")}{" "}
                {approval.status.toLowerCase()}
              </h3>
              <p className="whitespace-pre-wrap break-words text-sm">
                {approval.decision?.comment}
              </p>
            </section>
          ))}

        <div
          className="rr-panel"
          role="tabpanel"
          id="review-panel-activity"
          aria-labelledby="review-tab-activity"
          hidden={reviewTab !== "activity"}
        >
          {reviewTab === "activity" && (
            <>
              <HarnessResults
                results={harnessResults}
                sessions={harnessSessions}
                tasks={tasks}
              />
              <HarnessWorkflowResults tasks={tasks} />
              <TaskArtifacts tasks={tasks} />
              <details className="rr-advanced">
                <summary>Contract, memory & cấu hình thực thi</summary>
                <div className="rr-panel">
                  <ContractPanel key={run.id} scope={{ runId: run.id }} />
                  <MemoryPanel
                    key={`memory-${run.id}`}
                    scope={{ runId: run.id }}
                  />
                  <ContractExecutionPanel
                    key={`execution-${run.id}`}
                    scope={{ runId: run.id }}
                  />
                </div>
              </details>
              <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(320px,0.8fr)]">
                <Card className="justify-start bg-background">
                  <CardHeader>
                    <CardTitle>{translateUi("Tasks")}</CardTitle>
                    <CardDescription>
                      {tasks.length} công việc · mở để xem lịch sử thực hiện.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <ol className="divide-y rounded-md border">
                      {tasks.map((task) => {
                        const attemptsUsed = task.retry_count + 1;
                        const maxAttempts = taskMaxAttempts(task);
                        const retryable =
                          task.status === "FAILED" && run.status === "PAUSED";
                        const expanded = expandedTaskId === task.id;
                        const loopTask = isTaskLoop(task);
                        const TaskHeading = loopTask ? "div" : "button";
                        const agentBacked =
                          task.plan_traceability?.package_id ===
                            "coding-agent-opencode" ||
                          task.plan_traceability?.package_id ===
                            "coding-agent-deepseek-harness" ||
                          (task.plan_traceability?.package_id ===
                            "coding-agent" &&
                            task.plan_traceability.package_version === "0.2.0");
                        return (
                          <li
                            key={task.id}
                            className={`flex flex-col gap-3 p-4 ${expanded ? "bg-muted/20" : ""}`}
                          >
                            <div className="flex items-center justify-between gap-4">
                              <TaskHeading
                                className="flex min-w-0 flex-1 items-center gap-2 text-left"
                                {...(loopTask
                                  ? {}
                                  : {
                                      type: "button" as const,
                                      "aria-expanded": expanded,
                                      onClick: () =>
                                        setExpandedTaskId(
                                          expanded ? undefined : task.id,
                                        ),
                                    })}
                              >
                                {!loopTask && (
                                  <ForwardedIconComponent
                                    name={
                                      expanded ? "ChevronDown" : "ChevronRight"
                                    }
                                    className="h-4 w-4 shrink-0 text-muted-foreground"
                                  />
                                )}
                                <div className="min-w-0">
                                  <p className="truncate text-sm font-medium">
                                    {task.name}
                                  </p>
                                  <p className="truncate font-mono text-xs text-muted-foreground">
                                    {task.task_type}
                                  </p>
                                  {task.result?.error && (
                                    <p className="mt-2 break-words text-xs text-destructive">
                                      {task.result.error.code}:{" "}
                                      {task.result.error.message}
                                    </p>
                                  )}
                                  {task.plan_traceability && (
                                    <p
                                      className="truncate font-mono text-[11px] text-muted-foreground"
                                      title={
                                        task.plan_traceability
                                          .resolved_node_digest
                                      }
                                    >
                                      {task.plan_traceability.package_id}@
                                      {task.plan_traceability.package_version}{" "}
                                      {translateUi("· plan task")}{" "}
                                      {task.plan_traceability.plan_task_id.slice(
                                        0,
                                        8,
                                      )}
                                    </p>
                                  )}
                                </div>
                              </TaskHeading>
                              <div className="flex shrink-0 items-center gap-2">
                                {task.status === "RUNNING" && (
                                  <span className="relative flex h-2.5 w-2.5">
                                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500 opacity-60" />
                                    <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500" />
                                  </span>
                                )}
                                {agentBacked && (
                                  <span
                                    title={
                                      loopTask
                                        ? translateUi(
                                            "Coding Agent iteration history below",
                                          )
                                        : translateUi(
                                            "Click to view Coding Agent activity",
                                          )
                                    }
                                    className="flex h-5 w-5 items-center justify-center rounded-full bg-muted"
                                  >
                                    <ForwardedIconComponent
                                      name="Bot"
                                      className="h-3.5 w-3.5 text-muted-foreground"
                                    />
                                  </span>
                                )}
                                <StatusBadge status={task.status} />
                              </div>
                            </div>
                            {!loopTask && subtasksByTask[task.id] && (
                              <SubtaskProgress
                                summary={subtasksByTask[task.id].summary}
                                compact
                              />
                            )}
                            {expanded &&
                              !loopTask &&
                              subtasksByTask[task.id] && (
                                <TaskSubtaskPanel
                                  key={`${run.id}:${task.id}`}
                                  runId={run.id}
                                  taskRunId={task.id}
                                  data={subtasksByTask[task.id]}
                                  isMockData={subtasksByTask[task.id].is_mock}
                                  results={harnessResultsForTask(task.id)}
                                  sessions={harnessSessionsForTask(task.id)}
                                  tasks={tasks}
                                />
                              )}
                            {expanded &&
                              !loopTask &&
                              subtasksLoading[task.id] &&
                              !subtasksByTask[task.id] && (
                                <p role="status">{translateUi("Loading…")}</p>
                              )}
                            {expanded &&
                              !isTaskLoop(task) &&
                              (!subtasksByTask[task.id] ||
                                subtasksByTask[task.id].is_mock) && (
                                <TaskActivityPanel runId={run.id} task={task} />
                              )}
                            {expanded && !loopTask && (
                              <TaskArtifactsList task={task} />
                            )}
                            {isTaskLoop(task) ? (
                              <TaskLoopTimeline
                                runId={run.id}
                                task={task}
                                runStatus={run.status}
                                acting={!!actingOn}
                                onRetry={() =>
                                  void runAction(`retry-${task.id}`, () =>
                                    retryAdlcTask(task.id),
                                  )
                                }
                              />
                            ) : (
                              <AttemptList
                                task={task}
                                events={events}
                                retrySlot={
                                  retryable ? (
                                    attemptsUsed < maxAttempts ? (
                                      <Button
                                        variant="outline"
                                        size="xs"
                                        loading={
                                          actingOn === `retry-${task.id}`
                                        }
                                        onClick={() =>
                                          void runAction(
                                            `retry-${task.id}`,
                                            () => retryAdlcTask(task.id),
                                          )
                                        }
                                      >
                                        {translateUi("Retry")}
                                      </Button>
                                    ) : (
                                      <span className="text-xs text-muted-foreground">
                                        {attemptsUsed}/{maxAttempts}{" "}
                                        {translateUi("attempts used")}
                                      </span>
                                    )
                                  ) : undefined
                                }
                              />
                            )}
                          </li>
                        );
                      })}
                    </ol>
                  </CardContent>
                </Card>

                <Card className="justify-start bg-background">
                  <CardHeader>
                    <CardTitle>{translateUi("Event timeline")}</CardTitle>
                    <CardDescription>
                      {translateUi(
                        "Ordered state changes emitted by the coordinator",
                      )}
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <ol className="space-y-0">
                      {events.map((event, index) => (
                        <li
                          key={event.event_id}
                          className="relative flex gap-3 pb-5 last:pb-0"
                        >
                          {index < events.length - 1 && (
                            <span className="absolute left-[7px] top-4 h-full w-px bg-border" />
                          )}
                          <span className="relative mt-1.5 h-[15px] w-[15px] shrink-0 rounded-full border-2 border-background bg-primary" />
                          <div className="min-w-0 space-y-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <p className="break-all font-mono text-xs">
                                {event.event_type}
                              </p>
                              <StatusBadge status={event.status} />
                            </div>
                            {event.task_run_id &&
                              taskNamesById.get(event.task_run_id) && (
                                <p className="break-all text-xs font-medium">
                                  {taskNamesById.get(event.task_run_id)}
                                  {event.attempt_id &&
                                    attemptNumbersById.get(event.attempt_id) &&
                                    translateUi(" · attempt #{{value0}}", {
                                      value0: attemptNumbersById.get(
                                        event.attempt_id,
                                      ),
                                    })}
                                </p>
                              )}
                            <p className="text-xs text-muted-foreground">
                              #{event.sequence} ·{" "}
                              {formatTime(event.occurred_at)}
                            </p>
                          </div>
                        </li>
                      ))}
                    </ol>
                  </CardContent>
                </Card>
              </div>
            </>
          )}
        </div>
      </div>
    </main>
  );
}
