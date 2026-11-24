import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import "@/i18n";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import Loading from "@/components/ui/loading";
import { getAdlcSubtaskActivity } from "@/controllers/API/adlc";
import type {
  AdlcSubtaskRun,
  AdlcTaskActivityEntry,
  AdlcTaskAgentActivity,
} from "@/types/adlc";

interface SubtaskDetailProps {
  runId: string;
  taskRunId: string;
  subtask: AdlcSubtaskRun;
}

const ACTIVE_STATUSES = new Set(["pending", "ready", "running"]);
const POLL_INTERVAL_MS = 2000;
const WAITING_NOTES = new Set([
  "HARNESS_SESSION_PENDING",
  "HARNESS_SESSION_BINDING",
  "SUBTASK_NOT_REGISTERED",
]);

function isWaitingNote(note: string): boolean {
  return WAITING_NOTES.has(note);
}

function formatDuration(ms: number | null | undefined): string {
  if (typeof ms !== "number" || !Number.isFinite(ms) || ms <= 0)
    return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${Math.round(seconds - minutes * 60)}s`;
}

function formatTimestamp(ts: string | null | undefined): string {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function statusVariant(
  status: AdlcSubtaskRun["status"],
): "successStatic" | "errorStatic" | "emerald" | "secondaryStatic" {
  if (status === "succeeded") return "successStatic";
  if (status === "failed" || status === "cancelled") return "errorStatic";
  if (status === "running" || status === "ready") return "emerald";
  return "secondaryStatic";
}

function entryIcon(kind: string): string {
  if (kind === "reasoning") return "Brain";
  if (kind === "tool") return "Wrench";
  if (kind === "patch") return "FileDiff";
  if (kind === "prompt") return "User";
  if (kind === "text") return "Bot";
  if (kind === "error") return "AlertTriangle";
  return "Pulse";
}

function entryVariant(kind: string): string {
  if (kind === "prompt") return "text-primary";
  if (kind === "reasoning") return "text-muted-foreground italic";
  if (kind === "text") return "text-foreground";
  if (kind === "tool") return "text-accent-foreground";
  if (kind === "patch") return "text-emerald-700 dark:text-emerald-400";
  if (kind === "error") return "text-destructive";
  return "text-muted-foreground";
}

function ActivityEntry({ entry }: { entry: AdlcTaskActivityEntry }) {
  return (
    <li className="relative flex gap-3 pb-3 last:pb-0">
      <span className="relative mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border bg-background">
        <ForwardedIconComponent
          name={entryIcon(entry.kind)}
          className="h-3.5 w-3.5 text-muted-foreground"
        />
      </span>
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <p
            className={`break-words text-xs font-medium ${entryVariant(entry.kind)}`}
          >
            {entry.title}
          </p>
          {entry.status === "pending" || entry.status === "running" ? (
            <Badge variant="emerald" size="tag">
              running
            </Badge>
          ) : null}
          {entry.status === "error" ? (
            <Badge variant="errorStatic" size="tag">
              error
            </Badge>
          ) : null}
          {entry.occurred_at ? (
            <span className="text-[11px] text-muted-foreground">
              {new Date(entry.occurred_at).toLocaleTimeString()}
            </span>
          ) : null}
        </div>
        {entry.detail ? (
          <details className="group">
            <summary className="cursor-pointer select-none whitespace-pre-wrap break-words font-mono text-[11px] text-muted-foreground line-clamp-3 group-open:line-clamp-none">
              {entry.detail}
            </summary>
          </details>
        ) : null}
      </div>
    </li>
  );
}

/**
 * Detail panel for a single subtask. Shows status, timing, dependencies,
 * result/error if available, and the live DSH transcript (execution detail)
 * fetched from the subtask's own DSH session.
 */
export default function SubtaskDetail({
  runId,
  taskRunId,
  subtask,
}: SubtaskDetailProps) {
  const { t } = useTranslation();
  const [activity, setActivity] = useState<AdlcTaskAgentActivity>();
  const [error, setError] = useState<string>();
  const inFlight = useRef(false);
  const failuresRef = useRef(0);

  const load = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const snapshot = await getAdlcSubtaskActivity(runId, taskRunId, subtask.id);
      failuresRef.current = 0;
      setActivity(snapshot);
      setError(undefined);
    } catch {
      failuresRef.current += 1;
      if (failuresRef.current >= 3 || !activity) {
        setError(t("adlc.run.subtaskActivityFailed"));
      }
    } finally {
      inFlight.current = false;
    }
  }, [runId, taskRunId, subtask.id, activity]);

  const isActive = ACTIVE_STATUSES.has(subtask.status);

  useEffect(() => {
    failuresRef.current = 0;
    void load();
  }, [load, subtask.status]);

  useEffect(() => {
    if (!isActive) return;
    const timer = window.setInterval(() => void load(), POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [isActive, load]);

  return (
    <div
      className="space-y-3 rounded-md border bg-muted/20 p-4"
      data-testid="subtask-detail"
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <h4 className="text-sm font-semibold">{subtask.name}</h4>
          {subtask.description && (
            <p className="mt-1 text-xs text-muted-foreground">
              {subtask.description}
            </p>
          )}
        </div>
        <Badge variant={statusVariant(subtask.status)} size="tag">
          {subtask.status}
        </Badge>
      </div>

      <dl className="grid grid-cols-2 gap-2 text-xs">
        <div>
          <dt className="text-muted-foreground">{t("adlc.run.started")}</dt>
          <dd className="font-mono">{formatTimestamp(subtask.started_at)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("adlc.run.completed")}</dt>
          <dd className="font-mono">{formatTimestamp(subtask.completed_at)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("adlc.run.duration")}</dt>
          <dd className="font-mono">{formatDuration(subtask.duration_ms)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("adlc.run.trigger")}</dt>
          <dd className="font-mono">{subtask.trigger}</dd>
        </div>
        {subtask.dependencies.length > 0 && (
          <div className="col-span-2">
            <dt className="text-muted-foreground">{t("adlc.bp.dependencies")}</dt>
            <dd className="flex flex-wrap gap-1">
              {subtask.dependencies.map((dep) => (
                <Badge key={dep} variant="secondaryStatic" size="tag">
                  {dep}
                </Badge>
              ))}
            </dd>
          </div>
        )}
      </dl>

      {subtask.error && (
        <div
          className="rounded-md border border-red-200 bg-red-50 p-2 text-xs dark:border-red-900 dark:bg-red-950"
          data-testid="subtask-error"
        >
          <div className="flex items-center gap-1 font-semibold text-red-700 dark:text-red-400">
            <ForwardedIconComponent name="AlertTriangle" className="h-3.5 w-3.5" />
            {subtask.error.code}
          </div>
          <p className="mt-1 text-red-600 dark:text-red-300">
            {subtask.error.message}
          </p>
        </div>
      )}

      {subtask.result && Object.keys(subtask.result).length > 0 && (
        <div
          className="rounded-md border bg-background p-2 text-xs"
          data-testid="subtask-result"
        >
          <div className="mb-1 font-semibold text-muted-foreground">{t("adlc.run.result")}</div>
          <pre className="overflow-auto text-xs">
            {JSON.stringify(subtask.result, null, 2)}
          </pre>
        </div>
      )}

      <div
        className="space-y-2 rounded-md border bg-background p-3"
        data-testid="subtask-execution-detail"
      >
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-xs font-semibold text-muted-foreground">
            {t("adlc.run.executionDetail")}
          </p>
          {activity?.running ? (
            <Badge variant="emerald" size="tag" className="gap-1">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500 opacity-60" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
              </span>
              LIVE
            </Badge>
          ) : null}
          {activity?.source ? (
            <Badge variant="secondaryStatic" size="tag">
              {activity.source.replace("agent-provider:", "")}
            </Badge>
          ) : null}
          {activity?.session_id ? (
            <span className="font-mono text-[11px] text-muted-foreground">
              {t("adlc.run.sessionPrefix", { id: activity.session_id.slice(0, 16) })}
            </span>
          ) : null}
        </div>

        {activity?.note ? (
          <p className="break-words text-xs text-muted-foreground">
            <ForwardedIconComponent
              name="Info"
              className="mr-1 inline h-3.5 w-3.5"
            />
            {activity.note === "HARNESS_SESSION_BINDING" ? (
              <>
                {t("adlc.run.connectingDsh")}
                <span className="ml-1 text-[10px]">{t("adlc.run.sessionCreating")}</span>
              </>
            ) : activity.note === "HARNESS_SESSION_PENDING" ? (
              <>
                {t("adlc.run.waitingDshStart")}
                <span className="ml-1 text-[10px]">{t("adlc.run.noAttemptYet")}</span>
              </>
            ) : activity.note === "SUBTASK_NOT_REGISTERED" ? (
              <>
                {t("adlc.run.subtaskNotRegistered")}
                <span className="ml-1 text-[10px]">{t("adlc.run.mockOrPre")}</span>
              </>
            ) : (
              <>{t("adlc.run.transcriptUnavailable", { note: activity.note })}</>
            )}
          </p>
        ) : null}

        {activity?.note && isWaitingNote(activity.note) ? (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loading className="h-4 w-4" />
            {t("adlc.run.waitingDsh")}
          </div>
        ) : null}

        {error ? <p className="text-xs text-destructive">{error}</p> : null}

        {!activity && !error ? (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loading className="h-4 w-4" />
            {t("adlc.run.loadingAgentActivity")}
          </div>
        ) : null}

        {activity && activity.entries.length > 0 ? (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-xs font-medium text-muted-foreground">
                {t("adlc.run.agentActivity")}
                {activity.entries_total > activity.entries.length
                  ? t("adlc.run.lastOf", { count: activity.entries.length, total: activity.entries_total })
                  : ` (${activity.entries.length})`}
              </p>
              <Button
                variant="ghost"
                size="xs"
                className="text-muted-foreground"
                onClick={() => void load()}
              >
                <ForwardedIconComponent name="RefreshCw" className="h-3.5 w-3.5" />
                Refresh
              </Button>
            </div>
            <ol className="max-h-[480px] space-y-0 overflow-y-auto pl-1">
              {activity.entries.map((entry) => (
                <ActivityEntry key={entry.seq} entry={entry} />
              ))}
            </ol>
          </div>
        ) : null}

        {isActive && activity && activity.entries.length === 0 && !activity.note ? (
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <Loading className="h-4 w-4" />
            {t("adlc.run.waitingAgentStart")}
          </p>
        ) : null}
      </div>
    </div>
  );
}
