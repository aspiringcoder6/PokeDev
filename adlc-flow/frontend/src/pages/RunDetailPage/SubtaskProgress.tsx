import { useTranslation } from "react-i18next";
import "@/i18n";
import { Badge } from "@/components/ui/badge";
import type { AdlcSubtaskSummary } from "@/types/adlc";

interface SubtaskProgressProps {
  summary: AdlcSubtaskSummary;
  compact?: boolean;
}

/**
 * Compact progress bar showing subtask completion stats.
 *
 * Displays "5/8" style counts with color-coded segments for each
 * status (succeeded, failed, running, pending, skipped).
 */
export default function SubtaskProgress({
  summary,
  compact = false,
}: SubtaskProgressProps) {
  const { t } = useTranslation();
  const { total, succeeded, failed, running, pending, skipped } = summary;

  if (total === 0) {
    return (
      <span className="text-xs text-muted-foreground">{t("adlc.run.noSubtasks")}</span>
    );
  }

  const segments = [
    { count: succeeded, color: "bg-emerald-500", label: "succeeded" },
    { count: running, color: "bg-blue-500 animate-pulse", label: "running" },
    { count: failed, color: "bg-red-500", label: "failed" },
    { count: skipped, color: "bg-gray-400", label: "skipped" },
    { count: pending, color: "bg-gray-200 dark:bg-gray-700", label: "pending" },
  ];

  return (
    <div className="flex items-center gap-2" data-testid="subtask-progress">
      <div className="flex h-2 w-32 overflow-hidden rounded-full bg-gray-100 dark:bg-gray-800">
        {segments.map(
          (seg) =>
            seg.count > 0 && (
              <div
                key={seg.label}
                className={seg.color}
                style={{ width: `${(seg.count / total) * 100}%` }}
                title={`${seg.count} ${seg.label}`}
              />
            ),
        )}
      </div>
      <span className="text-xs font-medium tabular-nums">
        {succeeded}/{total}
      </span>
      {!compact && (
        <div className="flex gap-1">
          {failed > 0 && (
            <Badge variant="errorStatic" size="tag">
              {failed} failed
            </Badge>
          )}
          {running > 0 && (
            <Badge variant="emerald" size="tag">
              {running} running
            </Badge>
          )}
          {skipped > 0 && (
            <Badge variant="secondaryStatic" size="tag">
              {skipped} skipped
            </Badge>
          )}
        </div>
      )}
    </div>
  );
}
