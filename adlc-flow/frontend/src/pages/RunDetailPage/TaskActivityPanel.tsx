import { translateUi, useUiLocale } from "@/i18n/ui";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import "@/i18n";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import Loading from "@/components/ui/loading";
import { getAdlcTaskActivity } from "@/controllers/API/adlc";
import type {
  AdlcTaskActivity,
  AdlcTaskActivityEntry,
  AdlcTaskRun,
} from "@/types/adlc";

const ACTIVE_STATUSES = new Set(["CREATED", "QUEUED", "READY", "RUNNING"]);
const POLL_INTERVAL_MS = 2000;
const WAITING_NOTES = new Set([
  "HARNESS_SESSION_PENDING",
  "HARNESS_SESSION_BINDING",
]);

function isWaitingNote(note: string): boolean {
  return WAITING_NOTES.has(note);
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

function formatDuration(ms: unknown): string {
  if (typeof ms !== "number" || !Number.isFinite(ms) || ms <= 0)
    return "unknown";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${Math.round(seconds - minutes * 60)}s`;
}

function formatTokens(metrics: Record<string, unknown>): string | null {
  const usage = metrics.token_usage;
  if (!usage || typeof usage !== "object") return null;
  const total = (usage as Record<string, unknown>).total_tokens;
  if (typeof total !== "number") return null;
  return total.toLocaleString();
}

function formatCost(metrics: Record<string, unknown>): string | null {
  const custom = metrics.custom;
  if (!custom || typeof custom !== "object") return null;
  const cost = (custom as Record<string, unknown>).cost;
  if (typeof cost !== "number" || cost <= 0) return null;
  return `$${cost.toFixed(4)}`;
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

export default function TaskActivityPanel({
  runId,
  task,
}: {
  runId: string;
  task: AdlcTaskRun;
}) {
  const { t } = useTranslation();
  useUiLocale();
  const [activity, setActivity] = useState<AdlcTaskActivity>();
  const [error, setError] = useState<string>();
  const inFlight = useRef(false);
  // Consecutive poll failures tolerated before the persistent error banner
  // replaces/annotates the panel; a single hiccup must not flap the UI.
  const failuresRef = useRef(0);

  const load = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const snapshot = await getAdlcTaskActivity(runId, task.id);
      failuresRef.current = 0;
      setActivity(snapshot);
      setError(undefined);
    } catch {
      setError(
        translateUi("Unable to load task activity from the coding agent."),
      );
    } finally {
      inFlight.current = false;
    }
  }, [runId, task.id, activity]);

  const isActive = ACTIVE_STATUSES.has(task.status);

  useEffect(() => {
    void load();
  }, [load, task.status, task.retry_count]);

  useEffect(() => {
    if (!isActive) return;
    const timer = window.setInterval(() => void load(), POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [isActive, load]);

  const agent = activity?.agent;
  const metrics = activity?.metrics ?? {};
  const model =
    typeof activity?.result_metadata?.model_id === "string"
      ? activity.result_metadata.model_id
      : null;
  const tokens = formatTokens(metrics);
  const cost = formatCost(metrics);
  const durationMs = metrics.duration_ms;

  return (
    <div
      className="space-y-4 rounded-md border bg-muted/20 p-4"
      data-testid="task-activity-panel"
    >
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm font-semibold">
          {translateUi("Execution detail")}
        </p>
        {agent?.running ? (
          <Badge variant="emerald" size="tag" className="gap-1">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500 opacity-60" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
            </span>
            LIVE
          </Badge>
        ) : null}
        {agent?.source ? (
          <Badge variant="secondaryStatic" size="tag">
            {agent.source.replace("agent-provider:", "")}
          </Badge>
        ) : null}
        {model ? (
          <Badge variant="secondaryStatic" size="tag">
            {model}
          </Badge>
        ) : null}
        {tokens ? (
          <Badge variant="secondaryStatic" size="tag">
            {tokens} tokens
          </Badge>
        ) : null}
        {cost ? (
          <Badge variant="secondaryStatic" size="tag">
            {cost}
          </Badge>
        ) : null}
      </div>

      <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
        <span>
          {translateUi("Attempt")} {task.retry_count + 1} · {task.task_type}
        </span>
        <span>
          {translateUi("Duration:")} {formatDuration(durationMs)}
        </span>
        {activity?.started_at ? (
          <span>
            {translateUi("Started")}{" "}
            {new Date(activity.started_at).toLocaleTimeString()}
          </span>
        ) : null}
        {activity?.completed_at ? (
          <span>
            {translateUi("Finished")}{" "}
            {new Date(activity.completed_at).toLocaleTimeString()}
          </span>
        ) : null}
        {agent?.session_id ? (
          <span className="font-mono">
            session {agent.session_id.slice(0, 16)}…
          </span>
        ) : null}
      </div>

      {activity?.requirement ? (
        <details>
          <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
            {translateUi("Requirement")}
          </summary>
          <pre className="mt-1 max-h-48 overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-background p-3 font-mono text-[11px] leading-relaxed">
            {activity.requirement}
          </pre>
        </details>
      ) : null}

      {activity?.output_summary ? (
        <details>
          <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
            {translateUi("Agent result")}
          </summary>
          <pre className="mt-1 max-h-64 overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-background p-3 font-mono text-[11px] leading-relaxed">
            {activity.output_summary}
          </pre>
        </details>
      ) : null}

      {activity?.error_code ? (
        <div
          role="alert"
          className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-xs"
        >
          <p className="font-mono font-semibold">{activity.error_code}</p>
          <p className="break-words text-destructive">
            {activity.error_message}
          </p>
        </div>
      ) : null}

      {agent?.note ? (
        <p className="break-words text-xs text-muted-foreground">
          <ForwardedIconComponent
            name="Info"
            className="mr-1 inline h-3.5 w-3.5"
          />
          {translateUi("Agent transcript unavailable:")} {agent.note}
        </p>
      ) : null}

      {agent?.note && isWaitingNote(agent.note) ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loading className="h-4 w-4" />
          {t("adlc.run.waitingDsh")}
        </div>
      ) : null}

      {error ? <p className="text-xs text-destructive">{error}</p> : null}

      {!activity && !error ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loading className="h-4 w-4" />
          {translateUi("Loading agent activity…")}
        </div>
      ) : null}

      {agent && agent.entries.length > 0 ? (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium text-muted-foreground">
              {translateUi("Agent activity")}
              {agent.entries_total > agent.entries.length
                ? translateUi(" (last {{value0}} of {{value1}})", {
                    value0: agent.entries.length,
                    value1: agent.entries_total,
                  })
                : ` (${agent.entries.length})`}
            </p>
            <Button
              variant="ghost"
              size="xs"
              className="text-muted-foreground"
              onClick={() => void load()}
            >
              <ForwardedIconComponent
                name="RefreshCw"
                className="h-3.5 w-3.5"
              />
              {translateUi("Refresh")}
            </Button>
          </div>
          <ol className="max-h-[480px] space-y-0 overflow-y-auto pl-1">
            {agent.entries.map((entry) => (
              <ActivityEntry key={entry.seq} entry={entry} />
            ))}
          </ol>
        </div>
      ) : null}

      {isActive && agent && agent.entries.length === 0 && !agent.note ? (
        <p className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loading className="h-4 w-4" />
          {translateUi("Waiting for the coding agent to start…")}
        </p>
      ) : null}
    </div>
  );
}
