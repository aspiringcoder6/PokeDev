import { create } from "zustand";
import type {
  AdlcExecutionPlan,
  AdlcPlanProposal,
  AdlcPlanValidationIssue,
} from "@/types/adlc";
import type { AllNodeType, EdgeType } from "@/types/flow";
import {
  type AdlcCanvasIssueMap,
  mapAdlcIssuesToCanvas,
} from "@/utils/adlc-blueprint";

type AdlcBlueprintStore = AdlcCanvasIssueMap & {
  plan: AdlcExecutionPlan | null;
  proposal: AdlcPlanProposal | null;
  proposalOpen: boolean;
  issues: AdlcPlanValidationIssue[];
  previewOpen: boolean;
  previewMessage: string | null;
  /** Blueprint request (AI generation) dialog visibility. */
  requestDialogOpen: boolean;
  /** Flow ids whose auto-opened request dialog the user already dismissed. */
  dismissedRequestFlowIds: string[];
  setRequestDialogOpen: (open: boolean) => void;
  dismissRequestDialog: (flowId: string) => void;
  showPlan: (
    plan: AdlcExecutionPlan,
    nodes: AllNodeType[],
    edges: EdgeType[],
  ) => void;
  showProposal: (
    proposal: AdlcPlanProposal,
    nodes: AllNodeType[],
    edges: EdgeType[],
  ) => void;
  updateProposal: (
    proposal: AdlcPlanProposal,
    nodes: AllNodeType[],
    edges: EdgeType[],
  ) => void;
  showPlanningError: (
    message: string,
    issues: AdlcPlanValidationIssue[],
    nodes: AllNodeType[],
    edges: EdgeType[],
    retainedPlan?: AdlcExecutionPlan,
  ) => void;
  showSaveValidation: (
    issues: AdlcPlanValidationIssue[],
    nodes: AllNodeType[],
    edges: EdgeType[],
  ) => void;
  setPreviewOpen: (open: boolean) => void;
  setProposalOpen: (open: boolean) => void;
  clearValidation: () => void;
};

const emptyIssues: AdlcCanvasIssueMap = {
  nodeIssues: {},
  edgeIssues: {},
  globalIssues: [],
};

const useAdlcBlueprintStore = create<AdlcBlueprintStore>((set) => ({
  ...emptyIssues,
  plan: null,
  proposal: null,
  proposalOpen: false,
  issues: [],
  previewOpen: false,
  previewMessage: null,
  requestDialogOpen: false,
  dismissedRequestFlowIds: [],
  setRequestDialogOpen: (requestDialogOpen) => set({ requestDialogOpen }),
  dismissRequestDialog: (flowId) =>
    set((state) => ({
      requestDialogOpen: false,
      dismissedRequestFlowIds: state.dismissedRequestFlowIds.includes(flowId)
        ? state.dismissedRequestFlowIds
        : [...state.dismissedRequestFlowIds, flowId],
    })),
  showPlan: (plan, nodes, edges) => {
    const issues = [...plan.validation_errors, ...plan.warnings];
    set({
      plan,
      issues,
      previewOpen: true,
      proposalOpen: false,
      previewMessage: null,
      ...mapAdlcIssuesToCanvas(issues, nodes, edges),
    });
  },
  showProposal: (proposal, nodes, edges) => {
    const issues = [...proposal.validation_errors, ...proposal.warnings];
    set({
      proposal,
      proposalOpen: true,
      plan: null,
      previewOpen: false,
      previewMessage: null,
      issues,
      ...mapAdlcIssuesToCanvas(issues, nodes, edges),
    });
  },
  updateProposal: (proposal, nodes, edges) => {
    const issues = [...proposal.validation_errors, ...proposal.warnings];
    set({
      proposal,
      issues,
      ...mapAdlcIssuesToCanvas(issues, nodes, edges),
    });
  },
  showPlanningError: (message, issues, nodes, edges, retainedPlan) => {
    set({
      plan: retainedPlan ?? null,
      issues,
      previewOpen: true,
      proposalOpen: false,
      previewMessage: message,
      ...mapAdlcIssuesToCanvas(issues, nodes, edges),
    });
  },
  showSaveValidation: (issues, nodes, edges) => {
    set({
      issues,
      ...mapAdlcIssuesToCanvas(issues, nodes, edges),
    });
  },
  setPreviewOpen: (previewOpen) => set({ previewOpen }),
  setProposalOpen: (proposalOpen) => set({ proposalOpen }),
  clearValidation: () =>
    set({
      ...emptyIssues,
      plan: null,
      proposal: null,
      proposalOpen: false,
      issues: [],
      previewOpen: false,
      previewMessage: null,
    }),
}));

export default useAdlcBlueprintStore;
