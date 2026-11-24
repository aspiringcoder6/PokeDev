import {
  translateUi,
  useUiLocale,
  formatUiDateTime,
  formatUiStatus,
} from "@/i18n/ui";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { listAdlcRuns } from "@/controllers/API/adlc";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import type { AdlcRunListResponse, WorkflowRunStatus } from "@/types/adlc";
import { useTranslation } from "react-i18next";
import "@/i18n";

const PAGE_SIZE = 25;
const STATUSES: WorkflowRunStatus[] = [
  "CREATED",
  "QUEUED",
  "RUNNING",
  "WAITING_APPROVAL",
  "PAUSED",
  "SUCCEEDED",
  "FAILED",
  "CANCELLED",
];

function statusVariant(status: WorkflowRunStatus): BadgeProps["variant"] {
  if (status === "SUCCEEDED") return "successStatic";
  if (status === "FAILED" || status === "CANCELLED") return "errorStatic";
  if (status === "WAITING_APPROVAL" || status === "PAUSED")
    return "purpleStatic";
  return "secondaryStatic";
}

function formatTime(value: string): string {
  return formatUiDateTime(new Date(value));
}

export default function RunHistoryPage({
  reviewsOnly = false,
}: {
  reviewsOnly?: boolean;
}) {
  useUiLocale();
  const navigate = useCustomNavigate();
  const [params, setParams] = useSearchParams();
  const rawStatus = params.get("status");
  const status = reviewsOnly
    ? "WAITING_APPROVAL"
    : STATUSES.find((item) => item === rawStatus);
  const flowId = params.get("flowId") || undefined;
  const rawOffset = Number(params.get("offset") ?? 0);
  const offset =
    Number.isSafeInteger(rawOffset) && rawOffset >= 0 ? rawOffset : 0;
  const [page, setPage] = useState<AdlcRunListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let current = true;
    setLoading(true);
    setError(null);
    listAdlcRuns({ status, flowId, limit: PAGE_SIZE, offset })
      .then((response) => {
        if (current) setPage(response);
      })
      .catch(() => {
        if (current) {
          setPage(null);
          setError(
            translateUi(
              "Unable to load run history. Check that ADLC is available, then refresh.",
            ),
          );
        }
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [status, flowId, offset, refresh]);

  function updateFilter(key: string, value?: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "offset") next.delete("offset");
    setParams(next);
  }

  return (
    <main className="h-full overflow-auto p-6 md:p-8">
      <div className="mx-auto flex max-w-6xl flex-col gap-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold">
              {reviewsOnly ? translateUi("Reviews") : translateUi("Runs")}
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">
              {reviewsOnly
                ? translateUi(
                    "Runs waiting for an authorized human decision. Open a run to inspect its exact evidence before approving or rejecting.",
                  )
                : translateUi(
                    "Follow current work and reopen saved runs to inspect results or continue reviews.",
                  )}
            </p>
          </div>
          <Button
            variant="outline"
            onClick={() => setRefresh((value) => value + 1)}
            disabled={loading}
          >
            <ForwardedIconComponent name="RefreshCw" className="mr-2 h-4 w-4" />
            {translateUi("Refresh")}
          </Button>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <label htmlFor="run-history-status" className="text-sm font-medium">
            {translateUi("Status")}
          </label>
          <select
            id="run-history-status"
            className="rounded-md border bg-background px-3 py-2 text-sm"
            value={status ?? ""}
            disabled={reviewsOnly}
            onChange={(event) => updateFilter("status", event.target.value)}
          >
            <option value="">{translateUi("All statuses")}</option>
            {STATUSES.map((item) => (
              <option key={item} value={item}>
                {formatUiStatus(item, true)}
              </option>
            ))}
          </select>
          {flowId && (
            <Button variant="ghost" onClick={() => updateFilter("flowId")}>
              {translateUi("Clear workflow filter")}
            </Button>
          )}
        </div>

        {loading && (
          <p role="status" className="text-sm text-muted-foreground">
            {translateUi("Loading run history…")}
          </p>
        )}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {!loading && !error && page && (
          <>
            {page.runs.length === 0 ? (
              <Card>
                <CardContent className="p-6">
                  <h2 className="font-medium">
                    {reviewsOnly
                      ? translateUi("Nothing waiting for review")
                      : translateUi("No saved runs found")}
                  </h2>
                  <p className="mt-2 text-sm text-muted-foreground">
                    {reviewsOnly
                      ? translateUi(
                          "New run approvals will appear here. Open Runs to inspect past decisions.",
                        )
                      : translateUi(
                          "Start a reviewed workflow, or change the status filter to find earlier work.",
                        )}
                  </p>
                </CardContent>
              </Card>
            ) : (
              <ul
                aria-label={translateUi("Saved runs")}
                className="flex flex-col gap-3"
              >
                {page.runs.map((run) => (
                  <li key={run.id}>
                    <Card>
                      <CardContent className="flex flex-wrap items-center justify-between gap-4 p-5">
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-3">
                            <h2 className="break-words font-medium">
                              {run.name}
                            </h2>
                            <Badge
                              variant={statusVariant(run.status)}
                              size="tag"
                            >
                              {formatUiStatus(run.status, true)}
                            </Badge>
                          </div>
                          <p className="mt-2 text-sm text-muted-foreground">
                            {run.execution_mode === "EXECUTION_PLAN"
                              ? translateUi("Blueprint plan")
                              : translateUi("Legacy flow")}
                            {" · "}
                            {run.completed_task_count}/{run.task_count}{" "}
                            {translateUi("tasks completed")}
                          </p>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {translateUi("Started")}{" "}
                            {formatTime(run.created_at)}{" "}
                            {translateUi("· Updated")}{" "}
                            {formatTime(run.updated_at)}
                          </p>
                          <p className="mt-1 break-all font-mono text-xs text-muted-foreground">
                            {run.id}
                          </p>
                        </div>
                        <Button
                          variant="outline"
                          aria-label={translateUi("Open run {{value0}}", {
                            value0: run.name,
                          })}
                          onClick={() =>
                            navigate(`/runs/${encodeURIComponent(run.id)}`)
                          }
                        >
                          {translateUi("Open run")}
                        </Button>
                      </CardContent>
                    </Card>
                  </li>
                ))}
              </ul>
            )}
            <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
              <span className="text-muted-foreground">
                {page.total === 0
                  ? translateUi("0 runs")
                  : page.runs.length === 0
                    ? translateUi("0 of {{value0}} runs on this page", {
                        value0: page.total,
                      })
                    : translateUi("{{value0}}–{{value1}} of {{value2}} runs", {
                        value0: offset + 1,
                        value1: offset + page.runs.length,
                        value2: page.total,
                      })}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  disabled={offset === 0}
                  onClick={() =>
                    updateFilter(
                      "offset",
                      String(Math.max(0, offset - PAGE_SIZE)),
                    )
                  }
                >
                  {translateUi("Previous")}
                </Button>
                <Button
                  variant="outline"
                  disabled={offset + page.limit >= page.total}
                  onClick={() =>
                    updateFilter("offset", String(offset + PAGE_SIZE))
                  }
                >
                  {translateUi("Next")}
                </Button>
              </div>
            </div>
          </>
        )}
      </div>
    </main>
  );
}
