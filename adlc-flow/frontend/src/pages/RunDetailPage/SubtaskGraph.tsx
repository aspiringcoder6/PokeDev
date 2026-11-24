import ForwardedIconComponent from "@/components/common/genericIconComponent";
import type { AdlcSubtaskRun, SubtaskStatus } from "@/types/adlc";
import { useTranslation } from "react-i18next";
import "@/i18n";

interface SubtaskGraphProps {
  subtasks: AdlcSubtaskRun[];
  selectedId?: string;
  onSelect?: (subtaskId: string) => void;
}

interface GraphNode {
  id: string;
  subtask: AdlcSubtaskRun;
  level: number;
  column: number;
}

interface GraphLayout {
  nodes: GraphNode[];
  levels: number;
  maxColumns: number;
}

/**
 * Compute a layered layout for the subtask DAG.
 *
 * Uses a simple longest-path layering: each node's level is the max
 * level of its dependencies + 1. Within a level, nodes are ordered by
 * id for stability.
 */
function computeLayout(subtasks: AdlcSubtaskRun[]): GraphLayout {
  const byId = new Map(subtasks.map((s) => [s.id, s]));
  const levelById = new Map<string, number>();

  function levelOf(id: string, visiting: Set<string>): number {
    const cached = levelById.get(id);
    if (cached !== undefined) return cached;
    if (visiting.has(id)) return 0; // cycle guard
    visiting.add(id);
    const subtask = byId.get(id);
    if (!subtask || subtask.dependencies.length === 0) {
      levelById.set(id, 0);
      visiting.delete(id);
      return 0;
    }
    const maxDepLevel = Math.max(
      ...subtask.dependencies.map((dep) => levelOf(dep, visiting)),
    );
    const level = maxDepLevel + 1;
    levelById.set(id, level);
    visiting.delete(id);
    return level;
  }

  for (const subtask of subtasks) {
    levelOf(subtask.id, new Set());
  }

  const levels = Math.max(0, ...Array.from(levelById.values())) + 1;
  const byLevel: AdlcSubtaskRun[][] = Array.from({ length: levels }, () => []);
  for (const subtask of subtasks) {
    const level = levelById.get(subtask.id) ?? 0;
    byLevel[level].push(subtask);
  }
  // Sort within each level by id for stable layout.
  for (const group of byLevel) {
    group.sort((a, b) => a.id.localeCompare(b.id));
  }

  const nodes: GraphNode[] = [];
  let maxColumns = 0;
  for (let level = 0; level < levels; level++) {
    const group = byLevel[level];
    maxColumns = Math.max(maxColumns, group.length);
    group.forEach((subtask, column) => {
      nodes.push({ id: subtask.id, subtask, level, column });
    });
  }

  return { nodes, levels, maxColumns };
}

function nodeColor(status: SubtaskStatus): string {
  if (status === "succeeded") return "border-emerald-500 bg-emerald-50 dark:bg-emerald-900";
  if (status === "failed") return "border-red-500 bg-red-50 dark:bg-red-900";
  if (status === "cancelled") return "border-gray-500 bg-gray-50 dark:bg-gray-800";
  if (status === "running") return "border-blue-500 bg-blue-50 dark:bg-blue-900";
  if (status === "skipped") return "border-gray-300 bg-gray-50 dark:bg-gray-800";
  return "border-gray-200 bg-white dark:bg-gray-700";
}

function nodeIcon(status: SubtaskStatus): string {
  if (status === "succeeded") return "Check";
  if (status === "failed") return "X";
  if (status === "cancelled") return "Ban";
  if (status === "running") return "Loader";
  if (status === "skipped") return "SkipForward";
  return "Circle";
}

/**
 * Simple layered DAG visualization for subtasks.
 *
 * Each subtask is a node positioned by its longest-path level. Edges
 * connect dependencies to dependents. Clicking a node selects it.
 */
export default function SubtaskGraph({
  subtasks,
  selectedId,
  onSelect,
}: SubtaskGraphProps) {
  const { t } = useTranslation();
  if (subtasks.length === 0) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="subtask-graph-empty">
        {t("adlc.run.noSubtasksToVisualize")}
      </p>
    );
  }

  const layout = computeLayout(subtasks);
  const nodeById = new Map(layout.nodes.map((n) => [n.id, n]));
  const nodeWidth = 160;
  const nodeHeight = 48;
  const horizontalGap = 40;
  const verticalGap = 24;
  const padding = 16;

  const totalWidth =
    padding * 2 +
    layout.maxColumns * nodeWidth +
    (layout.maxColumns - 1) * horizontalGap;
  const totalHeight =
    padding * 2 +
    layout.levels * nodeHeight +
    (layout.levels - 1) * verticalGap;

  function nodePosition(node: GraphNode): { x: number; y: number } {
    const x =
      padding +
      node.column * (nodeWidth + horizontalGap) +
      (layout.maxColumns - 1 - node.column) * 0; // left-align
    const y = padding + node.level * (nodeHeight + verticalGap);
    return { x, y };
  }

  return (
    <div
      className="overflow-auto rounded-md border bg-background p-2"
      data-testid="subtask-graph"
    >
      <svg
        width={totalWidth}
        height={totalHeight}
        role="img"
        aria-label={t("adlc.run.ariaSubtaskGraph")}
      >
        {/* Edges */}
        {layout.nodes.flatMap((node) =>
          node.subtask.dependencies
            .map((depId) => {
              const dep = nodeById.get(depId);
              if (!dep) return null;
              const from = nodePosition(dep);
              const to = nodePosition(node);
              const x1 = from.x + nodeWidth / 2;
              const y1 = from.y + nodeHeight;
              const x2 = to.x + nodeWidth / 2;
              const y2 = to.y;
              const midY = (y1 + y2) / 2;
              const path = `M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}`;
              return (
                <path
                  key={`${depId}->${node.id}`}
                  d={path}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={1.5}
                  className="text-muted-foreground/50"
                />
              );
            })
            .filter(Boolean),
        )}
        {/* Nodes */}
        {layout.nodes.map((node) => {
          const { x, y } = nodePosition(node);
          const isSelected = node.id === selectedId;
          return (
            <g
              key={node.id}
              transform={`translate(${x}, ${y})`}
              className="cursor-pointer"
              onClick={() => onSelect?.(node.id)}
              data-testid={`subtask-graph-node-${node.id}`}
            >
              <rect
                width={nodeWidth}
                height={nodeHeight}
                rx={6}
                className={`${nodeColor(node.subtask.status)} ${
                  isSelected ? "stroke-2 ring-2 ring-primary" : "stroke-1"
                }`}
                strokeWidth={isSelected ? 2 : 1}
              />
              <foreignObject x={8} y={8} width={nodeWidth - 16} height={nodeHeight - 16}>
                <div className="flex items-center gap-1.5 overflow-hidden text-xs text-foreground">
                  <ForwardedIconComponent
                    name={nodeIcon(node.subtask.status)}
                    className="h-3.5 w-3.5 shrink-0"
                  />
                  <span className="truncate font-medium text-foreground">
                    {node.subtask.name}
                  </span>
                </div>
              </foreignObject>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
