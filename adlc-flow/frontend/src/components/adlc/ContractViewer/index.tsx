import { translateUi, useUiLocale, formatUiStatus } from "@/i18n/ui";
import { useId, useState } from "react";
import type { ContractRead } from "@/types/contracts";
import { isSupportedContract, skilltreeLayout } from "./model";
import { useTranslation } from "react-i18next";
import "@/i18n";

export default function ContractViewer({
  contract,
}: {
  contract: ContractRead;
}) {
  useUiLocale();
  const marker = useId().replaceAll(":", "");
  const [selectedNode, setSelectedNode] = useState<string>();
  const [tab, setTab] = useState<"roadmap" | "json">("roadmap");
  const supported = isSupportedContract(contract);
  const doc = contract.document;
  const layout = supported ? skilltreeLayout(contract) : null;
  const node = supported
    ? doc.nodes.find((item) => item.node_id === selectedNode)
    : undefined;
  const rawJson = (
    <pre className="max-h-[36rem] overflow-auto whitespace-pre-wrap break-all rounded-lg border bg-muted/30 p-4 text-xs">
      {JSON.stringify(contract, null, 2)}
    </pre>
  );
  if (!supported)
    return (
      <section
        aria-label={translateUi("Contract JSON fallback")}
        className="space-y-3"
      >
        <p role="status">
          {translateUi(
            "This schema/renderer or receipt is unsupported. Showing escaped JSON; review actions are unavailable.",
          )}
        </p>
        {rawJson}
      </section>
    );
  return (
    <section
      aria-label={translateUi("Skilltree contract")}
      className="space-y-5"
    >
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs uppercase tracking-widest text-muted-foreground">
            {translateUi("Skilltree · revision")} {doc.revision}
          </p>
          <h3 className="mt-1 break-words text-xl font-semibold">
            {doc.title}
          </h3>
        </div>
        <span
          className={`rounded-full border px-3 py-1 text-xs font-semibold ${contract.status === "APPROVED" ? "border-accent-emerald bg-accent-emerald text-accent-emerald-foreground" : "bg-muted/40"}`}
        >
          {formatUiStatus(contract.status)}
        </span>
      </header>
      <div className="rounded-lg border bg-muted/20 p-3 text-xs">
        <p className="break-all font-mono">{contract.reference.contract_id}</p>
        <p className="mt-1 break-all font-mono">
          {contract.reference.content_digest}
        </p>
        <p className="mt-2 text-muted-foreground">
          {translateUi(
            "Declaration checks do not execute acceptance criteria. Roadmap execution policy and evidence are reported separately, not by this document viewer.",
          )}
        </p>
      </div>
      <p className="whitespace-pre-wrap break-words text-sm">
        {doc.scope.objective}
      </p>
      <div className="grid gap-3 md:grid-cols-2">
        <ScopeList
          title={translateUi("In scope")}
          values={doc.scope.in_scope}
        />
        <ScopeList
          title={translateUi("Out of scope")}
          values={doc.scope.out_of_scope}
        />
      </div>
      <details className="rounded-lg border p-3">
        <summary className="cursor-pointer text-sm font-medium">
          {translateUi("Declared constraints ·")}{" "}
          {doc.constraints.read_only
            ? "read-only"
            : translateUi("changes permitted in scope")}
        </summary>
        <ScopeList
          title={translateUi("Allowed paths (declaration only)")}
          values={doc.constraints.allowed_paths}
        />
        <ScopeList
          title={translateUi("Forbidden actions")}
          values={doc.constraints.forbidden_actions}
        />
        {doc.supersedes && (
          <p className="mt-2 break-all font-mono text-xs">
            {translateUi("Supersedes")} {doc.supersedes.contract_id}{" "}
            {translateUi("· revision")} {doc.supersedes.revision} ·{" "}
            {doc.supersedes.content_digest}
          </p>
        )}
      </details>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b pb-3">
        <div
          className="flex gap-2"
          role="group"
          aria-label={translateUi("Contract view")}
        >
          {(["roadmap", "json"] as const).map((item) => (
            <button
              key={item}
              type="button"
              aria-pressed={tab === item}
              className={`rounded-md border px-3 py-1.5 text-sm ${tab === item ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}
              onClick={() => setTab(item)}
            >
              {item === "roadmap"
                ? translateUi("Roadmap")
                : translateUi("JSON & receipts")}
            </button>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">
          {doc.nodes.length} {translateUi("nodes ·")} {doc.dependencies.length}{" "}
          relationships
        </p>
      </div>
      {tab === "json" ? (
        rawJson
      ) : (
        <>
          <p className="text-xs text-muted-foreground">
            {translateUi(
              "Solid: requires (prerequisite → dependent). Dashed: contains (milestone → child). Select a node for its full criteria.",
            )}
          </p>
          {layout && doc.nodes.length > 0 ? (
            <div
              className="max-h-[32rem] overflow-auto rounded-xl border bg-muted/10"
              aria-label={translateUi("Roadmap graph")}
            >
              <div
                className="relative"
                style={{ width: layout.width, height: layout.height }}
              >
                <svg
                  width={layout.width}
                  height={layout.height}
                  className="absolute inset-0 text-muted-foreground"
                  aria-hidden="true"
                >
                  <defs>
                    <marker
                      id={marker}
                      markerWidth="8"
                      markerHeight="8"
                      refX="7"
                      refY="4"
                      orient="auto"
                    >
                      <path d="M0 0 L8 4 L0 8" fill="currentColor" />
                    </marker>
                  </defs>
                  {doc.dependencies.map((edge) => {
                    const a = layout.points.get(edge.source_id)!;
                    const b = layout.points.get(edge.target_id)!;
                    return (
                      <path
                        key={`${edge.source_id}-${edge.target_id}-${edge.relation}`}
                        d={`M ${a.x + 240} ${a.y + 44} C ${a.x + 264} ${a.y + 44}, ${b.x - 24} ${b.y + 44}, ${b.x} ${b.y + 44}`}
                        stroke="currentColor"
                        fill="none"
                        strokeWidth="1.5"
                        strokeDasharray={
                          edge.relation === "CONTAINS" ? "5 4" : undefined
                        }
                        markerEnd={`url(#${marker})`}
                      />
                    );
                  })}
                </svg>
                {doc.nodes.map((item) => {
                  const point = layout.points.get(item.node_id)!;
                  return (
                    <button
                      key={item.node_id}
                      type="button"
                      title={item.title}
                      aria-pressed={node?.node_id === item.node_id}
                      onClick={() => setSelectedNode(item.node_id)}
                      className={`absolute flex h-[88px] w-[240px] flex-col items-start rounded-lg border bg-background p-3 text-left shadow-sm hover:border-primary focus-visible:outline-primary ${node?.node_id === item.node_id ? "border-primary ring-1 ring-primary" : ""}`}
                      style={{ left: point.x, top: point.y }}
                    >
                      <span className="text-[10px] uppercase tracking-widest text-muted-foreground">
                        {formatUiStatus(item.kind)}
                      </span>
                      <span className="mt-1 line-clamp-2 w-full break-words text-sm font-medium">
                        {item.title}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          ) : (
            <p className="rounded-lg border border-dashed p-5 text-sm text-muted-foreground">
              {translateUi(
                "The draft has no nodes yet. The agent can add them through the writer tools.",
              )}
            </p>
          )}
          {node && <NodeDetail node={node} />}
          <details className="rounded-lg border p-4">
            <summary className="cursor-pointer text-sm font-medium">
              {translateUi("Full roadmap details and relationships")}
            </summary>
            <div className="mt-4 space-y-3">
              {doc.nodes.map((item) => (
                <NodeDetail key={item.node_id} node={item} />
              ))}
            </div>
            <ol className="mt-4 space-y-2 text-xs">
              {doc.dependencies.map((edge) => (
                <li
                  key={`${edge.source_id}-${edge.target_id}-${edge.relation}`}
                  className="break-words"
                >
                  {doc.nodes.find((n) => n.node_id === edge.source_id)?.title}{" "}
                  <span className="font-semibold">
                    {edge.relation === "CONTAINS"
                      ? "contains"
                      : translateUi("is required by")}
                  </span>{" "}
                  {doc.nodes.find((n) => n.node_id === edge.target_id)?.title}
                  <p className="break-all font-mono text-muted-foreground">
                    {edge.source_id} → {edge.target_id}
                  </p>
                </li>
              ))}
            </ol>
          </details>
        </>
      )}
      {contract.validation && (
        <details className="rounded-lg border p-3">
          <summary className="cursor-pointer text-sm">
            {translateUi("Declaration validation ·")}{" "}
            {contract.validation.passed
              ? "passed"
              : translateUi("needs changes")}
          </summary>
          <ul className="mt-2 space-y-1 text-xs">
            {contract.validation.checks.map((check) => (
              <li key={check.check_id}>
                {check.passed ? "✓" : "×"} {check.summary}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-muted-foreground">
            {translateUi("No acceptance criteria executed ·")}{" "}
            {contract.validation.checked_at}
          </p>
        </details>
      )}
      {contract.approval && (
        <div className="rounded-lg border border-accent-emerald bg-accent-emerald/20 p-3 text-xs">
          <p>
            {translateUi("Human-approved exact revision")}{" "}
            {contract.approval.reference.revision}. Content is locked.
          </p>
          <p className="mt-1 break-all text-muted-foreground">
            {translateUi("By")} {contract.approval.approved_by} ·{" "}
            {contract.approval.approved_at}
          </p>
          {contract.approval.comment && (
            <p className="mt-2 whitespace-pre-wrap">
              {contract.approval.comment}
            </p>
          )}
        </div>
      )}
    </section>
  );
}

function ScopeList({ title, values }: { title: string; values: string[] }) {
  useUiLocale();
  return (
    <div className="mt-2 text-sm">
      <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h4>
      {values.length ? (
        <ul className="mt-1 list-inside list-disc space-y-1">
          {values.map((value, index) => (
            <li className="whitespace-pre-wrap break-words" key={index}>
              {value}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1 text-xs text-muted-foreground">
          {translateUi("Not declared")}
        </p>
      )}
    </div>
  );
}
function NodeDetail({
  node,
}: {
  node: ContractRead["document"]["nodes"][number];
}) {
  useUiLocale();
  return (
    <article className="rounded-lg border bg-muted/10 p-4">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">
        {formatUiStatus(node.kind)}
      </p>
      <h4 className="mt-1 break-words font-medium">{node.title}</h4>
      <p className="mt-1 break-all font-mono text-[10px] text-muted-foreground">
        {node.node_id}
      </p>
      <p className="mt-3 whitespace-pre-wrap break-words text-sm">
        {node.description}
      </p>
      <ol className="mt-3 space-y-2 text-sm">
        {node.acceptance_criteria.map((criterion, index) => (
          <li key={index} className="rounded-md border p-2">
            <p className="whitespace-pre-wrap break-words">
              {index + 1}. {criterion.description}
            </p>
            <p className="mt-1 break-all text-xs text-muted-foreground">
              {criterion.verification} ·{" "}
              {criterion.verifier_ref ?? translateUi("human review")}{" "}
              {translateUi("· not executed")}
            </p>
          </li>
        ))}
      </ol>
    </article>
  );
}
