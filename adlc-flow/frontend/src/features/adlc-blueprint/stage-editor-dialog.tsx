import { translateUi, useUiLocale, formatUiStatus } from "@/i18n/ui";
import { useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { AdlcNodePackage, AdlcWorkflowStage } from "@/types/adlc";
import {
  adlcPackageKey,
  createAdlcStage,
  stageTypeForPackage,
} from "@/utils/adlc-blueprint";
import {
  APPROVED_REFERENCE_ERROR,
  parseApprovedReference,
} from "./approved-reference";
import { useTranslation } from "react-i18next";
import i18n from "@/i18n";

type StageEditorDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  packages: AdlcNodePackage[];
  initialStage?: AdlcWorkflowStage;
  onSave: (stage: AdlcWorkflowStage) => void;
  embedded?: boolean;
  readOnly?: boolean;
  boundInputs?: string[];
};

function serializeInput(value: unknown): string {
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

function parseInput(value: string): unknown {
  const trimmed = value.trim();
  if (!trimmed) return "";
  if (
    trimmed.startsWith("{") ||
    trimmed.startsWith("[") ||
    trimmed === "true" ||
    trimmed === "false" ||
    trimmed === "null" ||
    /^-?\d+(\.\d+)?$/.test(trimmed)
  ) {
    try {
      return JSON.parse(trimmed);
    } catch {
      return value;
    }
  }
  return value;
}

function defaultInputDraft(nodePackage: AdlcNodePackage, slotName: string) {
  if (nodePackage.package_id === "coding-agent" && slotName === "requirement") {
    return i18n.t("adlc.bp.placeholderRequirement");
  }
  return "";
}

function isUnifiedCodingAgent(nodePackage?: AdlcNodePackage) {
  return (
    nodePackage?.package_id === "coding-agent" &&
    ["0.2.0", "0.2.1", "0.3.0"].includes(nodePackage.version)
  );
}

const replacedPackages = new Set([
  "coding-agent-deepseek-harness",
  "coding-agent-contract-harness",
  "task-loop-opencode",
]);

export default function StageEditorDialog({
  open,
  onOpenChange,
  packages,
  initialStage,
  onSave,
  embedded = false,
  readOnly = false,
  boundInputs = [],
}: StageEditorDialogProps) {
  const { t } = useTranslation();
  useUiLocale();
  const unifiedPackage =
    packages.find((p) => isUnifiedCodingAgent(p) && p.version === "0.3.0") ??
    packages.find((p) => isUnifiedCodingAgent(p) && p.version === "0.2.1") ??
    packages.find(isUnifiedCodingAgent);
  const cataloguePackages = packages.filter(
    (item) =>
      !unifiedPackage ||
      isUnifiedCodingAgent(item) ||
      (item.package_id !== "coding-agent" &&
        !replacedPackages.has(item.package_id)) ||
      (initialStage &&
        adlcPackageKey(item) === adlcPackageKey(initialStage.package_ref)),
  );
  const initialPackageKey = initialStage
    ? adlcPackageKey(initialStage.package_ref)
    : cataloguePackages[0]
      ? adlcPackageKey(cataloguePackages[0])
      : "";
  const [packageKey, setPackageKey] = useState(initialPackageKey);
  const [name, setName] = useState("");
  const [objective, setObjective] = useState("");
  const [directInputs, setDirectInputs] = useState<string[]>([]);
  const [inputDrafts, setInputDrafts] = useState<Record<string, string>>({});
  const [configuration, setConfiguration] = useState<Record<string, unknown>>(
    {},
  );
  const [approvedReferenceDraft, setApprovedReferenceDraft] = useState("");
  const [timeoutMs, setTimeoutMs] = useState("");
  const [modelRef, setModelRef] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const selectedPackage = useMemo(
    () => packages.find((item) => adlcPackageKey(item) === packageKey),
    [packageKey, packages],
  );
  const selectedPackageIsDeprecated =
    selectedPackage?.lifecycle_status === "DEPRECATED";
  const unified = isUnifiedCodingAgent(selectedPackage);
  const loopEnabled =
    unified &&
    Boolean(
      configuration.task_loop_enabled ??
        selectedPackage?.defaults.task_loop_enabled,
    );

  useEffect(() => {
    if (!open) return;
    const nextPackageKey = initialStage
      ? adlcPackageKey(initialStage.package_ref)
      : cataloguePackages[0]
        ? adlcPackageKey(cataloguePackages[0])
        : "";
    const nodePackage = packages.find(
      (item) => adlcPackageKey(item) === nextPackageKey,
    );
    setPackageKey(nextPackageKey);
    setName(
      initialStage?.name ??
        nodePackage?.name.replace(/\s*\(Mock\)\s*$/, "") ??
        "",
    );
    setObjective(initialStage?.objective ?? nodePackage?.description ?? "");
    const initialInputs = initialStage?.inputs ?? {};
    const suppliedNames = initialStage
      ? Object.keys(initialInputs)
      : (nodePackage?.interface.inputs ?? [])
          .filter((slot) => slot.required)
          .map((slot) => slot.name);
    setDirectInputs(suppliedNames);
    setInputDrafts(
      Object.fromEntries(
        (nodePackage?.interface.inputs ?? []).map((slot) => [
          slot.name,
          slot.name in initialInputs
            ? serializeInput(initialInputs[slot.name])
            : defaultInputDraft(nodePackage!, slot.name),
        ]),
      ),
    );
    setConfiguration({
      ...initialStage?.configuration_overrides,
      ...(isUnifiedCodingAgent(nodePackage) && "task_loop_spec" in initialInputs
        ? { task_loop_enabled: true }
        : {}),
    });
    const reference =
      initialStage?.configuration_overrides.approved_contract_ref;
    setApprovedReferenceDraft(
      reference ? JSON.stringify(reference, null, 2) : "",
    );
    const timeout = initialStage?.policy_overrides?.timeout_ms;
    setTimeoutMs(timeout === undefined ? "" : String(timeout));
    const model = initialStage?.execution_profile_overrides?.model_ref;
    setModelRef(typeof model === "string" ? model : "");
    setFormError(null);
  }, [initialStage, open, packages]);

  const selectPackage = (nextPackageKey: string) => {
    const nodePackage = packages.find(
      (item) => adlcPackageKey(item) === nextPackageKey,
    );
    setPackageKey(nextPackageKey);
    if (!nodePackage) return;

    // Preserve user-typed name/objective if they differ from the previous
    // package's defaults. This avoids wiping the user's work when they
    // only want to switch the agent.
    const previousPackage = selectedPackage;
    const previousDefaultName = previousPackage?.name.replace(
      /\s*\(Mock\)\s*$/,
      "",
    );
    const previousDefaultObjective = previousPackage?.description;
    const newDefaultName = nodePackage.name.replace(/\s*\(Mock\)\s*$/, "");
    const newDefaultObjective = nodePackage.description;

    // Keep the user's name/objective if they had customised them; otherwise
    // fall back to the new package's defaults.
    setName(name && name !== previousDefaultName ? name : newDefaultName);
    setObjective(
      objective && objective !== previousDefaultObjective
        ? objective
        : newDefaultObjective,
    );

    // Preserve input values for slots that exist in BOTH the old and new
    // package's interface. Drop slots that no longer exist; add new slots
    // with their default draft.
    const oldInputNames = new Set(
      (previousPackage?.interface.inputs ?? []).map((slot) => slot.name),
    );
    const newInputNames = new Set(
      nodePackage.interface.inputs.map((slot) => slot.name),
    );
    const preservedDirectInputs = directInputs.filter(
      (slotName) =>
        newInputNames.has(slotName) && !boundInputs.includes(slotName),
    );
    // Add required slots from the new package that weren't in the old one.
    const requiredNewSlots = nodePackage.interface.inputs
      .filter((slot) => slot.required && !oldInputNames.has(slot.name))
      .map((slot) => slot.name);
    setDirectInputs(
      Array.from(new Set([...preservedDirectInputs, ...requiredNewSlots])),
    );
    setInputDrafts(
      Object.fromEntries(
        nodePackage.interface.inputs.map((slot) => [
          slot.name,
          slot.name in inputDrafts
            ? inputDrafts[slot.name]
            : defaultInputDraft(nodePackage, slot.name),
        ]),
      ),
    );

    // Preserve configuration_overrides keys that exist in the new package's
    // configuration_schema. Drop keys that no longer apply.
    const newConfigSchema = nodePackage.configuration_schema;
    const newConfigProperties =
      (newConfigSchema.properties as Record<string, unknown> | undefined) ?? {};
    const preservedConfiguration: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(configuration)) {
      if (key in newConfigProperties) {
        preservedConfiguration[key] = value;
      }
    }
    setConfiguration(preservedConfiguration);

    // Preserve approved reference draft if the new package supports it.
    const newPackageSupportsApprovedRef =
      nodePackage.package_id === "coding-agent-contract-harness" ||
      isUnifiedCodingAgent(nodePackage);
    setApprovedReferenceDraft(
      newPackageSupportsApprovedRef ? approvedReferenceDraft : "",
    );

    // Preserve timeout_ms and model_ref — these are package-agnostic.
    // (They are only saved if the new package's override_allowlist permits.)
    setTimeoutMs(timeoutMs);
    setModelRef(modelRef);
    setFormError(null);
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (readOnly) return;
    if (!selectedPackage) {
      setFormError(t("adlc.bp.selectPublished"));
      return;
    }
    if (selectedPackageIsDeprecated) {
      setFormError(t("adlc.bp.deprecatedVersion"));
      return;
    }
    if (!name.trim() || !objective.trim()) {
      setFormError(t("adlc.bp.nameObjectiveRequired"));
      return;
    }
    const parsedTimeout = timeoutMs ? Number(timeoutMs) : undefined;
    if (
      parsedTimeout !== undefined &&
      (!Number.isInteger(parsedTimeout) || parsedTimeout < 1)
    ) {
      setFormError(t("adlc.bp.timeoutPositive"));
      return;
    }

    const configurationForSave = { ...configuration };
    if (
      selectedPackage.package_id === "coding-agent-contract-harness" ||
      unified
    ) {
      try {
        configurationForSave.approved_contract_ref =
          unified && !approvedReferenceDraft.trim()
            ? null
            : parseApprovedReference(approvedReferenceDraft);
      } catch {
        setFormError(APPROVED_REFERENCE_ERROR);
        return;
      }
    }
    const inputs = Object.fromEntries(
      selectedPackage.interface.inputs
        .filter(
          (slot) =>
            directInputs.includes(slot.name) &&
            !boundInputs.includes(slot.name) &&
            (!unified || slot.name !== "task_loop_spec" || loopEnabled),
        )
        .map((slot) => [slot.name, parseInput(inputDrafts[slot.name] ?? "")]),
    );
    if (unified) {
      configurationForSave.task_loop_enabled = loopEnabled;
      if (
        !loopEnabled &&
        (typeof inputs.requirement !== "string" ||
          !inputs.requirement.trim()) &&
        directInputs.includes("requirement")
      ) {
        setFormError(t("adlc.bp.placeholderRequirement"));
        return;
      }
      if (loopEnabled && directInputs.includes("task_loop_spec")) {
        try {
          const spec = JSON.parse(inputDrafts.task_loop_spec ?? "");
          if (!spec || typeof spec !== "object" || Array.isArray(spec))
            throw new Error(t("adlc.bp.missingSpec"));
          inputs.task_loop_spec = spec;
        } catch {
          setFormError(
            "Paste a task loop specification as a JSON object with a pinned commit and verification checks.",
          );
          return;
        }
      }
      if (
        (loopEnabled || configurationForSave.approved_contract_ref) &&
        configurationForSave.submission_mode === "AUTO"
      ) {
        setFormError(t("adlc.bp.manualReviewRequired"));
        return;
      }
    }
    const base = initialStage ?? createAdlcStage(selectedPackage);
    const previousRetry = base.policy_overrides.retry;
    const retainedRetry =
      unified &&
      previousRetry !== null &&
      typeof previousRetry === "object" &&
      "max_attempts" in previousRetry
        ? { retry: { max_attempts: previousRetry.max_attempts } }
        : {};
    // Preserve any other policy_overrides from the base stage (e.g. retry
    // budget when switching between non-unified agents), then layer the
    // current form's timeout_ms on top.
    const preservedPolicyOverrides = { ...base.policy_overrides };
    delete preservedPolicyOverrides.timeout_ms;
    onSave({
      ...base,
      document_type: "WORKFLOW_STAGE",
      schema_version: "0.1",
      stage_type: stageTypeForPackage(selectedPackage),
      name: name.trim(),
      objective: objective.trim(),
      inputs,
      expected_outputs: selectedPackage.interface.outputs.map(
        (slot) => slot.name,
      ),
      package_ref: {
        package_id: selectedPackage.package_id,
        version: selectedPackage.version,
      },
      configuration_overrides: configurationForSave,
      policy_overrides: {
        ...preservedPolicyOverrides,
        ...retainedRetry,
        ...(parsedTimeout === undefined ? {} : { timeout_ms: parsedTimeout }),
      },
      execution_profile_overrides: {
        ...base.execution_profile_overrides,
        ...(modelRef.trim() ? { model_ref: modelRef.trim() } : {}),
      },
    });
    onOpenChange(false);
  };

  const configurationProperties = Object.entries(
    selectedPackage?.configuration_schema.properties ?? {},
  );
  const canOverrideTimeout = selectedPackage?.override_allowlist.includes(
    "/policies/timeout_ms",
  );
  const canOverrideModel = selectedPackage?.override_allowlist.includes(
    "/execution_profile/model_ref",
  );

  const form = (
    <>
      {!embedded && (
        <DialogHeader className="border-b px-6 py-5">
          <DialogTitle>
            {initialStage
              ? translateUi("Configure stage")
              : translateUi("Add workflow stage")}
          </DialogTitle>
          <DialogDescription>
            {translateUi(
              "Pick a versioned package and configure only the safe overrides that package exposes.",
            )}
          </DialogDescription>
        </DialogHeader>
      )}
      <form className="flex min-h-0 flex-1 flex-col" onSubmit={submit}>
        <fieldset disabled={readOnly} className="min-w-0">
          <div className="space-y-6 overflow-y-auto px-6 py-5">
            <section className="space-y-3">
              <div className="space-y-2">
                <Label htmlFor="adlc-stage-package">
                  {translateUi("Node package")}
                </Label>
                <Select value={packageKey} onValueChange={selectPackage}>
                  <SelectTrigger id="adlc-stage-package" className="w-full">
                    <SelectValue placeholder={translateUi("Select package")} />
                  </SelectTrigger>
                  <SelectContent>
                    {cataloguePackages.map((nodePackage) => (
                      <SelectItem
                        key={adlcPackageKey(nodePackage)}
                        value={adlcPackageKey(nodePackage)}
                        disabled={nodePackage.lifecycle_status === "DEPRECATED"}
                      >
                        {translateUi(nodePackage.name)} · {nodePackage.version}
                        {nodePackage.lifecycle_status === "DEPRECATED"
                          ? translateUi(" · Deprecated")
                          : ""}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {selectedPackage && (
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Badge variant="secondaryStatic" size="tag">
                      {formatUiStatus(selectedPackage.kind)}
                    </Badge>
                    {selectedPackageIsDeprecated && (
                      <Badge variant="errorStatic" size="tag">
                        {translateUi("Deprecated")}
                      </Badge>
                    )}
                    <span>{translateUi(selectedPackage.description)}</span>
                  </div>
                )}
                {selectedPackageIsDeprecated && (
                  <p className="text-xs text-error-foreground">
                    {translateUi(
                      "Existing workflows remain readable, but this version cannot be selected for new planning work.",
                    )}
                  </p>
                )}
                {unifiedPackage &&
                  selectedPackage &&
                  (replacedPackages.has(selectedPackage.package_id) ||
                    (isUnifiedCodingAgent(selectedPackage) &&
                      selectedPackage.version !== unifiedPackage.version)) && (
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => {
                        const previous = {
                          name,
                          objective,
                          directInputs,
                          inputDrafts,
                          timeoutMs,
                        };
                        selectPackage(adlcPackageKey(unifiedPackage));
                        setName(previous.name);
                        setObjective(previous.objective);
                        setDirectInputs(previous.directInputs);
                        setInputDrafts(previous.inputDrafts);
                        setTimeoutMs(previous.timeoutMs);
                        setConfiguration({
                          approved_contract_ref:
                            configuration.approved_contract_ref ?? null,
                          task_loop_enabled:
                            configuration.task_loop_enabled ??
                            previous.directInputs.includes("task_loop_spec"),
                          submission_mode: "MANUAL",
                          ...(unifiedPackage.version === "0.3.0"
                            ? {
                                loop_runtime:
                                  configuration.loop_runtime ?? "OPENCODE",
                              }
                            : {}),
                        });
                        setApprovedReferenceDraft(approvedReferenceDraft);
                      }}
                    >
                      {translateUi("Use unified Coding Agent")}
                    </Button>
                  )}
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="adlc-stage-name">
                    {translateUi("Stage name")}
                  </Label>
                  <Input
                    id="adlc-stage-name"
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    placeholder={translateUi("Implement backend")}
                  />
                </div>
                <div className="space-y-2">
                  <Label>{translateUi("Expected outputs")}</Label>
                  <div className="flex min-h-8 flex-wrap items-center gap-1 rounded-md border px-2 py-1.5">
                    {(selectedPackage?.interface.outputs ?? []).map((slot) => (
                      <Badge key={slot.name} variant="outline" size="tag">
                        {slot.name}
                      </Badge>
                    ))}
                  </div>
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="adlc-stage-objective">
                  {translateUi("Objective")}
                </Label>
                <Textarea
                  id="adlc-stage-objective"
                  className="min-h-20"
                  value={objective}
                  onChange={(event) => setObjective(event.target.value)}
                  placeholder={translateUi(
                    "Describe the outcome this stage must produce.",
                  )}
                />
              </div>
            </section>

            {(selectedPackage?.interface.inputs.length ?? 0) > 0 && (
              <section className="space-y-3 border-t pt-5">
                <div>
                  <h3 className="text-sm font-semibold">
                    {translateUi("Logical inputs")}
                  </h3>
                  <p className="text-xs text-muted-foreground">
                    {translateUi(
                      "Supply a value here, or clear the checkbox and bind a compatible upstream output on the dependency edge.",
                    )}
                  </p>
                </div>
                {selectedPackage?.interface.inputs
                  .filter(
                    (slot) =>
                      !unified || slot.name !== "task_loop_spec" || loopEnabled,
                  )
                  .map((slot) => {
                    const suppliedDirectly = directInputs.includes(slot.name);
                    return (
                      <div
                        className="space-y-2 rounded-md border p-3"
                        key={slot.name}
                      >
                        <div className="flex items-start gap-2">
                          <Checkbox
                            id={`adlc-input-${slot.name}`}
                            checked={suppliedDirectly}
                            disabled={boundInputs.includes(slot.name)}
                            onCheckedChange={(checked) =>
                              setDirectInputs((current) =>
                                checked
                                  ? [...new Set([...current, slot.name])]
                                  : current.filter(
                                      (name) => name !== slot.name,
                                    ),
                              )
                            }
                          />
                          <div className="space-y-1">
                            <Label htmlFor={`adlc-input-${slot.name}`}>
                              {slot.name}{" "}
                              {(
                                unified
                                  ? slot.name === "task_loop_spec"
                                    ? loopEnabled
                                    : !loopEnabled
                                  : slot.required
                              )
                                ? "(required)"
                                : "(optional)"}
                            </Label>
                            <p className="text-xs text-muted-foreground">
                              {translateUi(slot.description ?? "")} ·{" "}
                              {slot.schema_ref}
                            </p>
                          </div>
                        </div>
                        {boundInputs.includes(slot.name) && (
                          <p className="text-xs text-primary">
                            {translateUi(
                              "Supplied by the connected Requirement block.",
                            )}
                          </p>
                        )}
                        {suppliedDirectly &&
                          !boundInputs.includes(slot.name) && (
                            <Textarea
                              aria-label={translateUi("{{value0}} value", {
                                value0: slot.name,
                              })}
                              className="min-h-16 font-mono text-xs"
                              value={inputDrafts[slot.name] ?? ""}
                              onChange={(event) =>
                                setInputDrafts((current) => ({
                                  ...current,
                                  [slot.name]: event.target.value,
                                }))
                              }
                              placeholder={translateUi("Text or JSON value")}
                            />
                          )}
                      </div>
                    );
                  })}
              </section>
            )}

            {configurationProperties.length > 0 && (
              <section className="space-y-3 border-t pt-5">
                <div>
                  <h3 className="text-sm font-semibold">
                    {translateUi("Package configuration")}
                  </h3>
                  <p className="text-xs text-muted-foreground">
                    {translateUi(
                      "Defaults are inherited. A field is stored as an override only after you change it.",
                    )}
                  </p>
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  {configurationProperties.map(([key, schema]) => {
                    const effectiveValue =
                      configuration[key] ?? selectedPackage?.defaults[key];
                    if (
                      (selectedPackage?.package_id ===
                        "coding-agent-contract-harness" ||
                        unified) &&
                      key === "approved_contract_ref"
                    ) {
                      return (
                        <div className="space-y-2 sm:col-span-2" key={key}>
                          <Label htmlFor="adlc-config-approved_contract_ref">
                            {unified
                              ? translateUi("Approved contract (optional JSON)")
                              : translateUi("approved_contract_ref (JSON)")}
                          </Label>
                          <Textarea
                            id="adlc-config-approved_contract_ref"
                            rows={6}
                            value={approvedReferenceDraft}
                            onChange={(event) => {
                              setApprovedReferenceDraft(event.target.value);
                              setFormError(null);
                            }}
                            placeholder={translateUi(
                              "Paste the four-field reference from a human-approved contract.",
                            )}
                          />
                          <p className="text-xs text-muted-foreground">
                            {unified
                              ? translateUi(
                                  "Leave empty for a simple job. Add an approved reference to enforce its restrictions, including during repeated verification.",
                                )
                              : translateUi(
                                  "Select the exact human-approved revision and digest. No latest/default fallback; this field cannot approve a document.",
                                )}
                          </p>
                        </div>
                      );
                    }
                    if (schema.type === "boolean") {
                      return (
                        <div
                          className="flex flex-wrap items-center gap-2 rounded-md border px-3 py-2"
                          key={key}
                        >
                          <Checkbox
                            id={`adlc-config-${key}`}
                            checked={Boolean(effectiveValue)}
                            onCheckedChange={(checked) => {
                              setConfiguration((current) => ({
                                ...current,
                                [key]: Boolean(checked),
                              }));
                              if (unified && key === "task_loop_enabled")
                                setDirectInputs((current) =>
                                  checked
                                    ? [
                                        ...new Set([
                                          ...current,
                                          "task_loop_spec",
                                        ]),
                                      ]
                                    : current.filter(
                                        (name) => name !== "task_loop_spec",
                                      ),
                                );
                            }}
                          />
                          <Label htmlFor={`adlc-config-${key}`}>
                            {unified && key === "task_loop_enabled"
                              ? translateUi("Repeat until checks pass")
                              : key}
                          </Label>
                          {unified && key === "task_loop_enabled" && (
                            <p className="w-full text-xs text-muted-foreground">
                              {selectedPackage?.version === "0.3.0"
                                ? translateUi(
                                    "Choose the iteration runtime below. ADLC owns candidate capture, protected checks and human review for either runtime.",
                                  )
                                : translateUi(
                                    "Loops currently use the OpenCode adapter through a runtime-neutral iteration protocol. Requirement and contract-only work uses Harness; execution is not yet one unified Harness runtime.",
                                  )}
                            </p>
                          )}
                        </div>
                      );
                    }
                    if (unified && key === "loop_runtime") {
                      if (!loopEnabled) return null;
                      return (
                        <div className="space-y-2" key={key}>
                          <Label htmlFor="adlc-config-loop_runtime">
                            {translateUi("Loop runtime")}
                          </Label>
                          <Select
                            value={String(effectiveValue ?? "HARNESS")}
                            onValueChange={(value) =>
                              setConfiguration((current) => ({
                                ...current,
                                loop_runtime: value,
                              }))
                            }
                          >
                            <SelectTrigger id="adlc-config-loop_runtime">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="HARNESS">
                                {translateUi("Harness · file proposals")}
                              </SelectItem>
                              <SelectItem value="OPENCODE">
                                {translateUi("OpenCode · existing loop")}
                              </SelectItem>
                            </SelectContent>
                          </Select>
                          <p className="text-xs text-muted-foreground">
                            {translateUi(
                              "Changing runtime requires a newly compiled and accepted plan. Harness proposes file replacements only; no deletions or monetary budget. Each runtime must be explicitly enabled.",
                            )}
                          </p>
                        </div>
                      );
                    }
                    if (unified && key === "submission_mode") {
                      return (
                        <div className="space-y-2" key={key}>
                          <Label htmlFor="adlc-config-submission_mode">
                            {translateUi("Submission")}
                          </Label>
                          <Select
                            value={String(effectiveValue ?? "MANUAL")}
                            onValueChange={(value) =>
                              setConfiguration((current) => ({
                                ...current,
                                submission_mode: value,
                              }))
                            }
                          >
                            <SelectTrigger id="adlc-config-submission_mode">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="MANUAL">
                                {translateUi("Human review")}
                              </SelectItem>
                              <SelectItem value="AUTO">
                                {translateUi("Automatic (simple jobs)")}
                              </SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                      );
                    }
                    return (
                      <div className="space-y-2" key={key}>
                        <Label htmlFor={`adlc-config-${key}`}>{key}</Label>
                        <Input
                          id={`adlc-config-${key}`}
                          type={
                            schema.type === "integer" ||
                            schema.type === "number"
                              ? "number"
                              : "text"
                          }
                          min={schema.minimum}
                          max={schema.maximum}
                          value={String(effectiveValue ?? "")}
                          onChange={(event) =>
                            setConfiguration((current) => ({
                              ...current,
                              [key]:
                                schema.type === "integer" ||
                                schema.type === "number"
                                  ? Number(event.target.value)
                                  : event.target.value,
                            }))
                          }
                        />
                      </div>
                    );
                  })}
                </div>
              </section>
            )}

            {(canOverrideTimeout || canOverrideModel) && (
              <section className="space-y-3 border-t pt-5">
                <h3 className="text-sm font-semibold">
                  {translateUi("Execution policy")}
                </h3>
                <div className="grid gap-3 sm:grid-cols-2">
                  {canOverrideTimeout && (
                    <div className="space-y-2">
                      <Label htmlFor="adlc-timeout">
                        {translateUi("Timeout (ms)")}
                      </Label>
                      <Input
                        id="adlc-timeout"
                        type="number"
                        min={1}
                        value={timeoutMs}
                        onChange={(event) => setTimeoutMs(event.target.value)}
                        placeholder={String(
                          selectedPackage?.default_policies.timeout_ms ?? "",
                        )}
                      />
                    </div>
                  )}
                  {canOverrideModel && (
                    <div className="space-y-2">
                      <Label htmlFor="adlc-model-ref">
                        {translateUi("Model reference")}
                      </Label>
                      <Input
                        id="adlc-model-ref"
                        value={modelRef}
                        onChange={(event) => setModelRef(event.target.value)}
                        placeholder={
                          selectedPackage?.execution_profile?.model_ref ?? ""
                        }
                      />
                    </div>
                  )}
                </div>
              </section>
            )}

            {formError && (
              <p className="rounded-md bg-error-background px-3 py-2 text-sm text-error-foreground">
                {formError}
              </p>
            )}
          </div>
          <DialogFooter className="border-t px-6 py-4">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              {translateUi("Cancel")}
            </Button>
            <Button
              type="submit"
              disabled={!selectedPackage || selectedPackageIsDeprecated}
            >
              {initialStage
                ? translateUi("Save stage")
                : translateUi("Add stage")}
            </Button>
          </DialogFooter>
        </fieldset>
      </form>
    </>
  );
  return embedded ? (
    <div className="adlc-stage-form [&_.grid]:grid-cols-1 [&_.sm\\:col-span-2]:col-span-1 [&_.px-6]:px-4">
      {form}
    </div>
  ) : (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[88vh] max-w-2xl gap-0 overflow-hidden p-0">
        {form}
      </DialogContent>
    </Dialog>
  );
}
