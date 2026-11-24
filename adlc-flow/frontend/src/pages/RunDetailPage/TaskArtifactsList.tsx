import { useTranslation } from "react-i18next";
import "@/i18n";
import { Badge } from "@/components/ui/badge";
import type { AdlcTaskRun } from "@/types/adlc";

interface TaskArtifactsListProps {
  task: AdlcTaskRun;
}

function formatSize(sizeBytes: number): string {
  if (sizeBytes < 1024) return `${sizeBytes} B`;
  if (sizeBytes < 1024 * 1024) return `${(sizeBytes / 1024).toFixed(1)} KB`;
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Per-task artifacts list. Shows the deliverables produced by a single
 * task. Rendered inside the expanded task view, next to the subtask
 * list/graph.
 */
export default function TaskArtifactsList({ task }: TaskArtifactsListProps) {
  const { t } = useTranslation();
  const artifacts = task.artifacts ?? [];
  if (artifacts.length === 0) {
    return (
      <div
        className="rounded-md border bg-muted/20 p-3 text-xs text-muted-foreground"
        data-testid="task-artifacts-empty"
      >
        {t("adlc.run.noArtifacts")}
      </div>
    );
  }

  return (
    <div
      className="space-y-2 rounded-md border bg-muted/20 p-3"
      data-testid="task-artifacts"
    >
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Artifacts
        </h4>
        <Badge variant="secondaryStatic" size="tag">
          {artifacts.length}
        </Badge>
      </div>
      <ul className="divide-y rounded-md border bg-background">
        {artifacts.map((artifact) => (
          <li
            key={artifact.artifact_id}
            className="flex flex-wrap items-center justify-between gap-3 p-2"
          >
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{artifact.name}</p>
              <p className="truncate font-mono text-xs text-muted-foreground">
                {artifact.kind} · {artifact.media_type}
              </p>
            </div>
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span className="font-mono">
                {formatSize(artifact.size_bytes)}
              </span>
              {artifact.checksum?.value && (
                <span
                  className="truncate font-mono text-[10px]"
                  title={artifact.checksum.value}
                >
                  {artifact.checksum.value.slice(0, 12)}…
                </span>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
