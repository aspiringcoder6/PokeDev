import { translateUi, useUiLocale, formatUiStatus } from "@/i18n/ui";
import axios from "axios";
import { useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  createVerification,
  downloadVerification,
  listVerifications,
  verificationAction,
  verificationCandidates,
  verificationCapabilities,
} from "@/controllers/API/verification";
import useAuthStore from "@/stores/authStore";
import type {
  VerificationCandidates,
  VerificationCapabilities,
  VerificationRead,
  VerificationScope,
} from "@/types/verification";

const field = "w-full rounded-md border bg-background p-2 text-sm";
const scalar = (value: unknown) =>
  value === null ||
  typeof value === "boolean" ||
  (typeof value === "string" && value.length <= 4096) ||
  (typeof value === "number" &&
    Number.isFinite(value) &&
    Math.abs(value) <= Number.MAX_SAFE_INTEGER);
function errorMessage(error: unknown) {
  const code = axios.isAxiosError(error)
    ? error.response?.data?.detail?.code
    : undefined;
  if (code === "VERIFICATION_CANDIDATE_STALE")
    return translateUi(
      "This candidate is no longer the current attempt. Refresh and create a new plan.",
    );
  if (code === "VERIFICATION_PINNED_LOCAL_PROJECT_REQUIRED")
    return translateUi(
      "This check requires a captured JSON change from a pinned local project.",
    );
  if (code === "VERIFICATION_REFERENCE_CONFLICT")
    return translateUi(
      "The displayed reference changed. Refresh before acting.",
    );
  if (
    code === "CONTRACT_EXPLICIT_LOGIN_REQUIRED" ||
    code === "CONTRACT_USER_TOKEN_REQUIRED"
  )
    return translateUi(
      "Sign in explicitly to ADLC. Auto-login and service keys cannot approve or run verification.",
    );
  return translateUi(
    "Verification could not be confirmed. Refresh or sign in again; no success claim is available.",
  );
}
function supported(row: VerificationRead, scope: VerificationScope) {
  try {
    if (
      row.plan?.schema_version !== "0.1" ||
      row.plan.profile_ref !== "verification-profile:json-fixture/0.1.0" ||
      row.plan.revision !== 1 ||
      !/^sha256:[0-9a-f]{64}$/.test(row.plan_digest) ||
      !row.plan.cases?.length ||
      row.plan.cases.length > 16 ||
      ![
        "DRAFT",
        "APPROVED",
        "RUNNING",
        "DISPATCH_UNCERTAIN",
        "NOT_VERIFIED",
        "READY_FOR_SUBMISSION",
        "SUBMITTED",
      ].includes(row.state) ||
      new Set(row.plan.cases.map((c) => c.case_id)).size !==
        row.plan.cases.length ||
      row.plan.cases.some((c) => !scalar(c.expected)) ||
      (row.state !== "DRAFT" && (!row.approved_by || !row.approved_at)) ||
      ("runId" in scope
        ? row.plan.workflow_run_id !== scope.runId
        : row.plan.candidate.source_session_id !== scope.sessionId)
    )
      return false;
    if (!row.report)
      return (
        !row.receipt &&
        !["READY_FOR_SUBMISSION", "SUBMITTED"].includes(row.state)
      );
    if (
      !["READY_FOR_SUBMISSION", "SUBMITTED"].includes(row.state) ||
      !row.execution_id ||
      !row.evidence_digest ||
      row.receipt?.schema_version !== "0.1" ||
      row.receipt.execution_id !== row.execution_id ||
      row.receipt.runner_ref !== "runner:adlc-json-fixture/0.1.0" ||
      row.receipt.runner_digest !==
        "sha256:c2afb80f9585dd021ed819fdb5d115f8d602f2c63d50e587365dbc43d3b9966f" ||
      (row.receipt.completion_mode === "process-exit"
        ? row.receipt.exit_code !== 0
        : row.receipt.completion_mode !== "durable-checkpoint" ||
          row.receipt.exit_code !== null) ||
      !Number.isFinite(Date.parse(row.receipt.started_at)) ||
      !Number.isFinite(Date.parse(row.receipt.completed_at)) ||
      Date.parse(row.receipt.completed_at) < Date.parse(row.receipt.started_at)
    )
      return false;
    return (
      row.report.schema_version === "0.1" &&
      row.report.comparator_ref === "validator:json-fixture/0.1.0" &&
      row.report.natural_language_enforced === false &&
      row.report.contract_fully_verified === false &&
      row.report.plan_digest === row.plan_digest &&
      row.report.candidate_digest === row.plan.candidate.content_digest &&
      row.receipt?.plan_digest === row.plan_digest &&
      row.receipt.candidate_digest === row.plan.candidate.content_digest &&
      row.receipt.tests_run === row.plan.cases.length &&
      row.receipt.observations.length === row.plan.cases.length &&
      row.report.checks.length === row.plan.cases.length &&
      row.report.checks.every(
        (check, i) =>
          check.case_id === row.plan.cases[i].case_id &&
          check.pointer === row.plan.cases[i].pointer &&
          row.receipt?.observations[i].case_id === check.case_id &&
          row.receipt.observations[i].pointer === check.pointer &&
          JSON.stringify(check.expected) ===
            JSON.stringify(row.plan.cases[i].expected) &&
          check.found === row.receipt?.observations[i].found &&
          JSON.stringify(check.observed) ===
            JSON.stringify(row.receipt?.observations[i].observed) &&
          check.passed ===
            (check.found &&
              JSON.stringify(check.expected) ===
                JSON.stringify(check.observed)),
      ) &&
      (row.report.verdict === "PASS"
        ? row.report.checks.every((check) => check.passed === true)
        : row.report.verdict === "FAIL" &&
          row.report.checks.some((check) => check.passed === false))
    );
  } catch {
    return false;
  }
}

export default function VerificationPanel({
  scope,
  readOnly = false,
}: {
  scope: VerificationScope;
  readOnly?: boolean;
}) {
  useUiLocale();
  const key = "runId" in scope ? scope.runId : scope.sessionId;
  const isRun = "runId" in scope;
  const scopeIdentity = `${isRun ? "run" : "session"}:${key}`;
  const current = useRef(scopeIdentity);
  current.current = scopeIdentity;
  const auth = useAuthStore((state) => state.isAuthenticated);
  const autoLogin = useAuthStore((state) => state.autoLogin);
  const [caps, setCaps] = useState<VerificationCapabilities>();
  const [rows, setRows] = useState<VerificationRead[]>([]);
  const [options, setOptions] = useState<VerificationCandidates>();
  const [error, setError] = useState<string>();
  const [fresh, setFresh] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [acting, setActing] = useState<string>();
  const [reviewed, setReviewed] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const [open, setOpen] = useState(false);
  const [patchIndex, setPatchIndex] = useState(0);
  const [file, setFile] = useState("");
  const [contractIndex, setContractIndex] = useState(0);
  const [criterion, setCriterion] = useState("");
  const [pointer, setPointer] = useState("/answer");
  const [expected, setExpected] = useState("42");
  const requestKey = useRef<string | undefined>(undefined);

  useEffect(() => {
    setReviewed(undefined);
    setActing(undefined);
    setNotice(undefined);
    setOpen(false);
    requestKey.current = undefined;
  }, [key, isRun]);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    setCaps(undefined);
    setRows([]);
    setOptions(undefined);
    setFresh(false);
    setError(undefined);
    const load = async () => {
      try {
        const [capability, snapshot] = await Promise.all([
          verificationCapabilities(),
          listVerifications(isRun ? { runId: key } : { sessionId: key }),
        ]);
        if (!active) return;
        setCaps(capability);
        setRows(snapshot);
        setFresh(true);
        setError(undefined);
      } catch (e) {
        if (active) {
          setFresh(false);
          setRows([]);
          setError(errorMessage(e));
        }
      } finally {
        if (active) timer = setTimeout(() => void load(), 3000);
      }
    };
    void load();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [key, isRun, refresh, auth, autoLogin]);

  const human =
    !readOnly &&
    isRun &&
    auth &&
    !autoLogin &&
    caps?.human_actions_configured &&
    caps.enabled &&
    fresh &&
    !error;
  async function act(
    id: string,
    action: () => Promise<unknown>,
    success: string,
  ) {
    const scopeKey = scopeIdentity;
    setActing(id);
    setNotice(undefined);
    try {
      await action();
      if (current.current === scopeKey) {
        setNotice(success);
        setRefresh((n) => n + 1);
      }
    } catch (e) {
      if (current.current === scopeKey) {
        setError(errorMessage(e));
        setFresh(false);
      }
    } finally {
      if (current.current === scopeKey) setActing(undefined);
    }
  }
  async function openDraft() {
    if (!isRun) return;
    const scopeKey = scopeIdentity;
    setActing("draft");
    try {
      const result = await verificationCandidates(key);
      if (current.current !== scopeKey) return;
      setOptions(result);
      setFile(result.patches[0]?.files[0] ?? "");
      setPatchIndex(0);
      setContractIndex(0);
      const firstNode = result.contracts[0]?.document.nodes.find(
        (node) => node.acceptance_criteria.length,
      );
      setCriterion(firstNode ? `${firstNode.node_id}:0` : "");
      setOpen(true);
      requestKey.current = crypto.randomUUID();
    } catch (e) {
      if (current.current === scopeKey) setError(errorMessage(e));
    } finally {
      if (current.current === scopeKey) setActing(undefined);
    }
  }
  const contract = options?.contracts[contractIndex];
  const patch = options?.patches[patchIndex];

  return (
    <Card
      aria-label={translateUi("Real verification")}
      className="bg-background"
    >
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle>
            {translateUi("Verify · evidence, not a completion claim")}
          </CardTitle>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setRefresh((n) => n + 1)}
            disabled={!!acting}
          >
            {translateUi("Refresh verification")}
          </Button>
        </div>
        <CardDescription>
          {translateUi(
            "H6A checks one frozen JSON file against explicitly approved expected values. It does not execute project code or verify the whole application. A coding run's success is not a verification verdict.",
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {error && (
          <p role="alert" className="text-destructive">
            {error}
          </p>
        )}
        {notice && <p role="status">{notice}</p>}
        {caps && !caps.enabled && (
          <p className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">
            {translateUi(
              "Verification is not enabled. Existing results remain readable; configure the opt-in H6A worker before running new checks.",
            )}
          </p>
        )}
        {caps?.enabled && !caps.worker_ready && (
          <p role="status" className="rounded-lg border p-3 text-sm">
            {translateUi(
              "The reproducer is not ready. Plans can be reviewed, but execution is blocked.",
            )}
          </p>
        )}
        {caps?.provider === "local-fixture" && (
          <p className="text-sm text-muted-foreground">
            {translateUi(
              "Provider: protected local fixture subprocess · JSON data only, not an application sandbox.",
            )}
          </p>
        )}
        {caps?.provider === "sandbox-kit" && (
          <p className="text-sm text-muted-foreground">
            {translateUi(
              "Provider: Sandbox Kit · pinned image and disposable run-scoped session.",
            )}
          </p>
        )}
        {!readOnly &&
          caps?.enabled &&
          (!auth || autoLogin || !caps.human_actions_configured) && (
            <p role="status">
              {translateUi(
                "Explicit ADLC owner login is required for draft, approval, execution and Submit. Service tokens cannot make human decisions.",
              )}
            </p>
          )}
        {!rows.length && fresh && (
          <p className="text-sm text-muted-foreground">
            {translateUi(
              "No reproduction evidence yet. Review, contract approval and source-patch checks are not a substitute for Verify.",
            )}
          </p>
        )}
        {isRun && !readOnly && (
          <Button
            onClick={() => void openDraft()}
            disabled={!human || !!acting}
          >
            {translateUi("Create verification plan")}
          </Button>
        )}

        {open && human && options && (
          <form
            aria-label={translateUi("Create verification plan")}
            className="space-y-3 rounded-lg border p-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (!patch || !contract || !criterion || !isRun) return;
              let value;
              try {
                value = JSON.parse(expected);
                if (!scalar(value)) throw new Error();
              } catch {
                setNotice(
                  translateUi(
                    "Expected value must be a bounded JSON scalar: a string up to 4096 characters, finite safe number, true, false or null.",
                  ),
                );
                return;
              }
              const [nodeId, criterionIndex] = criterion.split(":");
              void act(
                "create",
                () =>
                  createVerification(key, {
                    source_task_id: patch.source_task_id,
                    artifact_id: patch.artifact_id,
                    file,
                    contract_reference: contract.reference,
                    timeout_seconds: 15,
                    idempotency_key: requestKey.current ?? crypto.randomUUID(),
                    cases: [
                      {
                        case_id: "case-1",
                        pointer,
                        expected: value,
                        criterion_node_id: nodeId,
                        criterion_index: Number(criterionIndex),
                      },
                    ],
                  }),
                "Draft frozen. Review its references and expected values before approving; no test has run.",
              );
            }}
          >
            <h3 className="font-medium">
              {translateUi("One-predicate pilot")}
            </h3>
            <p className="text-sm text-muted-foreground">
              {translateUi(
                "Choose an accepted JSON patch from a pinned local project and an approved roadmap criterion. Edits after approval require a new plan; existing evidence is retained.",
              )}
            </p>
            {!options.patches.length && (
              <p role="status">
                {translateUi(
                  "No eligible captured JSON change is available. Complete a local-project run that changes a JSON file first.",
                )}
              </p>
            )}
            {!options.contracts.length && (
              <p role="status">
                {translateUi(
                  "No approved roadmap reference is linked to this run.",
                )}
              </p>
            )}
            <label className="block text-sm">
              {translateUi("Captured candidate")}
              <select
                className={field}
                value={patchIndex}
                onChange={(e) => {
                  const index = Number(e.target.value);
                  setPatchIndex(index);
                  setFile(options.patches[index]?.files[0] ?? "");
                  requestKey.current = crypto.randomUUID();
                }}
              >
                {options.patches.map((item, i) => (
                  <option key={item.artifact_id} value={i}>
                    {item.task_name} · {item.artifact_id.slice(0, 8)}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm">
              {translateUi("JSON file")}
              <select
                className={field}
                value={file}
                onChange={(e) => {
                  setFile(e.target.value);
                  requestKey.current = crypto.randomUUID();
                }}
              >
                {patch?.files.map((name) => (
                  <option key={name}>{name}</option>
                ))}
              </select>
            </label>
            <label className="block text-sm">
              {translateUi("Approved roadmap")}
              <select
                className={field}
                value={contractIndex}
                onChange={(e) => {
                  setContractIndex(Number(e.target.value));
                  setCriterion("");
                  requestKey.current = crypto.randomUUID();
                }}
              >
                {options.contracts.map((item, i) => (
                  <option key={item.reference.contract_id} value={i}>
                    {item.document.title} {translateUi("· revision")}{" "}
                    {item.reference.revision}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm">
              {translateUi("Contract criterion")}
              <select
                className={field}
                value={criterion}
                onChange={(e) => {
                  setCriterion(e.target.value);
                  requestKey.current = crypto.randomUUID();
                }}
              >
                <option value="">{translateUi("Choose a criterion")}</option>
                {contract?.document.nodes.flatMap((node) =>
                  node.acceptance_criteria.map((item, i) => (
                    <option
                      key={`${node.node_id}:${i}`}
                      value={`${node.node_id}:${i}`}
                    >
                      {node.title}: {item.description}
                    </option>
                  )),
                )}
              </select>
            </label>
            <label className="block text-sm">
              {translateUi("JSON pointer")}{" "}
              <input
                className={field}
                value={pointer}
                placeholder="/answer"
                onChange={(e) => {
                  setPointer(e.target.value);
                  requestKey.current = crypto.randomUUID();
                }}
              />
            </label>
            <label className="block text-sm">
              {translateUi("Expected JSON value")}{" "}
              <input
                className={field}
                value={expected}
                onChange={(e) => {
                  setExpected(e.target.value);
                  requestKey.current = crypto.randomUUID();
                }}
              />
            </label>
            <Button
              type="submit"
              disabled={!!acting || !patch || !contract || !criterion || !file}
            >
              {translateUi("Save draft · do not execute")}
            </Button>
          </form>
        )}

        {rows.map((row) =>
          !supported(row, scope) ? (
            <div
              key={row.plan?.plan_id ?? JSON.stringify(row)}
              className="rounded-lg border p-3"
            >
              <p role="status">
                {translateUi(
                  "Unsupported or inconsistent evidence. No verification badge is available.",
                )}
              </p>
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all text-xs">
                {JSON.stringify(row, null, 2)}
              </pre>
            </div>
          ) : (
            <article
              key={row.plan.plan_id}
              className="space-y-3 rounded-lg border p-4"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="font-medium">{row.plan.candidate.file}</h3>
                <div className="flex gap-2">
                  <Badge
                    variant={
                      row.report?.verdict === "PASS"
                        ? "successStatic"
                        : row.report?.verdict === "FAIL"
                          ? "errorStatic"
                          : "secondaryStatic"
                    }
                  >
                    {row.report?.verdict ?? translateUi("NOT VERIFIED")}
                  </Badge>
                  <Badge variant="secondaryStatic">
                    {formatUiStatus(row.state, true)}
                  </Badge>
                </div>
              </div>
              {row.report && row.state !== "SUBMITTED" && (
                <p className="text-sm text-muted-foreground">
                  {translateUi(
                    "Prepared evidence preview · not submitted. Approval and result Submit are separate.",
                  )}
                </p>
              )}
              <p className="break-all font-mono text-xs">
                {translateUi("Contract revision")}{" "}
                {row.plan.contract_reference.revision} ·{" "}
                {row.plan.contract_reference.content_digest}
              </p>
              <p className="break-all font-mono text-xs">
                {translateUi("Candidate")} {row.plan.candidate.content_digest}{" "}
                {translateUi("· base")} {row.plan.candidate.base_commit}
              </p>
              <p className="break-all font-mono text-xs">
                {translateUi("Plan")} {row.plan.plan_id} · {row.plan_digest}
              </p>
              {row.error_code && (
                <p role="status" className="text-destructive">
                  {row.error_code}{" "}
                  {translateUi(
                    "· no passing verdict was accepted. Recovery observes the existing execution; it does not rerun it.",
                  )}
                </p>
              )}
              {row.receipt && (
                <p className="text-sm">
                  {translateUi("Reproduced")} {row.receipt.tests_run}/
                  {row.plan.cases.length} {translateUi("required cases ·")}{" "}
                  {row.receipt.provider} · {row.receipt.runner_ref}
                </p>
              )}
              {row.receipt?.completion_mode === "durable-checkpoint" && (
                <p className="text-sm text-muted-foreground">
                  {translateUi(
                    "Recovered atomic completion evidence. The original process exit was not observed after restart; no test was rerun.",
                  )}
                </p>
              )}
              <div className="overflow-auto">
                <table className="w-full text-left text-sm">
                  <caption className="sr-only">
                    {translateUi("Fixed criteria and observed evidence")}
                  </caption>
                  <thead>
                    <tr className="border-b">
                      <th className="p-2">{translateUi("Case")}</th>
                      <th className="p-2">{translateUi("Pointer")}</th>
                      <th className="p-2">{translateUi("Expected")}</th>
                      <th className="p-2">{translateUi("Observed")}</th>
                      <th className="p-2">{translateUi("Result")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {row.plan.cases.map((c) => {
                      const check = row.report?.checks.find(
                        (item) => item.case_id === c.case_id,
                      );
                      return (
                        <tr key={c.case_id} className="border-b">
                          <td className="p-2">{c.case_id}</td>
                          <td className="p-2 font-mono">
                            {c.pointer || "(root)"}
                          </td>
                          <td className="p-2">
                            <code>{JSON.stringify(c.expected)}</code>
                          </td>
                          <td className="p-2">
                            <code>
                              {check
                                ? check.found
                                  ? JSON.stringify(check.observed)
                                  : translateUi("Not found")
                                : translateUi("Not reproduced")}
                            </code>
                          </td>
                          <td className="p-2">
                            {check
                              ? check.passed
                                ? "PASS"
                                : "FAIL"
                              : translateUi("NOT VERIFIED")}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {row.state === "DRAFT" && human && (
                <label className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={reviewed === row.plan_digest}
                    onChange={(e) =>
                      setReviewed(
                        e.target.checked ? row.plan_digest : undefined,
                      )
                    }
                  />
                  {translateUi(
                    "I reviewed this exact contract, frozen candidate and expected values. Approval does not run the test.",
                  )}
                </label>
              )}
              <div className="flex flex-wrap gap-2">
                {row.state === "DRAFT" && !readOnly && (
                  <Button
                    disabled={
                      !human || reviewed !== row.plan_digest || !!acting
                    }
                    onClick={() =>
                      void act(
                        row.plan.plan_id,
                        () => verificationAction(key, row, "approve"),
                        "Exact verification plan approved. No test has run.",
                      )
                    }
                  >
                    {translateUi("Approve exact verification plan")}
                  </Button>
                )}
                {row.state === "APPROVED" && !readOnly && (
                  <Button
                    disabled={!human || !caps?.worker_ready || !!acting}
                    onClick={() =>
                      void act(
                        row.plan.plan_id,
                        () => verificationAction(key, row, "execute"),
                        "Reproduction dispatched. The recorded execution will be observed without automatic retries.",
                      )
                    }
                  >
                    {translateUi("Run approved verification")}
                  </Button>
                )}
                {["RUNNING", "DISPATCH_UNCERTAIN"].includes(row.state) &&
                  !readOnly && (
                    <Button
                      variant="outline"
                      disabled={!human || !!acting}
                      onClick={() =>
                        void act(
                          row.plan.plan_id,
                          () => verificationAction(key, row, "reconcile"),
                          "Existing execution observed. No new execution was created.",
                        )
                      }
                    >
                      {translateUi("Reconcile evidence · do not rerun")}
                    </Button>
                  )}
                {row.state === "READY_FOR_SUBMISSION" && !readOnly && (
                  <Button
                    disabled={!human || !!acting}
                    onClick={() =>
                      void act(
                        row.plan.plan_id,
                        () => verificationAction(key, row, "submit"),
                        "Verification report submitted to the ADLC archive. No deployment or workflow approval was granted.",
                      )
                    }
                  >
                    {translateUi("Submit verification report")}
                  </Button>
                )}
                {row.evidence_digest && (
                  <Button
                    variant="outline"
                    disabled={!fresh || !!acting}
                    onClick={() =>
                      void act(
                        "download",
                        () =>
                          downloadVerification(row.plan.workflow_run_id, row),
                        "Evidence checksum verified; download prepared.",
                      )
                    }
                  >
                    {translateUi("Download checksummed evidence")}
                  </Button>
                )}
              </div>
              <details>
                <summary className="cursor-pointer text-sm">
                  {translateUi("Plan, execution receipt and diagnostics")}
                </summary>
                <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-all rounded bg-muted p-3 text-xs">
                  {JSON.stringify(row, null, 2)}
                </pre>
              </details>
            </article>
          ),
        )}
      </CardContent>
    </Card>
  );
}
