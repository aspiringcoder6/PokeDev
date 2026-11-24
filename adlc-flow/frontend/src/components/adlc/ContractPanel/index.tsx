import { translateUi, useUiLocale } from "@/i18n/ui";
import axios from "axios";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  approveContract,
  downloadContract,
  forkContract,
  getContractViewerCapabilities,
  listContracts,
  readContract,
} from "@/controllers/API/contracts";
import useAuthStore from "@/stores/authStore";
import type {
  ContractRead,
  ContractViewerCapabilities,
} from "@/types/contracts";
import ContractViewer from "../ContractViewer";
import { isSupportedContract, referenceKey } from "../ContractViewer/model";
import { useTranslation } from "react-i18next";
import i18n from "@/i18n";

type Scope =
  | { runId: string; sessionId?: never }
  | { sessionId: string; runId?: never };
const buttonStyle =
  "rounded-md border px-3 py-2 text-sm hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50";
function message(error: unknown) {
  const code = axios.isAxiosError(error)
    ? error.response?.data?.detail?.code
    : undefined;
  if (code === "REVISION_CONFLICT") return i18n.t("adlc.run.revisionChanged");
  if (
    code === "CONTRACT_EXPLICIT_LOGIN_REQUIRED" ||
    code === "CONTRACT_USER_TOKEN_REQUIRED"
  )
    return i18n.t("adlc.ct.signInExplicit");
  return i18n.t("adlc.ct.stateUnconfirmed");
}

export default function ContractPanel({
  scope,
  readOnly = false,
}: {
  scope: Scope;
  readOnly?: boolean;
}) {
  const { t } = useTranslation();
  useUiLocale();
  const scopeKey = scope.runId ?? scope.sessionId;
  const currentScope = useRef(scopeKey);
  currentScope.current = scopeKey;
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const autoLogin = useAuthStore((state) => state.autoLogin);
  const [capabilities, setCapabilities] =
    useState<ContractViewerCapabilities>();
  const [heads, setHeads] = useState<ContractRead[]>([]);
  const [selectedId, setSelectedId] = useState<string>();
  const [historical, setHistorical] = useState<ContractRead>();
  const [historyLoading, setHistoryLoading] = useState(false);
  const historySequence = useRef(0);
  const [enabled, setEnabled] = useState<boolean>();
  const [fresh, setFresh] = useState(false);
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const [reviewed, setReviewed] = useState<string>();
  const [acting, setActing] = useState<string>();
  const [refresh, setRefresh] = useState(0);
  const retry = useRef<
    { operation: string; reference: string; key: string } | undefined
  >(undefined);

  useEffect(() => {
    setHeads([]);
    setSelectedId(undefined);
    setHistorical(undefined);
    setReviewed(undefined);
    setNotice(undefined);
    setError(undefined);
    setEnabled(undefined);
    setCapabilities(undefined);
    setFresh(false);
    setHistoryLoading(false);
    setActing(undefined);
    historySequence.current++;
    retry.current = undefined;
  }, [scopeKey]);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      let disabled = false;
      let featureRead = false;
      try {
        const capability = await getContractViewerCapabilities();
        featureRead = true;
        if (!active) return;
        setCapabilities(capability);
        setEnabled(true);
        const snapshot = await listContracts(scope);
        if (!active) return;
        setHeads(snapshot);
        setFresh(true);
        setError(undefined);
      } catch (loadError) {
        if (!active) return;
        setFresh(false);
        if (
          axios.isAxiosError(loadError) &&
          loadError.response?.status === 404 &&
          !featureRead
        ) {
          // Default-off hosts should not show an error or keep polling a missing feature.
          setEnabled(false);
          disabled = true;
        } else {
          setEnabled(true);
          setError(message(loadError));
        }
      } finally {
        if (active && !disabled) timer = setTimeout(() => void load(), 4000);
      }
    };
    void load();
    return () => {
      active = false;
      clearTimeout(timer);
    };
    // A refresh starts a new poll generation. Old completions cannot replace new state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeKey, refresh]);

  const head =
    heads.find((item) => item.reference.contract_id === selectedId) ?? heads[0];
  const shown = historical ?? head;
  const supported = !!shown && isSupportedContract(shown);
  const isCurrent =
    !!head &&
    !!shown &&
    referenceKey(head.reference) === referenceKey(shown.reference);
  const canAct =
    !readOnly &&
    !!scope.runId &&
    fresh &&
    isCurrent &&
    supported &&
    !historyLoading &&
    !!capabilities?.human_actions_configured &&
    isAuthenticated &&
    autoLogin === false;

  async function chooseRevision(revision: number) {
    historySequence.current++;
    const sequence = historySequence.current;
    const key = scopeKey;
    setReviewed(undefined);
    setHistorical(undefined);
    if (!head || revision === head.reference.revision) {
      setHistoryLoading(false);
      return;
    }
    setHistoryLoading(true);
    try {
      const snapshot = await readContract(
        head.binding.workflow_run_id,
        head.reference.contract_id,
        revision,
      );
      if (sequence === historySequence.current && currentScope.current === key)
        setHistorical(snapshot);
    } catch (loadError) {
      if (
        sequence === historySequence.current &&
        currentScope.current === key
      ) {
        setError(message(loadError));
        setFresh(false);
      }
    } finally {
      if (sequence === historySequence.current && currentScope.current === key)
        setHistoryLoading(false);
    }
  }

  async function act(operation: "approve" | "fork" | "download") {
    if (!shown || (operation !== "download" && !canAct)) return;
    const key = scopeKey;
    const reference = shown.reference;
    setActing(operation);
    setNotice(undefined);
    try {
      if (operation === "download")
        await downloadContract(shown.binding.workflow_run_id, reference);
      else {
        const identity = referenceKey(reference);
        if (
          retry.current?.operation !== operation ||
          retry.current.reference !== identity
        ) {
          retry.current = {
            operation,
            reference: identity,
            key: crypto.randomUUID(),
          };
        }
        const result = await (operation === "approve"
          ? approveContract
          : forkContract)(
          shown.binding.workflow_run_id,
          reference,
          retry.current.key,
        );
        if (currentScope.current !== key) return;
        setNotice(
          operation === "approve"
            ? translateUi(
                "This exact contract revision is approved and locked. The run was not submitted or resumed.",
              )
            : translateUi(
                "A new draft was created. The original approved contract is unchanged; the draft needs validation and approval again.",
              ),
        );
        setSelectedId(result.contract.reference.contract_id);
        setHistorical(undefined);
        setReviewed(undefined);
        setFresh(false);
        setRefresh((value) => value + 1);
      }
    } catch (actionError) {
      if (currentScope.current === key) {
        setError(message(actionError));
        setFresh(false);
        setReviewed(undefined);
      }
    } finally {
      if (currentScope.current === key) setActing(undefined);
    }
  }

  if (enabled === false || enabled === undefined) return null;
  return (
    <section
      aria-label={translateUi("Contract documents")}
      className="rounded-xl border bg-background p-5"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">
            {translateUi("Contract documents")}
          </h2>
          <p className="text-xs text-muted-foreground">
            {translateUi(
              "Stored by ADLC · shared read-only Skilltree renderer",
            )}
          </p>
        </div>
        <button
          className={buttonStyle}
          type="button"
          onClick={() => {
            setFresh(false);
            setRefresh((value) => value + 1);
          }}
        >
          {translateUi("Refresh contracts")}
        </button>
      </div>
      {error && (
        <p
          role="alert"
          className="mt-3 rounded-md border border-destructive/40 p-3 text-sm"
        >
          {error}
        </p>
      )}
      {notice && (
        <p
          role="status"
          className="mt-3 rounded-md border border-accent-emerald p-3 text-sm"
        >
          {notice}
        </p>
      )}
      {!shown ? (
        <p className="mt-5 text-sm text-muted-foreground">
          {translateUi("No contracts have been authored for this")}{" "}
          {scope.sessionId ? "session" : "run"} yet.
        </p>
      ) : (
        <>
          <div className="my-4 flex flex-wrap items-center gap-3">
            <label className="text-xs">
              {translateUi("Document")}{" "}
              <select
                aria-label={translateUi("Contract document")}
                className="ml-2 max-w-full rounded border bg-background p-2"
                value={head?.reference.contract_id}
                onChange={(event) => {
                  setSelectedId(event.target.value);
                  setHistorical(undefined);
                  setReviewed(undefined);
                  historySequence.current++;
                  setHistoryLoading(false);
                }}
              >
                {heads.map((item) => (
                  <option
                    key={item.reference.contract_id}
                    value={item.reference.contract_id}
                  >
                    {item.document.title} ·{" "}
                    {item.reference.contract_id.slice(0, 8)}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs">
              {translateUi("Revision")}{" "}
              <select
                aria-label={translateUi("Contract revision")}
                className="ml-2 rounded border bg-background p-2"
                disabled={historyLoading || !fresh}
                value={shown.reference.revision}
                onChange={(event) =>
                  void chooseRevision(Number(event.target.value))
                }
              >
                {Array.from(
                  { length: head?.reference.revision ?? 0 },
                  (_, index) => index + 1,
                )
                  .reverse()
                  .map((revision) => (
                    <option key={revision} value={revision}>
                      {revision}
                      {revision === head?.reference.revision
                        ? t("adlc.ct.currentSuffix")
                        : t("adlc.ct.historicalSuffix")}
                    </option>
                  ))}
              </select>
            </label>
            <button
              type="button"
              className={buttonStyle}
              disabled={!fresh || !!acting || historyLoading || !supported}
              onClick={() => void act("download")}
            >
              {translateUi("Download exact JSON")}
            </button>
          </div>
          {!isCurrent && (
            <p role="status" className="mb-4 text-sm text-muted-foreground">
              {translateUi(
                "Historical revision — review actions are unavailable. Current head is revision",
              )}
              {head?.reference.revision}.
            </p>
          )}
          {historyLoading ? (
            <p role="status">{translateUi("Loading historical revision…")}</p>
          ) : (
            <ContractViewer
              key={referenceKey(shown.reference)}
              contract={shown}
            />
          )}
          <div className="mt-5 border-t pt-4">
            {readOnly ? (
              <p className="text-sm">
                {translateUi("Read-only Harness view.")}{" "}
                <Link
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline"
                  to={`/runs/${shown.binding.workflow_run_id}/`}
                >
                  {translateUi("Review and approve in ADLC")}
                </Link>
                {t("adlc.ct.signInThere")}
              </p>
            ) : (
              <>
                {!canAct && (
                  <p className="mb-3 text-xs text-muted-foreground">
                    {translateUi(
                      "Actions require a current supported revision, a successful refresh, and explicit ADLC login with auto-login disabled.",
                    )}
                  </p>
                )}
                {shown.status === "VALIDATED" && (
                  <label className="mb-3 flex items-start gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={reviewed === referenceKey(shown.reference)}
                      disabled={!canAct || !!acting}
                      onChange={(event) =>
                        setReviewed(
                          event.target.checked
                            ? referenceKey(shown.reference)
                            : undefined,
                        )
                      }
                    />
                    <span>
                      {translateUi("I reviewed revision")}{" "}
                      {shown.reference.revision}{" "}
                      {translateUi(
                        "and its exact digest. Approve the contract, not execution or run submission.",
                      )}
                    </span>
                  </label>
                )}
                <div className="flex gap-2">
                  {shown.status === "VALIDATED" && (
                    <button
                      className={buttonStyle}
                      type="button"
                      disabled={
                        !canAct ||
                        reviewed !== referenceKey(shown.reference) ||
                        !!acting
                      }
                      onClick={() => void act("approve")}
                    >
                      {acting === "approve"
                        ? translateUi("Approving…")
                        : translateUi("Approve exact contract")}
                    </button>
                  )}
                  {shown.status === "APPROVED" && (
                    <button
                      className={buttonStyle}
                      type="button"
                      disabled={!canAct || !!acting}
                      onClick={() => void act("fork")}
                    >
                      {acting === "fork"
                        ? translateUi("Creating draft…")
                        : translateUi("Fork new draft")}
                    </button>
                  )}
                  {shown.status === "DRAFT" && (
                    <p className="text-sm text-muted-foreground">
                      {translateUi(
                        "Draft — use the authoring tools to edit and validate before human approval.",
                      )}
                    </p>
                  )}
                </div>
              </>
            )}
          </div>
        </>
      )}
    </section>
  );
}
