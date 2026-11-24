import {
  translateUi,
  useUiLocale,
  getUiLanguage,
  formatUiStatus,
} from "@/i18n/ui";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import "@/i18n";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import type { AdlcRunEvent, AdlcTaskRun } from "@/types/adlc";

export interface AdlcAttemptSummary {
  attemptId: string;
  number: number;
  status: string;
  errorCode?: string;
  startedAt?: string;
  finishedAt?: string;
}

const TERMINAL_ATTEMPT_EVENTS: Record<string, string> = {
  "task_run.succeeded": "SUCCEEDED",
  "task_run.failed": "FAILED",
  "task_run.cancelled": "CANCELLED",
};

function isTerminalStatus(status: string): boolean {
  return (
    status === "SUCCEEDED" || status === "FAILED" || status === "CANCELLED"
  );
}

export function buildTaskAttempts(
  task: AdlcTaskRun,
  events: AdlcRunEvent[],
): AdlcAttemptSummary[] {
  const attempts = new Map<string, AdlcAttemptSummary>();
  const order: string[] = [];

  for (const event of events) {
    if (event.task_run_id !== task.id || !event.attempt_id) continue;
    let attempt = attempts.get(event.attempt_id);
    if (!attempt) {
      attempt = {
        attemptId: event.attempt_id,
        number: order.length + 1,
        status: "RUNNING",
      };
      attempts.set(event.attempt_id, attempt);
      order.push(event.attempt_id);
    }
    if (
      event.event_type === "task_run.started" ||
      event.event_type === "task_run.resumed"
    ) {
      attempt.startedAt ??= event.occurred_at;
      if (!isTerminalStatus(attempt.status)) attempt.status = "RUNNING";
    } else if (event.event_type === "task_run.waiting_approval") {
      if (!isTerminalStatus(attempt.status)) {
        attempt.status = "WAITING_APPROVAL";
      }
    } else if (event.event_type === "task_run.ready") {
      if (!isTerminalStatus(attempt.status) && !attempt.startedAt) {
        attempt.status = "READY";
      }
    } else if (event.event_type in TERMINAL_ATTEMPT_EVENTS) {
      attempt.status = TERMINAL_ATTEMPT_EVENTS[event.event_type];
      attempt.finishedAt ??= event.occurred_at;
      if (attempt.status === "FAILED") {
        const code = event.payload?.error_code;
        if (typeof code === "string") attempt.errorCode = code;
      }
    }
  }

  if (order.length === 0 && task.status !== "PENDING") {
    return [
      {
        attemptId: task.current_attempt_id ?? "",
        number: 1,
        status: task.status,
        errorCode: task.result?.error?.code ?? undefined,
        startedAt: task.started_at,
        finishedAt: task.completed_at,
      },
    ];
  }

  return order.map(
    (attemptId) => attempts.get(attemptId) as AdlcAttemptSummary,
  );
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

function formatTime(value: string): string {
  return new Intl.DateTimeFormat(getUiLanguage(), {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export default function AttemptList({
  task,
  events,
  retrySlot,
}: {
  task: AdlcTaskRun;
  events: AdlcRunEvent[];
  retrySlot?: ReactNode;
}) {
  useUiLocale();
  const attempts = buildTaskAttempts(task, events);
  if (attempts.length === 0) return null;

  return (
    <div className="space-y-1.5 pl-3">
      <p className="text-xs font-medium text-muted-foreground">
        {translateUi("Attempts")}
      </p>
      <ol className="space-y-1.5">
        {attempts.map((attempt) => {
          const isLatest = attempt.number === attempts.length;
          return (
            <li
              key={attempt.attemptId || `attempt-${attempt.number}`}
              className="flex flex-wrap items-center gap-2"
            >
              <span className="font-mono text-xs text-muted-foreground">
                {translateUi("Attempt #")}
                {attempt.number}
              </span>
              <Badge variant={statusVariant(attempt.status)} size="tag">
                {formatUiStatus(attempt.status, true)}
              </Badge>
              {attempt.errorCode && (
                <span className="break-all font-mono text-xs text-destructive">
                  {attempt.errorCode}
                </span>
              )}
              <span className="text-xs text-muted-foreground">
                {attempt.startedAt
                  ? formatTime(attempt.startedAt)
                  : translateUi("not started")}
                {attempt.finishedAt
                  ? ` → ${formatTime(attempt.finishedAt)}`
                  : ""}
              </span>
              {isLatest && retrySlot}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
