import { translateUi, useUiLocale, formatUiStatus } from "@/i18n/ui";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import useAdlcBlueprintStore from "@/stores/adlcBlueprintStore";
import { useTranslation } from "react-i18next";
import "@/i18n";

type PlanPreviewDialogProps = {
  onGenerateAgain: () => void;
  onApprovePlan: () => void;
  onStartRun: () => void;
  isGenerating: boolean;
  isApproving: boolean;
  isStarting: boolean;
  canExecute: boolean;
};

function shortId(value: string) {
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value;
}

export default function PlanPreviewDialog({
  onGenerateAgain,
  onApprovePlan,
  onStartRun,
  isGenerating,
  isApproving,
  isStarting,
  canExecute,
}: PlanPreviewDialogProps) {
  useUiLocale();
  const navigate = useCustomNavigate();
  const open = useAdlcBlueprintStore((state) => state.previewOpen);
  const setOpen = useAdlcBlueprintStore((state) => state.setPreviewOpen);
  const plan = useAdlcBlueprintStore((state) => state.plan);
  const issues = useAdlcBlueprintStore((state) => state.issues);
  const previewMessage = useAdlcBlueprintStore((state) => state.previewMessage);
  const taskNames = new Map(
    plan?.tasks.map((task) => [task.plan_task_id, task.name]) ?? [],
  );
  const specs = new Map(
    plan?.resolved_node_specs.map((spec) => [
      spec.resolved_node_spec_id,
      spec,
    ]) ?? [],
  );
  const valid = plan?.validation_status === "VALID";
  const project = plan?.metadata?.adlc_local_project as
    | { name: string; base_commit: string }
    | undefined;
  const canApprovePlan =
    !previewMessage &&
    valid &&
    plan?.approval_required &&
    plan.status === "VALIDATED";
  const canStartRun =
    !previewMessage &&
    valid &&
    (plan?.status === "APPROVED" ||
      (plan?.status === "VALIDATED" && !plan.approval_required));

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-h-[90vh] max-w-4xl gap-0 overflow-hidden p-0">
        <DialogHeader className="border-b px-6 py-5">
          <div className="flex items-start justify-between gap-4 pr-8">
            <div className="space-y-1">
              <DialogTitle>{translateUi("ADLC Plan Preview")}</DialogTitle>
              <DialogDescription>
                {translateUi(
                  "Review the planned tasks, accept the plan when required, then start a run from this exact plan.",
                )}
              </DialogDescription>
            </div>
            <div className="flex flex-wrap justify-end gap-2">
              {plan && (
                <Badge
                  variant={
                    plan.status === "SUPERSEDED"
                      ? "errorStatic"
                      : "secondaryStatic"
                  }
                  size="sq"
                >
                  {formatUiStatus(plan.status, true)}
                </Badge>
              )}
              <Badge
                variant={valid ? "successStatic" : "errorStatic"}
                size="sq"
              >
                {plan?.validation_status ?? translateUi("STRUCTURAL ERROR")}
              </Badge>
            </div>
          </div>
        </DialogHeader>

        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-6 py-5">
          {project && (
            <div className="rounded-md border bg-muted/30 px-4 py-3 text-sm">
              <div className="font-medium">
                {translateUi("Project:")} {project.name}
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {translateUi("Committed revision")}{" "}
                {project.base_commit.slice(0, 12)}. This plan uses a separate
                working copy and preserves your local files.
              </div>
            </div>
          )}
          {previewMessage && (
            <div className="flex items-start gap-2 rounded-md bg-error-background px-3 py-3 text-sm text-error-foreground">
              <ForwardedIconComponent
                name="AlertTriangle"
                className="mt-0.5 h-4 w-4 shrink-0"
              />
              <span>{previewMessage}</span>
            </div>
          )}

          {plan?.status === "SUPERSEDED" && (
            <div className="flex items-start gap-2 rounded-md bg-error-background px-3 py-3 text-sm text-error-foreground">
              <ForwardedIconComponent
                name="History"
                className="mt-0.5 h-4 w-4 shrink-0"
              />
              <span>
                {translateUi(
                  "This plan is historical and read-only. Existing runs remain available, but new runs must use the latest plan version.",
                )}
              </span>
            </div>
          )}

          {plan?.supersedes_plan_id && (
            <div className="rounded-md border bg-muted/20 px-3 py-3 text-sm">
              <p className="font-medium">
                {translateUi("Version")} {plan.plan_version}{" "}
                {translateUi("replaces an earlier plan")}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {translateUi("Previous plan")}{" "}
                {shortId(plan.supersedes_plan_id)}{" "}
                {translateUi(
                  "is now SUPERSEDED and remains available for history. Approval never carries into a new version.",
                )}
              </p>
            </div>
          )}

          {plan && (
            <section className="grid gap-3 sm:grid-cols-4">
              <div className="rounded-md border p-3">
                <p className="text-xs text-muted-foreground">
                  {translateUi("Plan")}
                </p>
                <p
                  className="mt-1 font-mono text-xs"
                  title={plan.execution_plan_id}
                >
                  {shortId(plan.execution_plan_id)}
                </p>
              </div>
              <div className="rounded-md border p-3">
                <p className="text-xs text-muted-foreground">
                  {translateUi("Version")}
                </p>
                <p className="mt-1 text-sm font-semibold">
                  v{plan.plan_version}
                </p>
              </div>
              <div className="rounded-md border p-3">
                <p className="text-xs text-muted-foreground">
                  {translateUi("Tasks")}
                </p>
                <p className="mt-1 text-sm font-semibold">
                  {plan.tasks.length}
                </p>
              </div>
              <div className="rounded-md border p-3">
                <p className="text-xs text-muted-foreground">
                  {translateUi("Plan approval")}
                </p>
                <p className="mt-1 text-sm font-semibold">
                  {plan.status === "APPROVED" || plan.status === "EXECUTING"
                    ? translateUi("Accepted")
                    : plan.status === "SUPERSEDED"
                      ? translateUi("Superseded")
                      : plan.approval_required
                        ? translateUi("Required")
                        : translateUi("Not required")}
                </p>
              </div>
            </section>
          )}

          {issues.length > 0 && (
            <section className="space-y-2">
              <h3 className="text-sm font-semibold">
                {translateUi("Validation findings (")}
                {issues.length})
              </h3>
              <div className="space-y-2">
                {issues.map((issue, index) => (
                  <div
                    className="rounded-md border border-destructive/30 bg-error-background/50 px-3 py-2"
                    key={`${issue.code}-${issue.path}-${index}`}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="errorStatic" size="tag">
                        {issue.code}
                      </Badge>
                      {issue.path && (
                        <code className="text-[11px] text-muted-foreground">
                          {issue.path}
                        </code>
                      )}
                    </div>
                    <p className="mt-1 text-sm">{issue.message}</p>
                  </div>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                {translateUi(
                  "Affected stages and dependency edges are highlighted on the canvas after this preview closes.",
                )}
              </p>
            </section>
          )}

          {plan?.tasks.length ? (
            <section className="space-y-3">
              <div>
                <h3 className="text-sm font-semibold">
                  {translateUi("Resolved task order")}
                </h3>
                <p className="text-xs text-muted-foreground">
                  {translateUi(
                    "Tasks are shown in deterministic topological order.",
                  )}
                </p>
              </div>
              <div className="space-y-3">
                {plan.tasks.map((task, index) => {
                  const spec = specs.get(task.resolved_node_spec_id);
                  const dependencies = task.dependency_task_ids.map(
                    (dependencyId) =>
                      taskNames.get(dependencyId) ?? shortId(dependencyId),
                  );
                  return (
                    <article
                      className="rounded-lg border"
                      key={task.plan_task_id}
                    >
                      <header className="flex flex-wrap items-start justify-between gap-3 border-b bg-muted/20 px-4 py-3">
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
                              {index + 1}
                            </span>
                            <h4 className="text-sm font-semibold">
                              {task.name}
                            </h4>
                            <Badge variant="secondaryStatic" size="tag">
                              {task.task_type}
                            </Badge>
                          </div>
                          <p className="mt-2 text-xs text-muted-foreground">
                            {task.objective}
                          </p>
                        </div>
                        <code className="text-[11px] text-muted-foreground">
                          {shortId(task.plan_task_id)}
                        </code>
                      </header>
                      <div className="grid gap-4 px-4 py-3 text-xs sm:grid-cols-2 lg:grid-cols-3">
                        <div>
                          <p className="font-medium">
                            {translateUi("Dependencies")}
                          </p>
                          <p className="mt-1 text-muted-foreground">
                            {dependencies.length
                              ? dependencies.join(", ")
                              : translateUi("Root task")}
                          </p>
                        </div>
                        <div>
                          <p className="font-medium">
                            {translateUi("Package")}
                          </p>
                          <p className="mt-1 text-muted-foreground">
                            {spec
                              ? `${spec.package_ref.package_id}@${spec.package_ref.version}`
                              : translateUi("Unavailable")}
                          </p>
                        </div>
                        <div>
                          <p className="font-medium">
                            {translateUi("Execution")}
                          </p>
                          <p className="mt-1 text-muted-foreground">
                            {spec?.execution_profile?.provider_ref ??
                              translateUi("Control plane")}
                          </p>
                        </div>
                        <div>
                          <p className="font-medium">{translateUi("Inputs")}</p>
                          <p className="mt-1 text-muted-foreground">
                            {[
                              ...Object.keys(task.inputs),
                              ...task.input_bindings.map(
                                (binding) => binding.target_input,
                              ),
                            ].join(", ") || translateUi("None")}
                          </p>
                        </div>
                        <div>
                          <p className="font-medium">
                            {translateUi("Expected artifacts")}
                          </p>
                          <p className="mt-1 text-muted-foreground">
                            {task.expected_artifacts.join(", ") ||
                              translateUi("None")}
                          </p>
                        </div>
                        <div>
                          <p className="font-medium">{translateUi("Policy")}</p>
                          <p className="mt-1 text-muted-foreground">
                            {task.effective_policies.timeout_ms}{" "}
                            {translateUi("ms · max")}{" "}
                            {task.effective_policies.retry.max_attempts}{" "}
                            attempt(s)
                          </p>
                        </div>
                        {spec && (
                          <div>
                            <p className="font-medium">
                              {translateUi("Resolved digest")}
                            </p>
                            <p
                              className="mt-1 font-mono text-muted-foreground"
                              title={spec.resolved_digest}
                            >
                              {shortId(spec.resolved_digest)}
                            </p>
                          </div>
                        )}
                        {spec && (
                          <div className="sm:col-span-2">
                            <p className="font-medium">
                              {translateUi("Effective configuration")}
                            </p>
                            <code className="mt-1 block break-all text-muted-foreground">
                              {JSON.stringify(spec.configuration)}
                            </code>
                          </div>
                        )}
                        {spec?.execution_profile && (
                          <div className="sm:col-span-2 lg:col-span-3">
                            <p className="font-medium">
                              {translateUi("Runtime composition")}
                            </p>
                            <p className="mt-1 break-all text-muted-foreground">
                              model {spec.execution_profile.model_ref}{" "}
                              {translateUi("· memory")}{" "}
                              {spec.execution_profile.memory_policy_ref}{" "}
                              {translateUi("· sandbox")}{" "}
                              {spec.execution_profile.sandbox_policy_ref}
                            </p>
                          </div>
                        )}
                      </div>
                    </article>
                  );
                })}
              </div>
            </section>
          ) : null}
        </div>

        <DialogFooter className="items-center gap-3 border-t px-6 py-4 sm:justify-between">
          <p className="text-xs text-muted-foreground">
            {translateUi(
              "A new plan gets a new version and requires a fresh acceptance. A workflow Approval stage is separate and pauses the runtime later.",
            )}
          </p>
          <div className="flex flex-wrap justify-end gap-2">
            {plan && (
              <Button
                type="button"
                variant="ghost"
                onClick={() => navigate(`/plans/${plan.execution_plan_id}`)}
                data-testid="open-plan-detail-button"
              >
                <ForwardedIconComponent
                  name="ExternalLink"
                  className="h-4 w-4"
                />
                {translateUi("Open detail page")}
              </Button>
            )}
            <Button
              type="button"
              variant="outline"
              onClick={() => setOpen(false)}
            >
              {translateUi("Close")}
            </Button>
            <Button
              type="button"
              variant="outline"
              loading={isGenerating}
              disabled={isApproving || isStarting}
              onClick={onGenerateAgain}
            >
              {plan
                ? translateUi("Generate new plan")
                : translateUi("Try again")}
            </Button>
            {canApprovePlan && (
              <Button
                type="button"
                loading={isApproving}
                disabled={!canExecute || isStarting}
                onClick={onApprovePlan}
              >
                {translateUi("Accept plan")}
              </Button>
            )}
            {canStartRun && (
              <Button
                type="button"
                ignoreTitleCase
                loading={isStarting}
                disabled={!canExecute || isApproving}
                onClick={onStartRun}
              >
                {translateUi("Run This Plan")}
              </Button>
            )}
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
