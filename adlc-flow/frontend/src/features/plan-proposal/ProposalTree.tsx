import { translateUi, useUiLocale } from "@/i18n/ui";
import { useMemo } from "react";
import { motion } from "framer-motion";

import ForwardedIconComponent from "@/components/common/genericIconComponent";
import { Badge } from "@/components/ui/badge";
import type { AdlcProposedTask } from "@/types/adlc";

import {
  PROPOSAL_TREE_LAYOUT,
  buildProposalTreeLayout,
  collectProposalIssueTasks,
} from "./proposal-tree";
import { useTranslation } from "react-i18next";
import "@/i18n";

const { NODE_WIDTH, NODE_HEIGHT } = PROPOSAL_TREE_LAYOUT;

function ProposalTaskCard({
  task,
  issueCount,
}: {
  task: AdlcProposedTask;
  issueCount: number;
}) {
  const { t } = useTranslation();
  useUiLocale();
  return (
    <div
      className={[
        "flex h-full w-full flex-col gap-1 rounded-lg border bg-background/90 p-3 text-left",
        issueCount > 0
          ? "border-red-500/70 shadow-[0_0_0_2px_rgba(239,68,68,0.15)]"
          : "border-border",
      ].join(" ")}
      data-testid={`proposal-task-${task.task_id}`}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="truncate text-sm font-semibold">{task.name}</p>
        <Badge
          variant="secondaryStatic"
          size="tag"
          className="shrink-0 font-mono"
        >
          {task.task_id}
        </Badge>
      </div>
      <p
        className="line-clamp-2 text-[11px] text-muted-foreground"
        title={task.objective}
      >
        {task.objective}
      </p>
      <div className="mt-auto flex flex-wrap items-center gap-1 text-[10px]">
        <span className="rounded bg-primary/10 px-1.5 py-0.5 font-mono text-primary">
          {task.assigned_package.package_id}@{task.assigned_package.version}
        </span>
        {task.expected_outputs.map((output) => (
          <span
            key={output}
            className="rounded bg-muted px-1.5 py-0.5 text-muted-foreground"
            title={translateUi("Expected output: {{value0}}", {
              value0: output,
            })}
          >
            → {output}
          </span>
        ))}
        {issueCount > 0 && (
          <span className="rounded bg-red-500/10 px-1.5 py-0.5 text-red-600 dark:text-red-300">
            {t("adlc.pp.issueCount", { count: issueCount })}
          </span>
        )}
      </div>
      {task.dependency_task_ids.length > 0 && (
        <p className="truncate font-mono text-[10px] text-muted-foreground">
          {t("adlc.pp.afterList", {
            list: task.dependency_task_ids.join(", "),
          })}
        </p>
      )}
    </div>
  );
}

export function ProposalTree({
  tasks,
  issues,
}: {
  tasks: AdlcProposedTask[];
  issues: { code: string; message: string; path?: string }[];
}) {
  const { t } = useTranslation();
  useUiLocale();
  const layout = useMemo(() => buildProposalTreeLayout(tasks), [tasks]);
  const issueByTask = useMemo(
    () => collectProposalIssueTasks(issues),
    [issues],
  );

  if (tasks.length === 0) {
    return (
      <div className="flex h-28 items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground">
        {translateUi("The planner proposed no tasks.")}
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-md border bg-muted/20 p-2">
      <svg
        role="img"
        aria-label={translateUi("Proposed task tree")}
        width={layout.width}
        height={layout.height}
        className="block"
        data-testid="proposal-tree-svg"
      >
        <defs>
          <marker
            id="proposal-arrow"
            viewBox="0 0 8 8"
            refX={7}
            refY={4}
            markerWidth={6}
            markerHeight={6}
            orient="auto-start-reverse"
          >
            <path
              d="M 0 0 L 8 4 L 0 8 z"
              fill="hsl(var(--muted-foreground))"
              opacity={0.55}
            />
          </marker>
        </defs>
        {layout.edges.map((edge, index) => {
          const midY = (edge.sourceY + edge.targetY) / 2;
          const path = `M ${edge.sourceX} ${edge.sourceY} C ${edge.sourceX} ${midY}, ${edge.targetX} ${midY}, ${edge.targetX} ${edge.targetY}`;
          return (
            <path
              key={`${edge.sourceId}-${edge.targetId}-${index}`}
              d={path}
              fill="none"
              stroke="hsl(var(--muted-foreground))"
              strokeOpacity={0.45}
              strokeWidth={1.5}
              strokeDasharray="5 4"
              markerEnd="url(#proposal-arrow)"
            />
          );
        })}
        {layout.nodes.map((node, index) => (
          <motion.g
            key={node.task.task_id}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, delay: Math.min(index * 0.04, 0.8) }}
          >
            <foreignObject
              x={node.x - NODE_WIDTH / 2}
              y={node.y - NODE_HEIGHT / 2}
              width={NODE_WIDTH}
              height={NODE_HEIGHT}
            >
              <ProposalTaskCard
                task={node.task}
                issueCount={issueByTask.get(node.task.task_id)?.length ?? 0}
              />
            </foreignObject>
          </motion.g>
        ))}
      </svg>
    </div>
  );
}

export function ProposalIssueList({
  title,
  issues,
  tone,
}: {
  title: string;
  issues: { code: string; message: string; path?: string }[];
  tone: "error" | "warning";
}) {
  if (issues.length === 0) return null;
  return (
    <section
      className={[
        "space-y-1 rounded-md border p-3 text-xs",
        tone === "error"
          ? "border-red-500/40 bg-red-500/5"
          : "border-amber-500/40 bg-amber-500/5",
      ].join(" ")}
    >
      <p className="flex items-center gap-1.5 font-medium">
        <ForwardedIconComponent
          name={tone === "error" ? "CircleAlert" : "TriangleAlert"}
          className="h-3.5 w-3.5"
        />
        {title} ({issues.length})
      </p>
      <ul className="space-y-1">
        {issues.map((issue, index) => (
          <li key={`${issue.code}-${index}`} className="font-mono">
            <span className="font-semibold">{issue.code}</span>
            {issue.path ? ` · ${issue.path}` : ""} — {issue.message}
          </li>
        ))}
      </ul>
    </section>
  );
}
