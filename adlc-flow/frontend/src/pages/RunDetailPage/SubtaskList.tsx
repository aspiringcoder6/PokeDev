import { useTranslation } from "react-i18next";
import "@/i18n";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { AdlcSubtaskRun, SubtaskStatus } from "@/types/adlc";

interface SubtaskListProps {
  subtasks: AdlcSubtaskRun[];
  selectedId?: string;
  onSelect?: (subtaskId: string) => void;
}

function statusVariant(
  status: SubtaskStatus,
): "successStatic" | "errorStatic" | "emerald" | "secondaryStatic" {
  if (status === "succeeded") return "successStatic";
  if (status === "failed" || status === "cancelled") return "errorStatic";
  if (status === "running" || status === "ready") return "emerald";
  return "secondaryStatic";
}

function statusIcon(status: SubtaskStatus): string {
  if (status === "succeeded") return "Check";
  if (status === "failed") return "X";
  if (status === "cancelled") return "Ban";
  if (status === "running") return "Loader";
  if (status === "ready") return "Clock";
  if (status === "skipped") return "SkipForward";
  return "Circle";
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

/**
 * List of subtasks with their status. Clicking a subtask selects it
 * for detail viewing.
 */
export default function SubtaskList({
  subtasks,
  selectedId,
  onSelect,
}: SubtaskListProps) {
  const { t } = useTranslation();
  if (subtasks.length === 0) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="subtask-list-empty">
        {t("adlc.run.noSubtasks")}
      </p>
    );
  }

  return (
    <ul className="space-y-1" data-testid="subtask-list">
      {subtasks.map((subtask) => {
        const isSelected = subtask.id === selectedId;
        return (
          <li key={subtask.id}>
            <Button
              variant={isSelected ? "secondary" : "ghost"}
              className="w-full justify-start gap-2 px-2 py-1.5 h-auto"
              onClick={() => onSelect?.(subtask.id)}
              data-testid={`subtask-item-${subtask.id}`}
            >
              <ForwardedIconComponent
                name={statusIcon(subtask.status)}
                className="h-4 w-4 shrink-0"
              />
              <span className="flex-1 truncate text-left text-sm">
                {subtask.name}
              </span>
              <Badge variant={statusVariant(subtask.status)} size="tag">
                {subtask.status}
              </Badge>
              <span className="w-16 text-right text-xs text-muted-foreground tabular-nums">
                {formatDuration(subtask.duration_ms)}
              </span>
            </Button>
          </li>
        );
      })}
    </ul>
  );
}
