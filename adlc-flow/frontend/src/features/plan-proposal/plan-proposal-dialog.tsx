import { translateUi, useUiLocale, formatUiStatus } from "@/i18n/ui";
import { useState } from "react";

import ForwardedIconComponent from "@/components/common/genericIconComponent";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  approveAdlcPlanProposal,
  regenerateAdlcPlanProposal,
  rejectAdlcPlanProposal,
  validateAdlcPlanProposal,
} from "@/controllers/API/adlc";
import { getAdlcPlanningError } from "@/utils/adlc-blueprint";
import useAlertStore from "@/stores/alertStore";
import useAdlcBlueprintStore from "@/stores/adlcBlueprintStore";
import useFlowStore from "@/stores/flowStore";

import { ProposalIssueList, ProposalTree } from "./ProposalTree";
import { useTranslation } from "react-i18next";
import "@/i18n";

function proposalStatusVariant(status: string): BadgeProps["variant"] {
  if (status === "VALIDATED") return "emerald";
  if (status === "APPROVED") return "successStatic";
  if (status === "REVISION_REQUIRED") return "errorStatic";
  if (status === "REJECTED") return "errorStatic";
  return "secondaryStatic";
}

function ProposalStatusBadge({ status }: { status: string }) {
  return (
    <Badge variant={proposalStatusVariant(status)} size="tag">
      {formatUiStatus(status, true)}
    </Badge>
  );
}

export default function PlanProposalDialog({
  canExecute,
}: {
  canExecute: boolean;
}) {
  useUiLocale();
  const open = useAdlcBlueprintStore((state) => state.proposalOpen);
  const setOpen = useAdlcBlueprintStore((state) => state.setProposalOpen);
  const proposal = useAdlcBlueprintStore((state) => state.proposal);
  const updateProposal = useAdlcBlueprintStore((state) => state.updateProposal);
  const showPlan = useAdlcBlueprintStore((state) => state.showPlan);
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const [isValidating, setIsValidating] = useState(false);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  const [isRejecting, setIsRejecting] = useState(false);

  if (!proposal) return null;

  const validated = proposal.status === "VALIDATED";
  const actionable = canExecute && validated && !proposal.materialized_plan_id;
  const canValidate = proposal.status === "GENERATED";
  const terminal =
    proposal.status === "APPROVED" || proposal.status === "REJECTED";
  const busy = isValidating || isRegenerating || isApproving || isRejecting;

  const handleValidate = async () => {
    if (!canValidate || busy) return;
    setIsValidating(true);
    try {
      const updated = await validateAdlcPlanProposal(proposal.proposal_id);
      const { nodes, edges } = useFlowStore.getState();
      updateProposal(updated, nodes, edges);
      if (updated.status === "VALIDATED") {
        setSuccessData({
          title: translateUi("Proposal validated: {{value0}} tasks proposed", {
            value0: updated.tasks.length,
          }),
        });
      }
    } catch (error) {
      const { message } = getAdlcPlanningError(error);
      setErrorData({
        title: translateUi("Unable to validate proposal"),
        list: [message],
      });
    } finally {
      setIsValidating(false);
    }
  };

  const handleRegenerate = async () => {
    if (terminal || busy) return;
    setIsRegenerating(true);
    try {
      const successor = await regenerateAdlcPlanProposal(proposal.proposal_id);
      const { nodes, edges } = useFlowStore.getState();
      updateProposal(successor, nodes, edges);
      setSuccessData({
        title: translateUi("Proposal v{{value0}} generated", {
          value0: successor.proposal_version,
        }),
      });
    } catch (error) {
      const { message } = getAdlcPlanningError(error);
      setErrorData({
        title: translateUi("Unable to regenerate proposal"),
        list: [message],
      });
    } finally {
      setIsRegenerating(false);
    }
  };

  const handleApprove = async () => {
    if (!actionable || busy) return;
    setIsApproving(true);
    try {
      const result = await approveAdlcPlanProposal(proposal.proposal_id);
      const { nodes, edges } = useFlowStore.getState();
      updateProposal(result.proposal, nodes, edges);
      showPlan(result.execution_plan, nodes, edges);
      setSuccessData({
        title: translateUi("Execution plan created from the approved proposal"),
      });
    } catch (error) {
      const { message } = getAdlcPlanningError(error);
      setErrorData({
        title: translateUi("Unable to approve proposal"),
        list: [message],
      });
    } finally {
      setIsApproving(false);
    }
  };

  const handleReject = async () => {
    if (!canExecute || terminal || busy) return;
    setIsRejecting(true);
    try {
      const rejected = await rejectAdlcPlanProposal(proposal.proposal_id);
      const { nodes, edges } = useFlowStore.getState();
      updateProposal(rejected, nodes, edges);
      setSuccessData({ title: translateUi("Proposal rejected") });
    } catch (error) {
      const { message } = getAdlcPlanningError(error);
      setErrorData({
        title: translateUi("Unable to reject proposal"),
        list: [message],
      });
    } finally {
      setIsRejecting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-4xl" data-testid="plan-proposal-dialog">
        <DialogHeader>
          <div className="flex flex-wrap items-center gap-2">
            <DialogTitle>{translateUi("Proposed Execution Plan")}</DialogTitle>
            <ProposalStatusBadge status={proposal.status} />
            <Badge variant="secondaryStatic" size="tag">
              {proposal.planner_mode} planner
            </Badge>
            <Badge variant="secondaryStatic" size="tag">
              v{proposal.proposal_version}
            </Badge>
          </div>
          <DialogDescription>
            {proposal.tasks.length}{" "}
            {translateUi(
              "tasks proposed from your workflow. The orchestrator validates every proposal before it can run.",
            )}
          </DialogDescription>
        </DialogHeader>

        <div className="flex max-h-[60vh] flex-col gap-3 overflow-y-auto pr-1">
          <ProposalIssueList
            title={translateUi("Validation errors")}
            issues={proposal.validation_errors}
            tone="error"
          />
          <ProposalIssueList
            title={translateUi("Warnings")}
            issues={proposal.warnings}
            tone="warning"
          />

          {proposal.assumptions.length > 0 && (
            <section className="rounded-md border bg-muted/30 p-3 text-xs">
              <p className="font-medium">{translateUi("Assumptions")}</p>
              <ul className="mt-1 list-disc pl-4 text-muted-foreground">
                {proposal.assumptions.map((assumption, index) => (
                  <li key={index}>{assumption}</li>
                ))}
              </ul>
            </section>
          )}
          {proposal.clarifications.length > 0 && (
            <section className="rounded-md border bg-blue-500/5 p-3 text-xs">
              <p className="font-medium">
                {translateUi("Planner needs clarification")}
              </p>
              <ul className="mt-1 list-disc text-muted-foreground">
                {proposal.clarifications.map((item, index) => (
                  <li key={index}>{item}</li>
                ))}
              </ul>
            </section>
          )}

          <ProposalTree
            tasks={proposal.tasks}
            issues={proposal.validation_errors}
          />
        </div>

        <DialogFooter className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="md"
            disabled={!canValidate || busy}
            loading={isValidating}
            onClick={() => void handleValidate()}
            data-testid="validate-proposal-button"
          >
            <ForwardedIconComponent name="ListChecks" className="h-4 w-4" />
            {translateUi("Validate")}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="md"
            disabled={terminal || busy}
            loading={isRegenerating}
            onClick={() => void handleRegenerate()}
            data-testid="regenerate-proposal-button"
          >
            <ForwardedIconComponent name="RefreshCw" className="h-4 w-4" />
            {translateUi("Regenerate")}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="md"
            disabled={!canExecute || terminal || busy}
            loading={isRejecting}
            onClick={() => void handleReject()}
            data-testid="reject-proposal-button"
          >
            {translateUi("Reject")}
          </Button>
          <Button
            type="button"
            size="md"
            disabled={!actionable || busy}
            loading={isApproving}
            onClick={() => void handleApprove()}
            data-testid="approve-proposal-button"
          >
            <ForwardedIconComponent name="Sparkles" className="h-4 w-4" />
            {translateUi("Approve & Create Execution Plan")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
