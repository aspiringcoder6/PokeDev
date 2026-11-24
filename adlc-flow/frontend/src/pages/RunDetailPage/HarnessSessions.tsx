import { translateUi, useUiLocale, formatUiStatus } from "@/i18n/ui";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type {
  AdlcHarnessInteraction,
  AdlcHarnessJsonSchemaProperty,
  AdlcHarnessRunSession,
  AdlcTaskRun,
} from "@/types/adlc";
import { useTranslation } from "react-i18next";
import "@/i18n";

interface HarnessSessionsProps {
  sessions: AdlcHarnessRunSession[];
  tasks: AdlcTaskRun[];
  actingOn?: string;
  onRespond: (
    sessionId: string,
    interactionId: string,
    response: Record<string, unknown>,
  ) => void;
  onSubmit: (sessionId: string) => void;
  onReconcileVerification?: (sessionId: string) => void;
  canSubmit?: (sessionId: string) => boolean;
}

function fieldValue(
  rawValue: string | boolean | string[],
  property: AdlcHarnessJsonSchemaProperty,
): unknown {
  if (property.type === "array") return Array.isArray(rawValue) ? rawValue : [];
  if (property.type === "boolean") return Boolean(rawValue);
  if (property.type === "number" || property.type === "integer") {
    return rawValue === "" ? null : Number(rawValue);
  }
  if (property.enum) {
    return (
      property.enum.find((candidate) => String(candidate) === rawValue) ??
      rawValue
    );
  }
  return rawValue;
}

function HarnessForm({
  sessionId,
  interaction,
  actingOn,
  onRespond,
}: {
  sessionId: string;
  interaction: AdlcHarnessInteraction;
  actingOn?: string;
  onRespond: HarnessSessionsProps["onRespond"];
}) {
  useUiLocale();
  const properties = interaction.input_schema.properties ?? {};
  const [values, setValues] = useState<
    Record<string, string | boolean | string[]>
  >(() =>
    Object.fromEntries(
      Object.entries(properties).map(([name, property]) => [
        name,
        property.default === undefined
          ? property.type === "array"
            ? []
            : property.type === "boolean"
              ? false
              : ""
          : property.type === "array"
            ? Array.isArray(property.default)
              ? property.default.map(String)
              : []
            : property.type === "boolean"
              ? Boolean(property.default)
              : String(property.default),
      ]),
    ),
  );
  const actionKey = `harness-interaction-${interaction.interaction_id}`;

  return (
    <form
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        onRespond(
          sessionId,
          interaction.interaction_id,
          Object.fromEntries(
            Object.entries(properties).map(([name, property]) => [
              name,
              fieldValue(values[name] ?? "", property),
            ]),
          ),
        );
      }}
    >
      {Object.entries(properties).map(([name, property]) => {
        const label = property.title ?? formatUiStatus(name, true);
        const inputId = `${interaction.interaction_id}-${name}`;
        return (
          <div key={name} className="space-y-2">
            {property.type === "array" && property.items?.enum ? (
              <fieldset className="space-y-2">
                <legend className="text-sm font-medium leading-none">
                  {label}
                </legend>
                <div className="space-y-2">
                  {property.items.enum.map((choice) => {
                    const choiceValue = String(choice);
                    const selected = Array.isArray(values[name])
                      ? values[name]
                      : [];
                    const choiceId = `${inputId}-${choiceValue}`;
                    return (
                      <div
                        key={choiceValue}
                        className="flex items-center gap-2"
                      >
                        <Checkbox
                          id={choiceId}
                          checked={selected.includes(choiceValue)}
                          onCheckedChange={(checked) =>
                            setValues((current) => {
                              const currentValues = Array.isArray(current[name])
                                ? current[name]
                                : [];
                              return {
                                ...current,
                                [name]:
                                  checked === true
                                    ? [...currentValues, choiceValue]
                                    : currentValues.filter(
                                        (value) => value !== choiceValue,
                                      ),
                              };
                            })
                          }
                        />
                        <Label htmlFor={choiceId}>{choiceValue}</Label>
                      </div>
                    );
                  })}
                </div>
              </fieldset>
            ) : property.type === "boolean" ? (
              <div className="flex items-center gap-2">
                <Checkbox
                  id={inputId}
                  checked={Boolean(values[name])}
                  onCheckedChange={(checked) =>
                    setValues((current) => ({
                      ...current,
                      [name]: checked === true,
                    }))
                  }
                />
                <Label htmlFor={inputId}>{label}</Label>
              </div>
            ) : (
              <>
                <Label htmlFor={inputId}>{label}</Label>
                {property.enum ? (
                  <select
                    id={inputId}
                    required={interaction.input_schema.required?.includes(name)}
                    value={String(values[name] ?? "")}
                    onChange={(event) =>
                      setValues((current) => ({
                        ...current,
                        [name]: event.target.value,
                      }))
                    }
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                  >
                    <option value="">{translateUi("Select an option")}</option>
                    {property.enum.map((choice) => (
                      <option key={String(choice)} value={String(choice)}>
                        {String(choice)}
                      </option>
                    ))}
                  </select>
                ) : (
                  <Input
                    id={inputId}
                    type={
                      property.type === "number" || property.type === "integer"
                        ? "number"
                        : "text"
                    }
                    required={interaction.input_schema.required?.includes(name)}
                    value={String(values[name] ?? "")}
                    onChange={(event) =>
                      setValues((current) => ({
                        ...current,
                        [name]: event.target.value,
                      }))
                    }
                  />
                )}
              </>
            )}
            {property.description && (
              <p className="text-xs text-muted-foreground">
                {property.description}
              </p>
            )}
          </div>
        );
      })}
      <Button type="submit" loading={actingOn === actionKey}>
        {translateUi("Submit response")}
      </Button>
    </form>
  );
}

export default function HarnessSessions({
  sessions,
  tasks,
  actingOn,
  onRespond,
  onSubmit,
  onReconcileVerification,
  canSubmit,
}: HarnessSessionsProps) {
  useUiLocale();
  const actionable = sessions.filter(
    ({ session }) =>
      session.interactions.some(
        (interaction) => interaction.status === "PENDING",
      ) ||
      (session.submission_mode === "MANUAL" &&
        session.status === "READY_FOR_SUBMISSION") ||
      (Boolean(onReconcileVerification) &&
        session.status === "VERIFYING" &&
        session.events?.at(-1)?.event_type ===
          "execution.reconciliation_waiting"),
  );
  if (actionable.length === 0) return null;

  return (
    <section className="space-y-4" aria-label={translateUi("Agent requests")}>
      {actionable.map(({ task_run_id: taskRunId, session }) => {
        const task = tasks.find((candidate) => candidate.id === taskRunId);
        const pending = session.interactions.find(
          (interaction) => interaction.status === "PENDING",
        );
        const submitKey = `harness-submit-${session.session_id}`;
        const recoveryPending =
          session.status === "VERIFYING" &&
          session.events?.at(-1)?.event_type ===
            "execution.reconciliation_waiting";
        return (
          <Card
            key={session.session_id}
            className="border-primary/30 bg-background"
          >
            <CardHeader>
              <CardTitle>
                {pending?.title ??
                  (recoveryPending
                    ? translateUi("Verification recovery is waiting")
                    : translateUi("Return agent result"))}
              </CardTitle>
              <CardDescription>
                {pending?.prompt ??
                  (recoveryPending
                    ? translateUi(
                        "Restore the ADLC connection, then retry the saved verification. This does not call the model again or Submit the result.",
                      )
                    : translateUi(
                        "Review the output and verification below, then Submit to return this result to the workflow.",
                      ))}
                {task
                  ? translateUi(" Task: {{value0}}.", { value0: task.name })
                  : ""}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {recoveryPending && onReconcileVerification && (
                <Button
                  loading={
                    actingOn === `harness-recovery-${session.session_id}`
                  }
                  disabled={
                    Boolean(actingOn) &&
                    actingOn !== `harness-recovery-${session.session_id}`
                  }
                  onClick={() => onReconcileVerification(session.session_id)}
                >
                  {translateUi("Retry verification recovery")}
                </Button>
              )}
              {pending?.kind === "APPROVAL" && (
                <div className="flex flex-wrap gap-2">
                  <Button
                    loading={
                      actingOn ===
                      `harness-interaction-${pending.interaction_id}`
                    }
                    onClick={() =>
                      onRespond(session.session_id, pending.interaction_id, {
                        action: "approve",
                      })
                    }
                  >
                    {translateUi("Approve agent request")}
                  </Button>
                  <Button
                    variant="outline"
                    disabled={
                      actingOn ===
                      `harness-interaction-${pending.interaction_id}`
                    }
                    onClick={() =>
                      onRespond(session.session_id, pending.interaction_id, {
                        action: "reject",
                      })
                    }
                  >
                    {translateUi("Reject agent request")}
                  </Button>
                </div>
              )}
              {pending?.kind === "FORM" && (
                <HarnessForm
                  key={pending.interaction_id}
                  sessionId={session.session_id}
                  interaction={pending}
                  actingOn={actingOn}
                  onRespond={onRespond}
                />
              )}
              {!pending &&
                session.submission_mode === "MANUAL" &&
                session.status === "READY_FOR_SUBMISSION" && (
                  <Button
                    disabled={canSubmit?.(session.session_id) === false}
                    loading={actingOn === submitKey}
                    onClick={() => onSubmit(session.session_id)}
                  >
                    {session.result?.status === "FAILED" ||
                    session.result?.status === "CANCELLED"
                      ? translateUi("Submit failed result")
                      : translateUi("Submit verified result")}
                  </Button>
                )}
            </CardContent>
          </Card>
        );
      })}
    </section>
  );
}
