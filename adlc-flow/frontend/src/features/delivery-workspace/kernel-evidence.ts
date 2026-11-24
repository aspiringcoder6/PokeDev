import { z } from "zod";
import type { AdlcTaskRun } from "@/types/adlc";

const digest = z.string().regex(/^sha256:[0-9a-f]{64}$/);
const check = z.object({
  check_id: z.string(),
  label: z.string(),
  kind: z.enum(["BEHAVIORAL", "CONTRACT", "MOCK"]),
  passed: z.boolean(),
  exit_code: z.number().int().nullable(),
  executed_tests: z.number().int().nonnegative().nullable(),
  timed_out: z.boolean().nullable(),
});
const inspection = z.object({
  schema_version: z.literal("0.1"),
  workflow_run_id: z.string().uuid(),
  task_run_id: z.string().uuid(),
  mode: z.enum(["COMMAND", "MOCK"]),
  history_source: z.enum([
    "CHECKPOINT",
    "MEMORY",
    "RUN_SNAPSHOT",
    "UNAVAILABLE",
    "NOT_STARTED",
  ]),
  history_complete: z.boolean(),
  spec_digest: digest.nullable(),
  current_candidate_id: z.string().uuid().nullable(),
  current_candidate_digest: digest.nullable(),
  iterations: z.array(
    z.object({
      iteration: z.number().int().positive(),
      attempt_id: z.string().uuid(),
      phase: z.enum([
        "RESERVED",
        "AGENT_RUNNING",
        "CANDIDATE_CAPTURED",
        "VERIFIED",
        "FINISHED",
      ]),
      status: z.enum([
        "IN_PROGRESS",
        "PASSED",
        "CHECKS_FAILED",
        "FAILED",
        "CANCELLED",
      ]),
      candidate_id: z.string().uuid().nullable(),
      candidate_digest: digest.nullable(),
      patch_artifact_id: z.string().uuid().nullable(),
      changed_paths: z.array(z.string()),
      checks: z.array(check),
      duration_ms: z.number().int().nonnegative().nullable(),
    }),
  ),
});

export function isLiveLoop(task: AdlcTaskRun): boolean {
  return [
    "agent-provider:task-loop-harness",
    "agent-provider:coding-agent-harness-contract-loop",
    "agent-provider:task-loop-opencode",
    "agent-provider:coding-agent-contract-loop",
  ].includes(task.executor?.service ?? "");
}

export function readKernelEvidence(
  value: unknown,
  runId: string,
  taskId: string,
) {
  const view = inspection.parse(value);
  if (view.workflow_run_id !== runId || view.task_run_id !== taskId)
    throw new Error("Loop evidence scope mismatch");
  return view;
}

export function summarizeKernelEvidence(
  view: ReturnType<typeof readKernelEvidence>,
  task: AdlcTaskRun,
) {
  const latest = view.iterations.at(-1);
  const patch = (task.artifacts || []).find(
    (artifact) => artifact.artifact_id === latest?.patch_artifact_id,
  );
  // Only the authorized kernel inspection is evidence. Never infer a pass from
  // SUCCEEDED, agent output/metadata, mock comparisons, or a previous attempt.
  const bound = Boolean(
    isLiveLoop(task) &&
      view.mode === "COMMAND" &&
      view.history_complete &&
      ["CHECKPOINT", "MEMORY"].includes(view.history_source) &&
      view.spec_digest &&
      latest &&
      latest.phase === "FINISHED" &&
      latest.attempt_id === task.current_attempt_id &&
      latest.candidate_id &&
      latest.candidate_id === view.current_candidate_id &&
      latest.candidate_digest &&
      latest.candidate_digest === view.current_candidate_digest &&
      patch?.kind === "SOURCE_PATCH" &&
      patch.workflow_run_id === view.workflow_run_id &&
      patch.task_run_id === task.id &&
      patch.attempt_id === latest.attempt_id &&
      patch.metadata?.candidate_id === latest.candidate_id &&
      patch.metadata?.candidate_digest === latest.candidate_digest,
  );
  const behavioral =
    latest?.checks.filter((item) => item.kind === "BEHAVIORAL") || [];
  const tests = behavioral.reduce(
    (sum, item) => sum + (item.executed_tests || 0),
    0,
  );
  const passed = Boolean(
    bound &&
      latest?.status === "PASSED" &&
      behavioral.length &&
      behavioral.every(
        (item) =>
          item.executed_tests !== null &&
          item.executed_tests > 0 &&
          item.exit_code === 0 &&
          item.timed_out === false,
      ) &&
      latest.checks.every(
        (item) =>
          item.kind !== "MOCK" &&
          item.passed &&
          item.timed_out !== true &&
          (item.exit_code === null || item.exit_code === 0),
      ),
  );
  return { bound, passed, tests, latest };
}
