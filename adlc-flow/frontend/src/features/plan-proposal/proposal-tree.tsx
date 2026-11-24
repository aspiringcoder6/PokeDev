import type { AdlcProposedTask } from "@/types/adlc";
export interface ProposalTreeNode {
  task: AdlcProposedTask;
  x: number;
  y: number;
  column: number;
}

export interface ProposalTreeEdge {
  sourceId: string;
  targetId: string;
  sourceX: number;
  sourceY: number;
  targetX: number;
  targetY: number;
}

export interface ProposalTreeLayout {
  width: number;
  height: number;
  nodes: ProposalTreeNode[];
  edges: ProposalTreeEdge[];
}

const NODE_WIDTH = 236;
const NODE_HEIGHT = 128;
const COLUMN_GAP = 56;
const ROW_GAP = 40;
const PADDING = 24;

/** Longest-path layering over the dependency graph (deterministic). */
export function buildProposalTreeLayout(
  tasks: AdlcProposedTask[],
): ProposalTreeLayout {
  if (tasks.length === 0) {
    return { width: 0, height: 0, nodes: [], edges: [] };
  }
  const byId = new Map(tasks.map((task) => [task.task_id, task]));
  const memo = new Map<string, number>();

  const depthOf = (taskId: string): number => {
    const cached = memo.get(taskId);
    if (cached !== undefined) return cached;
    const task = byId.get(taskId);
    if (!task) {
      memo.set(taskId, 0);
      return 0;
    }
    const value =
      1 +
      Math.max(
        -1,
        ...task.dependency_task_ids.map((dependency) =>
          byId.has(dependency) ? depthOf(dependency) : -1,
        ),
      );
    memo.set(taskId, value);
    return value;
  };

  const layers = new Map<number, AdlcProposedTask[]>();
  for (const task of tasks) {
    const depth = depthOf(task.task_id);
    const layer = layers.get(depth) ?? [];
    layer.push(task);
    layers.set(depth, layer);
  }
  const sortedDepths = [...layers.keys()].sort((a, b) => a - b);
  const widest = Math.max(...[...layers.values()].map((l) => l.length));
  const width = widest * NODE_WIDTH + (widest - 1) * COLUMN_GAP + PADDING * 2;
  const height =
    sortedDepths.length * NODE_HEIGHT + (sortedDepths.length - 1) * ROW_GAP + PADDING * 2;

  const positions = new Map<string, { x: number; y: number }>();
  const nodes: ProposalTreeNode[] = [];
  for (const depth of sortedDepths) {
    const layer = layers.get(depth) ?? [];
    const layerWidth = layer.length * NODE_WIDTH + (layer.length - 1) * COLUMN_GAP;
    const startX = (width - layerWidth) / 2 + NODE_WIDTH / 2;
    layer.forEach((task, column) => {
      const x = startX + column * (NODE_WIDTH + COLUMN_GAP);
      const y = PADDING + depth * (NODE_HEIGHT + ROW_GAP) + NODE_HEIGHT / 2;
      positions.set(task.task_id, { x, y });
      nodes.push({ task, x, y, column });
    });
  }

  const edges: ProposalTreeEdge[] = [];
  for (const task of tasks) {
    const target = positions.get(task.task_id);
    if (!target) continue;
    for (const dependency of task.dependency_task_ids) {
      const source = positions.get(dependency);
      if (!source) continue;
      edges.push({
        sourceId: dependency,
        targetId: task.task_id,
        sourceX: source.x,
        sourceY: source.y + NODE_HEIGHT / 2,
        targetX: target.x,
        targetY: target.y - NODE_HEIGHT / 2,
      });
    }
  }
  return { width, height, nodes, edges };
}

export function collectProposalIssueTasks(
  issues: { code: string; message: string; path?: string }[],
): Map<string, { code: string; message: string; path?: string }[]> {
  const byTask = new Map<string, { code: string; message: string; path?: string }[]>();
  for (const issue of issues) {
    const match = /^\/tasks\/([^/]+)/.exec(issue.path ?? "");
    if (!match) continue;
    const list = byTask.get(match[1]) ?? [];
    list.push(issue);
    byTask.set(match[1], list);
  }
  return byTask;
}

export const PROPOSAL_TREE_LAYOUT = {
  NODE_WIDTH,
  NODE_HEIGHT,
} as const;
