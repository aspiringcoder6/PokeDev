import { translateUi, useUiLocale } from "@/i18n/ui";
import type { AdlcLoopRuntimeView } from "@/types/adlc";

const PROTOCOL = "task-loop-runtime:iteration/0.1.0";
const PROTOCOL_V2 = "task-loop-runtime:iteration/0.2.0";
const runtimeName = (value: unknown) =>
  typeof value === "string" && /^[A-Za-z0-9_./:-]{1,160}$/.test(value);

export function supportedLoopRuntime(
  value: AdlcLoopRuntimeView | null | undefined,
  runId: string,
  taskId: string,
): boolean {
  if (
    !value ||
    !["0.1", "0.2"].includes(value.schema_version) ||
    value.workflow_run_id !== runId ||
    value.task_run_id !== taskId ||
    value.execution_unified_with_harness !== false ||
    !["CHECKPOINT", "LEGACY", "NOT_STARTED", "UNAVAILABLE"].includes(
      value.binding_source,
    )
  )
    return false;
  if (value.binding_source !== "CHECKPOINT")
    return value.runtime === null && value.protocol_ref === null;
  const r = value.runtime;
  const protocol = value.schema_version === "0.2" ? PROTOCOL_V2 : PROTOCOL;
  return (
    !!r &&
    value.protocol_ref === protocol &&
    r.protocol_ref === protocol &&
    (value.schema_version !== "0.2" || r.cost_reporting === "UNAVAILABLE") &&
    runtimeName(r.runtime_ref) &&
    runtimeName(r.provider_id) &&
    runtimeName(r.model_id) &&
    (r.agent === null || runtimeName(r.agent)) &&
    ["OPENCODE", "HARNESS", "CUSTOM"].includes(r.family) &&
    Array.isArray(r.modes) &&
    r.modes.length >= 1 &&
    r.modes.length <= 2 &&
    new Set(r.modes).size === r.modes.length &&
    r.modes.every((mode) =>
      ["WORKSPACE_EDIT", "FILE_PROPOSAL"].includes(mode),
    ) &&
    r.fresh_sessions === true &&
    r.reported_usage === true &&
    r.cancellation === true
  );
}

export default function TaskLoopRuntimeDisclosure({
  value,
  runId,
  taskId,
  mock,
}: {
  value: AdlcLoopRuntimeView | null | undefined;
  runId: string;
  taskId: string;
  mock: boolean;
}) {
  useUiLocale();
  const valid = supportedLoopRuntime(value, runId, taskId);
  const runtime = valid ? value?.runtime : null;
  return (
    <div
      aria-label={translateUi("Task loop runtime")}
      className="space-y-1 text-xs text-muted-foreground"
    >
      <p>
        {mock
          ? translateUi("Runtime: deterministic mock; not a Harness execution.")
          : runtime
            ? translateUi("Runtime: {{value0}} · {{value1}}/{{value2}}", {
                value0:
                  runtime.family === "OPENCODE"
                    ? "OpenCode"
                    : runtime.family === "HARNESS"
                      ? "Harness adapter"
                      : "Custom adapter",
                value1: runtime.provider_id,
                value2: runtime.model_id,
              })
            : valid && value?.binding_source === "LEGACY"
              ? translateUi(
                  "Runtime: legacy checkpoint; no standardized runtime binding was recorded.",
                )
              : valid && value?.binding_source === "NOT_STARTED"
                ? translateUi(
                    "Runtime: pending dispatch; no runtime binding has been recorded.",
                  )
                : translateUi(
                    "Runtime identity unavailable; no unification claim can be made.",
                  )}
      </p>
      {runtime && (
        <p>
          {translateUi("Iteration protocol")} {value?.schema_version} ·{" "}
          {runtime.runtime_ref}
        </p>
      )}
      {runtime?.cost_reporting === "UNAVAILABLE" && (
        <p>
          {translateUi(
            "Reported token usage is retained when available; monetary cost is unavailable, not zero.",
          )}
        </p>
      )}
      {!mock && (
        <p>
          {runtime?.family === "HARNESS"
            ? translateUi(
                "This loop uses Harness proposals; ADLC still owns candidate capture, Verify and human approval. Other plugin profiles have separate lifecycles; this is not one fully unified Harness runtime.",
              )
            : translateUi(
                "Runtime-neutral loop protocol; requirement and contract-only runs still use their existing Harness profiles. This is not one fully unified Harness runtime.",
              )}
        </p>
      )}
    </div>
  );
}
