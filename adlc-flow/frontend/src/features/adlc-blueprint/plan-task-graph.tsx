import { translateUi, useUiLocale } from "@/i18n/ui";
import { useId, type ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import type { AdlcPlanTask, AdlcResolvedNodeSpec } from "@/types/adlc";
import { useTranslation } from "react-i18next";
import "@/i18n";

export const PLAN_TASK_GRAPH_LAYOUT = {
  NODE_WIDTH: 236,
  NODE_HEIGHT: 108,
  COLUMN_GAP: 48,
  ROW_GAP: 56,
  PADDING: 24,
} as const;

export interface PlanTaskNode {
  task: AdlcPlanTask;
  level: number;
  row: number;
  x: number;
  y: number;
}

export interface PlanTaskEdge {
  sourceId: string;
  targetId: string;
  path: string;
}

export interface PlanTaskGraphLayout {
  width: number;
  height: number;
  nodes: PlanTaskNode[];
  edges: PlanTaskEdge[];
}

const { NODE_WIDTH, NODE_HEIGHT, COLUMN_GAP, ROW_GAP, PADDING } =
  PLAN_TASK_GRAPH_LAYOUT;

/**
 * Longest-path layering over the plan's dependency DAG. Each task appears
 * exactly once; a task with several dependencies sits below all of them and
 * every dependency draws its own edge, so shared (diamond) dependencies stay
 * visible instead of being flattened into a parent-child tree.
 *
 * The compiler guarantees an acyclic plan, but the layout stays total for
 * malformed data: unknown dependencies are ignored and any residual cycle is
 * broken by assigning sequential levels after the last valid level.
 */
export function buildPlanTaskGraphLayout(
  tasks: AdlcPlanTask[],
): PlanTaskGraphLayout {
  if (tasks.length === 0) {
    return { width: 0, height: 0, nodes: [], edges: [] };
  }

  const byId = new Map(tasks.map((task) => [task.plan_task_id, task]));
  const knownDependencies = new Map(
    tasks.map((task) => [
      task.plan_task_id,
      task.dependency_task_ids.filter((dependency) => byId.has(dependency)),
    ]),
  );

  const levels = new Map<string, number>();
  const remaining = new Map(
    [...knownDependencies].map(([id, dependencies]) => [
      id,
      dependencies.length,
    ]),
  );
  const dependents = new Map<string, string[]>();
  for (const [id, dependencies] of knownDependencies) {
    for (const dependency of dependencies) {
      dependents.set(dependency, [...(dependents.get(dependency) ?? []), id]);
    }
  }

  let frontier = tasks
    .filter((task) => remaining.get(task.plan_task_id) === 0)
    .map((task) => task.plan_task_id);
  let maxLevel = 0;
  while (frontier.length > 0) {
    const next: string[] = [];
    for (const id of frontier) {
      const dependencies = knownDependencies.get(id) ?? [];
      const level = dependencies.reduce(
        (highest, dependency) =>
          Math.max(highest, (levels.get(dependency) ?? -1) + 1),
        0,
      );
      levels.set(id, level);
      maxLevel = Math.max(maxLevel, level);
    }
    for (const id of frontier) {
      for (const dependent of dependents.get(id) ?? []) {
        const left = (remaining.get(dependent) ?? 0) - 1;
        remaining.set(dependent, left);
        if (left === 0) next.push(dependent);
      }
    }
    frontier = next;
  }

  let fallbackLevel = maxLevel + 1;
  for (const task of tasks) {
    if (!levels.has(task.plan_task_id)) {
      levels.set(task.plan_task_id, fallbackLevel);
      fallbackLevel += 1;
    }
  }

  const rowsByLevel = new Map<number, string[]>();
  for (const task of tasks) {
    const level = levels.get(task.plan_task_id) ?? 0;
    const row = rowsByLevel.get(level) ?? [];
    row.push(task.plan_task_id);
    rowsByLevel.set(level, row);
  }
  const sortedLevels = [...rowsByLevel.keys()].sort((a, b) => a - b);
  const widestRow = Math.max(
    ...[...rowsByLevel.values()].map((row) => row.length),
  );
  const width =
    widestRow * NODE_WIDTH + (widestRow - 1) * COLUMN_GAP + PADDING * 2;
  const height =
    sortedLevels.length * NODE_HEIGHT +
    (sortedLevels.length - 1) * ROW_GAP +
    PADDING * 2;

  const positions = new Map<string, { x: number; y: number }>();
  const nodes: PlanTaskNode[] = [];
  for (const level of sortedLevels) {
    const row = rowsByLevel.get(level) ?? [];
    const rowWidth = row.length * NODE_WIDTH + (row.length - 1) * COLUMN_GAP;
    const startX = (width - rowWidth) / 2 + NODE_WIDTH / 2;
    row.forEach((id, index) => {
      const x = startX + index * (NODE_WIDTH + COLUMN_GAP);
      const y = PADDING + level * (NODE_HEIGHT + ROW_GAP) + NODE_HEIGHT / 2;
      positions.set(id, { x, y });
      const task = byId.get(id);
      if (task) {
        nodes.push({ task, level, row: index, x, y });
      }
    });
  }

  const edges: PlanTaskEdge[] = [];
  for (const task of tasks) {
    const target = positions.get(task.plan_task_id);
    if (!target) continue;
    for (const dependency of knownDependencies.get(task.plan_task_id) ?? []) {
      const source = positions.get(dependency);
      if (!source) continue;
      const sourceX = source.x;
      const sourceY = source.y + NODE_HEIGHT / 2;
      const targetX = target.x;
      const targetY = target.y - NODE_HEIGHT / 2;
      const bend = (sourceY + targetY) / 2;
      edges.push({
        sourceId: dependency,
        targetId: task.plan_task_id,
        path: `M ${sourceX} ${sourceY} C ${sourceX} ${bend}, ${targetX} ${bend}, ${targetX} ${targetY}`,
      });
    }
  }

  return { width, height, nodes, edges };
}

function shortId(value: string): string {
  return value.length > 12 ? `${value.slice(0, 8)}…` : value;
}

export default function PlanTaskGraph({
  tasks,
  specs,
  onSelectTask,
  renderTask,
  selectedTaskId,
  scale = 1,
}: {
  tasks: AdlcPlanTask[];
  specs: Map<string, AdlcResolvedNodeSpec>;
  onSelectTask?: (taskId: string) => void;
  renderTask?: (task: AdlcPlanTask, spec?: AdlcResolvedNodeSpec) => ReactNode;
  selectedTaskId?: string;
  scale?: number;
}) {
  useUiLocale();
  const arrowId = `plan-task-arrow-${useId().replace(/:/g, "")}`;
  const zoom = Number.isFinite(scale) ? Math.min(2, Math.max(0.5, scale)) : 1;
  const layout = buildPlanTaskGraphLayout(tasks);
  if (layout.nodes.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {translateUi("This plan has no tasks to display.")}
      </p>
    );
  }

  const taskNames = new Map(
    layout.nodes.map((node) => [node.task.plan_task_id, node.task.name]),
  );

  return (
    <div
      className="plan-task-graph-scroll overflow-auto rounded-md border bg-muted/10"
      role="region"
      aria-label={translateUi("Task dependency graph")}
      tabIndex={0}
    >
      <div
        className="relative mx-auto"
        style={{ width: layout.width * zoom, height: layout.height * zoom }}
      >
        <div
          className="relative origin-top-left"
          style={{
            width: layout.width,
            height: layout.height,
            transform: `scale(${zoom})`,
          }}
          data-testid="plan-task-graph"
        >
          <svg
            className="absolute inset-0 h-full w-full"
            width={layout.width}
            height={layout.height}
            aria-hidden="true"
          >
            <defs>
              <marker
                id={arrowId}
                markerWidth="8"
                markerHeight="8"
                refX="7"
                refY="4"
                orient="auto"
              >
                <path
                  d="M 0 0 L 8 4 L 0 8 z"
                  className="fill-muted-foreground"
                />
              </marker>
            </defs>
            {layout.edges.map((edge) => (
              <path
                key={`${edge.sourceId}->${edge.targetId}`}
                d={edge.path}
                fill="none"
                strokeWidth="1.5"
                className="stroke-muted-foreground/60"
                markerEnd={`url(#${arrowId})`}
                data-testid="plan-task-edge"
                data-source-task-id={edge.sourceId}
                data-target-task-id={edge.targetId}
              />
            ))}
          </svg>
          {layout.nodes.map((node) => {
            const spec = specs.get(node.task.resolved_node_spec_id);
            const dependencies = node.task.dependency_task_ids.map(
              (dependency) => taskNames.get(dependency) ?? shortId(dependency),
            );
            const Node = onSelectTask ? "button" : "article";
            return (
              <Node
                key={node.task.plan_task_id}
                data-testid="plan-task-node"
                data-plan-task-id={node.task.plan_task_id}
                className="plan-task-node absolute flex flex-col justify-between rounded-lg border bg-background p-3 shadow-sm"
                {...(onSelectTask
                  ? {
                      type: "button" as const,
                      onClick: () => onSelectTask(node.task.plan_task_id),
                      "aria-label": node.task.name,
                      "aria-pressed": selectedTaskId === node.task.plan_task_id,
                    }
                  : {})}
                style={{
                  left: node.x - NODE_WIDTH / 2,
                  top: node.y - NODE_HEIGHT / 2,
                  width: NODE_WIDTH,
                  height: NODE_HEIGHT,
                }}
              >
                {renderTask ? (
                  renderTask(node.task, spec)
                ) : (
                  <>
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold">
                        {node.task.name}
                      </p>
                      <div className="mt-1 flex flex-wrap items-center gap-1">
                        <Badge variant="secondaryStatic" size="tag">
                          {node.task.task_type}
                        </Badge>
                        <span className="font-mono text-[10px] text-muted-foreground">
                          {shortId(node.task.plan_task_id)}
                        </span>
                      </div>
                    </div>
                    <div className="space-y-0.5 text-[11px] leading-tight text-muted-foreground">
                      <p className="truncate">
                        {spec
                          ? `${spec.package_ref.package_id}@${spec.package_ref.version} · ${spec.implementation?.adapter_ref ?? translateUi("Executor unavailable")}`
                          : translateUi("Package unavailable")}
                      </p>
                      <p className="truncate">
                        max{" "}
                        {node.task.effective_policies?.retry?.max_attempts ??
                          "—"}{" "}
                        attempt(s)
                        {dependencies.length > 0
                          ? translateUi(" · after {{value0}}", {
                              value0: dependencies.join(", "),
                            })
                          : translateUi(" · root task")}
                      </p>
                    </div>
                  </>
                )}
              </Node>
            );
          })}
        </div>
      </div>
    </div>
  );
}
