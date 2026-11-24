import { getUiLanguage, translateUi, useUiLocale } from "@/i18n/ui";
import axios from "axios";
import i18n from "@/i18n";
import { useEffect, useMemo, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  getAdlcHarnessSourcePatchPreview,
  getAdlcSourcePatch,
} from "@/controllers/API/adlc";
import type {
  AdlcArtifact,
  AdlcHarnessRunResult,
  AdlcHarnessRunSession,
  AdlcSourcePatch,
  AdlcTaskRun,
} from "@/types/adlc";
import CodeDiffViewer from "./CodeDiffViewer";
import "./review.css";

interface SourcePatchReviewProps {
  runId: string;
  tasks: AdlcTaskRun[];
  results?: AdlcHarnessRunResult[];
  sessions?: AdlcHarnessRunSession[];
  onAvailabilityChange: (readyKey: string | undefined) => void;
  onPreviewAvailabilityChange?: (sessionIds: string[]) => void;
}

interface PatchCandidate {
  artifact: AdlcArtifact;
  taskName: string;
  preview: boolean;
  sessionId?: string;
}

export function capturedSourcePatches(
  tasks: AdlcTaskRun[],
  results: AdlcHarnessRunResult[] = [],
  sessions: AdlcHarnessRunSession[] = [],
): PatchCandidate[] {
  const candidates = new Map<string, PatchCandidate>();
  const captured = (artifact: AdlcArtifact) =>
    artifact.kind === "SOURCE_PATCH" &&
    ([
      "workspace-vcs-diff",
      "dsh-final-message",
      "harness-git-diff",
      "task-loop-candidate",
    ].includes(String(artifact.metadata?.capture)) ||
      ([
        "agent-provider:task-loop-opencode",
        "agent-provider:coding-agent-contract-loop",
      ].includes(artifact.producer ?? "") &&
        artifact.metadata?.payload_retained === true));
  for (const task of tasks) {
    for (const artifact of task.artifacts ?? []) {
      if (captured(artifact))
        candidates.set(artifact.artifact_id, {
          artifact,
          taskName: task.name,
          preview: false,
        });
    }
  }
  for (const entry of results) {
    for (const artifact of entry.result.artifacts ?? []) {
      if (captured(artifact))
        candidates.set(artifact.artifact_id, {
          artifact,
          taskName:
            tasks.find((task) => task.id === entry.task_run_id)?.name ??
            i18n.t("adlc.run.agentTask"),
          preview: false,
        });
    }
  }
  for (const entry of sessions) {
    for (const artifact of entry.session.result?.artifacts ?? []) {
      if (captured(artifact) && !candidates.has(artifact.artifact_id))
        candidates.set(artifact.artifact_id, {
          artifact,
          taskName:
            tasks.find((task) => task.id === entry.task_run_id)?.name ??
            i18n.t("adlc.run.agentTask"),
          preview: true,
          sessionId: entry.session.session_id,
        });
    }
  }
  return [...candidates.values()];
}

export function sourcePatchReviewKey(
  runId: string,
  candidates: ReturnType<typeof capturedSourcePatches>,
): string {
  return `${runId}:${candidates.map(({ artifact, preview }) => `${artifact.artifact_id}${preview ? ":preview" : ""}`).join(",")}`;
}

function patchError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail?.message === "string") return detail.message;
  }
  return error instanceof Error
    ? error.message
    : i18n.t("adlc.run.loadPatchFailed");
}

export default function SourcePatchReview({
  runId,
  tasks,
  results = [],
  sessions = [],
  onAvailabilityChange,
  onPreviewAvailabilityChange,
}: SourcePatchReviewProps) {
  useUiLocale();
  const candidates = useMemo(
    () => capturedSourcePatches(tasks, results, sessions),
    [tasks, results, sessions],
  );
  const reviewKey = sourcePatchReviewKey(runId, candidates);
  const taskReviewKey = sourcePatchReviewKey(
    runId,
    capturedSourcePatches(tasks),
  );
  const inputs = useRef({ candidates, tasks });
  inputs.current = { candidates, tasks };
  const [selectedId, setSelectedId] = useState<string>();
  const [patches, setPatches] = useState<Record<string, AdlcSourcePatch>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const expiries = Object.values(patches)
      .flatMap((patch) =>
        patch.artifact.expires_at
          ? [Date.parse(patch.artifact.expires_at)]
          : [],
      )
      .filter(Number.isFinite);
    if (expiries.length === 0) return;
    const timer = window.setTimeout(
      () => setReload((value) => value + 1),
      Math.max(0, Math.min(...expiries) - Date.now()),
    );
    return () => window.clearTimeout(timer);
  }, [patches]);

  useEffect(() => {
    const currentCandidates = inputs.current.candidates;
    const currentTasks = inputs.current.tasks;
    if (currentCandidates.length === 0) {
      onAvailabilityChange(undefined);
      onPreviewAvailabilityChange?.([]);
      return;
    }
    let active = true;
    onAvailabilityChange(undefined);
    onPreviewAvailabilityChange?.([]);
    setPatches({});
    setErrors({});
    setLoading(true);
    void Promise.allSettled(
      currentCandidates.map(({ artifact, preview, sessionId }) =>
        preview && sessionId
          ? getAdlcHarnessSourcePatchPreview(
              runId,
              sessionId,
              artifact.artifact_id,
            )
          : getAdlcSourcePatch(runId, artifact.artifact_id),
      ),
    ).then((results) => {
      if (!active) return;
      const nextPatches: Record<string, AdlcSourcePatch> = {};
      const nextErrors: Record<string, string> = {};
      results.forEach((result, index) => {
        const artifactId = currentCandidates[index].artifact.artifact_id;
        if (result.status === "fulfilled") {
          nextPatches[artifactId] = result.value;
        } else {
          nextErrors[artifactId] = patchError(result.reason);
        }
      });
      setPatches(nextPatches);
      setErrors(nextErrors);
      setLoading(false);
      onAvailabilityChange(
        capturedSourcePatches(currentTasks).every(
          ({ artifact }) => nextPatches[artifact.artifact_id],
        )
          ? taskReviewKey
          : undefined,
      );
      const previewSessionIds = [
        ...new Set(
          currentCandidates.flatMap((item) =>
            item.sessionId ? [item.sessionId] : [],
          ),
        ),
      ];
      onPreviewAvailabilityChange?.(
        previewSessionIds.filter((id) =>
          currentCandidates
            .filter((item) => item.sessionId === id)
            .every((item) => nextPatches[item.artifact.artifact_id]),
        ),
      );
    });
    return () => {
      active = false;
    };
  }, [
    onAvailabilityChange,
    onPreviewAvailabilityChange,
    reload,
    reviewKey,
    taskReviewKey,
    runId,
  ]);

  if (candidates.length === 0) return null;

  const activeId = candidates.some(
    ({ artifact }) => artifact.artifact_id === selectedId,
  )
    ? selectedId
    : candidates[0].artifact.artifact_id;
  const activePatch = activeId ? patches[activeId] : undefined;
  const activeError = activeId ? errors[activeId] : undefined;
  const activeCandidate = candidates.find(
    (item) => item.artifact.artifact_id === activeId,
  );

  const downloadPatch = () => {
    if (!activePatch) return;
    const blob = new Blob(
      [activePatch.files.map((file) => file.patch).join("")],
      { type: "text/plain;charset=utf-8" },
    );
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `source-patch-${activePatch.artifact.artifact_id}.patch`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Card className="rr-patch-card bg-background">
      <CardHeader>
        <CardTitle>
          {getUiLanguage().startsWith("vi")
            ? "So sánh mã nguồn"
            : translateUi("Changes to review")}
        </CardTitle>
        <CardDescription>
          Đỏ là phần xóa, xanh là phần thêm. Xem thay đổi trước khi duyệt.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {candidates.length > 1 && (
          <div
            className="flex flex-wrap gap-2"
            aria-label={translateUi("Source patch artifacts")}
          >
            {candidates.map(({ artifact, taskName, preview }) => (
              <Button
                key={artifact.artifact_id}
                variant={
                  activeId === artifact.artifact_id ? "default" : "outline"
                }
                size="sm"
                onClick={() => setSelectedId(artifact.artifact_id)}
              >
                {taskName} ·{" "}
                {preview ? translateUi("Preview") : translateUi("Saved")}
              </Button>
            ))}
          </div>
        )}
        {loading && (
          <p role="status" className="text-sm text-muted-foreground">
            {translateUi("Loading source patches…")}
          </p>
        )}
        {activeError && (
          <div role="alert" className="space-y-2 text-sm text-destructive">
            <p>{activeError}</p>
            <p>
              {translateUi(
                "Do not approve this run until a new reviewable patch is available.",
              )}
            </p>
            <Button
              variant="outline"
              size="xs"
              onClick={() => setReload((value) => value + 1)}
            >
              {translateUi("Retry loading")}
            </Button>
          </div>
        )}
        {activePatch && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge
                variant={
                  activeCandidate?.preview ? "purpleStatic" : "successStatic"
                }
                size="tag"
              >
                {activeCandidate?.preview
                  ? translateUi("Preview — not submitted")
                  : getUiLanguage().startsWith("vi")
                    ? "Bản thay đổi đã lưu"
                    : translateUi("Saved artifact")}
              </Badge>
              <Button
                size="xs"
                variant="outline"
                ignoreTitleCase
                onClick={downloadPatch}
              >
                {translateUi("Download patch")}
              </Button>
            </div>
            <details className="rr-technical">
              <summary>Thông tin kỹ thuật & thời hạn lưu</summary>
              <p className="text-xs text-muted-foreground">
                {activePatch.files.length} {translateUi("file(s) ·")}{" "}
                {activePatch.artifact.size_bytes}{" "}
                {translateUi("bytes · Expires")}{" "}
                {activePatch.artifact.expires_at ??
                  translateUi("with retention policy")}
              </p>
              {activePatch.base_commit && (
                <p className="font-mono text-xs text-muted-foreground">
                  {translateUi("Base commit")} {activePatch.base_commit}
                </p>
              )}
              {typeof activePatch.artifact.metadata?.candidate_id ===
                "string" && (
                <p className="break-all font-mono text-xs text-muted-foreground">
                  {translateUi("Candidate")}{" "}
                  {activePatch.artifact.metadata.candidate_id}
                </p>
              )}
              {typeof activePatch.artifact.metadata?.candidate_digest ===
                "string" && (
                <p className="break-all font-mono text-xs text-muted-foreground">
                  {translateUi("Candidate digest")}{" "}
                  {activePatch.artifact.metadata.candidate_digest}
                </p>
              )}
              <p className="font-mono text-xs text-muted-foreground">
                SHA-256 {activePatch.artifact.checksum.value}
              </p>
            </details>
            {activePatch.files.length === 0 && (
              <p className="text-sm text-muted-foreground">
                {translateUi("No changed files were captured.")}
              </p>
            )}
            {activePatch.files.map((file) => (
              <details key={file.file} open className="rounded-md border">
                <summary className="rr-file-heading cursor-pointer px-3 py-2 text-sm font-medium">
                  <span>{file.file}</span>
                  <span className="rr-file-count">
                    <span>+{file.additions}</span>
                    <span>−{file.deletions}</span>
                  </span>
                </summary>
                <CodeDiffViewer file={file.file} patch={file.patch} />
              </details>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
