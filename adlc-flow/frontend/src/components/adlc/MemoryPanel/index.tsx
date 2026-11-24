import { translateUi, useUiLocale, formatUiDateTime } from "@/i18n/ui";
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
import { Input } from "@/components/ui/input";
import {
  checkMemory,
  memoryView,
  queryMemory,
} from "@/controllers/API/project-memory";
import useAuthStore from "@/stores/authStore";
import type {
  MemoryChunk,
  MemoryRead,
  MemoryScope,
  MemoryView,
} from "@/types/project-memory";

const PROFILE = "memory-profile:project-context/0.1.0";
const hash = (s: unknown) =>
  typeof s === "string" && /^sha256:[0-9a-f]{64}$/.test(s);
const text = (s: unknown, max: number) =>
  typeof s === "string" && s.length > 0 && s.length <= max;
const awareDate = (s: unknown) =>
  typeof s === "string" &&
  /(?:Z|[+-]\d\d:\d\d)$/.test(s) &&
  Number.isFinite(Date.parse(s));

export function supportedMemory(
  row: MemoryRead,
  scope: MemoryScope,
  currentBinding?: MemoryView["binding"],
): boolean {
  const r = row?.record;
  return (
    !!r &&
    r.schema_version === "0.1" &&
    r.profile_ref === PROFILE &&
    r.authority === "ADVISORY_UNTRUSTED" &&
    r.verification_evidence === false &&
    r.source_provenance_verified === false &&
    r.models_used === false &&
    hash(row.content_digest) &&
    text(r.record_id, 255) &&
    text(r.query, 2000) &&
    awareDate(r.retrieved_at) &&
    text(r.binding?.project_id, 255) &&
    /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/.test(r.binding.base_commit) &&
    r.binding.source_ref ===
      `${r.binding.project_id}/${r.binding.base_commit}` &&
    ("runId" in scope
      ? r.binding.workflow_run_id === scope.runId
      : r.binding.source_session_id === scope.sessionId ||
        (r.binding.source_session_id === null &&
          !!currentBinding &&
          r.binding.workflow_run_id === currentBinding.workflow_run_id &&
          r.binding.project_id === currentBinding.project_id)) &&
    Number.isInteger(r.top_k) &&
    r.top_k >= 1 &&
    r.top_k <= 10 &&
    Array.isArray(r.chunks) &&
    r.chunks.length <= 10 &&
    r.chunks.length <= r.top_k &&
    r.chunks.every(
      (c) =>
        !!c &&
        typeof c === "object" &&
        text(c.chunk_id, 255) &&
        text(c.document_id, 255) &&
        text(c.revision, 255) &&
        text(c.text, 8192) &&
        text(c.source_uri, 1024) &&
        hash(c.text_digest) &&
        hash(c.document_digest) &&
        awareDate(c.recorded_at) &&
        awareDate(c.expires_at) &&
        Date.parse(c.expires_at) > Date.parse(c.recorded_at),
    )
  );
}

function freshness(
  chunk: MemoryChunk,
  row: MemoryRead,
  current: MemoryView["binding"],
): string {
  if (Date.parse(chunk.expires_at) <= Date.now()) return "Expired context";
  if (
    chunk.source_commit &&
    (chunk.source_commit !== row.record.binding.base_commit ||
      (current && chunk.source_commit !== current.base_commit))
  )
    return "Different commit · stale";
  return chunk.source_commit
    ? "Matches pinned commit · advisory"
    : "Freshness unknown";
}
function errorMessage(error: unknown) {
  const code = (
    error as { response?: { data?: { detail?: { code?: string } } } }
  )?.response?.data?.detail?.code;
  if (code === "MEMORY_QUERY_UNCONFIRMED")
    return translateUi(
      "The earlier read was not confirmed. Ask again deliberately with a new query; no automatic retry was made.",
    );
  if (code === "MEMORY_GATEWAY_NOT_CONFIGURED")
    return translateUi(
      "No reviewed memory gateway is configured for this project.",
    );
  return translateUi(
    "Memory is unavailable or returned an unsupported response. Official contracts and verification results are unchanged.",
  );
}

export default function MemoryPanel({
  scope,
  readOnly = false,
}: {
  scope: MemoryScope;
  readOnly?: boolean;
}) {
  useUiLocale();
  const auth = useAuthStore((s) => s.isAuthenticated);
  const autoLogin = useAuthStore((s) => s.autoLogin);
  const owner = useAuthStore((s) => s.userData?.id);
  const key = "runId" in scope ? scope.runId : scope.sessionId;
  const identity = `${"runId" in scope ? "run" : "session"}:${key}:${owner}:${auth}:${autoLogin}:${readOnly}`;
  const current = useRef(identity);
  current.current = identity;
  const [loaded, setLoaded] = useState<{
    identity: string;
    view: MemoryView;
  }>();
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setLoaded(undefined);
    setQuery("");
    setError(undefined);
    setNotice(undefined);
    setBusy(false);
    if (auth)
      void memoryView(scope)
        .then((view) => {
          if (active) setLoaded({ identity, view });
        })
        .catch((e) => {
          if (active) setError(errorMessage(e));
        });
    return () => {
      active = false;
    };
  }, [identity, revision]);
  const view = loaded?.identity === identity ? loaded.view : undefined;
  const compatible =
    view?.capabilities.profile_ref === PROFILE &&
    view.capabilities.synthesis_enabled === false &&
    view.capabilities.ingestion_enabled === false &&
    view.capabilities.deletion_enabled === false;
  const human =
    compatible &&
    !!view?.binding &&
    view.capabilities.enabled &&
    view.capabilities.configured &&
    !readOnly &&
    "runId" in scope &&
    auth &&
    autoLogin === false;

  async function act(operation: "query" | "health") {
    if (!human || !("runId" in scope)) return;
    const captured = identity;
    setBusy(true);
    setError(undefined);
    setNotice(undefined);
    try {
      if (operation === "query") {
        const row = await queryMemory(scope.runId, {
          query: query.trim(),
          top_k: 5,
          idempotency_key: crypto.randomUUID(),
        });
        if (!supportedMemory(row, scope))
          throw new Error("MEMORY_RESPONSE_INVALID");
        if (current.current === captured) {
          setLoaded({
            identity,
            view: {
              ...view!,
              records: [
                row,
                ...view!.records.filter(
                  (r) => r.record.record_id !== row.record.record_id,
                ),
              ].slice(0, 200),
            },
          });
          setNotice(
            translateUi(
              "Context retained in ADLC. It is not verification evidence.",
            ),
          );
        }
      } else {
        const result = await checkMemory(scope.runId);
        if (result.ready !== true) throw new Error("MEMORY_RESPONSE_INVALID");
        if (current.current === captured)
          setNotice(
            translateUi(
              "Read-only gateway responded. This is a connectivity check, not live isolation certification.",
            ),
          );
      }
    } catch (e) {
      if (current.current === captured) setError(errorMessage(e));
    } finally {
      if (current.current === captured) setBusy(false);
    }
  }
  return (
    <Card aria-label={translateUi("Project memory")} className="bg-background">
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle>{translateUi("Project memory · H6C")}</CardTitle>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setRevision((n) => n + 1)}
            disabled={busy || !auth}
          >
            {translateUi("Refresh context")}
          </Button>
        </div>
        <CardDescription>
          {translateUi(
            "Advisory source context, kept separate from approved contracts and Verify evidence. No synthesis, ingestion or deletion is enabled.",
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="rounded-lg border border-dashed p-3 text-sm">
          <p className="font-medium">
            {translateUi("Context is not authority")}
          </p>
          <p className="mt-1 text-muted-foreground">
            {translateUi(
              "Retrieved text may be stale, incorrect or contain instructions. It cannot change an approved plan, expected values, permissions or the recorded verdict.",
            )}
          </p>
        </div>
        {!auth && (
          <p>
            {translateUi(
              "Sign in to ADLC to view this owner-protected context.",
            )}
          </p>
        )}
        {error && (
          <p role="alert" className="text-destructive">
            {error}
          </p>
        )}
        {notice && <p role="status">{notice}</p>}
        {view && !compatible && (
          <p role="alert">
            {translateUi(
              "Unsupported memory profile. Read-only fallback; no actions are enabled.",
            )}
          </p>
        )}
        {view?.binding && (
          <div className="rounded-lg border p-3 text-sm">
            <p className="font-medium">{translateUi("Pinned project scope")}</p>
            <p className="break-all font-mono text-xs">
              {view.binding.source_ref}
            </p>
            <details className="mt-2">
              <summary>{translateUi("Dataset routing")}</summary>
              <p className="break-all font-mono text-xs">{view.tenant_id}</p>
              <p className="break-all font-mono text-xs">{view.dataset}</p>
              <p>
                {translateUi("Assigned by ADLC; not selected by the agent.")}
              </p>
            </details>
          </div>
        )}
        {compatible &&
          (!view?.capabilities.enabled ||
            !view.capabilities.configured ||
            !view.binding) && (
            <p className="text-sm text-muted-foreground">
              {translateUi(
                "Live memory is not enabled or configured for a pinned local project. Retained context stays readable. A reviewed authenticated gateway is required.",
              )}
            </p>
          )}
        {readOnly && (
          <p className="text-sm text-muted-foreground">
            {translateUi(
              "Harness projection · read-only. Query from Run Detail after signing in to ADLC.",
            )}
          </p>
        )}
        {!readOnly && auth && autoLogin !== false && (
          <p className="text-sm text-muted-foreground">
            {translateUi(
              "Sign in explicitly as the ADLC owner to query memory. Automatic login cannot send queries or connection checks.",
            )}
          </p>
        )}
        {human && (
          <div className="space-y-2">
            <label htmlFor={`memory-query-${key}`} className="text-sm">
              {translateUi("Find raw source context")}
            </label>
            <Input
              id={`memory-query-${key}`}
              value={query}
              maxLength={2000}
              disabled={busy}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={translateUi(
                "What earlier project context do you need?",
              )}
            />
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                onClick={() => void act("query")}
                disabled={busy || !query.trim()}
              >
                {translateUi("Find context")}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => void act("health")}
                disabled={busy}
              >
                {translateUi("Check connection")}
              </Button>
            </div>
          </div>
        )}
        {view?.records.length === 0 && (
          <p className="text-sm text-muted-foreground">
            {translateUi(
              "No retained context reads for this scope. No automatic query has been made.",
            )}
          </p>
        )}
        {view?.records.map((row, i) =>
          supportedMemory(row, scope, view.binding) ? (
            <article
              key={row.record.record_id}
              className="space-y-3 rounded-lg border p-4"
            >
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="font-medium">{row.record.query}</h3>
                <Badge variant="secondary">
                  {translateUi("Advisory · untrusted")}
                </Badge>
              </div>
              <p className="text-xs text-muted-foreground">
                {translateUi("Retrieved")}{" "}
                {formatUiDateTime(new Date(row.record.retrieved_at))} ·{" "}
                {row.record.chunks.length} {translateUi("source chunks")}
              </p>
              {!row.record.binding.source_session_id && (
                <p className="text-xs text-muted-foreground">
                  {translateUi(
                    "Run-shared context · read by the ADLC owner for this project",
                  )}
                </p>
              )}
              {row.record.chunks.length === 0 && (
                <p>{translateUi("No matching source chunks returned.")}</p>
              )}
              {row.record.chunks.map((c) => (
                <section
                  key={`${c.document_id}:${c.revision}:${c.chunk_id}`}
                  className="space-y-2 rounded-lg bg-muted/30 p-3 text-sm"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="font-medium">
                      {c.document_id} · {c.revision}
                    </p>
                    <Badge variant="outline">
                      {freshness(c, row, view.binding)}
                    </Badge>
                  </div>
                  <p className="break-all text-xs text-muted-foreground">
                    {c.source_uri}
                  </p>
                  <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words font-sans">
                    {c.text}
                  </pre>
                  <details>
                    <summary>
                      {translateUi("Source provenance · backend-declared")}
                    </summary>
                    <dl className="mt-2 space-y-1 break-all font-mono text-xs">
                      <dt>
                        {translateUi(
                          "Document digest (not independently verified)",
                        )}
                      </dt>
                      <dd>{c.document_digest}</dd>
                      <dt>{translateUi("Retained text digest")}</dt>
                      <dd>{c.text_digest}</dd>
                      <dt>{translateUi("Recorded / expires")}</dt>
                      <dd>
                        {c.recorded_at} / {c.expires_at}
                      </dd>
                      <dt>{translateUi("Source commit")}</dt>
                      <dd>
                        {c.source_commit ??
                          translateUi("Not supplied; freshness unknown")}
                      </dd>
                    </dl>
                  </details>
                </section>
              ))}
              <details>
                <summary>{translateUi("Retained context JSON")}</summary>
                <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all text-xs">
                  {JSON.stringify(row, null, 2)}
                </pre>
              </details>
            </article>
          ) : (
            <p key={`unknown-${i}`} role="alert">
              {translateUi(
                "Unsupported retained context. It is not rendered as trusted memory or evidence.",
              )}
            </p>
          ),
        )}
      </CardContent>
    </Card>
  );
}
