import { useState } from "react";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { AdlcApprovalRequest, AdlcTaskRun } from "@/types/adlc";
import HarnessWorkflowReview, {
  workflowHarnessReview,
} from "./HarnessWorkflowReview";
import { useTranslation } from "react-i18next";
import "@/i18n";

interface ApprovalPanelProps {
  approval: AdlcApprovalRequest;
  tasks: AdlcTaskRun[];
  acting: boolean;
  disabled?: boolean;
  disabledReason?: string;
  onApprove: (comment: string | undefined) => void;
  onReject: (comment: string, targetTaskId: string | undefined) => void;
}

/**
 * Approval panel for a pending approval request.
 *
 * Shows:
 * - Approval context (title, summary, candidates)
 * - Approve button (accepts the work)
 * - Reject button (opens a form to collect reason + target task to redo)
 *
 * When rejecting, the user must:
 * 1. Provide a reason or new requirement
 * 2. Optionally select which task to redo (reverse connection)
 *
 * The rejection sends the reason back to the selected task so the
 * system can re-execute it with the user's feedback.
 */
export default function ApprovalPanel({
  approval,
  tasks,
  acting,
  disabled = false,
  disabledReason,
  onApprove,
  onReject,
}: ApprovalPanelProps) {
  const { t } = useTranslation();
  const [showRejectForm, setShowRejectForm] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [targetTaskId, setTargetTaskId] = useState<string>("");
  const [harnessConfirmed, setHarnessConfirmed] = useState(false);
  const harnessReview = workflowHarnessReview(
    approval.context.payload?.harness_workflow_review,
  );

  // Find tasks that can be redone (completed tasks that this approval depends on).
  const redoableTasks = tasks.filter(
    (t) =>
      t.status === "SUCCEEDED" || t.status === "FAILED",
  );

  const handleReject = () => {
    if (!rejectReason.trim()) return;
    onReject(rejectReason.trim(), targetTaskId || undefined);
    setShowRejectForm(false);
    setRejectReason("");
    setTargetTaskId("");
  };

  return (
    <Card className="bg-background" data-testid="approval-panel">
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle>{approval.title}</CardTitle>
          <Badge variant="emerald" size="tag">
            {approval.status}
          </Badge>
        </div>
        <CardDescription>{approval.context.summary}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {disabled && disabledReason && (
          <p
            className="text-sm text-destructive"
            data-testid="approval-disabled-reason"
          >
            {disabledReason}
          </p>
        )}
        {approval.context.payload?.reviewed_candidates?.map((candidate) => (
          <div
            key={candidate.artifact_id}
            className="w-full space-y-1 rounded border p-2"
          >
            <p className="text-xs font-medium">
              {t("adlc.run.approveCandidateIteration", {
                iteration: candidate.iteration ?? t("adlc.run.unknown"),
              })}
            </p>
            <p className="break-all font-mono text-xs">
              {candidate.candidate_id ?? candidate.artifact_id}
            </p>
            <p className="break-all font-mono text-[11px] text-muted-foreground">
              {candidate.candidate_digest}
            </p>
          </div>
        ))}

        {harnessReview && (
          <>
            <HarnessWorkflowReview review={harnessReview} />
            <label className="flex w-full items-start gap-2 text-sm">
              <input
                type="checkbox"
                checked={harnessConfirmed}
                onChange={(e) => setHarnessConfirmed(e.target.checked)}
                data-testid="approval-harness-confirm"
              />
              {t("adlc.run.harnessConfirm")}
            </label>
          </>
        )}

        {!showRejectForm ? (
          <div className="flex flex-wrap gap-2">
            <Button
              size="md"
              disabled={disabled || (Boolean(harnessReview) && !harnessConfirmed)}
              loading={acting}
              onClick={() => onApprove(undefined)}
              data-testid="approval-approve"
            >
              <ForwardedIconComponent name="Check" className="h-4 w-4" />
              {t("adlc.run.accept")}
            </Button>
            <Button
              variant="outline"
              size="md"
              disabled={disabled}
              onClick={() => setShowRejectForm(true)}
              data-testid="approval-reject-toggle"
            >
              <ForwardedIconComponent name="X" className="h-4 w-4" />
              {t("adlc.run.reject")}
            </Button>
          </div>
        ) : (
          <div
            className="space-y-3 rounded-md border border-destructive/30 bg-destructive/5 p-3"
            data-testid="approval-reject-form"
          >
            <div className="flex items-center gap-2 text-sm font-medium text-destructive">
              <ForwardedIconComponent name="AlertTriangle" className="h-4 w-4" />
              {t("adlc.run.rejectAndRequestChanges")}
            </div>

            <label className="block space-y-1 text-xs text-muted-foreground">
              {t("adlc.run.reasonRequired")}
              <textarea
                aria-label={t("adlc.run.ariaRejectionReason")}
                className="w-full rounded-md border bg-background p-2 text-sm text-foreground"
                rows={3}
                maxLength={4096}
                value={rejectReason}
                onChange={(event) => setRejectReason(event.target.value)}
                placeholder={t("adlc.run.placeholderRejection")}
                data-testid="approval-reject-reason"
              />
            </label>

            {redoableTasks.length > 0 && (
              <label className="block space-y-1 text-xs text-muted-foreground">
                {t("adlc.run.sendFeedbackTo")}
                <select
                  aria-label={t("adlc.run.ariaRedoTarget")}
                  className="w-full rounded-md border bg-background p-2 text-sm text-foreground"
                  value={targetTaskId}
                  onChange={(event) => setTargetTaskId(event.target.value)}
                  data-testid="approval-reject-target"
                >
                  <option value="">{t("adlc.run.noSpecificTask")}</option>
                  {redoableTasks.map((task) => (
                    <option key={task.id} value={task.id}>
                      {task.name} ({task.status.toLowerCase()})
                    </option>
                  ))}
                </select>
                <span className="text-[11px] text-muted-foreground">
                  {t("adlc.run.taskRedoNote")}
                </span>
              </label>
            )}

            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setShowRejectForm(false);
                  setRejectReason("");
                  setTargetTaskId("");
                }}
                data-testid="approval-reject-cancel"
              >
                {t("adlc.run.cancel")}
              </Button>
              <Button
                size="sm"
                disabled={!rejectReason.trim()}
                loading={acting}
                onClick={handleReject}
                data-testid="approval-reject-submit"
              >
                <ForwardedIconComponent name="RotateCcw" className="h-4 w-4" />
                {t("adlc.run.rejectAnd")}{" "}
                {targetTaskId ? t("adlc.run.redoTask") : t("adlc.run.sendFeedback")}
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
