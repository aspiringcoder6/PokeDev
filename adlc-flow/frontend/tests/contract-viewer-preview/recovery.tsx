import { useState } from "react";
import ContractViewer from "@/components/adlc/ContractViewer";
import { copyContract } from "@/components/adlc/ContractViewer/test-fixtures";
import HarnessSessions from "@/pages/RunDetailPage/HarnessSessions";
import type { AdlcHarnessRunSession } from "@/types/adlc";

export default function RecoveryPreview() {
  const [status, setStatus] = useState<
    "VERIFYING" | "READY_FOR_SUBMISSION" | "SUCCEEDED"
  >("VERIFYING");
  const contract = copyContract();
  contract.status = "APPROVED";
  contract.approval = {
    reference: contract.reference,
    approval_id: "offline-approval",
    approved_by: "fixture-owner",
    approved_at: "2026-10-08T00:00:00Z",
    comment: null,
  };
  const session: AdlcHarnessRunSession = {
    attempt_id: "fixture-attempt",
    task_run_id: "fixture-task",
    attempt_status: "VERIFYING",
    session: {
      schema_version: "0.1",
      session_id: "session-h5d",
      status,
      submission_mode: "MANUAL",
      interactions: [],
      events: [{ event_type: "execution.reconciliation_waiting" }],
      created_at: "2026-10-08T00:00:00Z",
      updated_at: "2026-10-08T00:00:00Z",
    },
  };
  return (
    <div className="space-y-5">
      <div className="rounded-lg border bg-muted/30 p-4 text-sm">
        <h2 className="font-semibold">H5D recovery — isolated UI fixture</h2>
        <p className="mt-2 text-muted-foreground">
          These buttons simulate local display states only. No API, model,
          approval or callback is called.
        </p>
        <p className="mt-2">
          State: {status}. The saved candidate still needs a separate human
          Submit after recovery.
        </p>
      </div>
      <HarnessSessions
        sessions={[session]}
        tasks={[]}
        onRespond={() => {}}
        onReconcileVerification={() => setStatus("READY_FOR_SUBMISSION")}
        onSubmit={() => setStatus("SUCCEEDED")}
      />
      {status === "SUCCEEDED" && (
        <p role="status" className="rounded-lg border p-4 text-sm">
          Fixture submitted. Live callback and owner-login sign-off remain
          separate.
        </p>
      )}
      <ContractViewer contract={contract} />
    </div>
  );
}
