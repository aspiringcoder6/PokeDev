import { translateUi, useUiLocale } from "@/i18n/ui";
import { ArrowRight, Box, GitBranch } from "lucide-react";
import { useStartNewFlow } from "@/components/core/flowBuilderWelcome/hooks/use-start-new-flow";
import { Button } from "@/components/ui/button";
import { useAdlcNodePackages } from "@/hooks/adlc/use-adlc-node-packages";
import {
  packageLabel,
  plannedPackages,
  visiblePackages,
} from "./builder-model";
import { useTranslation } from "react-i18next";
import "@/i18n";

export default function WorkspaceLibraryPage() {
  useUiLocale();
  const query = useAdlcNodePackages();
  const start = useStartNewFlow();
  return (
    <main className="h-full w-full overflow-auto p-5 lg:p-8">
      <div className="mx-auto max-w-5xl space-y-8">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="mb-2 text-xs font-medium text-primary">
              {translateUi("PokeDev · Resources")}
            </p>
            <h1 className="text-2xl font-semibold tracking-tight">
              {translateUi("Package library")}
            </h1>
            <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
              {translateUi(
                "Compose workflows from versioned packages. Every stage keeps its own inputs, settings, and review gates.",
              )}
            </p>
          </div>
          <Button onClick={() => void start().catch(() => undefined)}>
            <GitBranch size={15} className="mr-2" />
            {translateUi("New workflow")}
          </Button>
        </header>
        <section className="rounded-xl border bg-card p-5">
          <h2 className="text-sm font-semibold">
            {translateUi("Start with one outcome")}
          </h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            {translateUi(
              "Add a Requirement, connect it to a Coding Agent, and finish with Human Approval. You can add an approved contract, repeat verification checks, or use both in the same Coding Agent.",
            )}
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
            {[
              translateUi("Requirement"),
              translateUi("Coding Agent"),
              translateUi("Human Approval"),
            ].map((label, index) => (
              <span key={label} className="inline-flex items-center gap-2">
                <span className="rounded-md border bg-background px-3 py-2">
                  {label}
                </span>
                {index < 2 && (
                  <ArrowRight size={13} className="text-muted-foreground" />
                )}
              </span>
            ))}
          </div>
        </section>
        <section className="space-y-4">
          <h2 className="text-sm font-semibold">
            {translateUi("Available to your account")}
          </h2>
          {query.isLoading && (
            <p role="status" className="text-sm text-muted-foreground">
              {translateUi("Loading packages…")}
            </p>
          )}
          {query.isError && (
            <div className="text-sm">
              <p>{translateUi("Package access could not be loaded.")}</p>
              <Button
                className="mt-3"
                variant="outline"
                onClick={() => void query.refetch()}
              >
                {translateUi("Retry")}
              </Button>
            </div>
          )}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {visiblePackages(query.data ?? []).map((p) => (
              <article
                key={`${p.package_id}@${p.version}`}
                className="space-y-3 rounded-xl border bg-card p-5"
              >
                <div className="flex items-center justify-between">
                  <Box size={18} className="text-primary" />
                  <span className="rounded border px-2 py-0.5 text-[10px]">
                    v{p.version}
                  </span>
                </div>
                <h3 className="text-sm font-semibold">{packageLabel(p)}</h3>
                <p className="text-xs leading-5 text-muted-foreground">
                  {translateUi(p.description)}
                </p>
                <p className="border-t pt-3 text-[10px] text-muted-foreground">
                  {p.name.includes("(Mock)") ||
                  p.execution_profile?.provider_ref.startsWith("mock")
                    ? translateUi("Mock runtime")
                    : p.kind === "APPROVAL"
                      ? translateUi("Authorized human decision")
                      : translateUi(
                          "Execution requires permitted, configured runtime references",
                        )}
                </p>
              </article>
            ))}
          </div>
          {query.isSuccess && !visiblePackages(query.data).length && (
            <p className="text-sm text-muted-foreground">
              {translateUi(
                "No published packages are available. Ask your workspace administrator to enable package access.",
              )}
            </p>
          )}
        </section>
        <section className="space-y-4">
          <div>
            <h2 className="text-sm font-semibold">
              {translateUi("Future packages · WIP")}
            </h2>
            <p className="mt-2 text-xs text-muted-foreground">
              {translateUi(
                "Add these to design drafts to plan the wider development lifecycle. They cannot be reviewed or run until implemented and published.",
              )}
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {plannedPackages.map((p) => (
              <article
                key={p.package_id}
                className="rounded-xl border border-dashed bg-card p-5"
              >
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-sm font-semibold">
                    {translateUi(p.name)}
                  </h3>
                  <span className="rounded border px-2 py-0.5 text-[10px] text-muted-foreground">
                    {translateUi(p.category)} {translateUi("· WIP")}
                  </span>
                </div>
                <p className="mt-2 text-xs leading-5 text-muted-foreground">
                  {translateUi(p.description)}
                </p>
                <details className="mt-3 text-xs">
                  <summary className="cursor-pointer font-medium text-muted-foreground">
                    {translateUi("Delivery requirements")}
                  </summary>
                  <p className="mt-2 leading-5 text-muted-foreground">
                    {translateUi(p.delivery_gate)}
                  </p>
                </details>
              </article>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
