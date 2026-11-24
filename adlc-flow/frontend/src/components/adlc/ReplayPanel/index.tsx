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
  createReplay,
  downloadReplay,
  listReplays,
  replayAction,
  replayCapabilities,
} from "@/controllers/API/replay";
import { verificationCandidates } from "@/controllers/API/verification";
import useAuthStore from "@/stores/authStore";
import type {
  ReplayCapabilities,
  ReplayCase,
  ReplayRead,
  ReplayScope,
} from "@/types/replay";
import type { VerificationCandidates } from "@/types/verification";
import TestProposalPanel from "../TestProposalPanel";
import ReplayInsights from "./insights";
import ReplayScreenshots from "./screenshots";

const field = "w-full rounded-md border bg-background p-2 text-sm";
const scalar = (v: unknown) =>
  v === null ||
  typeof v === "boolean" ||
  (typeof v === "string" && v.length <= 4096) ||
  (typeof v === "number" &&
    Number.isFinite(v) &&
    Math.abs(v) <= Number.MAX_SAFE_INTEGER);
const isDigest = (v: string) => /^sha256:[0-9a-f]{64}$/.test(v);
const configDigest =
  "sha256:d634ef15e33d6ab44ac44f2d62da5d80ae97e718da7e5222a3e83566f742e191";
const runnerDigest =
  "sha256:b181341587bdc60dde4be167d9504af960927cb173046cd26886bd27ae250803";
function junitSupported(row: ReplayRead) {
  const receipt = row.receipt!,
    report = row.report!;
  // Defence-in-depth for display. The backend's safe parser and authenticated
  // archive remain authoritative. Never render external XML as HTML.
  if (receipt.junit_xml.length > 32768 || receipt.junit_xml.includes("<!"))
    return false;
  const doc = new DOMParser().parseFromString(
    receipt.junit_xml,
    "application/xml",
  );
  const root = doc.documentElement;
  if (
    root.tagName !== "testsuite" ||
    root.attributes.length !== 5 ||
    root.getAttribute("name") !== "adlc-http-json-replay" ||
    root.getAttribute("tests") !== String(row.plan.cases.length) ||
    root.getAttribute("failures") !==
      String(report.checks.filter((c) => !c.passed).length) ||
    root.getAttribute("errors") !== "0" ||
    root.getAttribute("skipped") !== "0" ||
    root.children.length !== row.plan.cases.length
  )
    return false;
  return Array.from(root.children).every((node, i) => {
    if (
      node.tagName !== "testcase" ||
      node.attributes.length !== 2 ||
      node.getAttribute("classname") !== "http-json-fixture" ||
      node.getAttribute("name") !== row.plan.cases[i].case_id
    )
      return false;
    if (report.checks[i].passed) return node.children.length === 0;
    const failure = node.children[0];
    return (
      node.children.length === 1 &&
      failure.tagName === "failure" &&
      failure.attributes.length === 1 &&
      failure.getAttribute("type") === "AssertionError" &&
      failure.children.length === 0
    );
  });
}
function supported(row: ReplayRead, scope: ReplayScope) {
  try {
    const p = row.plan,
      r = row.receipt,
      report = row.report;
    if (
      p.schema_version !== "0.1" ||
      p.revision !== 1 ||
      p.profile_ref !== "verification-profile:http-json-replay/0.1.0" ||
      p.config_digest !== configDigest ||
      !isDigest(p.suite_digest) ||
      !isDigest(row.plan_digest) ||
      !isDigest(p.candidate.content_digest) ||
      p.heal !== false ||
      p.models !== false ||
      p.skip_policy !== "no-required-skips" ||
      p.target_profile_ref !== "target-profile:disposable-http-json/0.1.0" ||
      p.credential_ref !== "credential-profile:ephemeral-fixture/0.1.0" ||
      p.risk_class !== "read-only-non-production" ||
      !p.cases.length ||
      p.cases.length > 16 ||
      new Set(p.cases.map((c) => c.case_id)).size !== p.cases.length ||
      p.cases.some(
        (c) =>
          !scalar(c.expected) || c.method !== "GET" || c.path !== "/fixture",
      ) ||
      ("runId" in scope
        ? p.workflow_run_id !== scope.runId
        : p.candidate.source_session_id !== scope.sessionId) ||
      ![
        "DRAFT",
        "APPROVED",
        "RUNNING",
        "DISPATCH_UNCERTAIN",
        "CANCEL_REQUESTED",
        "CANCELLED",
        "NOT_VERIFIED",
        "READY_FOR_SUBMISSION",
        "SUBMITTED",
      ].includes(row.state) ||
      (row.state !== "DRAFT" && (!row.approved_at || !row.approved_by)) ||
      (row.state === "CANCELLED" &&
        (!row.cancel_requested_at || !row.cancelled_at)) ||
      (row.state === "CANCEL_REQUESTED" && !row.cancel_requested_at)
    )
      return false;
    if (!report)
      return !r && !["READY_FOR_SUBMISSION", "SUBMITTED"].includes(row.state);
    if (
      !r ||
      !["READY_FOR_SUBMISSION", "SUBMITTED"].includes(row.state) ||
      !row.evidence_digest ||
      r.schema_version !== "0.1" ||
      r.execution_id !== row.execution_id ||
      r.target_instance_id !== row.execution_id ||
      r.runner_ref !== "runner:adlc-http-json-replay/0.1.0" ||
      r.runner_digest !== runnerDigest ||
      r.provider !== "local-http-fixture" ||
      r.target_profile_ref !== p.target_profile_ref ||
      r.credential_ref !== p.credential_ref ||
      !/^http:\/\/127\.0\.0\.1:[1-9][0-9]{0,4}$/.test(r.target_origin) ||
      Number(r.target_origin.split(":").at(-1)) > 65535 ||
      r.target_released !== true ||
      r.heal !== false ||
      r.models_used !== false ||
      r.tests_run !== p.cases.length ||
      r.observations.length !== p.cases.length ||
      !isDigest(r.junit_digest) ||
      !r.junit_xml ||
      !Number.isFinite(Date.parse(r.started_at)) ||
      !Number.isFinite(Date.parse(r.completed_at)) ||
      Date.parse(r.completed_at) < Date.parse(r.started_at) ||
      report.schema_version !== "0.1" ||
      report.comparator_ref !== "validator:http-json-replay/0.1.0" ||
      report.natural_language_enforced !== false ||
      report.contract_fully_verified !== false ||
      report.application_verified !== false ||
      report.required_cases !== p.cases.length ||
      report.completed_cases !== p.cases.length ||
      report.checks.length !== p.cases.length ||
      report.plan_digest !== row.plan_digest ||
      r.plan_digest !== row.plan_digest ||
      report.candidate_digest !== p.candidate.content_digest ||
      r.candidate_digest !== p.candidate.content_digest ||
      report.suite_digest !== p.suite_digest ||
      r.suite_digest !== p.suite_digest ||
      report.config_digest !== p.config_digest ||
      r.config_digest !== p.config_digest ||
      report.junit_digest !== r.junit_digest
    )
      return false;
    if (
      !report.checks.every((c, i) => {
        const expected = p.cases[i],
          o = r.observations[i];
        const passed =
          o.found &&
          o.http_status === expected.expected_status &&
          o.observed === expected.expected;
        return (
          scalar(o.observed) &&
          typeof o.found === "boolean" &&
          (o.found || o.observed === null) &&
          c.case_id === expected.case_id &&
          o.case_id === expected.case_id &&
          c.pointer === expected.pointer &&
          o.pointer === expected.pointer &&
          c.expected === expected.expected &&
          c.observed === o.observed &&
          c.found === o.found &&
          c.expected_status === expected.expected_status &&
          c.observed_status === o.http_status &&
          o.response_digest === p.candidate.content_digest &&
          c.passed === passed &&
          o.outcome === (passed ? "PASS" : "FAIL")
        );
      })
    )
      return false;
    const failed = report.checks.some((c) => !c.passed);
    return (
      junitSupported(row) &&
      report.verdict === (failed ? "FAIL" : "PASS") &&
      (r.completion_mode === "process-exit"
        ? r.exit_code === (failed ? 1 : 0)
        : r.completion_mode === "durable-checkpoint" && r.exit_code === null)
    );
  } catch {
    return false;
  }
}
export { supported as isSupportedReplay };
function message(error: unknown) {
  const code = axios.isAxiosError(error)
    ? error.response?.data?.detail?.code
    : undefined;
  if (code === "VERIFICATION_CANDIDATE_STALE")
    return "The coding attempt changed. Create a successor suite for the current candidate; the existing evidence stays archived.";
  if (code === "VERIFICATION_IDEMPOTENCY_CONFLICT")
    return "This draft changed after a previous save. Refresh and create a new suite.";
  if (
    code === "CONTRACT_EXPLICIT_LOGIN_REQUIRED" ||
    code === "CONTRACT_USER_TOKEN_REQUIRED"
  )
    return "Explicit owner login is required. Auto-login and service tokens cannot approve a suite.";
  return "Replay could not be confirmed. Refresh or sign in again. No job is automatically retried and no PASS is available.";
}
type DraftCase = {
  rowKey: number;
  caseId: string;
  criterion: string;
  pointer: string;
  expected: string;
  status: string;
};
const draftCase = (n: number, criterion: string): DraftCase => ({
  rowKey: n,
  caseId: `case-${n}`,
  criterion,
  pointer: "/answer",
  expected: "42",
  status: "200",
});

export default function ReplayPanel({
  scope,
  readOnly = false,
}: {
  scope: ReplayScope;
  readOnly?: boolean;
}) {
  useUiLocale();
  const key = "runId" in scope ? scope.runId : scope.sessionId,
    isRun = "runId" in scope;
  const auth = useAuthStore((state) => state.isAuthenticated),
    autoLogin = useAuthStore((state) => state.autoLogin),
    userId = useAuthStore((state) => state.userData?.id);
  const identity = `${isRun ? "run" : "session"}:${key}:${auth}:${autoLogin}:${userId}:${readOnly}`;
  const current = useRef(identity);
  current.current = identity;
  const [caps, setCaps] = useState<ReplayCapabilities>();
  const [rows, setRows] = useState<ReplayRead[]>([]);
  const [loadedIdentity, setLoadedIdentity] = useState<string>();
  const [fresh, setFresh] = useState(false),
    [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState<string>(),
    [error, setError] = useState<string>(),
    [notice, setNotice] = useState<string>();
  const [reviewed, setReviewed] = useState<string>();
  const [options, setOptions] = useState<VerificationCandidates>();
  const [open, setOpen] = useState(false),
    [patchIndex, setPatchIndex] = useState(0),
    [contractIndex, setContractIndex] = useState(0);
  const [file, setFile] = useState(""),
    [cases, setCases] = useState<DraftCase[]>([]);
  const commandKey = useRef<string | undefined>(undefined);
  const nextCase = useRef(1);
  useEffect(() => {
    setOpen(false);
    setOptions(undefined);
    setReviewed(undefined);
    setBusy(undefined);
    setNotice(undefined);
    commandKey.current = undefined;
  }, [identity]);
  useEffect(() => {
    let active = true,
      timer: ReturnType<typeof setTimeout>;
    setRows([]);
    setCaps(undefined);
    setFresh(false);
    setError(undefined);
    const load = async () => {
      try {
        const [c, snapshot] = await Promise.all([
          replayCapabilities(),
          listReplays(isRun ? { runId: key } : { sessionId: key }),
        ]);
        if (!active) return;
        setCaps(c);
        setRows(snapshot);
        setLoadedIdentity(identity);
        setFresh(true);
        setError(undefined);
      } catch (e) {
        if (active) {
          setFresh(false);
          setRows([]);
          setError(message(e));
        }
      } finally {
        if (active) timer = setTimeout(() => void load(), 3000);
      }
    };
    if (auth) void load();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [identity, revision]);
  const human =
    !readOnly &&
    isRun &&
    auth &&
    !autoLogin &&
    loadedIdentity === identity &&
    caps?.enabled &&
    caps.human_actions_configured &&
    fresh &&
    !error;
  async function act(
    id: string,
    action: () => Promise<unknown>,
    success: string,
  ) {
    const captured = identity;
    setBusy(id);
    setNotice(undefined);
    try {
      await action();
      if (current.current === captured) {
        setNotice(success);
        setRevision((n) => n + 1);
      }
    } catch (e) {
      if (current.current === captured) {
        setError(message(e));
        setFresh(false);
      }
    } finally {
      if (current.current === captured) setBusy(undefined);
    }
  }
  async function openDraft() {
    const captured = identity;
    setBusy("draft");
    try {
      const result = await verificationCandidates(key);
      if (current.current !== captured) return;
      setOptions(result);
      setPatchIndex(0);
      setContractIndex(0);
      setFile(result.patches[0]?.files[0] ?? "");
      const node = result.contracts[0]?.document.nodes.find(
        (n) => n.acceptance_criteria.length,
      );
      setCases([draftCase(1, node ? `${node.node_id}:0` : "")]);
      nextCase.current = 2;
      commandKey.current = undefined;
      setOpen(true);
    } catch (e) {
      if (current.current === captured) setError(message(e));
    } finally {
      if (current.current === captured) setBusy(undefined);
    }
  }
  const contract = options?.contracts[contractIndex],
    patch = options?.patches[patchIndex];
  const edit = (index: number, update: Partial<DraftCase>) => {
    commandKey.current = undefined;
    setCases((cs) => cs.map((c, i) => (i === index ? { ...c, ...update } : c)));
  };

  const visibleRows = loadedIdentity === identity && auth ? rows : [];
  const validatedRows = visibleRows.filter((row) => supported(row, scope));
  return (
    <>
      <Card aria-label={translateUi("Frozen replay")} className="bg-background">
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle>{translateUi("Frozen replay · H6B")}</CardTitle>
            <Button
              variant="outline"
              size="sm"
              disabled={!!busy}
              onClick={() => setRevision((n) => n + 1)}
            >
              {translateUi("Refresh replay")}
            </Button>
          </div>
          <CardDescription>
            {translateUi(
              "Real HTTP requests against a disposable JSON fixture, then exact assertions and JUnit validation. This pilot does not run your project application or the TestForge backend.",
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="rounded-lg border border-dashed p-3 text-sm">
            <p className="font-medium">
              {translateUi("TestForge remote · blocked")}
            </p>
            <p className="mt-1 text-muted-foreground">
              {translateUi(
                "The supplied plugin is a client, not the broker. Backend source, reachability, authenticated suite/evidence transfer, idempotency, cancellation and no-model/no-heal routing need review before activation.",
              )}
            </p>
          </div>
          {error && (
            <p role="alert" className="text-destructive">
              {error}
            </p>
          )}
          {notice && <p role="status">{notice}</p>}
          {caps && !caps.enabled && (
            <p className="text-sm text-muted-foreground">
              {translateUi(
                "Frozen replay is not enabled. Retained results remain readable; the protected H6B worker is opt-in.",
              )}
            </p>
          )}
          {caps?.enabled && !caps.worker_ready && (
            <p role="status">
              {translateUi(
                "Local replay worker not ready. Approvals do not start an unavailable runner.",
              )}
            </p>
          )}
          {!readOnly &&
            (!auth ||
              autoLogin ||
              (caps && !caps.human_actions_configured)) && (
              <p role="status">
                {translateUi(
                  "Sign in explicitly as the ADLC owner to author, approve, run, cancel or submit a suite.",
                )}
              </p>
            )}
          {readOnly && (
            <p className="text-sm text-muted-foreground">
              {translateUi(
                "Read-only Harness projection · human decisions stay in ADLC.",
              )}
            </p>
          )}
          {!rows.length && fresh && (
            <p className="text-sm text-muted-foreground">
              {translateUi(
                "No frozen replay suite or evidence for this source yet.",
              )}
            </p>
          )}
          {isRun && !readOnly && (
            <Button
              disabled={!human || !!busy}
              onClick={() => void openDraft()}
            >
              {translateUi("Create frozen replay suite")}
            </Button>
          )}
          {open && human && options && (
            <form
              className="space-y-3 rounded-lg border p-4"
              aria-label={translateUi("Create frozen replay suite")}
              onSubmit={(event) => {
                event.preventDefault();
                if (!patch || !contract) return;
                let parsed: ReplayCase[];
                try {
                  parsed = cases.map((c) => {
                    const expected = JSON.parse(c.expected),
                      [node, index] = c.criterion.split(":");
                    if (
                      !scalar(expected) ||
                      !/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$/.test(c.caseId) ||
                      !/^(?:|\/(?:[^~]|~[01])*)$/.test(c.pointer) ||
                      c.pointer.length > 512 ||
                      !node ||
                      !Number.isInteger(Number(index)) ||
                      !/^\d{3}$/.test(c.status) ||
                      Number(c.status) < 100 ||
                      Number(c.status) > 599
                    )
                      throw new Error();
                    return {
                      case_id: c.caseId,
                      pointer: c.pointer,
                      expected,
                      criterion_node_id: node,
                      criterion_index: Number(index),
                      method: "GET",
                      path: "/fixture",
                      expected_status: Number(c.status),
                    };
                  });
                  if (
                    !parsed.length ||
                    parsed.length > 16 ||
                    new Set(parsed.map((c) => c.case_id)).size !==
                      parsed.length ||
                    new Set(
                      parsed.map(
                        (c) => `${c.criterion_node_id}:${c.criterion_index}`,
                      ),
                    ).size !== parsed.length
                  )
                    throw new Error();
                } catch {
                  setNotice(
                    translateUi(
                      "Use 1–16 unique case IDs and mapped criteria, valid JSON pointers, HTTP statuses and bounded JSON scalar expectations.",
                    ),
                  );
                  return;
                }
                commandKey.current ??= crypto.randomUUID();
                void act(
                  "save",
                  async () => {
                    await createReplay(key, {
                      source_task_id: patch.source_task_id,
                      artifact_id: patch.artifact_id,
                      contract_reference: contract.reference,
                      file,
                      cases: parsed,
                      timeout_seconds: 15,
                      idempotency_key: commandKey.current!,
                    });
                    if (current.current === identity) setOpen(false);
                  },
                  "Frozen suite saved as a draft. Review its exact digest before approval.",
                );
              }}
            >
              <label className="block text-sm">
                {translateUi("Captured candidate")}
                <select
                  className={field}
                  value={patchIndex}
                  onChange={(e) => {
                    const i = Number(e.target.value);
                    setPatchIndex(i);
                    setFile(options.patches[i]?.files[0] ?? "");
                    commandKey.current = undefined;
                  }}
                >
                  {options.patches.map((p, i) => (
                    <option key={p.artifact_id} value={i}>
                      {p.task_name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-sm">
                {translateUi("Frozen JSON file")}
                <select
                  className={field}
                  value={file}
                  onChange={(e) => {
                    setFile(e.target.value);
                    commandKey.current = undefined;
                  }}
                >
                  {patch?.files.map((f) => (
                    <option key={f}>{f}</option>
                  ))}
                </select>
              </label>
              <label className="block text-sm">
                {translateUi("Approved contract")}
                <select
                  className={field}
                  value={contractIndex}
                  onChange={(e) => {
                    setContractIndex(Number(e.target.value));
                    setCases((cs) => cs.map((c) => ({ ...c, criterion: "" })));
                    commandKey.current = undefined;
                  }}
                >
                  {options.contracts.map((c, i) => (
                    <option key={c.reference.contract_id} value={i}>
                      {c.document.title} {translateUi("· revision")}{" "}
                      {c.reference.revision}
                    </option>
                  ))}
                </select>
              </label>
              <p className="text-xs text-muted-foreground">
                {translateUi(
                  "Target and ephemeral test account are allocated by the protected runner. GET /fixture only · heal OFF · models OFF · every case required. No arbitrary URLs or credentials.",
                )}
              </p>
              {cases.map((c, i) => (
                <fieldset
                  key={c.rowKey}
                  className="space-y-2 rounded-md border p-3"
                >
                  <legend className="px-1 text-sm">
                    {translateUi("Case")} {i + 1}
                  </legend>
                  <label className="block text-sm">
                    {translateUi("Case ID")}
                    <input
                      className={field}
                      value={c.caseId}
                      onChange={(e) => edit(i, { caseId: e.target.value })}
                    />
                  </label>
                  <label className="block text-sm">
                    {translateUi("Contract criterion")}
                    <select
                      className={field}
                      value={c.criterion}
                      onChange={(e) => edit(i, { criterion: e.target.value })}
                    >
                      <option value="">
                        {translateUi("Select a required criterion")}
                      </option>
                      {contract?.document.nodes.flatMap((n) =>
                        n.acceptance_criteria.map((text, index) => (
                          <option
                            key={`${n.node_id}:${index}`}
                            value={`${n.node_id}:${index}`}
                          >
                            {n.title}: {text.description}
                          </option>
                        )),
                      )}
                    </select>
                  </label>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <label className="block text-sm">
                      {translateUi("JSON pointer")}
                      <input
                        className={field}
                        value={c.pointer}
                        onChange={(e) => edit(i, { pointer: e.target.value })}
                      />
                    </label>
                    <label className="block text-sm">
                      {translateUi("Expected JSON scalar")}
                      <input
                        className={field}
                        value={c.expected}
                        onChange={(e) => edit(i, { expected: e.target.value })}
                      />
                    </label>
                  </div>
                  <label className="block text-sm">
                    {translateUi("Expected HTTP status")}
                    <input
                      className={field}
                      value={formatUiStatus(c.status)}
                      onChange={(e) => edit(i, { status: e.target.value })}
                    />
                  </label>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={cases.length === 1}
                    onClick={() => {
                      setCases((cs) => cs.filter((_, index) => i !== index));
                      commandKey.current = undefined;
                    }}
                  >
                    {translateUi("Remove case")} {i + 1}
                  </Button>
                </fieldset>
              ))}
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  disabled={cases.length >= 16}
                  onClick={() => {
                    setCases((cs) => [
                      ...cs,
                      draftCase(nextCase.current++, ""),
                    ]);
                    commandKey.current = undefined;
                  }}
                >
                  {translateUi("Add required case")}
                </Button>
                <Button
                  type="submit"
                  disabled={!!busy || !patch || !contract || !file}
                >
                  {translateUi("Save frozen suite")}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setOpen(false)}
                >
                  {translateUi("Close draft")}
                </Button>
              </div>
            </form>
          )}
          <ReplayInsights rows={validatedRows} />
          {visibleRows.map((row) => {
            if (!supported(row, scope))
              return (
                <div
                  key={row.plan?.plan_id ?? "unsupported"}
                  className="rounded-lg border p-3"
                >
                  <p>
                    {translateUi(
                      "Unsupported or incomplete replay evidence · no verdict or actions.",
                    )}
                  </p>
                  <pre className="mt-2 max-h-72 overflow-auto text-xs">
                    {JSON.stringify(row, null, 2).slice(0, 131072)}
                  </pre>
                </div>
              );
            const plan = row.plan,
              id = plan.plan_id,
              canAct = human && !busy;
            const action = (
              op: Parameters<typeof replayAction>[2],
              success: string,
            ) => void act(id, () => replayAction(key, row, op), success);
            return (
              <article
                key={id}
                id={`replay-${id}`}
                className="space-y-3 rounded-lg border p-4"
              >
                <div className="flex flex-wrap gap-2">
                  <Badge variant="secondary">{formatUiStatus(row.state)}</Badge>
                  {row.report && (
                    <Badge
                      variant={
                        row.report.verdict === "FAIL"
                          ? "destructive"
                          : "successStatic"
                      }
                    >
                      {formatUiStatus(row.report.verdict)}
                    </Badge>
                  )}
                </div>
                <p className="break-all text-sm font-medium">
                  {plan.candidate.file} · {plan.cases.length}{" "}
                  {translateUi("required cases")}
                </p>
                <dl className="grid gap-1 text-xs text-muted-foreground">
                  <div className="break-all">
                    {translateUi("Plan:")} {row.plan_digest}
                  </div>
                  <div className="break-all">
                    {translateUi("Suite:")} {plan.suite_digest}
                  </div>
                  <div className="break-all">
                    {translateUi("Candidate:")} {plan.candidate.content_digest}
                  </div>
                  <div className="break-all">
                    {translateUi("Config:")} {plan.config_digest}
                  </div>
                  <div>
                    {translateUi(
                      "GET /fixture · disposable authenticated loopback target · heal OFF · models OFF",
                    )}
                  </div>
                </dl>
                {row.error_code && (
                  <p
                    role="status"
                    className="break-all text-sm text-destructive"
                  >
                    {row.error_code}{" "}
                    {translateUi(
                      "· not verified. Observe the existing job; do not resubmit it.",
                    )}
                  </p>
                )}
                {row.state === "CANCEL_REQUESTED" && (
                  <p role="status">
                    {translateUi(
                      "Cancellation requested, not confirmed. No PASS/FAIL verdict and no replacement job. A restart never kills an unproven stored process ID.",
                    )}
                  </p>
                )}
                {row.state === "CANCELLED" && (
                  <p role="status">
                    {translateUi(
                      "Cancelled · confirmed stopped (or never dispatched). No verification verdict; retained history is preserved.",
                    )}
                  </p>
                )}
                {row.receipt && row.report && (
                  <>
                    <p className="text-sm">
                      {row.state === "SUBMITTED"
                        ? translateUi("Archived replay report")
                        : translateUi("Prepared replay evidence preview")}{" "}
                      · {row.report.completed_cases}/{row.report.required_cases}{" "}
                      {translateUi(
                        "required cases completed · target released.",
                      )}
                    </p>
                    <p className="break-all text-xs text-muted-foreground">
                      {translateUi("Instance:")}{" "}
                      {row.receipt.target_instance_id} ·{" "}
                      {row.receipt.target_origin} (closed).{" "}
                      {row.receipt.completion_mode === "durable-checkpoint"
                        ? translateUi(
                            "Recovered completed checkpoint; OS exit was not observed.",
                          )
                        : translateUi("Observed runner exit {{value0}}.", {
                            value0: row.receipt.exit_code,
                          })}{" "}
                      {translateUi(
                        "This is fixture coverage, not application verification.",
                      )}
                    </p>
                    <div className="overflow-x-auto">
                      <table className="w-full min-w-[520px] text-left text-sm">
                        <thead>
                          <tr>
                            <th className="p-2">
                              {translateUi("Case / pointer")}
                            </th>
                            <th className="p-2">{translateUi("Expected")}</th>
                            <th className="p-2">{translateUi("Observed")}</th>
                            <th className="p-2">{translateUi("Result")}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {row.report.checks.map((c) => (
                            <tr key={c.case_id} className="border-t">
                              <td className="p-2">
                                {c.case_id}
                                <code className="block text-xs">
                                  {c.pointer || "(root)"}
                                </code>
                                <span className="block break-all text-xs text-muted-foreground">
                                  {translateUi("Criterion")}{" "}
                                  {
                                    plan.cases.find(
                                      (item) => item.case_id === c.case_id,
                                    )?.criterion_node_id
                                  }
                                  :
                                  {(plan.cases.find(
                                    (item) => item.case_id === c.case_id,
                                  )?.criterion_index ?? 0) + 1}
                                </span>
                              </td>
                              <td className="max-w-60 break-all p-2">
                                <code>{JSON.stringify(c.expected)}</code>
                                <span className="block text-xs">
                                  HTTP {c.expected_status}
                                </span>
                              </td>
                              <td className="max-w-60 break-all p-2">
                                <code>
                                  {c.found
                                    ? JSON.stringify(c.observed)
                                    : translateUi("Missing pointer")}
                                </code>
                                <span className="block text-xs">
                                  HTTP {c.observed_status}
                                </span>
                              </td>
                              <td className="p-2">
                                {c.passed ? "PASS" : "FAIL"}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <details>
                      <summary className="cursor-pointer text-sm">
                        {translateUi(
                          "JUnit evidence · checksummed, no skipped required tests",
                        )}
                      </summary>
                      <pre className="mt-2 max-h-60 overflow-auto rounded border p-2 text-xs">
                        {row.receipt.junit_xml}
                      </pre>
                    </details>
                    <div className="flex flex-wrap gap-2">
                      {(["json", "junit"] as const).map((kind) => (
                        <Button
                          key={kind}
                          variant="outline"
                          size="sm"
                          disabled={!fresh || !!busy}
                          onClick={() =>
                            void act(
                              id,
                              () =>
                                downloadReplay(plan.workflow_run_id, row, kind),
                              "Checksummed replay evidence downloaded.",
                            )
                          }
                        >
                          {translateUi("Download")}{" "}
                          {kind === "json"
                            ? translateUi("replay JSON")
                            : translateUi("JUnit XML")}
                        </Button>
                      ))}
                    </div>
                    <ReplayScreenshots
                      key={`${id}:${identity}`}
                      row={row}
                      identity={`${identity}:${id}`}
                      human={!!human}
                    />
                  </>
                )}
                <details>
                  <summary className="cursor-pointer text-sm">
                    {translateUi("Frozen suite & diagnostics")}
                  </summary>
                  <pre className="mt-2 max-h-72 overflow-auto rounded border p-2 text-xs">
                    {JSON.stringify(row, null, 2)}
                  </pre>
                </details>
                {human && row.state === "DRAFT" && (
                  <label className="flex gap-2 text-sm">
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
                      "I reviewed this exact suite, mapped criteria, candidate, target and expected values.",
                    )}
                  </label>
                )}
                {!readOnly && (
                  <div className="flex flex-wrap gap-2">
                    {row.state === "DRAFT" && (
                      <Button
                        disabled={!canAct || reviewed !== row.plan_digest}
                        onClick={() =>
                          action(
                            "approve",
                            "Exact frozen suite approved. Execution and Submit are separate.",
                          )
                        }
                      >
                        {translateUi("Approve exact replay suite")}
                      </Button>
                    )}
                    {row.state === "APPROVED" && (
                      <Button
                        disabled={!canAct || !caps?.worker_ready}
                        onClick={() =>
                          action(
                            "execute",
                            "Replay intent recorded. Only this execution will be observed; no automatic retry.",
                          )
                        }
                      >
                        {translateUi("Run approved replay")}
                      </Button>
                    )}
                    {[
                      "RUNNING",
                      "DISPATCH_UNCERTAIN",
                      "CANCEL_REQUESTED",
                    ].includes(row.state) && (
                      <Button
                        variant="outline"
                        disabled={!canAct}
                        onClick={() =>
                          action(
                            "reconcile",
                            "Existing execution observed; no new job created.",
                          )
                        }
                      >
                        {translateUi("Observe existing replay")}
                      </Button>
                    )}
                    {["APPROVED", "RUNNING", "DISPATCH_UNCERTAIN"].includes(
                      row.state,
                    ) && (
                      <Button
                        variant="outline"
                        disabled={!canAct}
                        onClick={() =>
                          action(
                            "cancel",
                            "Cancellation intent recorded. Check its confirmed status before assuming the target stopped.",
                          )
                        }
                      >
                        {translateUi("Cancel replay")}
                      </Button>
                    )}
                    {row.state === "READY_FOR_SUBMISSION" && (
                      <Button
                        disabled={!canAct}
                        onClick={() =>
                          action(
                            "submit",
                            "Replay report archived by explicit owner submission. No deployment or coding result was changed.",
                          )
                        }
                      >
                        {translateUi("Submit replay report")}
                      </Button>
                    )}
                  </div>
                )}
              </article>
            );
          })}
        </CardContent>
      </Card>
      <TestProposalPanel
        key={identity}
        scope={scope}
        replays={validatedRows}
        readOnly={readOnly}
        onMaterialized={() => setRevision((n) => n + 1)}
      />
    </>
  );
}
