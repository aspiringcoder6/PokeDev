import type {
  AdlcSubtaskRun,
  AdlcSubtaskSummary,
  AdlcTaskSubtasks,
} from "@/types/adlc";

/**
 * Mock subtask data for demo purposes.
 *
 * Generates realistic subtasks that:
 * - Are unique per task (based on task ID hash, not just name pattern)
 * - Respect dependencies (B only runs after A succeeds)
 * - "Final review" only succeeds when parent task is SUCCEEDED
 * - Match the task's content (research/implementation/testing/etc.)
 *
 * Replace with real API calls once the backend endpoint is available.
 */

function hashString(str: string): number {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = (hash << 5) - hash + str.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}

interface SubtaskTemplate {
  name: string;
  description: string;
  deps?: number[]; // indices of dependencies
}

const SUBTASK_TEMPLATES: Record<string, SubtaskTemplate[]> = {
  research: [
    { name: "Search documentation", description: "Find relevant docs and references" },
    { name: "Read source code", description: "Analyze existing implementation", deps: [0] },
    { name: "Identify patterns", description: "Extract common patterns and conventions", deps: [1] },
    { name: "Summarize findings", description: "Write up research summary", deps: [2] },
  ],
  implementation: [
    { name: "Design data model", description: "Define types, schemas, interfaces" },
    { name: "Implement core logic", description: "Write the main business logic", deps: [0] },
    { name: "Add error handling", description: "Handle edge cases and errors", deps: [1] },
    { name: "Write unit tests", description: "Cover core logic with tests", deps: [1] },
    { name: "Integration tests", description: "Test end-to-end flows", deps: [2, 3] },
    { name: "Final review", description: "Code review and cleanup", deps: [4] },
  ],
  testing: [
    { name: "Set up test environment", description: "Configure test fixtures and mocks" },
    { name: "Write test cases", description: "Cover happy path and edge cases", deps: [0] },
    { name: "Run test suite", description: "Execute and collect results", deps: [1] },
    { name: "Final review", description: "Review test coverage and quality", deps: [2] },
  ],
  refactor: [
    { name: "Identify code smells", description: "Find areas needing improvement" },
    { name: "Plan refactoring", description: "Design the refactoring approach", deps: [0] },
    { name: "Apply changes", description: "Implement the refactoring", deps: [1] },
    { name: "Verify behavior", description: "Ensure no regressions", deps: [2] },
    { name: "Final review", description: "Review changes and cleanup", deps: [3] },
  ],
  default: [
    { name: "Analyze requirements", description: "Understand what needs to be done" },
    { name: "Plan approach", description: "Design the solution", deps: [0] },
    { name: "Execute work", description: "Implement the solution", deps: [1] },
    { name: "Verify results", description: "Check correctness", deps: [2] },
    { name: "Final review", description: "Review and finalize", deps: [3] },
  ],
};

function getTemplate(taskName: string): SubtaskTemplate[] {
  const lower = taskName.toLowerCase();
  if (lower.includes("research") || lower.includes("analyze") || lower.includes("investigate")) {
    return SUBTASK_TEMPLATES.research;
  }
  if (lower.includes("implement") || lower.includes("build") || lower.includes("code") || lower.includes("create")) {
    return SUBTASK_TEMPLATES.implementation;
  }
  if (lower.includes("test") || lower.includes("verify") || lower.includes("check") || lower.includes("validate")) {
    return SUBTASK_TEMPLATES.testing;
  }
  if (lower.includes("refactor") || lower.includes("cleanup") || lower.includes("improve")) {
    return SUBTASK_TEMPLATES.refactor;
  }
  return SUBTASK_TEMPLATES.default;
}

/**
 * Compute realistic subtask statuses based on parent task status and dependencies.
 *
 * Rules:
 * - If parent SUCCEEDED: all subtasks succeeded
 * - If parent FAILED: last subtask failed, earlier ones succeeded/skipped
 * - If parent CANCELLED: all cancelled
 * - If parent RUNNING: subtasks progress through the DAG
 *   - Subtask N can only be succeeded if all its deps are succeeded
 *   - "Final review" (last subtask) is always pending/running when task is RUNNING
 */
function computeStatuses(
  template: SubtaskTemplate[],
  parentStatus: string,
  seed: number,
): AdlcSubtaskRun["status"][] {
  const n = template.length;
  const statuses: AdlcSubtaskRun["status"][] = new Array(n).fill("pending");

  if (parentStatus === "SUCCEEDED") {
    return new Array(n).fill("succeeded");
  }

  if (parentStatus === "FAILED") {
    // Find the failing subtask (usually the last one or one that depends on others)
    const failIdx = n - 1;
    for (let i = 0; i < n; i++) {
      if (i < failIdx) {
        statuses[i] = "succeeded";
      } else if (i === failIdx) {
        statuses[i] = "failed";
      } else {
        statuses[i] = "skipped";
      }
    }
    return statuses;
  }

  if (parentStatus === "CANCELLED") {
    return new Array(n).fill("cancelled");
  }

  // RUNNING, QUEUED, READY, CREATED — simulate progress through DAG
  // Determine how many subtasks have "completed" based on seed
  const progress = (seed % (n + 1)); // 0 to n
  const failedIdx = progress < n && (seed % 7 === 0) ? Math.min(progress, n - 1) : -1;

  for (let i = 0; i < n; i++) {
    const deps = template[i].deps || [];
    const allDepsDone = deps.every((d) => statuses[d] === "succeeded");

    if (i === failedIdx) {
      statuses[i] = "failed";
    } else if (i < progress && allDepsDone) {
      statuses[i] = "succeeded";
    } else if (i === progress && allDepsDone) {
      statuses[i] = "running";
    } else if (deps.some((d) => statuses[d] === "failed" || statuses[d] === "skipped")) {
      statuses[i] = "skipped";
    } else {
      statuses[i] = "pending";
    }
  }

  // Ensure "Final review" (last subtask) is never succeeded when task is RUNNING
  if (parentStatus === "RUNNING" && statuses[n - 1] === "succeeded") {
    statuses[n - 1] = "running";
  }

  return statuses;
}

export function getMockSubtasks(
  taskId: string,
  taskName: string,
  taskStatus: string,
): AdlcTaskSubtasks {
  const seed = hashString(taskId);
  const template = getTemplate(taskName);
  const statuses = computeStatuses(template, taskStatus, seed);

  const subtasks: AdlcSubtaskRun[] = template.map((t, i) => {
    const id = `${taskId}.sub-${i + 1}`;
    const status = statuses[i];
    const deps = (t.deps || []).map((d) => `${taskId}.sub-${d + 1}`);

    const baseDuration = 800 + ((seed + i * 137) % 4000);
    const duration =
      status === "succeeded" || status === "failed"
        ? baseDuration
        : status === "running"
          ? Math.floor(baseDuration * 0.6)
          : null;

    const startedAt =
      status !== "pending" && status !== "ready"
        ? new Date(Date.now() - (duration || 0) - 500).toISOString()
        : null;

    const completedAt =
      status === "succeeded" || status === "failed" || status === "skipped"
        ? new Date(Date.now() - 500).toISOString()
        : null;

    return {
      id,
      task_run_id: taskId,
      name: t.name,
      description: t.description,
      status,
      dependencies: deps,
      trigger: "on_success",
      started_at: startedAt,
      completed_at: completedAt,
      duration_ms: duration,
      result:
        status === "succeeded"
          ? { summary: `${t.name} completed`, artifacts: [] }
          : null,
      error:
        status === "failed"
          ? { code: "SUBTASK_FAILED", message: `${t.name} encountered an error` }
          : null,
      attempt_id: `attempt-${seed}-${i}`,
    };
  });

  const summary: AdlcSubtaskSummary = {
    total: subtasks.length,
    succeeded: subtasks.filter((s) => s.status === "succeeded").length,
    failed: subtasks.filter((s) => s.status === "failed").length,
    running: subtasks.filter((s) => s.status === "running").length,
    pending: subtasks.filter(
      (s) => s.status === "pending" || s.status === "ready",
    ).length,
    skipped: subtasks.filter((s) => s.status === "skipped").length,
  };

  return {
    task_run_id: taskId,
    subtasks,
    summary,
  };
}
