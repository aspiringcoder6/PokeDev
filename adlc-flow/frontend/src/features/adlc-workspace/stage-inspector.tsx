import { translateUi, useUiLocale } from "@/i18n/ui";
import { Link2, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import StageEditorDialog from "@/features/adlc-blueprint/stage-editor-dialog";
import type { AdlcNodePackage, AdlcWorkflowStage } from "@/types/adlc";
import type { AdlcAuthoringBlock, AllNodeType, EdgeType } from "@/types/flow";
import {
  blockName,
  boundRequirementInputs,
  packageForNode,
  plannedPackages,
} from "./builder-model";
import { useTranslation } from "react-i18next";
import "@/i18n";

type Props = {
  node: AllNodeType;
  nodes: AllNodeType[];
  edges: EdgeType[];
  packages: AdlcNodePackage[];
  readOnly: boolean;
  onClose: () => void;
  onDelete: () => void;
  onStage: (stage: AdlcWorkflowStage) => void;
  onDraft: (draft: AdlcAuthoringBlock) => void;
  onConnect: (source: string, target: string) => void;
  onRemoveEdge: (id: string) => void;
  onBindInput: (edge: EdgeType, input: string) => void;
};
export default function StageInspector({
  node,
  nodes,
  edges,
  packages,
  readOnly,
  onClose,
  onDelete,
  onStage,
  onDraft,
  onConnect,
  onRemoveEdge,
  onBindInput,
}: Props) {
  useUiLocale();
  const [draft, setDraft] = useState(node.data.adlcDraft);
  const [source, setSource] = useState("");
  useEffect(() => {
    setDraft(node.data.adlcDraft);
    setSource("");
  }, [node.id, node.data.adlcDraft]);
  const planned = plannedPackages.find(
    (p) => p.package_id === draft?.proposed_package_id,
  );
  const nodePackage = packageForNode(node, packages);
  const incoming = edges.filter((e) => e.target === node.id);
  const boundInputs = boundRequirementInputs(node.id, nodes, edges);
  return (
    <aside
      aria-label={translateUi("Stage inspector")}
      className="absolute inset-y-0 right-0 z-20 flex w-[min(320px,100%)] shrink-0 flex-col border-l bg-card shadow-lg xl:relative xl:w-[304px] xl:shadow-none"
    >
      <header className="flex h-12 shrink-0 items-center justify-between border-b px-4">
        <div className="min-w-0">
          <h2
            className="truncate text-sm font-semibold"
            title={blockName(node)}
          >
            {blockName(node)}
          </h2>
        </div>
        <Button
          aria-label={translateUi("Close stage inspector")}
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={onClose}
        >
          <X size={15} />
        </Button>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {draft && (
          <form
            className="space-y-4 px-4 py-5"
            onSubmit={(event) => {
              event.preventDefault();
              if (!readOnly && draft.name.trim() && draft.objective.trim())
                onDraft(draft);
            }}
          >
            <fieldset disabled={readOnly} className="space-y-4">
              <p className="rounded-lg border bg-muted/30 px-3 py-2.5 text-xs leading-5">
                {draft.kind === "PLANNED_PACKAGE"
                  ? translateUi(
                      "WIP · This package is available for planning. Replace it with a published package before reviewing or running a plan.",
                    )
                  : translateUi(
                      "This requirement supplies text to the named input on each connected stage.",
                    )}
              </p>
              <div className="space-y-2">
                <Label htmlFor="authoring-name">
                  {translateUi("Stage name")}
                </Label>
                <Input
                  id="authoring-name"
                  maxLength={256}
                  required
                  value={draft.name}
                  onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="authoring-objective">
                  {translateUi("Goal")}
                </Label>
                <Textarea
                  id="authoring-objective"
                  maxLength={2000}
                  required
                  value={draft.objective}
                  onChange={(e) =>
                    setDraft({ ...draft, objective: e.target.value })
                  }
                />
              </div>
              {draft.kind === "REQUIREMENT" && (
                <div className="space-y-2">
                  <Label htmlFor="authoring-requirement">
                    {translateUi("Requirement")}
                  </Label>
                  <Textarea
                    id="authoring-requirement"
                    placeholder={translateUi(
                      "What should the team build, and how will we know it is done?",
                    )}
                    required
                    maxLength={20000}
                    className="min-h-40"
                    value={draft.requirement ?? ""}
                    onChange={(e) =>
                      setDraft({ ...draft, requirement: e.target.value })
                    }
                  />
                </div>
              )}
              {planned && (
                <>
                  <dl className="space-y-2 text-xs">
                    <dt className="font-medium">
                      {translateUi("Planned inputs")}
                    </dt>
                    <dd className="text-muted-foreground">
                      {planned.inputs.join(", ")}
                    </dd>
                    <dt className="font-medium">
                      {translateUi("Planned outputs")}
                    </dt>
                    <dd className="text-muted-foreground">
                      {planned.outputs.join(", ")}
                    </dd>
                  </dl>
                  <div className="space-y-2">
                    <h3 className="text-xs font-semibold">
                      {translateUi("What makes this available")}
                    </h3>
                    <p className="text-xs leading-5 text-muted-foreground">
                      {translateUi(planned.delivery_gate)}
                    </p>
                  </div>
                </>
              )}
              <Button type="submit" size="sm" className="w-full">
                {translateUi("Save stage")}
              </Button>
            </fieldset>
          </form>
        )}
        {node.data.adlc &&
          (nodePackage ? (
            <StageEditorDialog
              embedded
              open
              readOnly={readOnly}
              packages={packages}
              initialStage={node.data.adlc}
              boundInputs={boundInputs}
              onSave={onStage}
              onOpenChange={onClose}
            />
          ) : (
            <div className="space-y-3 p-4 text-xs">
              <p>
                {translateUi(
                  "This exact package version is unavailable to your account. The saved stage is preserved.",
                )}
              </p>
              <pre className="overflow-auto whitespace-pre-wrap break-all">
                {JSON.stringify(node.data.adlc, null, 2)}
              </pre>
            </div>
          ))}
        {draft?.kind !== "REQUIREMENT" && (
          <section className="space-y-3 border-t p-4">
            <h3 className="flex items-center gap-2 text-xs font-semibold">
              <Link2 size={13} /> {translateUi("Dependencies")}
            </h3>
            <p className="text-[11px] leading-4 text-muted-foreground">
              {translateUi(
                "Connections define order. Use connection settings to bind compatible package outputs.",
              )}
            </p>
            {incoming.length === 0 && (
              <p className="text-xs text-muted-foreground">
                {translateUi("No incoming dependencies.")}
              </p>
            )}
            {incoming.map((edge) => {
              const upstream = nodes.find((n) => n.id === edge.source);
              const requirement =
                upstream?.data.adlcDraft?.kind === "REQUIREMENT";
              return (
                <div
                  key={edge.id}
                  className="space-y-2 rounded-lg border p-2.5"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-xs">
                      {upstream ? blockName(upstream) : edge.source}
                    </span>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-8 w-8 shrink-0"
                      disabled={readOnly}
                      aria-label={translateUi(
                        "Remove dependency from {{value0}}",
                        {
                          value0: upstream ? blockName(upstream) : edge.source,
                        },
                      )}
                      onClick={() => onRemoveEdge(edge.id)}
                    >
                      <X size={13} />
                    </Button>
                  </div>
                  {requirement && nodePackage && (
                    <div className="space-y-1">
                      <label
                        className="text-[10px] text-muted-foreground"
                        htmlFor={`bound-input-${edge.id}`}
                      >
                        {translateUi("Supplies stage input")}
                      </label>
                      <select
                        id={`bound-input-${edge.id}`}
                        disabled={readOnly}
                        value={String(
                          edge.data?.adlc?.metadata.authoring_input ??
                            "requirement",
                        )}
                        onChange={(e) => onBindInput(edge, e.target.value)}
                        className="h-8 w-full rounded-md border bg-background px-2 text-xs"
                      >
                        <option value="">
                          {translateUi("Choose an input")}
                        </option>
                        {nodePackage.interface.inputs.map((slot) => (
                          <option key={slot.name} value={slot.name}>
                            {slot.name}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}
                </div>
              );
            })}
            <div className="space-y-2">
              <label
                htmlFor="dependency-source"
                className="text-xs font-medium"
              >
                {translateUi("Connect from")}
              </label>
              <select
                id="dependency-source"
                disabled={readOnly}
                value={source}
                onChange={(e) => setSource(e.target.value)}
                className="h-9 w-full rounded-md border bg-background px-2 text-xs"
              >
                <option value="">{translateUi("Choose a stage")}</option>
                {nodes
                  .filter(
                    (n) =>
                      n.id !== node.id &&
                      !incoming.some((e) => e.source === n.id),
                  )
                  .map((n) => (
                    <option key={n.id} value={n.id}>
                      {blockName(n)}
                    </option>
                  ))}
              </select>
              <Button
                variant="outline"
                size="sm"
                className="w-full"
                disabled={readOnly || !source}
                onClick={() => {
                  onConnect(source, node.id);
                  setSource("");
                }}
              >
                {translateUi("Connect stages")}
              </Button>
            </div>
          </section>
        )}
      </div>
      <footer className="border-t px-4 py-3">
        <Button
          variant="ghost"
          size="sm"
          className="w-full text-destructive"
          disabled={readOnly}
          onClick={onDelete}
        >
          <Trash2 size={14} className="mr-2" />
          {translateUi("Remove stage")}
        </Button>
      </footer>
    </aside>
  );
}
