import { translateUi, useUiLocale } from "@/i18n/ui";
import axios from "axios";
import { useEffect, useState } from "react";
import { listContractExecutions } from "@/controllers/API/contracts";
import type { ContractExecutionRead } from "@/types/contractExecution";
import ContractViewer from "../ContractViewer";
import { supportedExecution } from "./model";
import { useTranslation } from "react-i18next";
import "@/i18n";

export default function ContractExecutionPanel({
  scope,
}: {
  scope: { runId: string } | { sessionId: string };
}) {
  const { t } = useTranslation();
  useUiLocale();
  const key = "runId" in scope ? scope.runId : scope.sessionId;
  const isRun = "runId" in scope;
  const [snapshot, setSnapshot] = useState<{
    key: string;
    rows: ContractExecutionRead[];
  }>();
  const [error, setError] = useState(false);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    setSnapshot(undefined);
    setError(false);
    const load = async () => {
      let disabled = false;
      try {
        const rows = await listContractExecutions(
          isRun ? { runId: key } : { sessionId: key },
        );
        if (active) {
          setSnapshot({ key, rows });
          setError(false);
        }
      } catch (e) {
        disabled = axios.isAxiosError(e) && e.response?.status === 404;
        if (active) {
          setSnapshot(undefined);
          setError(!disabled);
        }
      } finally {
        if (active && !disabled) timer = setTimeout(() => void load(), 5000);
      }
    };
    void load();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [key, isRun, refresh]);
  if (error)
    return (
      <section
        aria-label={translateUi("Contract execution evidence")}
        className="rounded-lg border p-4"
      >
        <p role="status">
          {translateUi(
            "Execution evidence could not be confirmed. No completion claim is available.",
          )}
        </p>
        <button
          type="button"
          className="mt-2 rounded border px-3 py-2 text-sm"
          onClick={() => setRefresh((n) => n + 1)}
        >
          {translateUi("Refresh evidence")}
        </button>
      </section>
    );
  if (snapshot?.key !== key || !snapshot.rows.length) return null;
  return (
    <section
      aria-label={translateUi("Contract execution evidence")}
      className="space-y-4 rounded-lg border p-5"
    >
      <h2 className="text-lg font-semibold">
        {translateUi("Contract execution · bounded machine evidence")}
      </h2>
      <p className="text-sm text-muted-foreground">
        {translateUi(
          "These checks prove only the registered predicates on this captured patch. Natural-language scope, implementation correctness and dependency order are not automatically verified. Contract approval and Submit are separate human decisions.",
        )}
      </p>
      {snapshot.rows.map((row, i) =>
        !supportedExecution(row) ||
        (isRun
          ? row.binding.scope.workflow_run_id !== key
          : row.binding.scope.session_id !== key) ? (
          <div key={i}>
            <p role="status">
              {translateUi(
                "Unsupported or inconsistent evidence. Showing escaped JSON without a completion badge.",
              )}
            </p>
            <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all text-xs">
              {JSON.stringify(row, null, 2)}
            </pre>
          </div>
        ) : (
          <article
            key={row.binding.scope.attempt_id}
            className="space-y-3 rounded-lg border p-4"
          >
            <p className="break-all text-xs font-mono">
              {translateUi("Attempt")} {row.binding.scope.attempt_id}{" "}
              {translateUi("· session")} {row.binding.scope.session_id}
            </p>
            <p className="break-all text-xs font-mono">
              {translateUi("Plan")} {row.binding.execution_plan_id}{" "}
              {translateUi("· revision")} {row.binding.reference.revision} ·{" "}
              {row.binding.reference.content_digest}
            </p>
            <p className="break-all text-xs font-mono">
              {translateUi("Policy")} {row.binding.policy_digest}
            </p>
            <p className="text-sm">
              {row.binding.policy.read_only
                ? translateUi("Read-only repository tools")
                : translateUi("Guarded text writes")}{" "}
              {translateUi("· allowed paths:")}{" "}
              {row.binding.policy.allowed_paths.join(", ")}
            </p>
            <p className="text-sm">
              {translateUi("Always denied:")}{" "}
              {row.binding.policy.denied_actions.join(", ")}
            </p>
            {row.proof ? (
              <>
                <p
                  className={
                    row.proof.checks.every((c) => c.passed)
                      ? "text-sm text-accent-emerald"
                      : "text-sm text-destructive"
                  }
                >
                  {row.proof.checks.every((c) => c.passed)
                    ? translateUi("Registered machine predicates passed")
                    : translateUi("Machine predicates rejected this candidate")}
                </p>
                <p className="break-all text-xs font-mono">
                  {translateUi("Captured artifact")} {row.proof.artifact_id} ·{" "}
                  {row.proof.artifact_checksum}
                </p>
                <p className="break-all text-xs font-mono">
                  {translateUi("Base commit")} {row.proof.base_commit}
                </p>
                <p className="text-sm">
                  {translateUi("Changed paths:")}{" "}
                  {row.proof.changed_paths.join(", ") || "none"}
                </p>
                <ul className="space-y-2 text-sm">
                  {row.proof.checks.map((check) => (
                    <li key={`${check.node_id}:${check.criterion_index}`}>
                      {check.passed
                        ? t("adlc.ct.passBadge")
                        : t("adlc.ct.failBadge")}{" "}
                      · {check.verifier_ref} ·{" "}
                      {
                        row.contract.document.nodes.find(
                          (n) => n.node_id === check.node_id,
                        )?.title
                      }{" "}
                      {translateUi("· criterion")} {check.criterion_index + 1}
                    </li>
                  ))}
                </ul>
                <p className="text-xs text-muted-foreground">
                  {translateUi(
                    "Evidence retained independently of patch expiry; patch bytes may no longer be downloadable.",
                  )}
                </p>
              </>
            ) : (
              <p role="status" className="text-sm">
                {translateUi(
                  "Exact contract bound. Verification evidence has not been recorded.",
                )}
              </p>
            )}
            <details className="rounded border p-3">
              <summary className="cursor-pointer text-sm">
                {translateUi("Bound approved roadmap")}
              </summary>
              <div className="mt-4">
                <ContractViewer contract={row.contract} />
              </div>
            </details>
            <details>
              <summary className="cursor-pointer text-sm">
                {translateUi("Binding and evidence JSON")}
              </summary>
              <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all text-xs">
                {JSON.stringify(row, null, 2)}
              </pre>
            </details>
          </article>
        ),
      )}
    </section>
  );
}
