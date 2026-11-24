import { translateUi, useUiLocale, formatUiStatus } from "@/i18n/ui";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { AdlcArtifact, AdlcTaskRun } from "@/types/adlc";
import { useTranslation } from "react-i18next";
import "@/i18n";

interface ArtifactEntry {
  artifact: AdlcArtifact;
  taskName: string;
}

function collectArtifacts(tasks: AdlcTaskRun[]): ArtifactEntry[] {
  return tasks.flatMap((task) =>
    (task.artifacts ?? []).map((artifact) => ({
      artifact,
      taskName: task.name,
    })),
  );
}

function formatSize(sizeBytes: number): string {
  if (sizeBytes < 1024) return `${sizeBytes} B`;
  if (sizeBytes < 1024 * 1024) return `${(sizeBytes / 1024).toFixed(1)} KB`;
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function TaskArtifacts({ tasks }: { tasks: AdlcTaskRun[] }) {
  useUiLocale();
  const entries = collectArtifacts(tasks);
  if (entries.length === 0) return null;

  return (
    <Card className="bg-background">
      <CardHeader>
        <CardTitle>{translateUi("Artifacts")}</CardTitle>
        <CardDescription>
          {translateUi(
            "Deliverables produced by the executed tasks. Source patches captured by the live agent also appear under “Changes to review”.",
          )}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="divide-y rounded-md border">
          {entries.map(({ artifact, taskName }) => (
            <li
              key={artifact.artifact_id}
              className="flex flex-wrap items-center justify-between gap-3 p-3"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{artifact.name}</p>
                <p className="truncate font-mono text-xs text-muted-foreground">
                  {taskName} · {artifact.media_type} ·{" "}
                  {formatSize(artifact.size_bytes)}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {artifact.metadata?.mock === true && (
                  <Badge variant="secondaryStatic" size="tag">
                    {translateUi("mock artifact")}
                  </Badge>
                )}
                <Badge variant="secondaryStatic" size="tag">
                  {formatUiStatus(artifact.kind, true)}
                </Badge>
              </div>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
