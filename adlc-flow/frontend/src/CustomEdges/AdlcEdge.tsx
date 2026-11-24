import { translateUi, useUiLocale } from "@/i18n/ui";
import {
  BaseEdge,
  EdgeLabelRenderer,
  type EdgeProps,
  getBezierPath,
} from "@xyflow/react";
import { memo, useMemo, useState } from "react";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
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
import { Label } from "@/components/ui/label";
import { useIsFlowReadOnly } from "@/contexts/permissionsContext";
import { useAdlcNodePackages } from "@/hooks/adlc/use-adlc-node-packages";
import useAdlcBlueprintStore from "@/stores/adlcBlueprintStore";
import useFlowStore from "@/stores/flowStore";
import useFlowsManagerStore from "@/stores/flowsManagerStore";
import type { AdlcEdgeCondition, AdlcSlotBinding } from "@/types/adlc";
import type { EdgeType } from "@/types/flow";
import {
  adlcPackageKey,
  createAdlcEdgeData,
  createAdlcWorkflowEdge,
  isAdlcStageNode,
} from "@/utils/adlc-blueprint";
import { useTranslation } from "react-i18next";
import i18n from "@/i18n";

const EDGE_CONDITIONS: {
  value: AdlcEdgeCondition;
  label: string;
  hint: string;
}[] = [
  {
    value: "ON_SUCCESS",
    get label() {
      return translateUi("On success");
    },
    get hint() {
      return translateUi("Runs after the source stage succeeds.");
    },
  },
  {
    value: "ON_FAILURE",
    get label() {
      return translateUi("On failure");
    },
    get hint() {
      return translateUi(
        "Runs only when the source stage fails (fallback branch).",
      );
    },
  },
  {
    value: "ALWAYS",
    get label() {
      return translateUi("Always");
    },
    get hint() {
      return translateUi(
        "Runs when the source stage finishes, success or failure.",
      );
    },
  },
];

function AdlcEdge({
  id,
  source,
  target,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerEnd,
  data,
}: EdgeProps<EdgeType>) {
  useUiLocale();
  const [editorOpen, setEditorOpen] = useState(false);
  const currentFlowId = useFlowStore((state) => state.currentFlow?.id);
  const flowLocked = useFlowStore(
    (state) => state.currentFlow?.locked === true,
  );
  const sourceNode = useFlowStore((state) =>
    state.nodes.find((node) => node.id === source),
  );
  const targetNode = useFlowStore((state) =>
    state.nodes.find((node) => node.id === target),
  );
  const setEdges = useFlowStore((state) => state.setEdges);
  const takeSnapshot = useFlowsManagerStore((state) => state.takeSnapshot);
  const issues = useAdlcBlueprintStore((state) => state.edgeIssues[id] ?? []);
  const clearValidation = useAdlcBlueprintStore(
    (state) => state.clearValidation,
  );
  const isReadOnly = useIsFlowReadOnly(currentFlowId);
  const canEdit = !isReadOnly && !flowLocked;
  const { data: packages = [] } = useAdlcNodePackages();
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  const compatibleBindings = useMemo(() => {
    if (!isAdlcStageNode(sourceNode) || !isAdlcStageNode(targetNode)) return [];
    const sourcePackage = packages.find(
      (item) =>
        adlcPackageKey(item) ===
        adlcPackageKey(sourceNode.data.adlc.package_ref),
    );
    const targetPackage = packages.find(
      (item) =>
        adlcPackageKey(item) ===
        adlcPackageKey(targetNode.data.adlc.package_ref),
    );
    if (!sourcePackage || !targetPackage) return [];
    return sourcePackage.interface.outputs.flatMap((output) =>
      targetPackage.interface.inputs
        .filter((input) => input.schema_ref === output.schema_ref)
        .map((input) => ({
          source_output: output.name,
          target_input: input.name,
          schema_ref: output.schema_ref,
        })),
    );
  }, [packages, sourceNode, targetNode]);

  const bindings = data?.adlc?.bindings ?? [];
  const bindingSelected = (candidate: AdlcSlotBinding) =>
    bindings.some(
      (binding) =>
        binding.source_output === candidate.source_output &&
        binding.target_input === candidate.target_input,
    );

  const toggleBinding = (candidate: AdlcSlotBinding, checked: boolean) => {
    takeSnapshot();
    clearValidation();
    setEdges((edges) =>
      edges.map((edge) => {
        if (edge.id !== id) return edge;
        const metadata = edge.data?.adlc ?? createAdlcWorkflowEdge();
        const edgeData =
          edge.data ?? createAdlcEdgeData(metadata, edge.source, edge.target);
        const nextBindings = checked
          ? [...metadata.bindings, candidate]
          : metadata.bindings.filter(
              (binding) =>
                binding.source_output !== candidate.source_output ||
                binding.target_input !== candidate.target_input,
            );
        return {
          ...edge,
          data: {
            ...edgeData,
            adlc: { ...metadata, bindings: nextBindings },
          },
        };
      }),
    );
  };

  const removeEdge = () => {
    takeSnapshot();
    clearValidation();
    setEdges((edges) => edges.filter((edge) => edge.id !== id));
    setEditorOpen(false);
  };

  const condition: AdlcEdgeCondition = data?.adlc?.condition ?? "ON_SUCCESS";

  const setCondition = (next: AdlcEdgeCondition) => {
    takeSnapshot();
    clearValidation();
    setEdges((edges) =>
      edges.map((edge) => {
        if (edge.id !== id) return edge;
        const metadata = edge.data?.adlc ?? createAdlcWorkflowEdge();
        const edgeData =
          edge.data ?? createAdlcEdgeData(metadata, edge.source, edge.target);
        return {
          ...edge,
          data: {
            ...edgeData,
            adlc: { ...metadata, condition: next },
          },
        };
      }),
    );
  };

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        style={{
          stroke: issues.length ? "hsl(var(--destructive))" : undefined,
          strokeWidth: issues.length ? 2.5 : 2,
        }}
      />
      <EdgeLabelRenderer>
        <Button
          type="button"
          variant={issues.length ? "destructive" : "secondary"}
          size="icon"
          aria-label={translateUi("Configure dependency binding ({{value0}})", {
            value0: condition,
          })}
          className="nodrag nopan h-7 w-7 rounded-full shadow-sm"
          style={{
            position: "absolute",
            transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
            pointerEvents: "all",
          }}
          onClick={() => setEditorOpen(true)}
        >
          <ForwardedIconComponent
            name={issues.length ? "AlertTriangle" : "Link2"}
            className="h-3.5 w-3.5"
          />
        </Button>
        {condition !== "ON_SUCCESS" && (
          <span
            className="nodrag nopan rounded-full border bg-background px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground shadow-sm"
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY + 18}px)`,
              pointerEvents: "none",
            }}
          >
            {condition}
          </span>
        )}
      </EdgeLabelRenderer>
      <Dialog open={editorOpen} onOpenChange={setEditorOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{translateUi("Configure dependency")}</DialogTitle>
            <DialogDescription>
              {translateUi(
                "The edge always enforces ordering. Add a logical binding only when the output and input schemas match.",
              )}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="rounded-md border bg-muted/30 px-3 py-2 text-sm">
              <span className="font-medium">
                {isAdlcStageNode(sourceNode)
                  ? sourceNode.data.adlc.name
                  : source}
              </span>
              <span className="mx-2 text-muted-foreground">→</span>
              <span className="font-medium">
                {isAdlcStageNode(targetNode)
                  ? targetNode.data.adlc.name
                  : target}
              </span>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor={`${id}-condition`}>
                {translateUi("Run condition")}
              </Label>
              <div className="grid grid-cols-3 gap-2">
                {EDGE_CONDITIONS.map((option) => (
                  <button
                    type="button"
                    id={`${id}-condition-${option.value}`}
                    key={option.value}
                    disabled={!canEdit}
                    title={option.hint}
                    onClick={() => setCondition(option.value)}
                    className={`rounded-md border px-2 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
                      condition === option.value
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border bg-background text-muted-foreground hover:bg-muted"
                    }`}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                {
                  EDGE_CONDITIONS.find((option) => option.value === condition)
                    ?.hint
                }
              </p>
            </div>
            {compatibleBindings.length === 0 ? (
              <p className="rounded-md border border-dashed px-3 py-4 text-sm text-muted-foreground">
                {translateUi(
                  "These packages have no schema-compatible slots. This remains a dependency-only edge; configure the target input directly.",
                )}
              </p>
            ) : (
              compatibleBindings.map((binding) => {
                const inputId = `${id}-${binding.source_output}-${binding.target_input}`;
                return (
                  <div
                    className="flex items-start gap-3 rounded-md border p-3"
                    key={inputId}
                  >
                    <Checkbox
                      id={inputId}
                      checked={bindingSelected(binding)}
                      disabled={!canEdit}
                      onCheckedChange={(checked) =>
                        toggleBinding(binding, Boolean(checked))
                      }
                    />
                    <div className="space-y-1">
                      <Label htmlFor={inputId}>
                        {binding.source_output} → {binding.target_input}
                      </Label>
                      <p className="text-xs text-muted-foreground">
                        {binding.schema_ref}
                      </p>
                    </div>
                  </div>
                );
              })
            )}
            {issues.map((issue) => (
              <p
                className="rounded-md bg-error-background px-3 py-2 text-xs text-error-foreground"
                key={`${issue.code}-${issue.path}`}
              >
                {issue.code}: {issue.message}
              </p>
            ))}
          </div>
          <DialogFooter>
            {canEdit && (
              <Button type="button" variant="destructive" onClick={removeEdge}>
                {translateUi("Delete dependency")}
              </Button>
            )}
            <Button
              type="button"
              variant="outline"
              onClick={() => setEditorOpen(false)}
            >
              {translateUi("Done")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

export default memo(AdlcEdge);
