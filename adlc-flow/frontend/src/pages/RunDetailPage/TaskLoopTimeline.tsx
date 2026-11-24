import { translateUi, useUiLocale, formatUiStatus } from "@/i18n/ui";
import { useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  getAdlcSourcePatch,
  getAdlcTaskLoop,
  getAdlcTaskLoopRuntime,
} from "@/controllers/API/adlc";
import useAuthStore from "@/stores/authStore";
import type {
  AdlcLoopIteration,
  AdlcLoopRuntimeView,
  AdlcSourcePatch,
  AdlcTaskLoopInspection,
  AdlcTaskRun,
  WorkflowRunStatus,
} from "@/types/adlc";
import { useTranslation } from "react-i18next";
import i18n from "@/i18n";
import TaskLoopRuntimeDisclosure from "./TaskLoopRuntimeDisclosure";

const loopServices = new Set([
  "agent-provider:task-loop-mock",
  "agent-provider:task-loop-opencode",
  "agent-provider:coding-agent-contract-loop",
  "agent-provider:task-loop-harness",
  "agent-provider:coding-agent-harness-contract-loop",
]);

export function isTaskLoop(task: AdlcTaskRun): boolean {
  return loopServices.has(task.executor?.service ?? "");
}

export function loopStopLabel(reason: string | null): string {
  const labels: Record<string, string> = {
    CHECKS_PASSED: translateUi("All checks passed"),
    TASK_LOOP_CHECKS_FAILED: translateUi(
      "Checks failed; another iteration is needed",
    ),
    TASK_LOOP_BUDGET_EXHAUSTED: translateUi("Iteration limit reached"),
    TASK_LOOP_TIME_BUDGET_EXHAUSTED: translateUi("Time limit reached"),
    TASK_LOOP_TOKEN_BUDGET_EXHAUSTED: translateUi("Token limit reached"),
    TASK_LOOP_COST_BUDGET_EXHAUSTED: translateUi("Cost limit reached"),
    TASK_LOOP_STALLED: translateUi(
      "Stopped after repeated unchanged candidates",
    ),
    TASK_LOOP_CANCELLED: translateUi("Cancelled by the operator"),
    ADLC_RECOVERY_TASK_LOOP_INTERRUPTED: translateUi(
      "Interrupted iteration retained for recovery",
    ),
    TASK_LOOP_DEADLINE_EXCEEDED: translateUi("Iteration timed out"),
    TASK_LOOP_CONTEXT_BUDGET_EXCEEDED: translateUi(
      "The specification exceeds the context limit",
    ),
    TASK_LOOP_RUNTIME_CHANGED: translateUi(
      "Runtime binding changed; start a new reviewed run",
    ),
    TASK_LOOP_LEGACY_RUNTIME_INCOMPATIBLE: translateUi(
      "This old checkpoint requires its original runtime",
    ),
    TASK_LOOP_RUNTIME_CAPABILITY_UNSUPPORTED: translateUi(
      "The runtime does not support this iteration mode",
    ),
    TASK_LOOP_RUNTIME_RESTRICTIONS_UNAVAILABLE: translateUi(
      "The runtime did not acknowledge the required tool restrictions",
    ),
    HARNESS_ITERATION_COST_BUDGET_UNSUPPORTED: translateUi(
      "Harness does not report monetary cost; remove the money budget or choose a priced runtime",
    ),
    HARNESS_ITERATION_RELEASE_MISMATCH: translateUi(
      "Harness iteration plugin is unavailable or does not match this release",
    ),
    HARNESS_ITERATION_INTERRUPTED: translateUi(
      "Harness iteration was interrupted; no model was automatically restarted",
    ),
  };
  return reason
    ? (labels[reason] ?? formatUiStatus(reason, true).toLowerCase())
    : translateUi("Preparing a fresh iteration");
}

function duration(value: number): string {
  return `${Math.round(value / 1000)}s`;
}

function cost(value: number): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: 6 });
}

function IterationPatch({
  runId,
  taskId,
  iteration,
}: {
  runId: string;
  taskId: string;
  iteration: AdlcLoopIteration;
}) {
  useUiLocale();
  const [open, setOpen] = useState(false);
  const [patch, setPatch] = useState<AdlcSourcePatch>();
  const [error, setError] = useState<string>();
  useEffect(() => {
    if (!open || !iteration.patch_artifact_id) return;
    let active = true;
    setPatch(undefined);
    setError(undefined);
    void getAdlcSourcePatch(runId, iteration.patch_artifact_id)
      .then((snapshot) => {
        if (!active) return;
        if (
          snapshot.artifact.workflow_run_id !== runId ||
          snapshot.artifact.task_run_id !== taskId ||
          snapshot.artifact.artifact_id !== iteration.patch_artifact_id ||
          snapshot.artifact.metadata.candidate_digest !==
            iteration.candidate_digest
        ) {
          setError(
            translateUi("This patch does not match the recorded candidate."),
          );
          return;
        }
        setPatch(snapshot);
      })
      .catch(() => {
        if (active)
          setError(
            translateUi("This saved patch is unavailable or has expired."),
          );
      });
    return () => {
      active = false;
    };
  }, [
    open,
    runId,
    taskId,
    iteration.patch_artifact_id,
    iteration.candidate_digest,
  ]);
  if (!iteration.patch_artifact_id) return null;
  return (
    <div className="space-y-2">
      <Button
        variant="outline"
        size="xs"
        ignoreTitleCase
        onClick={() => setOpen((value) => !value)}
      >
        {open ? translateUi("Hide") : translateUi("View")} iteration{" "}
        {iteration.iteration} patch
      </Button>
      {open && !patch && !error && (
        <p role="status" className="text-xs text-muted-foreground">
          {translateUi("Loading saved patch…")}
        </p>
      )}
      {open && error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
      {open &&
        patch?.files.map((file) => (
          <details key={file.file} className="rounded border">
            <summary className="cursor-pointer p-2 text-xs">
              {file.file} · +{file.additions} / -{file.deletions}
            </summary>
            <pre className="max-h-64 overflow-auto border-t p-2 font-mono text-xs">
              {file.patch}
            </pre>
          </details>
        ))}
      {open && patch && patch.files.length === 0 && (
        <p className="text-xs text-muted-foreground">
          {translateUi("No changed files.")}
        </p>
      )}
    </div>
  );
}

export default function TaskLoopTimeline({
  runId,
  task,
  runStatus,
  acting,
  onRetry,
}: {
  runId: string;
  task: AdlcTaskRun;
  runStatus: WorkflowRunStatus;
  acting: boolean;
  onRetry: () => void;
}) {
  useUiLocale();
  const owner = useAuthStore((s) => s.userData?.id);
  const identity = `${owner ?? "unknown"}:${runId}:${task.id}`;
  const currentIdentity = useRef(identity);
  currentIdentity.current = identity;
  const [snapshot, setSnapshot] = useState<{
    key: string;
    data: AdlcTaskLoopInspection;
  }>();
  const [runtimeSnapshot, setRuntimeSnapshot] = useState<{
    key: string;
    value: AdlcLoopRuntimeView | null;
  }>();
  const [error, setError] = useState<string>();
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    const key = identity;
    setError(undefined);
    const poll = async () => {
      try {
        const data = await getAdlcTaskLoop(runId, task.id);
        if (!active || currentIdentity.current !== key) return;
        if (data.workflow_run_id !== runId || data.task_run_id !== task.id)
          throw new Error(i18n.t("adlc.run.scopeMismatch"));
        setSnapshot({ key, data });
        setError(undefined);
      } catch {
        if (active && currentIdentity.current === key)
          setError(translateUi("Unable to refresh iteration history."));
      } finally {
        if (
          active &&
          [
            "CREATED",
            "QUEUED",
            "RUNNING",
            "PAUSED",
            "WAITING_APPROVAL",
          ].includes(runStatus)
        ) {
          timer = window.setTimeout(() => void poll(), 1500);
        }
      }
    };
    void poll();
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [
    runId,
    task.id,
    task.status,
    task.current_attempt_id,
    runStatus,
    refresh,
    identity,
  ]);
  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    const key = identity;
    const readRuntime = async () => {
      try {
        const value = await getAdlcTaskLoopRuntime(runId, task.id);
        if (active && currentIdentity.current === key)
          setRuntimeSnapshot({ key, value });
      } catch {
        if (active && currentIdentity.current === key)
          setRuntimeSnapshot({ key, value: null });
      } finally {
        if (
          active &&
          [
            "CREATED",
            "QUEUED",
            "RUNNING",
            "PAUSED",
            "WAITING_APPROVAL",
          ].includes(runStatus)
        )
          timer = window.setTimeout(() => void readRuntime(), 1500);
      }
    };
    void readRuntime();
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [identity, runId, task.id, task.current_attempt_id, runStatus, refresh]);
  const view = snapshot?.key === identity ? snapshot.data : undefined;
  const retryAllowed =
    !error &&
    view?.history_complete &&
    view?.can_retry &&
    task.status === "FAILED" &&
    runStatus === "PAUSED";
  const passed = view?.stop_reason === "CHECKS_PASSED";
  const awaitingReview =
    passed &&
    ["WAITING_APPROVAL", "SUCCEEDED"].includes(task.status) &&
    runStatus === "WAITING_APPROVAL";

  return (
    <section
      aria-label={translateUi("{{value0}} iteration timeline", {
        value0: task.name,
      })}
      className="space-y-3 rounded-md border bg-background p-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-medium">
          {translateUi("Task loop ·")} {view?.iterations.at(-1)?.iteration ?? 0}
          {view?.max_iterations ? ` / ${view.max_iterations}` : ""} iterations
        </h3>
        <div className="flex gap-2">
          {view?.mode === "MOCK" && (
            <Badge variant="secondaryStatic" size="tag">
              {translateUi("Mock checks")}
            </Badge>
          )}
          {retryAllowed && (
            <Button
              variant="outline"
              size="xs"
              disabled={acting}
              loading={acting}
              onClick={onRetry}
            >
              {view?.recovery_available
                ? translateUi("Recover saved result")
                : translateUi("Retry iteration")}
            </Button>
          )}
          <Button
            variant="ghost"
            size="xs"
            onClick={() => setRefresh((value) => value + 1)}
          >
            {translateUi("Refresh history")}
          </Button>
        </div>
      </div>
      <TaskLoopRuntimeDisclosure
        value={runtimeSnapshot?.key === identity ? runtimeSnapshot.value : null}
        runId={runId}
        taskId={task.id}
        mock={view?.mode === "MOCK"}
      />
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
      {!view && !error && (
        <p role="status" className="text-xs text-muted-foreground">
          {translateUi("Loading iteration history…")}
        </p>
      )}
      {view && (
        <>
          {!view.history_complete && (
            <p role="status" className="text-xs text-muted-foreground">
              {translateUi(
                "Full checkpoint history is unavailable. Showing the saved run record; iteration controls are unavailable.",
              )}
            </p>
          )}
          <p className="text-sm">
            {awaitingReview
              ? translateUi(
                  "Checks passed. Review and approve the exact candidate below.",
                )
              : passed && runStatus === "SUCCEEDED"
                ? translateUi("Verified candidate approved.")
                : passed && runStatus === "FAILED"
                  ? translateUi(
                      "Checks passed. The run was rejected or failed; its candidate is preserved for a successor run.",
                    )
                  : loopStopLabel(view.stop_reason)}
          </p>
          {view.mode === "MOCK" && (
            <p className="text-xs text-muted-foreground">
              {translateUi(
                "Mock file comparisons; behavioral tests and provider usage were not measured.",
              )}
            </p>
          )}
          <div
            className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground"
            aria-label={translateUi("Loop resource usage")}
          >
            {view.elapsed_ms !== null && (
              <span>
                {translateUi("Time")} {duration(view.elapsed_ms)}
                {view.max_duration_ms !== null
                  ? ` / ${duration(view.max_duration_ms)}`
                  : ""}
              </span>
            )}
            {view.total_tokens !== null && (
              <span>
                {translateUi("Tokens")} {view.total_tokens.toLocaleString()}
                {view.max_total_tokens !== null
                  ? ` / ${view.max_total_tokens.toLocaleString()}`
                  : ""}
              </span>
            )}
            {view.total_cost !== null && (
              <span>
                {translateUi("Reported cost")} {cost(view.total_cost)}
                {view.max_total_cost !== null
                  ? ` / ${cost(view.max_total_cost)}`
                  : ""}
              </span>
            )}
          </div>
          {view.current_candidate_id && (
            <p className="break-all font-mono text-xs text-muted-foreground">
              {translateUi("Current candidate")} {view.current_candidate_id}
            </p>
          )}
          {view.current_candidate_digest && (
            <p className="break-all font-mono text-[11px] text-muted-foreground">
              {view.current_candidate_digest}
            </p>
          )}
          {view.stopped && !passed && runStatus !== "CANCELLED" && (
            <p className="text-xs text-muted-foreground">
              {translateUi(
                "The candidate and findings are preserved. Address the stopping reason in a new run.",
              )}
            </p>
          )}
          <ol className="space-y-2">
            {view.iterations.map((iteration, index) => (
              <li key={iteration.attempt_id}>
                <details
                  open={index === view.iterations.length - 1}
                  className="rounded-md border"
                >
                  <summary className="cursor-pointer p-2 text-xs">
                    {translateUi("Iteration")} {iteration.iteration} ·{" "}
                    {iteration.status === "IN_PROGRESS"
                      ? {
                          RESERVED: translateUi("Preparing session"),
                          AGENT_RUNNING: translateUi("Agent running"),
                          CANDIDATE_CAPTURED: translateUi("Running checks"),
                          VERIFIED: translateUi("Checks recorded"),
                          FINISHED: translateUi("Finishing"),
                        }[iteration.phase]
                      : formatUiStatus(iteration.status, true).toLowerCase()}
                  </summary>
                  <div className="space-y-2 border-t p-2">
                    <p className="break-all font-mono text-[11px] text-muted-foreground">
                      {translateUi("Fresh session")}{" "}
                      {iteration.session_id ?? "pending"}
                    </p>
                    {iteration.candidate_id && (
                      <p className="break-all font-mono text-[11px] text-muted-foreground">
                        {translateUi("Candidate")} {iteration.candidate_id}
                      </p>
                    )}
                    {iteration.candidate_digest && (
                      <p className="break-all font-mono text-[11px] text-muted-foreground">
                        {translateUi("Candidate digest")}{" "}
                        {iteration.candidate_digest}
                      </p>
                    )}
                    {iteration.parent_candidate_id && (
                      <p className="break-all font-mono text-[11px] text-muted-foreground">
                        {translateUi("Based on")}{" "}
                        {iteration.parent_candidate_id}
                      </p>
                    )}
                    {iteration.changed_paths.length > 0 && (
                      <p className="break-words text-xs">
                        {translateUi("Candidate changes:")}{" "}
                        {iteration.changed_paths.join(", ")}
                      </p>
                    )}
                    <ul className="space-y-1">
                      {iteration.checks.map((check) => (
                        <li
                          key={`${check.kind}:${check.check_id}`}
                          className="flex items-start gap-2 text-xs"
                        >
                          <Badge
                            variant={
                              check.passed ? "successStatic" : "errorStatic"
                            }
                            size="tag"
                          >
                            {check.passed
                              ? translateUi("Pass")
                              : translateUi("Fail")}
                          </Badge>
                          <span>
                            {check.kind === "CONTRACT"
                              ? translateUi("Contract")
                              : check.kind === "MOCK"
                                ? translateUi("Mock")
                                : translateUi("Test")}
                            : {check.label}
                            {check.executed_tests !== null &&
                              translateUi(
                                " · {{value0}} tests · exit {{value1}}",
                                {
                                  value0: check.executed_tests,
                                  value1: check.exit_code,
                                },
                              )}
                            {check.timed_out && translateUi(" · timed out")}
                          </span>
                        </li>
                      ))}
                    </ul>
                    {iteration.checks.length === 0 && (
                      <p className="text-xs text-muted-foreground">
                        {translateUi(
                          "Checks have not been recorded for this iteration.",
                        )}
                      </p>
                    )}
                    <p className="text-xs text-muted-foreground">
                      {iteration.duration_ms !== null &&
                        `${duration(iteration.duration_ms)} · `}
                      {iteration.total_tokens !== null &&
                        translateUi("{{value0}} tokens · ", {
                          value0: iteration.total_tokens,
                        })}
                      {iteration.cost !== null &&
                        translateUi("reported cost {{value0}}", {
                          value0: cost(iteration.cost),
                        })}
                    </p>
                    {iteration.stop_reason && (
                      <p className="text-xs">
                        {loopStopLabel(iteration.stop_reason)}
                      </p>
                    )}
                    <IterationPatch
                      runId={runId}
                      taskId={task.id}
                      iteration={iteration}
                    />
                  </div>
                </details>
              </li>
            ))}
          </ol>
          {view.failure_patterns.length > 0 && (
            <div className="space-y-1 text-xs">
              <p className="font-medium">{translateUi("Recurring failures")}</p>
              {view.failure_patterns.map((pattern) => (
                <p key={`${pattern.kind}:${pattern.check_id}`}>
                  {pattern.label} {translateUi("failed in iterations")}{" "}
                  {pattern.iterations.join(", ")}. Use these findings to improve
                  the specification, tools, or checks for a successor run.
                </p>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}
