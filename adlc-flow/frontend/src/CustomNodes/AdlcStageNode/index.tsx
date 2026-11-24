import { translateUi, useUiLocale } from "@/i18n/ui";
import { Handle, Position } from "@xyflow/react";
import { memo, useState } from "react";
import { useTranslation } from "react-i18next";
import "@/i18n";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useIsFlowReadOnly } from "@/contexts/permissionsContext";
import StageEditorDialog from "@/features/adlc-blueprint/stage-editor-dialog";
import { useAdlcNodePackages } from "@/hooks/adlc/use-adlc-node-packages";
import useAdlcBlueprintStore from "@/stores/adlcBlueprintStore";
import useFlowStore from "@/stores/flowStore";
import useFlowsManagerStore from "@/stores/flowsManagerStore";
import type { NodeDataType } from "@/types/flow";
import {
  ADLC_STAGE_SOURCE_HANDLE,
  ADLC_STAGE_TARGET_HANDLE,
  adlcPackageKey,
  createAdlcCompatibilityNode,
} from "@/utils/adlc-blueprint";
import { cn } from "@/utils/utils";

function AdlcStageNode({
  data,
  selected,
}: {
  data: NodeDataType;
  selected?: boolean;
}) {
  const { t } = useTranslation();
  useUiLocale();
  const stage = data.adlc!;
  const [editorOpen, setEditorOpen] = useState(false);
  const currentFlowId = useFlowStore((state) => state.currentFlow?.id);
  const flowLocked = useFlowStore(
    (state) => state.currentFlow?.locked === true,
  );
  const setNode = useFlowStore((state) => state.setNode);
  const deleteNode = useFlowStore((state) => state.deleteNode);
  const takeSnapshot = useFlowsManagerStore((state) => state.takeSnapshot);
  const issues = useAdlcBlueprintStore(
    (state) => state.nodeIssues[data.id] ?? [],
  );
  const clearValidation = useAdlcBlueprintStore(
    (state) => state.clearValidation,
  );
  const isReadOnly = useIsFlowReadOnly(currentFlowId);
  const canEdit = !isReadOnly && !flowLocked;
  const { data: packages = [], isLoading } = useAdlcNodePackages();
  const nodePackage = packages.find(
    (item) => adlcPackageKey(item) === adlcPackageKey(stage.package_ref),
  );

  const removeNode = () => {
    takeSnapshot();
    clearValidation();
    deleteNode(data.id);
  };

  return (
    <>
      <Handle
        type="target"
        position={Position.Left}
        id={ADLC_STAGE_TARGET_HANDLE}
        isConnectable={canEdit}
        className="!h-3 !w-3 !border-2 !border-background !bg-primary"
      />
      <article
        className={cn(
          "w-72 rounded-xl border-2 bg-background shadow-sm transition-shadow",
          selected && "border-primary shadow-md",
          !selected && !issues.length && "border-border",
          issues.length && "border-destructive shadow-destructive/10",
        )}
        data-testid={`adlc-stage-node-${data.id}`}
      >
        <header className="flex items-start justify-between gap-3 border-b px-4 py-3">
          <div className="min-w-0 space-y-1">
            <div className="flex items-center gap-2">
              <ForwardedIconComponent
                name={stage.stage_type === "APPROVAL" ? "ShieldCheck" : "Box"}
                className="h-4 w-4 shrink-0 text-primary"
              />
              <h3 className="truncate text-sm font-semibold">{stage.name}</h3>
            </div>
            <div className="flex flex-wrap items-center gap-1">
              <Badge variant="secondaryStatic" size="tag">
                {nodePackage?.kind ?? stage.stage_type}
              </Badge>
              {nodePackage?.lifecycle_status === "DEPRECATED" && (
                <Badge variant="errorStatic" size="tag">
                  {translateUi("Deprecated")}
                </Badge>
              )}
              <span className="text-[11px] text-muted-foreground">
                {stage.package_ref.package_id}@{stage.package_ref.version}
              </span>
            </div>
          </div>
          {canEdit && (
            <div className="nodrag nopan flex shrink-0 items-center gap-0.5">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                aria-label={translateUi("Configure {{value0}}", {
                  value0: stage.name,
                })}
                disabled={isLoading}
                onClick={() => setEditorOpen(true)}
              >
                <ForwardedIconComponent
                  name="Settings2"
                  className="h-3.5 w-3.5"
                />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-7 w-7 text-destructive"
                aria-label={translateUi("Delete {{value0}}", {
                  value0: stage.name,
                })}
                onClick={removeNode}
              >
                <ForwardedIconComponent name="Trash2" className="h-3.5 w-3.5" />
              </Button>
            </div>
          )}
        </header>
        <div className="space-y-3 px-4 py-3">
          <p className="line-clamp-3 text-xs leading-5 text-muted-foreground">
            {stage.objective}
          </p>
          <div className="flex items-center justify-between text-[11px] text-muted-foreground">
            <span>
              {Object.keys(stage.inputs).length}{" "}
              {translateUi("direct input(s)")}
            </span>
            <span>{stage.expected_outputs.length} output(s)</span>
          </div>
          {nodePackage && (
            <div className="border-t pt-2 text-[11px] text-muted-foreground">
              <p className="truncate">
                {nodePackage.execution_profile?.provider_ref ??
                  translateUi("control plane")}
              </p>
              <p>
                {String(
                  stage.policy_overrides.timeout_ms ??
                    nodePackage.default_policies.timeout_ms,
                )}{" "}
                {translateUi("ms · max")}{" "}
                {nodePackage.default_policies.retry.max_attempts} attempt(s)
              </p>
            </div>
          )}
          {issues.length > 0 && (
            <div className="flex items-start gap-2 rounded-md bg-error-background px-2.5 py-2 text-xs text-error-foreground">
              <ForwardedIconComponent
                name="AlertTriangle"
                className="mt-0.5 h-3.5 w-3.5 shrink-0"
              />
              <span className="line-clamp-2">
                {issues[0].message}
                {issues.length > 1
                  ? t("adlc.node.moreIssues", { count: issues.length - 1 })
                  : ""}
              </span>
            </div>
          )}
        </div>
      </article>
      <Handle
        type="source"
        position={Position.Right}
        id={ADLC_STAGE_SOURCE_HANDLE}
        isConnectable={canEdit}
        className="!h-3 !w-3 !border-2 !border-background !bg-primary"
      />
      <StageEditorDialog
        open={editorOpen}
        onOpenChange={setEditorOpen}
        packages={packages}
        initialStage={stage}
        onSave={(stage) => {
          takeSnapshot();
          clearValidation();
          setNode(data.id, (node) =>
            node.type === "adlcStageNode"
              ? {
                  ...node,
                  data: {
                    ...node.data,
                    adlc: stage,
                    node: createAdlcCompatibilityNode(stage),
                  },
                }
              : node,
          );
        }}
      />
    </>
  );
}

export default memo(AdlcStageNode);
