import { translateUi, useUiLocale, formatUiStatus } from "@/i18n/ui";
import { SanitizedMarkdown } from "@/components/core/sanitizedMarkdown";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type {
  AdlcHarnessRunResult,
  AdlcHarnessRunSession,
  AdlcHarnessSessionResult,
  AdlcTaskRun,
} from "@/types/adlc";
import { useTranslation } from "react-i18next";
import "@/i18n";

function resultOutput(output: unknown): {
  summary?: string;
  structured?: unknown;
} {
  if (typeof output === "string") return { summary: output };
  if (output !== null && typeof output === "object" && !Array.isArray(output)) {
    const { summary, ...structured } = output as Record<string, unknown>;
    if (typeof summary === "string") {
      return {
        summary,
        structured: Object.keys(structured).length > 0 ? structured : undefined,
      };
    }
  }
  return { structured: output };
}

function downloadResult(attemptId: string, result: AdlcHarnessSessionResult) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }),
  );
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `harness-result-${attemptId}.json`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export default function HarnessResults({
  results,
  sessions,
  tasks,
  embedded = false,
}: {
  results: AdlcHarnessRunResult[];
  sessions: AdlcHarnessRunSession[];
  tasks: AdlcTaskRun[];
  embedded?: boolean;
}) {
  useUiLocale();
  // A callback-accepted ADLC copy always wins over a transient live preview.
  const storedAttempts = new Set(results.map((entry) => entry.attempt_id));
  const entries = [
    ...results.map((entry) => ({
      ...entry,
      stored: true,
      awaitingSubmit: false,
    })),
    ...sessions.flatMap((entry) =>
      entry.session.result && !storedAttempts.has(entry.attempt_id)
        ? [
            {
              attempt_id: entry.attempt_id,
              task_run_id: entry.task_run_id,
              attempt_status: entry.attempt_status,
              result: entry.session.result,
              stored_at: entry.session.updated_at,
              stored: false,
              awaitingSubmit:
                entry.session.submission_mode === "MANUAL" &&
                entry.session.status === "READY_FOR_SUBMISSION",
            },
          ]
        : [],
    ),
  ];
  if (entries.length === 0) return null;

  return (
    <section className="space-y-4" aria-label={translateUi("Agent results")}>
      <h2 className="text-lg font-semibold">{translateUi("Agent results")}</h2>
      {entries.map((entry) => {
        const { result } = entry;
        const task = tasks.find(
          (candidate) => candidate.id === entry.task_run_id,
        );
        const output = resultOutput(result.output);
        const route = result.metadata?.driver;
        return (
          <Card key={entry.attempt_id} className="bg-background">
            <CardHeader>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <CardTitle>
                  {task?.name ?? translateUi("Agent result")}
                </CardTitle>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge
                    variant={
                      result.status === "SUCCEEDED"
                        ? "successStatic"
                        : "errorStatic"
                    }
                    size="tag"
                  >
                    {result.status ?? entry.attempt_status}
                  </Badge>
                  <Button
                    variant="outline"
                    size="xs"
                    onClick={() => downloadResult(entry.attempt_id, result)}
                  >
                    {translateUi("Download result JSON")}
                  </Button>
                </div>
              </div>
              <CardDescription>
                {entry.stored
                  ? translateUi(
                      "Saved in ADLC. Available even after the Harness agent session closes.",
                    )
                  : entry.awaitingSubmit
                    ? translateUi(
                        "Harness preview. Not yet accepted and saved by ADLC; manual runs still require Submit.",
                      )
                    : translateUi(
                        "Awaiting result receipt by ADLC. This Harness result has not yet been accepted and saved by ADLC.",
                      )}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {route?.provider && route.model && (
                <p className="text-xs text-muted-foreground">
                  {translateUi("Executed with")} {route.provider} /{" "}
                  {route.model}
                </p>
              )}
              {result.error && (
                <div
                  role="alert"
                  className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm"
                >
                  <p className="font-medium">{result.error.code}</p>
                  <p className="mt-1 break-words">{result.error.message}</p>
                </div>
              )}
              {output.summary && (
                <SanitizedMarkdown
                  chatMessage={output.summary}
                  isEmpty={false}
                  className="break-words text-sm"
                />
              )}
              {output.structured !== undefined &&
                output.structured !== null && (
                  <div className="space-y-2">
                    <h3 className="text-sm font-medium">
                      {translateUi("Structured output")}
                    </h3>
                    <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted p-3 text-xs">
                      {JSON.stringify(output.structured, null, 2)}
                    </pre>
                  </div>
                )}
              {!output.summary &&
                (output.structured === undefined ||
                  output.structured === null) && (
                  <p className="text-sm text-muted-foreground">
                    {translateUi("No output was returned.")}
                  </p>
                )}
              <div className="space-y-2">
                <h3 className="text-sm font-medium">
                  {translateUi("Verification")}
                </h3>
                {result.verification_reports?.length ? (
                  <ul className="space-y-2">
                    {result.verification_reports.map((report, index) => (
                      <li
                        key={`${report.verifier_ref}-${index}`}
                        className="rounded-md border p-3 text-sm"
                      >
                        <p className="break-words font-medium">
                          {formatUiStatus(report.status)} ·{" "}
                          {report.verifier_ref}
                        </p>
                        <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
                          {report.checks.map((check) => (
                            <li key={check.check_id} className="break-words">
                              {formatUiStatus(check.status)}: {check.summary}
                            </li>
                          ))}
                        </ul>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    {translateUi("No verification report was returned.")}
                  </p>
                )}
              </div>
              {Boolean(result.artifacts?.length) && (
                <div className="space-y-2">
                  <h3 className="text-sm font-medium">
                    {translateUi("Artifacts")}
                  </h3>
                  <ul className="space-y-1 text-sm">
                    {result.artifacts?.map((artifact) => (
                      <li key={artifact.artifact_id} className="break-words">
                        {artifact.name} · {formatUiStatus(artifact.kind)}
                        <p className="font-mono text-xs text-muted-foreground">
                          {artifact.uri}
                        </p>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {Boolean(result.interaction_records?.length) && (
                <details className="rounded-md border p-3 text-sm">
                  <summary className="cursor-pointer font-medium">
                    {translateUi("Human interaction history")}
                  </summary>
                  <ol className="mt-3 space-y-3">
                    {result.interaction_records?.map((interaction) => (
                      <li
                        key={interaction.interaction_id}
                        className="space-y-1"
                      >
                        <p className="font-medium">
                          {interaction.title} ·{" "}
                          {formatUiStatus(interaction.status)}
                        </p>
                        <p className="whitespace-pre-wrap break-words">
                          {interaction.prompt}
                        </p>
                        {interaction.response && (
                          <pre className="overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted p-2 text-xs">
                            {JSON.stringify(interaction.response, null, 2)}
                          </pre>
                        )}
                      </li>
                    ))}
                  </ol>
                </details>
              )}
              <details className="rounded-md border p-3 text-sm">
                <summary className="cursor-pointer font-medium">
                  {translateUi("Result JSON & diagnostics")}
                </summary>
                <div className="mt-3 space-y-1 break-words text-xs text-muted-foreground">
                  <p>
                    {translateUi("Attempt:")} {entry.attempt_id}
                  </p>
                  <p>
                    {translateUi("Task:")} {entry.task_run_id}
                  </p>
                  {result.session_id && (
                    <p>
                      {translateUi("Harness session:")} {result.session_id}
                    </p>
                  )}
                  {result.completed_at && (
                    <p>
                      {translateUi("Completed:")} {result.completed_at}
                    </p>
                  )}
                  {entry.stored && (
                    <p>
                      {translateUi("Stored in ADLC:")} {entry.stored_at}
                    </p>
                  )}
                  {result.trace_ref && (
                    <p>
                      {translateUi("Trace reference:")} {result.trace_ref}
                    </p>
                  )}
                </div>
                <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted p-3 text-xs">
                  {JSON.stringify(result, null, 2)}
                </pre>
              </details>
            </CardContent>
          </Card>
        );
      })}
    </section>
  );
}
