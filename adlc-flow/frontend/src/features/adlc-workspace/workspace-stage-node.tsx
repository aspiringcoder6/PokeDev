import { translateUi, useUiLocale } from "@/i18n/ui";
import { Handle, type NodeProps, Position } from "@xyflow/react";
import { Box, CheckCircle2, FileText, ShieldCheck } from "lucide-react";
import { memo } from "react";
import useAdlcBlueprintStore from "@/stores/adlcBlueprintStore";
import type { AdlcStageNodeType } from "@/types/flow";
import { cn } from "@/utils/utils";
import { useTranslation } from "react-i18next";
import "@/i18n";

function WorkspaceStageNode({
  data,
  selected,
  isConnectable,
}: NodeProps<AdlcStageNodeType>) {
  useUiLocale();
  const draft = data.adlcDraft,
    stage = data.adlc;
  const name = draft?.name ?? stage?.name ?? translateUi("Stage");
  const wip = draft?.kind === "PLANNED_PACKAGE",
    requirement = draft?.kind === "REQUIREMENT";
  const issues = useAdlcBlueprintStore((s) => s.nodeIssues[data.id]);
  const configuration = stage?.configuration_overrides;
  const contract = Boolean(configuration?.approved_contract_ref),
    loop = Boolean(configuration?.task_loop_enabled);
  return (
    <>
      {!requirement && (
        <Handle
          id="adlc-stage-input"
          type="target"
          position={Position.Left}
          isConnectable={isConnectable}
          className="!h-3 !w-3 !border-2 !border-background !bg-primary"
          aria-label={translateUi("Before {{value0}}", { value0: name })}
        />
      )}
      <article
        className={cn(
          "w-[264px] rounded-xl border bg-card shadow-sm",
          selected ? "border-primary ring-2 ring-primary/15" : "border-border",
          wip && "border-dashed",
          issues?.length && "border-destructive",
        )}
        data-testid={`workspace-stage-${data.id}`}
      >
        <header className="flex items-center gap-2.5 border-b px-4 py-3">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border bg-background text-primary">
            {requirement ? (
              <FileText size={16} />
            ) : stage?.stage_type === "APPROVAL" ? (
              <ShieldCheck size={16} />
            ) : (
              <Box size={16} />
            )}
          </span>
          <div className="min-w-0">
            <h3 className="truncate text-xs font-semibold" title={name}>
              {name}
            </h3>
            <p className="mt-1 text-[10px] text-muted-foreground">
              {wip
                ? translateUi("WIP · Design only")
                : requirement
                  ? translateUi("Workflow input")
                  : `v${stage?.package_ref.version} · ${stage?.stage_type === "APPROVAL" ? translateUi("Human decision") : translateUi("Package stage")}`}
            </p>
          </div>
        </header>
        <div className="space-y-3 px-4 py-3">
          <p className="line-clamp-2 text-[11px] leading-5 text-muted-foreground">
            {requirement
              ? draft?.requirement ||
                translateUi("Add the requirement in the inspector.")
              : (draft?.objective ?? stage?.objective)}
          </p>
          {stage?.package_ref.package_id === "coding-agent" && (
            <div className="flex flex-wrap gap-1.5 text-[10px]">
              <span className="rounded border px-1.5 py-0.5">
                {contract
                  ? translateUi("Approved contract")
                  : translateUi("Direct requirement")}
              </span>
              {loop && (
                <span className="rounded border px-1.5 py-0.5">
                  {translateUi("Repeat checks")}
                </span>
              )}
            </div>
          )}
          {wip && (
            <p className="text-[10px] text-muted-foreground">
              {translateUi("Planning only · execution unavailable")}
            </p>
          )}
          {issues?.length ? (
            <p
              className="line-clamp-2 text-[11px] text-destructive"
              role="status"
            >
              {issues[0].message}
            </p>
          ) : (
            <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
              <CheckCircle2 size={11} />
              {requirement
                ? translateUi("Literal input")
                : translateUi("Select to configure")}
            </div>
          )}
        </div>
      </article>
      <Handle
        id="adlc-stage-output"
        type="source"
        position={Position.Right}
        isConnectable={isConnectable}
        className="!h-3 !w-3 !border-2 !border-background !bg-primary"
        aria-label={translateUi("Next after {{value0}}", { value0: name })}
      />
    </>
  );
}
export default memo(WorkspaceStageNode);
