import { translateUi, useUiLocale } from "@/i18n/ui";
import { useEffect, useRef, useState } from "react";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { usePermissions } from "@/contexts/permissionsContext";
import {
  type AdlcBlueprintGenerationResult,
  approveAdlcExecutionPlan,
  createAdlcExecutionPlan,
  createAdlcRunFromExecutionPlan,
  generateAdlcPlanProposal,
  regenerateAdlcExecutionPlan,
} from "@/controllers/API/adlc";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import BlueprintRequestDialog from "@/features/adlc-blueprint/blueprint-request-dialog";
import { heartAppExample } from "@/features/adlc-blueprint/demo-examples";
import PlanPreviewDialog from "@/features/adlc-blueprint/plan-preview-dialog";
import StageEditorDialog from "@/features/adlc-blueprint/stage-editor-dialog";
import PlanProposalDialog from "@/features/plan-proposal/plan-proposal-dialog";
import { useAdlcNodePackages } from "@/hooks/adlc/use-adlc-node-packages";
import useApplyFlowToCanvas from "@/hooks/flows/use-apply-flow-to-canvas";
import useSaveFlow from "@/hooks/flows/use-save-flow";
import useAdlcBlueprintStore from "@/stores/adlcBlueprintStore";
import useAlertStore from "@/stores/alertStore";
import useAssistantManagerStore from "@/stores/assistantManagerStore";
import useFlowBuilderWelcomeStore from "@/stores/flowBuilderWelcomeStore";
import useFlowStore from "@/stores/flowStore";
import useFlowsManagerStore from "@/stores/flowsManagerStore";
import type { AdlcWorkflowStage } from "@/types/adlc";
import type { AdlcStageNodeType } from "@/types/flow";
import {
  createAdlcCompatibilityNode,
  createAdlcWorkflowMarker,
  getAdlcPlanningError,
  isAdlcBlueprint,
  shouldAutoPromptBlueprintRequest,
} from "@/utils/adlc-blueprint";
import { useTranslation } from "react-i18next";
import "@/i18n";

export default function AdlcBlueprintControls({
  compact = false,
}: {
  compact?: boolean;
}) {
  useUiLocale();
  const [editorOpen, setEditorOpen] = useState(false);
  const [isInitializing, setIsInitializing] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isProposing, setIsProposing] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [isStarting, setIsStarting] = useState(false);
  const runRequest = useRef<{ planId: string; key: string } | undefined>(
    undefined,
  );
  const regenerationRequest = useRef<
    { planId: string; key: string } | undefined
  >(undefined);
  const autoPromptAttempted = useRef<string | null>(null);
  const currentFlow = useFlowStore((state) => state.currentFlow);
  const currentFlowId = useFlowsManagerStore((state) => state.currentFlowId);
  const nodes = useFlowStore((state) => state.nodes);
  const setCurrentFlow = useFlowStore((state) => state.setCurrentFlow);
  const setNodes = useFlowStore((state) => state.setNodes);
  const reactFlowInstance = useFlowStore((state) => state.reactFlowInstance);
  const takeSnapshot = useFlowsManagerStore((state) => state.takeSnapshot);
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const showPlan = useAdlcBlueprintStore((state) => state.showPlan);
  const showProposal = useAdlcBlueprintStore((state) => state.showProposal);
  const plan = useAdlcBlueprintStore((state) => state.plan);
  const showPlanningError = useAdlcBlueprintStore(
    (state) => state.showPlanningError,
  );
  const clearValidation = useAdlcBlueprintStore(
    (state) => state.clearValidation,
  );
  const requestDialogOpen = useAdlcBlueprintStore(
    (state) => state.requestDialogOpen,
  );
  const setRequestDialogOpen = useAdlcBlueprintStore(
    (state) => state.setRequestDialogOpen,
  );
  const dismissRequestDialog = useAdlcBlueprintStore(
    (state) => state.dismissRequestDialog,
  );
  const dismissedRequestFlowIds = useAdlcBlueprintStore(
    (state) => state.dismissedRequestFlowIds,
  );
  const applyFlowToCanvas = useApplyFlowToCanvas();
  const saveFlow = useSaveFlow();
  const navigate = useCustomNavigate();
  const { can, isLoading: permissionsLoading } = usePermissions();
  const canWrite = can(currentFlowId, "write");
  const canRead = can(currentFlowId, "read");
  const canExecute = can(currentFlowId, "execute");
  const canEdit =
    !permissionsLoading && canWrite && currentFlow?.locked !== true;
  const hasWip = nodes.some(
    (node) => node.data.adlcDraft?.kind === "PLANNED_PACKAGE",
  );
  const blueprint = isAdlcBlueprint(currentFlow);
  const welcomeOpen = useFlowBuilderWelcomeStore((state) => state.isOpen);
  const assistantOpen = useAssistantManagerStore(
    (state) => state.assistantSidebarOpen,
  );
  const { data: packages = [], isLoading: packagesLoading } =
    useAdlcNodePackages();

  const canvasNodes = nodes.filter((node) => node.type !== "noteNode");

  // Auto-open the blueprint request dialog the first time the user enters a
  // new, still-empty workflow. The welcome overlay and the assistant panel
  // take precedence; once they close, the dialog appears. Dismissed flows
  // (via the dialog's X) are never auto-prompted again this session — the
  // toolbar button reopens the request on demand.
  useEffect(() => {
    if (!currentFlowId || !currentFlow) return;
    if (autoPromptAttempted.current === currentFlowId) return;
    const shouldPrompt = shouldAutoPromptBlueprintRequest({
      flowId: currentFlowId,
      executableNodeCount: canvasNodes.length,
      isBlueprint: blueprint,
      dismissedFlowIds: dismissedRequestFlowIds,
      welcomeOpen,
      assistantOpen,
    });
    if (!shouldPrompt) {
      if (canvasNodes.length > 0 || blueprint) {
        autoPromptAttempted.current = currentFlowId;
      }
      return;
    }
    autoPromptAttempted.current = currentFlowId;
    setRequestDialogOpen(true);
  }, [
    currentFlowId,
    canvasNodes.length,
    blueprint,
    dismissedRequestFlowIds,
    welcomeOpen,
    assistantOpen,
    setRequestDialogOpen,
  ]);

  const handleRequestDialogChange = (open: boolean) => {
    if (!open && currentFlowId) {
      // Closing the request dialog (X / Escape) opts this flow out of the
      // auto-open for the rest of the session; the toolbar button still
      // reopens it on demand.
      dismissRequestDialog(currentFlowId);
      return;
    }
    setRequestDialogOpen(open);
  };

  const initializeBlueprint = async () => {
    if (!currentFlow || !currentFlowId || !canEdit || isInitializing) return;
    const executableNodes = useFlowStore
      .getState()
      .nodes.filter((node) => node.type !== "noteNode");
    if (executableNodes.length > 0) {
      setErrorData({
        title: translateUi("Start with an empty flow"),
        list: [
          translateUi(
            "Blueprint mode uses high-level ADLC stages. Remove existing Langflow component nodes or create a new empty flow first.",
          ),
        ],
      });
      return;
    }
    setIsInitializing(true);
    try {
      setCurrentFlow({
        ...currentFlow,
        data: {
          ...(currentFlow.data ?? {
            nodes: [],
            edges: [],
            viewport: { x: 0, y: 0, zoom: 1 },
          }),
          adlc: createAdlcWorkflowMarker(currentFlowId),
        },
      });
      await saveFlow();
      setSuccessData({ title: translateUi("ADLC Blueprint mode enabled") });
      setEditorOpen(true);
    } catch {
      // useSaveFlow already reports the persistence failure.
    } finally {
      setIsInitializing(false);
    }
  };

  const addStage = (stage: AdlcWorkflowStage) => {
    takeSnapshot();
    clearValidation();
    const existingNodes = useFlowStore.getState().nodes;
    const fallbackPosition = {
      x: 80 + existingNodes.length * 330,
      y: 140 + (existingNodes.length % 2) * 80,
    };
    const position =
      reactFlowInstance?.screenToFlowPosition({
        x: window.innerWidth / 2,
        y: window.innerHeight / 2,
      }) ?? fallbackPosition;
    const nodeId = `adlc-stage-${crypto.randomUUID()}`;
    const node: AdlcStageNodeType = {
      id: nodeId,
      type: "adlcStageNode",
      position: {
        x: position.x + existingNodes.length * 24,
        y: position.y + existingNodes.length * 24,
      },
      data: {
        id: nodeId,
        type: "adlcStage",
        adlc: stage,
        node: createAdlcCompatibilityNode(stage),
      },
    };
    setNodes([...existingNodes, node]);
  };

  const generatePlan = async () => {
    if (
      !currentFlowId ||
      !canRead ||
      permissionsLoading ||
      hasWip ||
      isGenerating ||
      isProposing
    )
      return;
    setIsGenerating(true);
    try {
      if (canEdit) {
        await saveFlow();
      }
      const plan = await createAdlcExecutionPlan(currentFlowId);
      runRequest.current = undefined;
      const { nodes, edges } = useFlowStore.getState();
      showPlan(plan, nodes, edges);
    } catch (error) {
      const { message, issues } = getAdlcPlanningError(error);
      const { nodes, edges } = useFlowStore.getState();
      showPlanningError(message, issues, nodes, edges, plan ?? undefined);
    } finally {
      setIsGenerating(false);
    }
  };

  const proposeTasks = async () => {
    if (
      !currentFlowId ||
      !canRead ||
      permissionsLoading ||
      hasWip ||
      isProposing ||
      isGenerating
    )
      return;
    setIsProposing(true);
    try {
      if (canEdit) {
        await saveFlow();
      }
      const proposal = await generateAdlcPlanProposal(currentFlowId);
      runRequest.current = undefined;
      const { nodes, edges } = useFlowStore.getState();
      showProposal(proposal, nodes, edges);
    } catch (error) {
      const { message } = getAdlcPlanningError(error);
      setErrorData({
        title: translateUi("Unable to propose tasks"),
        list: [message],
      });
    } finally {
      setIsProposing(false);
    }
  };

  const regeneratePlan = async () => {
    if (!plan) {
      await generatePlan();
      return;
    }
    if (!canRead || permissionsLoading || hasWip || isGenerating || isProposing)
      return;
    setIsGenerating(true);
    try {
      if (canEdit) {
        await saveFlow();
      }
      if (
        !regenerationRequest.current ||
        regenerationRequest.current.planId !== plan.execution_plan_id
      ) {
        regenerationRequest.current = {
          planId: plan.execution_plan_id,
          key: crypto.randomUUID(),
        };
      }
      const regenerated = await regenerateAdlcExecutionPlan(
        plan.execution_plan_id,
        regenerationRequest.current.key,
      );
      regenerationRequest.current = undefined;
      runRequest.current = undefined;
      const { nodes, edges } = useFlowStore.getState();
      showPlan(regenerated, nodes, edges);
      setSuccessData({
        title: translateUi("Execution plan v{{value0}} generated", {
          value0: regenerated.plan_version,
        }),
      });
    } catch (error) {
      const { message, issues } = getAdlcPlanningError(error);
      const { nodes, edges } = useFlowStore.getState();
      showPlanningError(message, issues, nodes, edges, plan);
    } finally {
      setIsGenerating(false);
    }
  };

  const approvePlan = async () => {
    if (!plan || !canExecute || permissionsLoading || hasWip || isApproving)
      return;
    setIsApproving(true);
    try {
      const approved = await approveAdlcExecutionPlan(plan.execution_plan_id);
      const { nodes, edges } = useFlowStore.getState();
      showPlan(approved, nodes, edges);
      setSuccessData({ title: translateUi("Execution plan accepted") });
    } catch (error) {
      const { message } = getAdlcPlanningError(error);
      setErrorData({
        title: translateUi("Unable to accept execution plan"),
        list: [message],
      });
    } finally {
      setIsApproving(false);
    }
  };

  const startPlanRun = async () => {
    if (!plan || !canExecute || permissionsLoading || hasWip || isStarting)
      return;
    setIsStarting(true);
    try {
      if (
        !runRequest.current ||
        runRequest.current.planId !== plan.execution_plan_id
      ) {
        runRequest.current = {
          planId: plan.execution_plan_id,
          key: crypto.randomUUID(),
        };
      }
      const run = await createAdlcRunFromExecutionPlan(
        plan.execution_plan_id,
        runRequest.current.key,
      );
      navigate(`/runs/${run.id}`);
    } catch (error) {
      const { message } = getAdlcPlanningError(error);
      setErrorData({
        title: translateUi("Unable to start plan run"),
        list: [message],
      });
    } finally {
      setIsStarting(false);
    }
  };

  const applyGeneratedBlueprint = (result: AdlcBlueprintGenerationResult) => {
    takeSnapshot();
    clearValidation();
    if (currentFlow) {
      applyFlowToCanvas({
        ...currentFlow,
        data: result.data,
      });
    }
    setSuccessData({
      title: translateUi(
        "Blueprint ready — {{value0}} stage{{value1}} applied",
        {
          value0: result.stages.length,
          value1: result.stages.length === 1 ? "" : "s",
        },
      ),
      ...(result.warnings.length > 0 ? { list: result.warnings } : {}),
    });
  };

  if (!blueprint) {
    return (
      <>
        <Button
          type="button"
          variant="ghost"
          size="md"
          className="h-8 gap-1.5 px-2 font-normal"
          disabled={!currentFlowId || !canEdit}
          loading={isInitializing}
          onClick={initializeBlueprint}
          ignoreTitleCase
          data-testid="create-adlc-blueprint-button"
        >
          <ForwardedIconComponent name="Workflow" className="h-4 w-4" />
          {translateUi("Create Blueprint")}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="md"
          className="h-8 gap-1.5 px-2 font-normal"
          disabled={!currentFlowId || !canEdit}
          onClick={() => setRequestDialogOpen(true)}
          ignoreTitleCase
          data-testid="adlc-blueprint-request-button"
        >
          <ForwardedIconComponent name="Sparkles" className="h-4 w-4" />
          {translateUi("AI Blueprint")}
        </Button>
        {currentFlowId && (
          <BlueprintRequestDialog
            open={requestDialogOpen}
            onOpenChange={handleRequestDialogChange}
            flowId={currentFlowId}
            hasStages={canvasNodes.length > 0}
            onGenerated={applyGeneratedBlueprint}
            defaultRequirement={heartAppExample().requirement}
            defaultInstructions={heartAppExample().instructions}
          />
        )}
      </>
    );
  }

  return (
    <>
      {!compact && (
        <Badge
          variant="purpleStatic"
          size="sq"
          className="ml-1"
          title={translateUi(
            "Runs only from an accepted, immutable execution plan.",
          )}
          data-testid="adlc-execution-mode-badge"
        >
          {translateUi("Blueprint plan")}
        </Badge>
      )}
      {!compact && (
        <Button
          type="button"
          variant="ghost"
          size="md"
          className="h-8 gap-1.5 px-2 font-normal"
          disabled={!canEdit || packagesLoading || packages.length === 0}
          onClick={() => setEditorOpen(true)}
          ignoreTitleCase
          data-testid="add-adlc-stage-button"
        >
          <ForwardedIconComponent name="Plus" className="h-4 w-4" />
          {translateUi("Add Stage")}
        </Button>
      )}
      <Button
        type="button"
        variant="ghost"
        size="md"
        className="h-8 gap-1.5 px-2 font-normal"
        disabled={!canEdit}
        onClick={() => setRequestDialogOpen(true)}
        ignoreTitleCase
        data-testid="adlc-blueprint-request-button"
      >
        <ForwardedIconComponent name="Sparkles" className="h-4 w-4" />
        {translateUi("AI Blueprint")}
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="md"
        className="h-8 gap-1.5 px-2 font-normal"
        loading={isGenerating}
        onClick={generatePlan}
        ignoreTitleCase
        data-testid="preview-adlc-plan-button"
        disabled={
          !currentFlowId ||
          permissionsLoading ||
          !canRead ||
          hasWip ||
          isProposing
        }
        title={
          hasWip
            ? translateUi(
                "Replace WIP stages before reviewing an execution plan.",
              )
            : undefined
        }
      >
        <ForwardedIconComponent name="ListChecks" className="h-4 w-4" />
        {compact
          ? translateUi("Review plan")
          : translateUi("Validate & Preview")}
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="md"
        className="h-8 gap-1.5 px-2 font-normal"
        loading={isProposing}
        onClick={proposeTasks}
        ignoreTitleCase
        data-testid="propose-adlc-tasks-button"
        disabled={
          !currentFlowId ||
          permissionsLoading ||
          !canRead ||
          hasWip ||
          isGenerating
        }
      >
        <ForwardedIconComponent name="Sparkles" className="h-4 w-4" />
        {compact ? translateUi("Propose tasks") : translateUi("Propose Tasks")}
      </Button>
      {!compact && (
        <Button
          type="button"
          variant="ghost"
          size="md"
          className="h-8 gap-1.5 px-2 font-normal"
          disabled={!currentFlowId}
          onClick={() => navigate(`/runs/?flowId=${currentFlowId}`)}
          ignoreTitleCase
          data-testid="adlc-run-history-button"
        >
          <ForwardedIconComponent name="History" className="h-4 w-4" />
          {translateUi("Run History")}
        </Button>
      )}
      <StageEditorDialog
        open={editorOpen}
        onOpenChange={setEditorOpen}
        packages={packages}
        onSave={addStage}
      />
      {currentFlowId && (
        <BlueprintRequestDialog
          open={requestDialogOpen}
          onOpenChange={handleRequestDialogChange}
          flowId={currentFlowId}
          hasStages={canvasNodes.length > 0}
          onGenerated={applyGeneratedBlueprint}
          defaultRequirement={heartAppExample().requirement}
          defaultInstructions={heartAppExample().instructions}
        />
      )}
      <PlanPreviewDialog
        onGenerateAgain={regeneratePlan}
        onApprovePlan={approvePlan}
        onStartRun={startPlanRun}
        isGenerating={isGenerating}
        isApproving={isApproving}
        isStarting={isStarting}
        canExecute={canExecute && !permissionsLoading && !hasWip}
      />
      <PlanProposalDialog
        canExecute={canExecute && !permissionsLoading && !hasWip}
      />
    </>
  );
}
