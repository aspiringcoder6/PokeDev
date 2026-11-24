import { translateUi, useUiLocale, formatUiStatus } from "@/i18n/ui";
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
  listTestProposals,
  testExtensionCapabilities,
  testProposalAction,
  testProposalTool,
} from "@/controllers/API/test-extensions";
import useAuthStore from "@/stores/authStore";
import type { ReplayCase, ReplayRead, ReplayScope } from "@/types/replay";
import type {
  ExtensionCapabilities,
  PerformanceBudget,
  ProposalCommand,
  ProposalRead,
  TestPermissions,
  TestProposal,
} from "@/types/test-extensions";

export const fixturePermissions: TestPermissions = {
  target_profile_ref: "target-profile:disposable-http-json/0.1.0",
  credential_ref: "credential-profile:ephemeral-fixture/0.1.0",
  environment: "non-production",
  data_scope: "synthetic-run-owned-only",
  allowed_methods: ["GET"],
  allowed_paths: ["/fixture"],
  network_scope: "allocated-loopback-target-only",
  cleanup: "release-owned-target",
  cancellation: "confirmed-worker-cancel",
  max_duration_seconds: 15,
};
const defaultBudget: PerformanceBudget = {
  virtual_users: 2,
  duration_seconds: 10,
  requests_per_second: 2,
  max_requests: 20,
  p95_latency_ms_max: 500,
  failed_requests_max: 0,
};
const isDigest = (v: unknown) =>
  typeof v === "string" && /^sha256:[0-9a-f]{64}$/.test(v);
const scalar = (v: unknown) =>
  v === null ||
  typeof v === "boolean" ||
  (typeof v === "string" && v.length <= 4096) ||
  (typeof v === "number" &&
    Number.isFinite(v) &&
    Math.abs(v) <= Number.MAX_SAFE_INTEGER);
const integer = (v: unknown, min: number, max: number) =>
  typeof v === "number" && Number.isInteger(v) && v >= min && v <= max;
const identityText = (v: unknown) =>
  typeof v === "string" && /^[A-Za-z0-9._-]{1,255}$/.test(v);
export function supportedProposal(row: ProposalRead, scope: ReplayScope) {
  try {
    const d = row.document,
      r = row.reference,
      s = d.source,
      p = d.permissions,
      b = d.performance;
    if (
      d.schema_version !== "0.1" ||
      d.profile_ref !== "test-extension-profile:proposals/0.1.0" ||
      d.executable !== false ||
      d.verification_evidence !== false ||
      d.models_used !== false ||
      d.heal !== false ||
      r.proposal_id !== d.proposal_id ||
      !identityText(d.proposal_id) ||
      !identityText(s.plan_id) ||
      !identityText(s.project_id) ||
      !identityText(s.workflow_run_id) ||
      !identityText(s.source_session_id) ||
      !identityText(s.contract_reference.contract_id) ||
      (d.authoring_session_id !== null &&
        !identityText(d.authoring_session_id)) ||
      r.revision !== d.revision ||
      !integer(d.revision, 1, 100) ||
      !isDigest(r.document_digest) ||
      !["suite-revision", "exploration", "performance"].includes(d.kind) ||
      !["DRAFT", "READY_FOR_REVIEW", "APPROVED", "MATERIALIZED"].includes(
        row.state,
      ) ||
      typeof d.title !== "string" ||
      !d.title.length ||
      d.title.length > 120 ||
      typeof d.rationale !== "string" ||
      !d.rationale.length ||
      d.rationale.length > 2000 ||
      !isDigest(s.plan_digest) ||
      !isDigest(s.suite_digest) ||
      !isDigest(s.candidate_digest) ||
      !isDigest(s.contract_reference.content_digest) ||
      s.contract_reference.schema_ref !==
        "adlc://schemas/skilltree-contract/0.1" ||
      !integer(s.contract_reference.revision, 1, 10000) ||
      ("runId" in scope
        ? s.workflow_run_id !== scope.runId
        : ![s.source_session_id, d.authoring_session_id].includes(
            scope.sessionId,
          )) ||
      !Array.isArray(d.cases) ||
      d.cases.length > 16 ||
      new Set(d.cases.map((c) => c.case_id)).size !== d.cases.length ||
      new Set(d.cases.map((c) => `${c.criterion_node_id}:${c.criterion_index}`))
        .size !== d.cases.length ||
      d.cases.some(
        (c) =>
          !scalar(c.expected) ||
          !/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(c.case_id) ||
          c.method !== "GET" ||
          c.path !== "/fixture" ||
          !integer(c.expected_status, 100, 599) ||
          !integer(c.criterion_index, 0, 15) ||
          !identityText(c.criterion_node_id) ||
          typeof c.pointer !== "string" ||
          c.pointer.length > 512 ||
          !/^(?:|\/(?:[^~]|~[01])*)$/.test(c.pointer),
      ) ||
      !Number.isFinite(Date.parse(row.created_at)) ||
      (d.revision === 1
        ? d.parent_reference !== null
        : !d.parent_reference ||
          d.parent_reference.revision !== d.revision - 1 ||
          !identityText(d.parent_reference.proposal_id) ||
          !isDigest(d.parent_reference.document_digest)) ||
      (["APPROVED", "MATERIALIZED"].includes(row.state)
        ? !identityText(row.approved_by) ||
          typeof row.approved_at !== "string" ||
          !Number.isFinite(Date.parse(row.approved_at))
        : row.approved_by !== null || row.approved_at !== null) ||
      (row.state === "MATERIALIZED"
        ? !identityText(row.materialized_plan_id) || d.kind !== "suite-revision"
        : row.materialized_plan_id !== null) ||
      (row.state !== "DRAFT" &&
        (!p || !d.cases.length || (d.kind === "performance" && !b)))
    )
      return false;
    if (
      p &&
      (p.target_profile_ref !== fixturePermissions.target_profile_ref ||
        p.credential_ref !== fixturePermissions.credential_ref ||
        p.environment !== "non-production" ||
        p.data_scope !== "synthetic-run-owned-only" ||
        p.network_scope !== "allocated-loopback-target-only" ||
        p.cleanup !== "release-owned-target" ||
        p.cancellation !== "confirmed-worker-cancel" ||
        JSON.stringify(p.allowed_methods) !== '["GET"]' ||
        JSON.stringify(p.allowed_paths) !== '["/fixture"]' ||
        !integer(p.max_duration_seconds, 1, 60))
    )
      return false;
    if (
      b &&
      (d.kind !== "performance" ||
        !integer(b.virtual_users, 1, 5) ||
        !integer(b.duration_seconds, 1, 30) ||
        !integer(b.requests_per_second, 1, 5) ||
        !integer(b.max_requests, 1, 100) ||
        !integer(b.p95_latency_ms_max, 1, 10000) ||
        !integer(b.failed_requests_max, 0, 10) ||
        b.duration_seconds * b.requests_per_second > b.max_requests ||
        (p && b.duration_seconds > p.max_duration_seconds))
    )
      return false;
    return true;
  } catch {
    return false;
  }
}
const field = "mt-1 w-full rounded border bg-background p-2 text-sm";
type RemoveCommandKey<T> = T extends unknown
  ? Omit<T, "idempotency_key">
  : never;
type DraftCommand = RemoveCommandKey<
  Extract<ProposalCommand, { idempotency_key: string }>
>;
function CaseEditor({
  item,
  disabled,
  save,
  remove,
}: {
  item: ReplayCase;
  disabled: boolean;
  save: (c: ReplayCase) => void;
  remove: () => void;
}) {
  useUiLocale();
  const [pointer, setPointer] = useState(item.pointer),
    [expected, setExpected] = useState(JSON.stringify(item.expected)),
    [status, setStatus] = useState(String(item.expected_status)),
    [error, setError] = useState(false);
  useEffect(() => {
    setPointer(item.pointer);
    setExpected(JSON.stringify(item.expected));
    setStatus(String(item.expected_status));
    setError(false);
  }, [item]);
  return (
    <form
      className="space-y-2 rounded border p-2"
      onSubmit={(e) => {
        e.preventDefault();
        try {
          const value: unknown = JSON.parse(expected),
            code = Number(status);
          if (
            !scalar(value) ||
            !integer(code, 100, 599) ||
            !/^(?:|\/(?:[^~]|~[01])*)$/.test(pointer) ||
            pointer.length > 512
          )
            throw new Error();
          setError(false);
          save({
            ...item,
            pointer,
            expected: value as ReplayCase["expected"],
            expected_status: code,
          });
        } catch {
          setError(true);
        }
      }}
    >
      <p className="break-all text-xs font-medium">
        {item.case_id} {translateUi("· criterion")} {item.criterion_node_id}:
        {item.criterion_index + 1}
      </p>
      <label className="block text-xs">
        {translateUi("Proposed pointer")}
        <input
          className={field}
          value={pointer}
          disabled={disabled}
          onChange={(e) => setPointer(e.target.value)}
        />
      </label>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="block text-xs">
          {translateUi("Proposed expected JSON scalar")}
          <input
            className={field}
            value={expected}
            disabled={disabled}
            onChange={(e) => setExpected(e.target.value)}
          />
        </label>
        <label className="block text-xs">
          {translateUi("Proposed HTTP status")}
          <input
            className={field}
            value={formatUiStatus(status)}
            disabled={disabled}
            onChange={(e) => setStatus(e.target.value)}
          />
        </label>
      </div>
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {translateUi(
            "Use a valid pointer, bounded JSON scalar and HTTP status.",
          )}
        </p>
      )}
      <div className="flex gap-2">
        <Button size="sm" type="submit" disabled={disabled}>
          {translateUi("Save proposed case")}
        </Button>
        <Button
          variant="outline"
          size="sm"
          type="button"
          disabled={disabled}
          onClick={remove}
        >
          {translateUi("Remove proposed case")}
        </Button>
      </div>
    </form>
  );
}

export default function TestProposalPanel({
  scope,
  replays,
  readOnly = false,
  onMaterialized,
}: {
  scope: ReplayScope;
  replays: ReplayRead[];
  readOnly?: boolean;
  onMaterialized: () => void;
}) {
  useUiLocale();
  const auth = useAuthStore((s) => s.isAuthenticated),
    autoLogin = useAuthStore((s) => s.autoLogin),
    userId = useAuthStore((s) => s.userData?.id);
  const isRun = "runId" in scope,
    id = isRun ? scope.runId : scope.sessionId;
  const identity = `${isRun}:${id}:${auth}:${autoLogin}:${userId}:${readOnly}`;
  const current = useRef(identity);
  current.current = identity;
  const mounted = useRef(true);
  const [loaded, setLoaded] = useState<string>(),
    [rows, setRows] = useState<ProposalRead[]>([]),
    [caps, setCaps] = useState<ExtensionCapabilities>();
  const [revision, setRevision] = useState(0),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string>(),
    [notice, setNotice] = useState<string>();
  const [title, setTitle] = useState("Successor test proposal"),
    [rationale, setRationale] = useState(
      "Explain why this is a new proposal; do not rewrite the old report.",
    ),
    [kind, setKind] = useState<TestProposal["kind"]>("suite-revision"),
    [sourceId, setSourceId] = useState("");
  const [permissionsReviewed, setPermissionsReviewed] = useState<string>(),
    [reviewed, setReviewed] = useState<string>();
  const keys = useRef(new Map<string, string>());
  useEffect(() => {
    mounted.current = true;
    setRows([]);
    setCaps(undefined);
    setLoaded(undefined);
    setBusy(false);
    setError(undefined);
    setNotice(undefined);
    setPermissionsReviewed(undefined);
    setReviewed(undefined);
    setSourceId("");
    keys.current.clear();
    return () => {
      mounted.current = false;
    };
  }, [identity]);
  useEffect(() => {
    let active = true;
    if (auth)
      void Promise.all([testExtensionCapabilities(), listTestProposals(scope)])
        .then(([c, r]) => {
          if (active && current.current === identity) {
            setCaps(c);
            setRows(r);
            setLoaded(identity);
            setError(undefined);
          }
        })
        .catch(() => {
          if (active) {
            setLoaded(undefined);
            setError(
              translateUi(
                "Proposal archive unavailable. Frozen reports are unaffected; no operation was retried.",
              ),
            );
          }
        });
    return () => {
      active = false;
    };
  }, [identity, revision]);
  const supportedCaps =
    caps?.schema_version === "0.1" &&
    caps.profile_ref === "test-extension-profile:proposals/0.1.0" &&
    caps.exploration_ready === false &&
    caps.performance_ready === false &&
    caps.screenshot_capture_ready === false &&
    typeof caps.enabled === "boolean" &&
    typeof caps.human_actions_configured === "boolean" &&
    Array.isArray(caps.blockers) &&
    caps.blockers.length <= 16 &&
    caps.blockers.every(
      (item) => typeof item === "string" && item.length <= 128,
    );
  const human =
    !readOnly &&
    isRun &&
    auth &&
    !autoLogin &&
    loaded === identity &&
    supportedCaps &&
    caps?.enabled &&
    caps.human_actions_configured;
  const source = replays.find((r) => r.plan.plan_id === sourceId) ?? replays[0];
  async function act(
    action: () => Promise<unknown>,
    success: string,
    materialized = false,
  ) {
    const captured = identity;
    setBusy(true);
    setError(undefined);
    setNotice(undefined);
    try {
      await action();
      if (mounted.current && current.current === captured) {
        setNotice(success);
        setRevision((n) => n + 1);
        setReviewed(undefined);
        setPermissionsReviewed(undefined);
        if (materialized) onMaterialized();
      }
    } catch {
      if (mounted.current && current.current === captured) {
        setError(
          translateUi(
            "Proposal operation was not confirmed. Refresh and review the exact revision before retrying. No job or PASS was created.",
          ),
        );
        setLoaded(undefined);
      }
    } finally {
      if (mounted.current && current.current === captured) setBusy(false);
    }
  }
  function send(command: DraftCommand) {
    const text = JSON.stringify(command);
    let key = keys.current.get(text);
    if (!key) {
      key = crypto.randomUUID();
      keys.current.set(text, key);
    }
    return testProposalTool(id, {
      ...command,
      idempotency_key: key,
    } as ProposalCommand);
  }
  return (
    <Card aria-label={translateUi("Test proposals")} className="bg-background">
      <CardHeader>
        <div className="flex flex-wrap justify-between gap-2">
          <CardTitle>{translateUi("Test proposals · H6D")}</CardTitle>
          <Button
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => setRevision((n) => n + 1)}
          >
            {translateUi("Refresh proposals")}
          </Button>
        </div>
        <CardDescription>
          {translateUi(
            "Exploration and repairs propose a new standard. They never silently heal a frozen suite. Owner review, replay approval, execution and Submit are distinct decisions.",
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="rounded border border-dashed p-3 text-sm">
          <p className="font-medium">
            {translateUi("Live exploration & performance · blocked")}
          </p>
          <p className="text-muted-foreground">
            {translateUi(
              "No approved browser/load runner or audited model route is configured. Planning limits are not runtime guarantees; approving a proposal does not authorize remote jobs or production actions.",
            )}
          </p>
          {supportedCaps && (
            <details>
              <summary className="cursor-pointer text-xs">
                {translateUi("Activation prerequisites")}
              </summary>
              <ul className="mt-2 list-inside list-disc text-xs">
                {caps!.blockers.map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {notice && (
          <p role="status" className="text-sm">
            {notice}
          </p>
        )}
        {caps && !caps.enabled && (
          <p className="text-xs">
            {translateUi(
              "Proposal authoring is disabled. Retained revisions remain readable.",
            )}
          </p>
        )}
        {readOnly && (
          <p className="text-xs text-muted-foreground">
            {translateUi(
              "Protected Harness projection · review and approve in ADLC. No approval credential is forwarded.",
            )}
          </p>
        )}
        {human && (
          <form
            className="space-y-2 rounded border p-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (!source || busy) return;
              void act(
                () =>
                  send({
                    operation: "init",
                    source_plan_id: source.plan.plan_id,
                    kind,
                    title,
                    rationale,
                  }),
                "Draft created by the proposal tool. Set explicit permissions before freezing it for owner review.",
              );
            }}
          >
            <label className="block text-xs">
              {translateUi("Source frozen suite")}
              <select
                className={field}
                value={source?.plan.plan_id ?? ""}
                disabled={busy}
                onChange={(e) => setSourceId(e.target.value)}
              >
                {replays.map((r) => (
                  <option key={r.plan.plan_id} value={r.plan.plan_id}>
                    {r.plan.candidate.file} · {r.plan.plan_id}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-xs">
              {translateUi("Proposal kind")}
              <select
                className={field}
                value={kind}
                disabled={busy}
                onChange={(e) =>
                  setKind(e.target.value as TestProposal["kind"])
                }
              >
                <option value="suite-revision">
                  {translateUi("Suite revision / repair")}
                </option>
                <option value="exploration">
                  {translateUi("Exploration intent (no execution)")}
                </option>
                <option value="performance">
                  {translateUi("Performance plan (no execution)")}
                </option>
              </select>
            </label>
            <label className="block text-xs">
              {translateUi("Title")}
              <input
                className={field}
                maxLength={120}
                value={title}
                disabled={busy}
                onChange={(e) => setTitle(e.target.value)}
              />
            </label>
            <label className="block text-xs">
              {translateUi("Reason for new standard")}
              <textarea
                className={field}
                maxLength={2000}
                value={rationale}
                disabled={busy}
                onChange={(e) => setRationale(e.target.value)}
              />
            </label>
            <Button
              type="submit"
              size="sm"
              disabled={busy || !source || !title.trim() || !rationale.trim()}
            >
              {translateUi("Create test proposal")}
            </Button>
          </form>
        )}
        {loaded === identity &&
          rows.map((row, i) => {
            if (!supportedProposal(row, scope))
              return (
                <p key={`unsupported-${i}`} className="text-sm">
                  {translateUi(
                    "Unsupported proposal revision · no actions or execution authority.",
                  )}
                </p>
              );
            const d = row.document,
              digest = row.reference.document_digest,
              sourceRow = replays.find(
                (r) => r.plan.plan_id === d.source.plan_id,
              );
            const sourceMatches =
              sourceRow &&
              sourceRow.plan_digest === d.source.plan_digest &&
              sourceRow.plan.suite_digest === d.source.suite_digest &&
              sourceRow.plan.candidate.content_digest ===
                d.source.candidate_digest &&
              sourceRow.plan.candidate.project_id === d.source.project_id &&
              sourceRow.plan.candidate.source_session_id ===
                d.source.source_session_id &&
              sourceRow.plan.contract_reference.contract_id ===
                d.source.contract_reference.contract_id &&
              sourceRow.plan.contract_reference.revision ===
                d.source.contract_reference.revision &&
              sourceRow.plan.contract_reference.content_digest ===
                d.source.contract_reference.content_digest;
            const canAct = human && !busy && sourceMatches;
            const changes = sourceRow
              ? [
                  ...d.cases
                    .filter((c) => {
                      const old = sourceRow.plan.cases.find(
                        (item) => item.case_id === c.case_id,
                      );
                      return (
                        !old ||
                        old.pointer !== c.pointer ||
                        old.expected !== c.expected ||
                        old.expected_status !== c.expected_status ||
                        old.criterion_node_id !== c.criterion_node_id ||
                        old.criterion_index !== c.criterion_index
                      );
                    })
                    .map((c) => {
                      const old = sourceRow.plan.cases.find(
                        (item) => item.case_id === c.case_id,
                      );
                      return `${c.case_id}: ${old ? `${old.pointer || "(root)"} = ${JSON.stringify(old.expected)}, HTTP ${old.expected_status}` : "new case"} → ${c.pointer || "(root)"} = ${JSON.stringify(c.expected)}, HTTP ${c.expected_status} (criterion ${c.criterion_node_id}:${c.criterion_index + 1})`;
                    }),
                  ...sourceRow.plan.cases
                    .filter(
                      (c) =>
                        !d.cases.some((item) => item.case_id === c.case_id),
                    )
                    .map(
                      (c) =>
                        `${c.case_id}: required source case removed from proposed suite`,
                    ),
                ]
              : [];
            return (
              <article
                key={d.proposal_id}
                className="space-y-3 rounded-lg border p-3"
              >
                <div className="flex flex-wrap gap-2">
                  <Badge variant="secondary">{formatUiStatus(row.state)}</Badge>
                  <Badge variant="outline">
                    {formatUiStatus(d.kind)} {translateUi("· revision")}{" "}
                    {d.revision}
                  </Badge>
                  <Badge variant="outline">
                    {translateUi("PROPOSAL ONLY")}
                  </Badge>
                </div>
                <h3 className="text-sm font-semibold">{d.title}</h3>
                <p className="whitespace-pre-wrap break-words text-sm">
                  {d.rationale}
                </p>
                <p className="break-all text-xs text-muted-foreground">
                  {translateUi("Exact document:")} {digest}
                  <br />
                  {translateUi("Source suite:")} {d.source.suite_digest}
                  <br />
                  {translateUi("Contract revision")}{" "}
                  {d.source.contract_reference.revision} ·{" "}
                  {d.source.contract_reference.content_digest}
                </p>
                {d.parent_reference && (
                  <p className="break-all text-xs">
                    {translateUi("Successor of revision")}{" "}
                    {d.parent_reference.revision} ·{" "}
                    {d.parent_reference.document_digest}. The earlier
                    suite/report is unchanged.
                  </p>
                )}
                {sourceRow && (
                  <div className="space-y-1 rounded border border-dashed p-2 text-xs">
                    <p className="font-medium">
                      {changes.length
                        ? translateUi("Proposed changes to the frozen standard")
                        : translateUi("No case changes from the source suite")}
                    </p>
                    {changes.map((change) => (
                      <p className="break-all" key={change}>
                        {change}
                      </p>
                    ))}
                    {changes.length > 0 && (
                      <p className="text-muted-foreground">
                        {translateUi(
                          "These changes define a different standard, not a repair of the old verdict. This fixture profile does not enforce natural-language requirements; review their meaning against the approved contract.",
                        )}
                      </p>
                    )}
                  </div>
                )}
                <div className="rounded border bg-muted/20 p-2 text-xs">
                  <p className="font-medium">
                    {translateUi("Target / data permissions")}{" "}
                    {d.permissions
                      ? translateUi("· recorded in this revision")
                      : translateUi("· not yet specified")}
                  </p>
                  <p>
                    {translateUi(
                      "Disposable non-production fixture · synthetic run-owned data only · GET /fixture · allocated loopback target only · ephemeral test account · release owned target · confirmed worker cancellation.",
                    )}
                  </p>
                  <p>
                    {translateUi("Maximum duration:")}{" "}
                    {d.permissions?.max_duration_seconds ??
                      translateUi("not set")}{" "}
                    {translateUi(
                      "seconds. No arbitrary URL, credentials, DELETE, deploy or Git permissions.",
                    )}
                  </p>
                </div>
                {d.performance && (
                  <p className="text-xs">
                    {translateUi("Planning budget only:")}{" "}
                    {d.performance.virtual_users} {translateUi("VUs ·")}{" "}
                    {d.performance.duration_seconds}
                    {translateUi("s ·")} {d.performance.requests_per_second}{" "}
                    {translateUi("requests/s · cap")}{" "}
                    {d.performance.max_requests}{" "}
                    {translateUi("requests · p95 ≤")}
                    {d.performance.p95_latency_ms_max}
                    {translateUi("ms · failed requests ≤")}
                    {d.performance.failed_requests_max}. No measurements or
                    verdict exist.
                  </p>
                )}
                {row.state === "DRAFT" && human ? (
                  <>
                    {d.cases.map((c) => (
                      <CaseEditor
                        key={`${c.case_id}:${digest}`}
                        item={c}
                        disabled={!canAct}
                        save={(item) =>
                          void act(
                            () =>
                              send({
                                operation: "upsert_case",
                                reference: row.reference,
                                case: item,
                              }),
                            "Proposed case saved. Existing replay standards remain unchanged.",
                          )
                        }
                        remove={() =>
                          void act(
                            () =>
                              send({
                                operation: "remove_case",
                                reference: row.reference,
                                case_id: c.case_id,
                              }),
                            "Proposed case removed; an empty suite cannot be frozen.",
                          )
                        }
                      />
                    ))}
                    {sourceRow &&
                      sourceRow.plan.cases
                        .filter(
                          (c) => !d.cases.some((x) => x.case_id === c.case_id),
                        )
                        .map((c) => (
                          <Button
                            key={c.case_id}
                            size="sm"
                            variant="outline"
                            disabled={!canAct}
                            onClick={() =>
                              void act(
                                () =>
                                  send({
                                    operation: "upsert_case",
                                    reference: row.reference,
                                    case: c,
                                  }),
                                "Required source case restored to this proposal.",
                              )
                            }
                          >
                            {translateUi("Restore case")} {c.case_id}
                          </Button>
                        ))}
                    <label className="flex gap-2 text-xs">
                      <input
                        type="checkbox"
                        disabled={!canAct}
                        checked={permissionsReviewed === digest}
                        onChange={(e) =>
                          setPermissionsReviewed(
                            e.target.checked ? digest : undefined,
                          )
                        }
                      />
                      {translateUi(
                        "I explicitly accept only the target/data limits above for this proposal.",
                      )}{" "}
                      {d.kind === "performance" &&
                        translateUi(
                          "Use the displayed bounded planning preset (2 VUs, 10s, 2 requests/s, cap 20, p95 500ms, zero failures).",
                        )}
                    </label>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={!canAct || permissionsReviewed !== digest}
                        onClick={() =>
                          void act(
                            () =>
                              send({
                                operation: "set_permissions",
                                reference: row.reference,
                                permissions: fixturePermissions,
                                performance:
                                  d.kind === "performance"
                                    ? defaultBudget
                                    : null,
                              }),
                            "Explicit planning permissions saved; they do not start a job.",
                          )
                        }
                      >
                        {translateUi("Record target / data permissions")}
                      </Button>
                      <Button
                        size="sm"
                        disabled={!canAct || !d.permissions || !d.cases.length}
                        onClick={() =>
                          void act(
                            () =>
                              send({
                                operation: "validate",
                                reference: row.reference,
                              }),
                            "Proposal frozen for review. Changes now require a successor revision.",
                          )
                        }
                      >
                        {translateUi("Freeze proposal for review")}
                      </Button>
                    </div>
                  </>
                ) : (
                  <div className="space-y-1 text-xs">
                    {d.cases.map((c) => (
                      <p key={c.case_id} className="break-all">
                        {c.case_id} {translateUi("· GET /fixture ·")}{" "}
                        {c.pointer || "(root)"} = {JSON.stringify(c.expected)}{" "}
                        {translateUi("· HTTP")} {c.expected_status}{" "}
                        {translateUi("· criterion")} {c.criterion_node_id}:
                        {c.criterion_index + 1}
                      </p>
                    ))}
                  </div>
                )}
                {row.state === "READY_FOR_REVIEW" && human && (
                  <label className="flex gap-2 text-xs">
                    <input
                      type="checkbox"
                      disabled={!canAct}
                      checked={reviewed === digest}
                      onChange={(e) =>
                        setReviewed(e.target.checked ? digest : undefined)
                      }
                    />
                    {translateUi(
                      "I reviewed this exact document, proposed expectations, contract and target/data limits. This is not execution or Submit approval.",
                    )}
                  </label>
                )}
                {row.approved_by && (
                  <p className="text-xs">
                    {translateUi("Proposal approved by")} {row.approved_by} ·{" "}
                    {row.approved_at}. No execution permission was granted.
                  </p>
                )}
                {row.materialized_plan_id && (
                  <p className="break-all text-xs">
                    {translateUi("New frozen replay draft:")}{" "}
                    {row.materialized_plan_id}. Review and approve that exact
                    suite in Frozen replay; Run and Submit remain separate.
                  </p>
                )}
                {human && (
                  <div className="flex flex-wrap gap-2">
                    {row.state === "READY_FOR_REVIEW" && (
                      <Button
                        size="sm"
                        disabled={!canAct || reviewed !== digest}
                        onClick={() =>
                          void act(
                            () => testProposalAction(id, row, "approve"),
                            "Exact proposal approved. No job, PASS or Submit was created.",
                          )
                        }
                      >
                        {translateUi("Approve exact proposal")}
                      </Button>
                    )}
                    {row.state === "APPROVED" &&
                      d.kind === "suite-revision" && (
                        <Button
                          size="sm"
                          disabled={!canAct}
                          onClick={() =>
                            void act(
                              () => testProposalAction(id, row, "materialize"),
                              "Successor replay draft created once; it requires its own exact approval before Run.",
                              true,
                            )
                          }
                        >
                          {translateUi("Create successor replay draft")}
                        </Button>
                      )}
                    {row.state !== "DRAFT" && (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={!canAct || d.revision >= 100}
                        onClick={() =>
                          void act(
                            () =>
                              send({
                                operation: "init",
                                source_plan_id: d.source.plan_id,
                                kind: d.kind,
                                title: d.title,
                                rationale: d.rationale,
                                parent_reference: row.reference,
                              }),
                            "Successor revision created. Approval and target/data permissions were not inherited.",
                          )
                        }
                      >
                        {translateUi("Fork new proposal revision")}
                      </Button>
                    )}
                  </div>
                )}
                <details>
                  <summary className="cursor-pointer text-xs">
                    {translateUi("Tool-created proposal JSON")}
                  </summary>
                  <pre className="mt-2 max-h-72 overflow-auto text-xs">
                    {JSON.stringify(row, null, 2)}
                  </pre>
                </details>
              </article>
            );
          })}
      </CardContent>
    </Card>
  );
}
