import {
  translateUi,
  useUiLocale,
  getUiLanguage,
  formatUiStatus,
} from "@/i18n/ui";
import axios from "axios";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import Loading from "@/components/ui/loading";
import {
  approveAdlcExecutionPlan,
  createAdlcRunFromExecutionPlan,
  getAdlcExecutionPlan,
} from "@/controllers/API/adlc";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import type { AdlcExecutionPlan } from "@/types/adlc";
import PlanTaskGraph from "@/features/adlc-blueprint/plan-task-graph";
import { useTranslation } from "react-i18next";
import i18n from "@/i18n";

function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail?.message === "string") return detail.message;
    if (typeof detail === "string") return detail;
  }
  return error instanceof Error
    ? error.message
    : translateUi("Unable to load this plan.");
}

function statusVariant(status: string): BadgeProps["variant"] {
  if (status === "APPROVED" || status === "EXECUTING") return "successStatic";
  if (status === "INVALID" || status === "REJECTED") return "errorStatic";
  if (status === "SUPERSEDED") return "purpleStatic";
  return "secondaryStatic";
}

function shortId(value: string): string {
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value;
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat(getUiLanguage(), {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));
}

export default function PlanDetailPage() {
  const { t } = useTranslation();
  useUiLocale();
  const { planId } = useParams();
  const navigate = useCustomNavigate();
  const [plan, setPlan] = useState<AdlcExecutionPlan>();
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState<"accept" | "run" | undefined>();
  const [error, setError] = useState<string>();
  const [showTransition, setShowTransition] = useState(false);

  const loadPlan = useCallback(async () => {
    if (!planId) return;
    try {
      const snapshot = await getAdlcExecutionPlan(planId);
      setPlan(snapshot);
      setError(undefined);
    } catch (loadError) {
      setError(errorMessage(loadError));
    } finally {
      setLoading(false);
    }
  }, [planId]);

  useEffect(() => {
    void loadPlan();
  }, [loadPlan]);

  const acceptPlan = async () => {
    if (!planId) return;
    setActing("accept");
    try {
      setPlan(await approveAdlcExecutionPlan(planId));
      setError(undefined);
      // Show 2s transition spinner so user sees the state change
      // before the Run button appears.
      setShowTransition(true);
      window.setTimeout(() => setShowTransition(false), 2000);
    } catch (actionError) {
      setError(errorMessage(actionError));
    } finally {
      setActing(undefined);
    }
  };

  const runPlan = async () => {
    if (!planId) return;
    setActing("run");
    try {
      const run = await createAdlcRunFromExecutionPlan(
        planId,
        crypto.randomUUID(),
      );
      navigate(`/runs/${run.id}`);
    } catch (actionError) {
      setError(errorMessage(actionError));
      setActing(undefined);
    }
  };

  if (loading) {
    return (
      <div className="flex h-full w-full items-center justify-center">
        <Loading
          aria-label={translateUi("Loading ADLC execution plan")}
          className="h-7 w-7 text-primary"
        />
      </div>
    );
  }

  if (!plan) {
    return (
      <div className="flex h-full w-full flex-col items-center justify-center gap-4 p-6">
        <p className="text-sm text-destructive">
          {error ?? translateUi("Execution plan not found.")}
        </p>
        <Button variant="outline" onClick={() => navigate("/flows")}>
          {translateUi("Back to flows")}
        </Button>
      </div>
    );
  }

  const specs = new Map(
    plan.resolved_node_specs.map((spec) => [spec.resolved_node_spec_id, spec]),
  );
  const taskNames = new Map(
    plan.tasks.map((task) => [task.plan_task_id, task.name]),
  );
  const valid = plan.validation_status === "VALID";
  const canAcceptPlan =
    valid && plan.approval_required && plan.status === "VALIDATED";
  const planIsRunnable =
    plan.status === "APPROVED" ||
    (plan.status === "VALIDATED" && !plan.approval_required);
  const canRunPlan = valid && planIsRunnable;

  return (
    <main className="h-full w-full overflow-y-auto bg-background">
      <div className="mx-auto flex max-w-6xl flex-col gap-6 p-6 lg:p-8">
        <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-2">
            <Button
              variant="ghost"
              size="xs"
              className="-ml-3 text-muted-foreground"
              onClick={() =>
                navigate(
                  plan.workflow_definition_id
                    ? `/flow/${plan.workflow_definition_id}`
                    : "/flows",
                )
              }
            >
              <ForwardedIconComponent name="ArrowLeft" className="h-4 w-4" />
              {translateUi("Back to workflow definition")}
            </Button>
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-2xl font-semibold">
                {translateUi("Execution Plan")}
              </h1>
              <Badge variant={statusVariant(plan.status)} size="tag">
                {formatUiStatus(plan.status, true)}
              </Badge>
              <Badge
                variant={valid ? "successStatic" : "errorStatic"}
                size="tag"
              >
                {formatUiStatus(plan.validation_status, true)}
              </Badge>
              <Badge variant="secondaryStatic" size="tag">
                v{plan.plan_version}
              </Badge>
            </div>
            <p className="font-mono text-xs text-muted-foreground">
              {translateUi("Plan")} {plan.execution_plan_id}
            </p>
            <p className="text-xs text-muted-foreground">
              {translateUi("Compiled from workflow definition")}{" "}
              <button
                type="button"
                className="font-mono underline-offset-2 hover:underline"
                onClick={() => navigate(`/flow/${plan.workflow_definition_id}`)}
              >
                {plan.workflow_definition_id}
              </button>{" "}
              {translateUi("· generated")} {formatTime(plan.generated_at)} by{" "}
              {plan.generated_by}
            </p>
            {plan.supersedes_plan_id && (
              <p className="text-xs text-muted-foreground">
                {translateUi("Replaces plan")}{" "}
                {shortId(plan.supersedes_plan_id)} (superseded).
              </p>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button variant="outline" size="md" onClick={() => void loadPlan()}>
              <ForwardedIconComponent name="RefreshCw" className="h-4 w-4" />
              {translateUi("Refresh")}
            </Button>
            <Button
              variant="outline"
              size="md"
              onClick={() =>
                navigate(`/runs/?planId=${plan.execution_plan_id}`)
              }
            >
              <ForwardedIconComponent name="History" className="h-4 w-4" />
              {translateUi("View runs")}
            </Button>
            {canAcceptPlan && (
              <Button
                size="md"
                ignoreTitleCase
                loading={acting === "accept"}
                onClick={() => void acceptPlan()}
              >
                {translateUi("Accept plan")}
              </Button>
            )}
            {canRunPlan && (
              <Button
                size="md"
                ignoreTitleCase
                loading={acting === "run"}
                onClick={() => void runPlan()}
              >
                <ForwardedIconComponent name="Play" className="h-4 w-4" />
                {translateUi("Run This Plan")}
              </Button>
            )}
          </div>
        </header>

        {showTransition && (
          <div
            className="flex flex-col items-center justify-center gap-3 rounded-md border bg-muted/30 p-8"
            data-testid="plan-transition-spinner"
            role="status"
            aria-live="polite"
          >
            <Loading
              aria-label={t("adlc.run.ariaPreparingRun")}
              className="h-10 w-10 animate-spin text-primary"
            />
            <p className="text-sm font-medium text-foreground">
              {t("adlc.plan.planApprovedPreparing")}
            </p>
            <p className="text-xs text-muted-foreground">
              {t("adlc.plan.subtasksGeneratedNote")}
            </p>
          </div>
        )}

        {error && (
          <div
            role="alert"
            className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm"
          >
            {error}
          </div>
        )}

        {plan.warnings.length > 0 && (
          <div className="rounded-md border border-warning bg-warning/20 p-3 text-sm">
            <p className="font-medium">
              {translateUi("Warnings (")}
              {plan.warnings.length})
            </p>
            <ul className="mt-1 list-inside list-disc text-xs text-muted-foreground">
              {plan.warnings.map((warning, index) => (
                <li key={`${warning.code}-${index}`}>
                  {warning.code}: {warning.message}
                </li>
              ))}
            </ul>
          </div>
        )}

        <Card className="bg-background">
          <CardHeader>
            <CardTitle>{translateUi("Task dependency graph")}</CardTitle>
            <CardDescription>
              {plan.tasks.length}{" "}
              {translateUi(
                "tasks compiled from the workflow definition. Each task appears once; arrows show which tasks must succeed first. Root tasks start as soon as the run begins.",
              )}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <PlanTaskGraph tasks={plan.tasks} specs={specs} />
          </CardContent>
        </Card>

        <Card className="bg-background">
          <CardHeader>
            <CardTitle>{translateUi("Task details")}</CardTitle>
            <CardDescription>
              {translateUi(
                "Resolved package snapshots, executors, and policies for every planned task.",
              )}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {plan.tasks.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {translateUi("This plan has no executable tasks")}
                {plan.status === "INVALID"
                  ? translateUi(
                      " because validation failed. Fix the blueprint and generate a new plan.",
                    )
                  : "."}
              </p>
            ) : (
              <ol className="divide-y rounded-md border">
                {plan.tasks.map((task) => {
                  const spec = specs.get(task.resolved_node_spec_id);
                  const dependencies = task.dependency_task_ids.map(
                    (dependency) =>
                      taskNames.get(dependency) ?? shortId(dependency),
                  );
                  return (
                    <li
                      key={task.plan_task_id}
                      className="flex flex-col gap-2 p-4"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <p className="truncate text-sm font-medium">
                              {task.name}
                            </p>
                            <Badge variant="secondaryStatic" size="tag">
                              {task.task_type}
                            </Badge>
                          </div>
                          <p className="truncate text-xs text-muted-foreground">
                            {task.objective}
                          </p>
                        </div>
                        <code className="text-[11px] text-muted-foreground">
                          {shortId(task.plan_task_id)}
                        </code>
                      </div>
                      <div className="grid gap-2 text-xs text-muted-foreground sm:grid-cols-2 lg:grid-cols-4">
                        <p>
                          <span className="font-medium text-foreground">
                            {translateUi("Depends on:")}
                          </span>{" "}
                          {dependencies.length
                            ? dependencies.join(", ")
                            : translateUi("nothing (root)")}
                        </p>
                        <p>
                          <span className="font-medium text-foreground">
                            {translateUi("Package:")}
                          </span>{" "}
                          {spec
                            ? `${spec.package_ref.package_id}@${spec.package_ref.version}`
                            : "unavailable"}
                        </p>
                        <p>
                          <span className="font-medium text-foreground">
                            {translateUi("Executor:")}
                          </span>{" "}
                          {spec?.implementation
                            ? `${spec.implementation.adapter_ref} (${spec.implementation.entrypoint})`
                            : "unavailable"}
                        </p>
                        <p>
                          <span className="font-medium text-foreground">
                            {translateUi("Policy:")}
                          </span>{" "}
                          max {task.effective_policies.retry.max_attempts}{" "}
                          {translateUi("attempt(s) ·")}{" "}
                          {task.effective_policies.timeout_ms}{" "}
                          {translateUi("ms timeout")}
                        </p>
                      </div>
                    </li>
                  );
                })}
              </ol>
            )}
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
