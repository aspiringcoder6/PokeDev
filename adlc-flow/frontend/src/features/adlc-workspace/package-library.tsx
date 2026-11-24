import { translateUi, useUiLocale, formatUiStatus } from "@/i18n/ui";
import { Box, FileText, GripVertical, Plus, Search, X } from "lucide-react";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { AdlcNodePackage } from "@/types/adlc";
import {
  type LibraryEntry,
  packageLabel,
  plannedPackages,
  visiblePackages,
} from "./builder-model";
import { useTranslation } from "react-i18next";
import "@/i18n";

type Props = {
  packages: AdlcNodePackage[];
  loading: boolean;
  error: boolean;
  readOnly: boolean;
  onAdd: (entry: LibraryEntry, screen?: { x: number; y: number }) => void;
  onClose: () => void;
  onRetry: () => void;
  canvas: React.RefObject<HTMLDivElement | null>;
};
export default function PackageLibrary({
  packages,
  loading,
  error,
  readOnly,
  onAdd,
  onClose,
  onRetry,
  canvas,
}: Props) {
  useUiLocale();
  const [search, setSearch] = useState("");
  const [dragLabel, setDragLabel] = useState<string | null>(null);
  const drag = useRef<{
    entry: LibraryEntry;
    x: number;
    y: number;
    moved: boolean;
    pointer: number;
  } | null>(null);
  const suppressClick = useRef(0);
  const matches = (text: string) =>
    `${text} ${translateUi(text)}`
      .toLowerCase()
      .includes(search.toLowerCase().trim());
  const card = (
    entry: LibraryEntry,
    label: string,
    description: string,
    status: string,
  ) => {
    label = translateUi(label);
    description = translateUi(description);
    return (
      <button
        key={`${entry.type}-${label}`}
        type="button"
        disabled={readOnly}
        aria-label={translateUi("Add {{value0}}", { value0: label })}
        title={translateUi(
          "{{value0}} Drag onto the canvas, or click to add.",
          { value0: description },
        )}
        className="group flex min-h-12 w-full touch-none items-start gap-2.5 rounded-lg border border-transparent px-2.5 py-3 text-left transition-colors hover:border-border hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
        onPointerDown={(event) => {
          if (readOnly || event.button !== 0) return;
          drag.current = {
            entry,
            x: event.clientX,
            y: event.clientY,
            moved: false,
            pointer: event.pointerId,
          };
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={(event) => {
          const active = drag.current;
          if (!active || active.pointer !== event.pointerId) return;
          if (
            Math.hypot(event.clientX - active.x, event.clientY - active.y) > 6
          ) {
            active.moved = true;
            setDragLabel(label);
          }
        }}
        onPointerUp={(event) => {
          const active = drag.current;
          drag.current = null;
          setDragLabel(null);
          if (!active || !active.moved) return;
          suppressClick.current = Date.now() + 400;
          const rect = canvas.current?.getBoundingClientRect();
          if (
            !readOnly &&
            rect &&
            event.clientX >= rect.left &&
            event.clientX <= rect.right &&
            event.clientY >= rect.top &&
            event.clientY <= rect.bottom
          )
            onAdd(active.entry, { x: event.clientX, y: event.clientY });
        }}
        onPointerCancel={() => {
          drag.current = null;
          setDragLabel(null);
        }}
        onClick={() => {
          if (Date.now() > suppressClick.current) onAdd(entry);
        }}
      >
        <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md border bg-background text-primary">
          {entry.type === "requirement" ? (
            <FileText size={15} />
          ) : (
            <Box size={15} />
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-xs font-semibold">{label}</span>
          <span className="mt-1 block text-[10px] leading-4 text-muted-foreground">
            {formatUiStatus(status)}
          </span>
        </span>
        <GripVertical
          size={12}
          className="mt-1 shrink-0 text-muted-foreground opacity-40 group-hover:opacity-100"
        />
      </button>
    );
  };
  return (
    <aside
      aria-label={translateUi("Package library")}
      className="absolute inset-y-0 left-0 z-20 flex w-[216px] shrink-0 flex-col border-r bg-card shadow-lg xl:relative xl:shadow-none"
    >
      <header className="flex h-12 shrink-0 items-center justify-between px-3">
        <h2 className="text-sm font-semibold">{translateUi("Add stage")}</h2>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          aria-label={translateUi("Hide package library")}
          onClick={onClose}
        >
          <X size={15} />
        </Button>
      </header>
      <div className="relative mx-3 mb-3">
        <Search
          size={13}
          className="pointer-events-none absolute left-2.5 top-2.5 text-muted-foreground"
        />
        <Input
          aria-label={translateUi("Search packages")}
          placeholder={translateUi("Find a package…")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="h-8 pl-8 text-xs"
        />
      </div>
      <div className="flex-1 overflow-y-auto px-1.5 pb-4">
        {matches(translateUi("Requirement workflow input")) &&
          card(
            { type: "requirement" },
            translateUi("Requirement"),
            translateUi("Supply a literal requirement to a named stage input."),
            translateUi("Workflow input"),
          )}
        <p className="px-2.5 pb-1 pt-4 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          {translateUi("Available packages")}
        </p>
        {loading && (
          <p role="status" className="px-3 py-2 text-xs text-muted-foreground">
            {translateUi("Loading packages…")}
          </p>
        )}
        {error && (
          <div className="space-y-2 px-3 py-2 text-xs">
            <p>{translateUi("Package access could not be loaded.")}</p>
            <Button variant="outline" size="sm" onClick={onRetry}>
              {translateUi("Retry")}
            </Button>
          </div>
        )}
        {!loading && !error && visiblePackages(packages).length === 0 && (
          <p className="px-3 py-2 text-xs text-muted-foreground">
            {translateUi(
              "No published packages are available to your account.",
            )}
          </p>
        )}
        {visiblePackages(packages)
          .filter((p) =>
            matches(
              `${p.name} ${packageLabel(p)} ${p.description} ${translateUi(p.description)}`,
            ),
          )
          .map((p) =>
            card(
              { type: "published", package: p },
              packageLabel(p),
              p.description,
              `v${p.version} · ${p.name.includes("(Mock)") || p.execution_profile?.provider_ref.startsWith("mock") ? translateUi("Mock runtime") : p.kind === "APPROVAL" ? translateUi("Human decision") : translateUi("Runtime required")}`,
            ),
          )}
        <details open className="mt-4 border-t pt-3">
          <summary className="cursor-pointer px-2.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            {translateUi("Future packages · WIP")}
          </summary>
          <p className="px-2.5 py-2 text-[11px] leading-4 text-muted-foreground">
            {translateUi(
              "Plan future work. Replace these stages before running.",
            )}
          </p>
          {plannedPackages
            .filter((p) =>
              matches(
                `${p.name} ${translateUi(p.name)} ${p.description} ${translateUi(p.description)} ${p.category} ${translateUi(p.category)}`,
              ),
            )
            .map((p) =>
              card(
                { type: "planned", package: p },
                p.name,
                p.description,
                `${translateUi(p.category)} · ${translateUi("Design only")}`,
              ),
            )}
        </details>
        {search &&
          !matches(translateUi("Requirement workflow input")) &&
          !visiblePackages(packages).some((p) =>
            matches(
              `${p.name} ${packageLabel(p)} ${p.description} ${translateUi(p.description)}`,
            ),
          ) &&
          !plannedPackages.some((p) =>
            matches(
              `${p.name} ${translateUi(p.name)} ${p.description} ${translateUi(p.description)} ${p.category} ${translateUi(p.category)}`,
            ),
          ) && (
            <p className="px-3 py-4 text-xs text-muted-foreground">
              {translateUi("No matching packages.")}
            </p>
          )}
      </div>
      <p className="flex shrink-0 items-center gap-1.5 border-t px-3 py-3 text-[10px] text-muted-foreground">
        <Plus size={12} /> {translateUi("Drag onto the canvas or click to add")}
      </p>
      {dragLabel && (
        <div
          role="status"
          className="pointer-events-none fixed bottom-20 left-1/2 z-50 -translate-x-1/2 rounded-lg border bg-card px-4 py-3 text-sm shadow-lg"
        >
          {translateUi("Drop")} {dragLabel} {translateUi("onto the canvas")}
        </div>
      )}
    </aside>
  );
}
