import * as React from "react";
import { createRoot } from "react-dom/client";
import { copyContract } from "@/components/adlc/ContractViewer/test-fixtures";
import MemoryPanel from "@/components/adlc/MemoryPanel";
import {
  memoryFixture,
  memoryViewFixture,
} from "@/components/adlc/MemoryPanel/test-fixtures";
import ReplayPanel from "@/components/adlc/ReplayPanel";
import {
  replayFixture,
  replayFixtureCapabilities,
} from "@/components/adlc/ReplayPanel/test-fixtures";
import {
  extensionCaps,
  proposalFixture,
} from "@/components/adlc/TestProposalPanel/test-fixtures";
import VerificationPanel from "@/components/adlc/VerificationPanel";
import {
  fixtureCapabilities,
  verificationFixture,
} from "@/components/adlc/VerificationPanel/test-fixtures";
import { api } from "@/controllers/API/api";
import { sha256 } from "@/controllers/API/test-extensions";
import useAuthStore from "@/stores/authStore";
import type {
  ProposalCommand,
  ProposalRead,
  ScreenshotRead,
} from "@/types/test-extensions";
import "@/style/index.css";

// This isolated entry point intercepts its own API instance. No fetch, account,
// model or real approval is made by the preview.
const query = new URLSearchParams(location.search);
const previewRoot = document.getElementById("root")!;
const embedded =
  previewRoot.dataset.previewEmbedded === "true" ||
  query.get("embedded") === "true" ||
  /^\/contracts\/harness\/source-session\//.test(location.pathname);
const appearance = embedded
  ? new URL(document.referrer || location.href).searchParams
  : query;
const harness = !embedded && query.get("host") === "harness";
const mode = query.get("mode") ?? "results";
const extensionSlice =
  previewRoot.dataset.previewSlice === "h6d" ||
  appearance.get("slice") === "h6d";
const replaySlice =
  extensionSlice ||
  previewRoot.dataset.previewSlice === "h6b" ||
  appearance.get("slice") === "h6b";
const memorySlice =
  previewRoot.dataset.previewSlice === "h6c" ||
  appearance.get("slice") === "h6c";
document.documentElement.classList.toggle(
  "dark",
  (previewRoot.dataset.previewTheme ?? appearance.get("theme")) !== "light",
);
document.body.className = "bg-background text-foreground";
useAuthStore.setState({ isAuthenticated: true, autoLogin: false });
const initial =
  mode === "draft"
    ? [verificationFixture()]
    : [
        verificationFixture("SUBMITTED"),
        verificationFixture("READY_FOR_SUBMISSION", "FAIL"),
        verificationFixture("DISPATCH_UNCERTAIN"),
      ];
const rows = initial.map((row, i) => ({
  ...row,
  plan: { ...row.plan, plan_id: `offline-plan-${i + 1}` },
}));
rows.forEach((row) => {
  if (row.state === "DISPATCH_UNCERTAIN")
    row.error_code = "VERIFICATION_EXECUTION_UNCONFIRMED";
});
const contract = copyContract();
contract.status = "APPROVED";
const replayRows = (
  mode === "draft"
    ? [replayFixture()]
    : [
        replayFixture("SUBMITTED"),
        replayFixture("READY_FOR_SUBMISSION", "FAIL"),
        replayFixture("CANCEL_REQUESTED"),
      ]
).map((row, i) => ({
  ...row,
  plan: { ...row.plan, plan_id: `offline-replay-${i + 1}` },
}));
const memory = memoryViewFixture();
if (extensionSlice && mode !== "draft") {
  // Illustrative fixed-standard regression: same expected 42, different candidate
  // observation 41. This is a mock UI ledger, never real execution evidence.
  const first = replayRows[0],
    second = replayRows[1];
  first.created_at = "2026-10-13T04:00:00Z";
  second.created_at = "2026-10-13T04:10:00Z";
  second.plan.cases = structuredClone(first.plan.cases);
  second.plan.candidate.content_digest = "sha256:" + "9".repeat(64);
  second.receipt!.candidate_digest = second.report!.candidate_digest =
    second.plan.candidate.content_digest;
  second.receipt!.observations[0].response_digest =
    second.plan.candidate.content_digest;
  second.receipt!.observations[0].observed =
    second.report!.checks[0].observed = 41;
  second.report!.checks[0].expected = 42;
}
const proposalRows: ProposalRead[] = extensionSlice
  ? [
      proposalFixture("READY_FOR_REVIEW"),
      proposalFixture("DRAFT", "performance"),
    ]
  : [];
for (const [i, row] of proposalRows.entries()) {
  const source = replayRows[mode === "draft" ? 0 : 1];
  row.document.proposal_id =
    row.reference.proposal_id = `offline-proposal-${i + 1}`;
  row.document.source = {
    workflow_run_id: source.plan.workflow_run_id,
    plan_id: source.plan.plan_id,
    plan_digest: source.plan_digest,
    suite_digest: source.plan.suite_digest,
    candidate_digest: source.plan.candidate.content_digest,
    project_id: source.plan.candidate.project_id,
    source_session_id: source.plan.candidate.source_session_id,
    contract_reference: source.plan.contract_reference,
  };
  row.document.cases = structuredClone(source.plan.cases);
  row.document.title = i
    ? "Bounded performance planning (no execution)"
    : "Review a successor assertion";
  row.document.rationale =
    "Offline proposal only. The recorded FAIL and approved expectation remain unchanged; any new expectation needs a new reviewed suite and fresh evidence.";
}
let pngPromise: Promise<Blob> | undefined;
function referencePng() {
  pngPromise ??= new Promise<Blob>((resolve, reject) => {
    const canvas = document.createElement("canvas");
    canvas.width = 600;
    canvas.height = 180;
    const ctx = canvas.getContext("2d")!;
    ctx.fillStyle = "#f8fafc";
    ctx.fillRect(0, 0, 600, 180);
    ctx.fillStyle = "#0f172a";
    ctx.font = "bold 20px sans-serif";
    ctx.fillText("Illustrative fixture reference", 24, 36);
    ctx.font = "16px monospace";
    ctx.fillText("GET /fixture   expected: 42   observed: 41", 24, 76);
    ctx.fillStyle = "#b91c1c";
    ctx.fillText("Reference image only — NOT execution evidence", 24, 118);
    ctx.fillStyle = "#64748b";
    ctx.fillText("Offline preview / no API or model call", 24, 154);
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("No fixture raster"))),
      "image/png",
    );
  });
  return pngPromise;
}
async function screenshotFixture(): Promise<ScreenshotRead> {
  const row = replayRows.find((r) => r.plan.plan_id === "offline-replay-2")!,
    blob = await referencePng(),
    hash = await sha256(await blob.arrayBuffer());
  return {
    schema_version: "0.1",
    profile_ref: "evidence-profile:supplementary-png/0.1.0",
    attachment_id: "offline-image-one",
    workflow_run_id: row.plan.workflow_run_id,
    plan_id: row.plan.plan_id,
    plan_digest: row.plan_digest,
    execution_id: row.execution_id!,
    candidate_digest: row.plan.candidate.content_digest,
    case_id: "answer",
    caption: "Illustrative owner reference · cannot change the FAIL report",
    authority: "SUPPLEMENTARY_UNTRUSTED",
    affects_verdict: false,
    capture_provenance_verified: false,
    uploaded_by: "offline-fixture-owner",
    uploaded_at: "2026-10-13T04:12:00Z",
    input_digest: hash,
    content_digest: hash,
    media_type: "image/png",
    byte_size: blob.size,
    width: 600,
    height: 180,
    case_evidence_digest: row.evidence_digest!,
  };
}
const stale = memoryFixture();
stale.record.record_id = "memory-stale";
stale.record.query = "Earlier deployment notes";
stale.record.chunks[0].document_id = "deployment-notes";
stale.record.chunks[0].source_commit = "e".repeat(40);
stale.record.chunks[0].text =
  "This note describes an older source commit. Do not use it to change the frozen requirements or a recorded verification verdict.";
memory.records.push(stale);
api.get = (async (url: string) => {
  if (url.endsWith("/test-extension-capabilities"))
    return { data: { ...extensionCaps, enabled: extensionSlice } };
  if (url.endsWith("/test-proposals"))
    return { data: structuredClone(proposalRows) };
  if (url.includes("/replay-screenshots/")) {
    if (extensionSlice && url.endsWith("/offline-image-one")) {
      const info = await screenshotFixture();
      return {
        data: await referencePng(),
        headers: { "x-adlc-content-digest": info.content_digest },
      };
    }
    return {
      data:
        extensionSlice && url.endsWith("/offline-replay-2")
          ? [await screenshotFixture()]
          : [],
    };
  }
  if (url.endsWith("/project-memory")) return { data: structuredClone(memory) };
  if (url.endsWith("/replay-capabilities"))
    return { data: replayFixtureCapabilities };
  if (url.endsWith("/replays")) return { data: structuredClone(replayRows) };
  if (url.endsWith("/verification-capabilities"))
    return { data: fixtureCapabilities };
  if (url.endsWith("/verification-candidates"))
    return {
      data: {
        contracts: [contract],
        patches: [
          {
            source_task_id: "task-one",
            artifact_id: "artifact-one",
            task_name: "Offline captured candidate",
            files: ["h6a-fixture.json"],
          },
        ],
      },
    };
  if (url.endsWith("/verifications")) return { data: structuredClone(rows) };
  throw new Error("Offline preview blocks all other API paths.");
}) as typeof api.get;
api.post = (async (url: string, input?: Record<string, unknown>) => {
  if (url.endsWith("/test-proposals/tools")) {
    const c = input as unknown as ProposalCommand;
    let row: ProposalRead;
    if (c.operation === "init") {
      const source = replayRows.find(
        (r) => r.plan.plan_id === c.source_plan_id,
      )!;
      row = proposalFixture();
      row.document.proposal_id =
        row.reference.proposal_id = `offline-proposal-${proposalRows.length + 1}`;
      row.document.kind = c.kind;
      row.document.title = c.title;
      row.document.rationale = c.rationale;
      row.document.source = {
        ...row.document.source,
        plan_id: source.plan.plan_id,
        candidate_digest: source.plan.candidate.content_digest,
      };
      row.document.cases = structuredClone(source.plan.cases);
      if (c.parent_reference) {
        const parent = proposalRows.find(
          (r) => r.reference.proposal_id === c.parent_reference!.proposal_id,
        )!;
        row.document.parent_reference = c.parent_reference;
        row.document.revision = row.reference.revision =
          parent.reference.revision + 1;
        row.document.cases = structuredClone(parent.document.cases);
        row.document.source = structuredClone(parent.document.source);
      }
      proposalRows.unshift(row);
    } else {
      if (c.operation === "get_status")
        return {
          data: structuredClone(
            proposalRows.find((r) => r.reference.proposal_id === c.proposal_id),
          ),
        };
      row = proposalRows.find(
        (r) => r.reference.proposal_id === c.reference.proposal_id,
      )!;
      if (row.state !== "DRAFT") throw new Error("Offline frozen proposal");
      if (c.operation === "upsert_case") {
        row.document.cases = row.document.cases.filter(
          (x) => x.case_id !== c.case.case_id,
        );
        row.document.cases.push(c.case);
      }
      if (c.operation === "remove_case")
        row.document.cases = row.document.cases.filter(
          (x) => x.case_id !== c.case_id,
        );
      if (c.operation === "set_permissions") {
        row.document.permissions = c.permissions;
        row.document.performance = c.performance;
      }
      if (c.operation === "validate") row.state = "READY_FOR_REVIEW";
    }
    row.reference.document_digest =
      "sha256:" + crypto.randomUUID().replaceAll("-", "").repeat(2);
    return { data: structuredClone(row) };
  }
  const proposed = proposalRows.find((r) =>
    url.includes(`/test-proposals/${r.reference.proposal_id}/`),
  );
  if (proposed) {
    if (url.endsWith("/approve") && proposed.state === "READY_FOR_REVIEW") {
      proposed.state = "APPROVED";
      proposed.approved_by = "offline-fixture-owner";
      proposed.approved_at = new Date().toISOString();
    }
    if (
      url.endsWith("/materialize") &&
      proposed.state === "APPROVED" &&
      proposed.document.kind === "suite-revision"
    ) {
      const source = replayRows.find(
        (r) => r.plan.plan_id === proposed.document.source.plan_id,
      )!;
      const successor = replayFixture();
      successor.plan = structuredClone(source.plan);
      successor.plan.plan_id = `offline-replay-${replayRows.length + 1}`;
      successor.plan.cases = structuredClone(proposed.document.cases);
      successor.plan.suite_digest = "sha256:" + "6".repeat(64);
      replayRows.unshift(successor);
      proposed.state = "MATERIALIZED";
      proposed.materialized_plan_id = successor.plan.plan_id;
    }
    return { data: structuredClone(proposed) };
  }
  if (url.endsWith("/project-memory/health")) return { data: { ready: true } };
  if (url.endsWith("/project-memory/context")) {
    const row = memoryFixture();
    row.record.record_id = `offline-query-${memory.records.length + 1}`;
    row.record.query =
      typeof input?.query === "string" ? input.query : "Offline query";
    row.record.binding.source_session_id = null;
    memory.records.unshift(row);
    return { data: row };
  }
  const replay = replayRows.find((row) => url.includes(row.plan.plan_id));
  if (replay) {
    if (url.endsWith("/approve") && replay.state === "DRAFT") {
      replay.state = "APPROVED";
      replay.approved_at = new Date().toISOString();
      replay.approved_by = "offline-fixture-owner";
    } else if (url.endsWith("/execute") && replay.state === "APPROVED") {
      Object.assign(replay, replayFixture("READY_FOR_SUBMISSION"), {
        plan: replay.plan,
      });
    } else if (url.endsWith("/cancel") && replay.state === "APPROVED") {
      replay.state = "CANCELLED";
      replay.cancel_requested_at = new Date().toISOString();
      replay.cancel_requested_by = "offline-fixture-owner";
      replay.cancelled_at = new Date().toISOString();
    } else if (
      url.endsWith("/submit") &&
      replay.state === "READY_FOR_SUBMISSION"
    ) {
      replay.state = "SUBMITTED";
      replay.submitted_at = new Date().toISOString();
    }
    return { data: structuredClone(replay) };
  }
  const row = rows.find((row) => url.includes(row.plan.plan_id));
  if (!row) throw new Error("Offline preview blocks all other API writes.");
  if (url.endsWith("/approve") && row.state === "DRAFT") {
    row.state = "APPROVED";
    row.approved_at = new Date().toISOString();
    row.approved_by = "offline-fixture-owner";
  } else if (url.endsWith("/execute") && row.state === "APPROVED") {
    const finished = verificationFixture("READY_FOR_SUBMISSION");
    Object.assign(row, finished, { plan: row.plan });
  } else if (url.endsWith("/submit") && row.state === "READY_FOR_SUBMISSION") {
    row.state = "SUBMITTED";
    row.submitted_at = new Date().toISOString();
  }
  return { data: structuredClone(row) };
}) as typeof api.post;

type NativePlugin = {
  Pane: React.ComponentType<{ ctx: Record<string, never>; sessionId: string }>;
};
function Preview() {
  const [plugin, setPlugin] = React.useState<NativePlugin>();
  React.useEffect(() => {
    if (!harness) return;
    const host = window as typeof window & {
      __ADLC_VERIFY_UI__: { baseUrl: string };
      __ADLC_MEMORY_UI__: { baseUrl: string };
      __ModuleLoader__: {
        load: (entry: {
          factory: (require: () => typeof React) => NativePlugin;
        }) => void;
      };
    };
    host.__ADLC_VERIFY_UI__ = {
      baseUrl:
        location.origin +
        (extensionSlice
          ? "/offline-h6d"
          : replaySlice
            ? "/offline-h6b"
            : "/offline-h6a"),
    };
    host.__ModuleLoader__ = {
      // Uses the actual installed native client with a fake host registry only.
      load: ({ factory }) => setPlugin(() => factory(() => React)),
    };
    host.__ADLC_MEMORY_UI__ = { baseUrl: location.origin + "/offline-h6c" };
    const script = document.createElement("script");
    script.type = "module";
    script.src = memorySlice
      ? "/harness-memory-client.js"
      : "/harness-verification-client.js";
    document.body.appendChild(script);
    return () => script.remove();
  }, []);
  if (embedded)
    return (
      <main className="p-3">
        {memorySlice ? (
          <MemoryPanel scope={{ sessionId: "source-session" }} readOnly />
        ) : replaySlice ? (
          <>
            <ReplayPanel scope={{ sessionId: "source-session" }} readOnly />
            {extensionSlice && (
              <MemoryPanel scope={{ sessionId: "source-session" }} readOnly />
            )}
          </>
        ) : (
          <VerificationPanel scope={{ sessionId: "source-session" }} readOnly />
        )}
      </main>
    );
  return (
    <main className="mx-auto max-w-6xl p-6">
      <header className="mb-5 space-y-2">
        <p className="text-xs uppercase tracking-widest text-muted-foreground">
          Offline UI fixtures · illustrative data only · no actual verification
          or API/model calls
        </p>
        <h1 className="text-2xl font-semibold">
          {harness
            ? memorySlice
              ? "Harness Memory pane"
              : "Harness Verify pane"
            : memorySlice
              ? "ADLC Project memory · H6C"
              : replaySlice
                ? extensionSlice
                  ? "ADLC Test proposals & evidence · H6D"
                  : "ADLC Frozen replay · H6B"
                : "ADLC Verify · H6A"}
        </h1>
        <nav className="flex flex-wrap gap-4 text-sm underline">
          <a href="?mode=draft">Approve → run → submit demo</a>
          <a href="?mode=results">PASS / FAIL / uncertain</a>
          <a href="?host=harness">Harness projection</a>
          <a href="?theme=light">Light theme</a>
          <a href="?slice=h6b&theme=light">H6B replay evidence</a>
          <a href="?slice=h6b&mode=draft&theme=light">H6B approval demo</a>
          <a href="?slice=h6b&host=harness&theme=light">
            H6B Harness projection
          </a>
          <a href="?slice=h6c&theme=light">H6C project context</a>
          <a href="?slice=h6c&host=harness&theme=light">
            H6C Harness projection
          </a>
          <a href="?slice=h6d&theme=light">
            H6D coverage / proposals / screenshots
          </a>
          <a href="?slice=h6d&host=harness&theme=light">
            H6D Harness projection
          </a>
        </nav>
      </header>
      {harness ? (
        <div
          className="rounded-lg border"
          style={{
            marginLeft: "auto",
            height: 800,
            width: "100%",
            maxWidth: 440,
          }}
        >
          {plugin ? (
            React.createElement(plugin.Pane, {
              ctx: {},
              sessionId: "source-session",
            })
          ) : (
            <p>Loading read-only viewer…</p>
          )}
        </div>
      ) : memorySlice ? (
        <MemoryPanel scope={{ runId: "run-one" }} />
      ) : replaySlice ? (
        <>
          <ReplayPanel scope={{ runId: "run-one" }} />
          {extensionSlice && <MemoryPanel scope={{ runId: "run-one" }} />}
        </>
      ) : (
        <VerificationPanel scope={{ runId: "run-one" }} />
      )}
    </main>
  );
}
createRoot(document.getElementById("root")!).render(<Preview />);
