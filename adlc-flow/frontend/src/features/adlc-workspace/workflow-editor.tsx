import { translateUi, useUiLocale } from "@/i18n/ui";
import {
  applyEdgeChanges,
  applyNodeChanges,
  Background,
  BackgroundVariant,
  BaseEdge,
  type Connection,
  type EdgeProps,
  getBezierPath,
  MiniMap,
  type NodeChange,
  ReactFlow,
} from "@xyflow/react";
import {
  Columns3,
  Expand,
  LayoutGrid,
  Maximize2,
  Minus,
  PanelLeft,
  PanelRight,
  Pencil,
  Plus,
  Redo2,
  Save,
  Undo2,
  Workflow,
  X,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import AdlcEdge from "@/CustomEdges/AdlcEdge";
import NoteNode from "@/CustomNodes/NoteNode";
import AdlcBlueprintControls from "@/components/core/flowToolbarComponent/components/adlc-blueprint-controls";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useIsFlowReadOnly } from "@/contexts/permissionsContext";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import { useAdlcNodePackages } from "@/hooks/adlc/use-adlc-node-packages";
import useAutoSaveFlow from "@/hooks/flows/use-autosave-flow";
import useSaveFlow from "@/hooks/flows/use-save-flow";
import useAdlcBlueprintStore from "@/stores/adlcBlueprintStore";
import useFlowStore from "@/stores/flowStore";
import useFlowsManagerStore from "@/stores/flowsManagerStore";
import type { AdlcAuthoringBlock, AllNodeType, EdgeType } from "@/types/flow";
import {
  createAdlcCompatibilityNode,
  isAdlcStageNode,
} from "@/utils/adlc-blueprint";
import { customStringify } from "@/utils/reactflowUtils";
import {
  arrangeNodes,
  blockName,
  connectionError,
  createDependency,
  createLibraryNode,
  type LibraryEntry,
  packageForNode,
  plannedCount,
} from "./builder-model";
import PackageLibrary from "./package-library";
import ProjectSelector from "./project-selector";
import StageInspector from "./stage-inspector";
import WorkspaceStageNode from "./workspace-stage-node";
import CanvasProjectBridge from "./canvas-project-bridge";
import { useTranslation } from "react-i18next";
import "@/i18n";

function WorkspaceEdge(props: EdgeProps<EdgeType>) {
  const source = useFlowStore((s) =>
    s.nodes.find((n) => n.id === props.source),
  );
  const target = useFlowStore((s) =>
    s.nodes.find((n) => n.id === props.target),
  );
  if (isAdlcStageNode(source) && isAdlcStageNode(target))
    return <AdlcEdge {...props} />;
  const [path] = getBezierPath(props);
  return (
    <BaseEdge
      id={props.id}
      path={path}
      style={{
        stroke: "hsl(var(--muted-foreground))",
        strokeWidth: props.selected ? 2.5 : 1.5,
      }}
    />
  );
}
const nodeTypes = { adlcStageNode: WorkspaceStageNode, noteNode: NoteNode };
const edgeTypes = { adlcEdge: WorkspaceEdge };

export default function AdlcWorkflowEditor() {
  const { t } = useTranslation();
  useUiLocale();
  const flow = useFlowStore((s) => s.currentFlow);
  const nodes = useFlowStore((s) => s.nodes),
    edges = useFlowStore((s) => s.edges);
  const instance = useFlowStore((s) => s.reactFlowInstance);
  const setNodes = useFlowStore((s) => s.setNodes),
    setEdges = useFlowStore((s) => s.setEdges);
  const setGraph = useFlowStore((s) => s.setNodesAndEdges);
  const savedFlow = useFlowsManagerStore((s) => s.currentFlow);
  const saving = useFlowsManagerStore((s) => s.saveLoading);
  const snapshot = useFlowsManagerStore((s) => s.takeSnapshot);
  const undo = useFlowsManagerStore((s) => s.undo),
    redo = useFlowsManagerStore((s) => s.redo);
  const readOnly = useIsFlowReadOnly(flow?.id) || flow?.locked === true;
  const packagesQuery = useAdlcNodePackages(),
    packages = packagesQuery.data ?? [];
  const autoSave = useAutoSaveFlow(),
    saveFlow = useSaveFlow();
  const navigate = useCustomNavigate();
  const canvas = useRef<HTMLDivElement>(null);
  const [library, setLibrary] = useState(() => window.innerWidth >= 900);
  const [inspector, setInspector] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [focus, setFocus] = useState(false),
    [overview, setOverview] = useState(false);
  const [zoom, setZoom] = useState(flow?.data?.viewport.zoom ?? 1);
  const [notice, setNotice] = useState<string | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [descriptionDraft, setDescriptionDraft] = useState("");
  const selected = nodes.find((n) => n.id === selectedId);
  const accessibleNodes = useMemo(
    () =>
      nodes.map((node) => ({
        ...node,
        ariaLabel: t("adlc.ws.stageAria", { name: blockName(node) }),
      })),
    [nodes],
  );
  const wip = plannedCount(nodes);
  const dirty = customStringify(flow) !== customStringify(savedFlow);
  useEffect(() => {
    useFlowStore.setState({ autoSaveFlow: autoSave });
    return () => {
      autoSave.cancel();
      if (useFlowStore.getState().autoSaveFlow === autoSave)
        useFlowStore.setState({ autoSaveFlow: undefined });
    };
  }, [autoSave]);
  const add = (entry: LibraryEntry, screen?: { x: number; y: number }) => {
    if (readOnly || !instance) return;
    const rect = canvas.current?.getBoundingClientRect();
    const position = instance.screenToFlowPosition(
      screen ?? {
        x: (rect?.left ?? 0) + (rect?.width ?? 800) / 2,
        y: (rect?.top ?? 0) + (rect?.height ?? 600) / 2,
      },
    );
    const node = createLibraryNode(entry, {
      x: position.x - 132,
      y: position.y - 65,
    });
    snapshot();
    setNodes([...nodes.map((n) => ({ ...n, selected: false })), node]);
    setSelectedId(node.id);
    setInspector(true);
    setNotice(null);
    if (window.innerWidth < 1280) setLibrary(false);
  };
  const connect = (source: string, target: string) => {
    if (readOnly) return;
    const error = connectionError(source, target, nodes, edges);
    if (error) {
      setNotice(error);
      return;
    }
    const edge = createDependency(source, target, nodes);
    let nextNodes = nodes;
    if (
      nodes.find((n) => n.id === source)?.data.adlcDraft?.kind === "REQUIREMENT"
    ) {
      const targetNode = nodes.find((n) => n.id === target)!;
      const p = packageForNode(targetNode, packages);
      const input =
        p?.interface.inputs.find((i) => i.name === "requirement")?.name ??
        p?.interface.inputs[0]?.name ??
        "requirement";
      edge.data!.adlc!.metadata.authoring_input = input;
      nextNodes = nodes.map((n) => {
        if (n.id !== target || !isAdlcStageNode(n)) return n;
        const inputs = { ...n.data.adlc.inputs };
        delete inputs[input];
        return { ...n, data: { ...n.data, adlc: { ...n.data.adlc, inputs } } };
      });
    }
    snapshot();
    setGraph(nextNodes, [...edges, edge]);
    setNotice(null);
  };
  const onConnect = (connection: Connection) =>
    connect(connection.source, connection.target);
  const remove = () => {
    if (readOnly || !selectedId) return;
    snapshot();
    setGraph(
      nodes.filter((n) => n.id !== selectedId),
      edges.filter((e) => e.source !== selectedId && e.target !== selectedId),
    );
    setSelectedId(null);
  };
  const starter = () => {
    if (readOnly || nodes.length) return;
    const coding =
        packages.find(
          (p) => p.package_id === "coding-agent" && p.version === "0.3.0",
        ) ??
        packages.find(
          (p) => p.package_id === "coding-agent" && p.version === "0.2.1",
        ) ??
        packages.find(
          (p) => p.package_id === "coding-agent" && p.version === "0.2.0",
        ),
      approval = packages.find(
        (p) =>
          p.package_id === "approval" && p.lifecycle_status !== "DEPRECATED",
      );
    if (!coding || !approval) {
      setNotice(
        translateUi(
          "The Coding Agent and Human Approval packages must be available before adding this starter.",
        ),
      );
      return;
    }
    const next = [
      createLibraryNode({ type: "requirement" }, { x: 80, y: 120 }),
      createLibraryNode(
        { type: "published", package: coding },
        { x: 410, y: 120 },
      ),
      createLibraryNode(
        { type: "published", package: approval },
        { x: 740, y: 120 },
      ),
    ];
    next[1].data.adlc!.inputs = {};
    const nextEdges = [
      createDependency(next[0].id, next[1].id, next),
      createDependency(next[1].id, next[2].id, next),
    ];
    snapshot();
    setGraph(
      next.map((n) => ({ ...n, selected: false })),
      nextEdges,
    );
    setSelectedId(next[0].id);
    setInspector(true);
    requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        void instance?.fitView({ padding: 0.18, maxZoom: 1 });
      }),
    );
  };
  const persistViewport = (viewport: {
    x: number;
    y: number;
    zoom: number;
  }) => {
    setZoom(viewport.zoom);
    const current = useFlowStore.getState().currentFlow;
    if (
      readOnly ||
      !current?.data ||
      customStringify(current.data.viewport) === customStringify(viewport)
    )
      return;
    useFlowStore
      .getState()
      .setCurrentFlow({ ...current, data: { ...current.data, viewport } });
    autoSave();
  };
  const changeNodes = (changes: NodeChange<AllNodeType>[]) => {
    const allowed = readOnly
      ? changes.filter((c) => c.type === "select" || c.type === "dimensions")
      : changes;
    setNodes(applyNodeChanges(allowed, nodes));
    const selection = allowed.find(
      (change) => change.type === "select" && change.selected,
    );
    if (selection && "id" in selection) {
      setSelectedId(selection.id);
      setSelectedEdgeId(null);
      setInspector(true);
    }
  };
  return (
    <section
      className="adlc-workspace-designer flex h-full min-h-0 w-full flex-col bg-background text-foreground"
      aria-label={translateUi("Workflow designer")}
      data-testid="adlc-workspace-designer"
      onKeyDown={(event) => {
        const target = event.target as HTMLElement;
        if (target.closest("input,textarea,select,[contenteditable=true]"))
          return;
        if (event.key === "Escape") {
          setFocus(false);
          setSelectedId(null);
          setSelectedEdgeId(null);
        }
        if (
          (event.ctrlKey || event.metaKey) &&
          event.key.toLowerCase() === "s"
        ) {
          event.preventDefault();
          if (!readOnly) void saveFlow().catch(() => undefined);
        }
        if (
          !readOnly &&
          (event.ctrlKey || event.metaKey) &&
          event.key.toLowerCase() === "z"
        ) {
          event.preventDefault();
          event.shiftKey ? redo() : undo();
        }
        if (
          !readOnly &&
          (event.key === "Delete" || event.key === "Backspace") &&
          (selectedId || selectedEdgeId) &&
          !target.closest("button")
        ) {
          event.preventDefault();
          if (selectedId) remove();
          else {
            snapshot();
            setEdges(edges.filter((edge) => edge.id !== selectedEdgeId));
            setSelectedEdgeId(null);
          }
        }
      }}
    >
      <header className="flex min-h-14 shrink-0 flex-wrap items-center justify-between gap-2 border-b px-3 py-2 lg:px-5">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="hidden rounded-lg border p-2 text-primary sm:block">
            <Workflow size={16} />
          </span>
          <div className="min-w-0">
            <h1
              className="max-w-[180px] truncate text-sm font-semibold lg:max-w-xs"
              title={flow?.name}
            >
              {flow?.name}
            </h1>
            <p className="mt-0.5 text-[10px] text-muted-foreground">
              {readOnly
                ? translateUi("Read-only workflow")
                : saving
                  ? translateUi("Saving…")
                  : dirty
                    ? translateUi("Unsaved changes")
                    : translateUi("Saved workflow")}
              {wip
                ? translateUi(" · {{value0}} WIP stage{{value1}}", {
                    value0: wip,
                    value1: wip === 1 ? "" : "s",
                  })
                : ""}
            </p>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 shrink-0"
            aria-label={translateUi("Edit workflow details")}
            disabled={readOnly}
            onClick={() => {
              setNameDraft(flow?.name ?? "");
              setDescriptionDraft(flow?.description ?? "");
              setDetailsOpen(true);
            }}
          >
            <Pencil size={13} />
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-1">
          <ProjectSelector
            projectId={flow?.folder_id}
            disabled={readOnly || saving}
            onSelected={async (project) => {
              if (!flow || readOnly) return;
              useAdlcBlueprintStore.getState().clearValidation();
              useFlowStore
                .getState()
                .setCurrentFlow({ ...flow, folder_id: project.project_id });
              await saveFlow();
            }}
          />
          <Button
            variant="ghost"
            size="sm"
            disabled={readOnly || saving}
            onClick={() => void saveFlow().catch(() => undefined)}
          >
            <Save size={14} className="mr-1.5" />
            {translateUi("Save")}
          </Button>
          <AdlcBlueprintControls compact />
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate(`/runs?flowId=${flow?.id}`)}
            className="hidden lg:inline-flex"
          >
            {translateUi("Runs")}
          </Button>
        </div>
      </header>
      {flow && <CanvasProjectBridge flowId={flow.id} projectId={flow.folder_id} name={flow.name} disabled={readOnly || saving || !nodes.length} save={saveFlow} />}
      <div className="flex h-10 shrink-0 items-center justify-between gap-2 border-b px-3 text-xs">
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            aria-label={translateUi("Toggle package library")}
            aria-pressed={library && !focus}
            onClick={() => {
              setFocus(false);
              setLibrary(focus ? true : !library);
            }}
          >
            <PanelLeft size={15} />
          </Button>
          <span className="hidden text-xs font-medium sm:inline">
            {translateUi("Designer")}
          </span>
          <span className="hidden px-2 text-muted-foreground md:inline">
            {translateUi("{{stages}} stages · {{connections}} connections", {
              stages: nodes.length,
              connections: edges.length,
            })}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            aria-label={translateUi("Undo graph edit")}
            disabled={readOnly}
            onClick={undo}
          >
            <Undo2 size={14} />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            aria-label={translateUi("Redo graph edit")}
            disabled={readOnly}
            onClick={redo}
          >
            <Redo2 size={14} />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            disabled={readOnly || !nodes.length}
            onClick={() => {
              snapshot();
              setNodes(arrangeNodes(nodes, edges));
              requestAnimationFrame(() => {
                void instance?.fitView({ padding: 0.2, maxZoom: 1 });
              });
            }}
          >
            <Columns3 size={14} className="mr-1.5" />
            {translateUi("Arrange")}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            aria-label={translateUi("Toggle stage inspector")}
            aria-pressed={inspector && !focus}
            onClick={() => {
              setFocus(false);
              setInspector(focus ? true : !inspector);
            }}
          >
            <PanelRight size={15} />
          </Button>
          <Button
            variant={focus ? "secondary" : "ghost"}
            size="icon"
            className="h-8 w-8"
            aria-label={translateUi("Focus canvas")}
            aria-pressed={focus}
            onClick={() => setFocus(!focus)}
          >
            <Expand size={15} />
          </Button>
        </div>
      </div>
      <div className="relative flex min-h-0 flex-1 overflow-hidden">
        {library && !focus && (
          <PackageLibrary
            packages={packages}
            loading={packagesQuery.isLoading}
            error={packagesQuery.isError}
            onRetry={() => void packagesQuery.refetch()}
            readOnly={readOnly}
            onAdd={add}
            onClose={() => setLibrary(false)}
            canvas={canvas}
          />
        )}
        <div
          ref={canvas}
          className="relative min-w-0 flex-1 bg-canvas"
          data-testid="adlc-workspace-canvas"
        >
          <ReactFlow<AllNodeType, EdgeType>
            nodes={accessibleNodes}
            edges={edges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            aria-label={translateUi(
              "Workflow canvas. Drag empty space to pan. Use the zoom controls or pinch to zoom.",
            )}
            onInit={useFlowStore.getState().setReactFlowInstance}
            defaultViewport={flow?.data?.viewport}
            onNodesChange={changeNodes}
            onEdgesChange={(changes) => {
              const selection = changes.find(
                (change) => change.type === "select" && change.selected,
              );
              if (selection && "id" in selection) {
                setSelectedId(null);
                setSelectedEdgeId(selection.id);
              }
              setEdges(
                applyEdgeChanges(
                  readOnly
                    ? changes.filter((c) => c.type === "select")
                    : changes,
                  edges,
                ),
              );
            }}
            onConnect={readOnly ? undefined : onConnect}
            isValidConnection={(connection) =>
              !readOnly &&
              !connectionError(
                connection.source,
                connection.target,
                nodes,
                edges,
              )
            }
            onNodeClick={(_, node) => {
              setSelectedId(node.id);
              setInspector(true);
            }}
            onEdgeClick={(_, edge) => {
              setSelectedId(null);
              setSelectedEdgeId(edge.id);
            }}
            onPaneClick={() => {
              setSelectedId(null);
              setSelectedEdgeId(null);
            }}
            onNodeDragStart={() => {
              if (!readOnly) snapshot();
            }}
            onMove={(_, viewport) => setZoom(viewport.zoom)}
            onMoveEnd={(_, viewport) => persistViewport(viewport)}
            nodesDraggable={!readOnly}
            nodesConnectable={!readOnly}
            edgesReconnectable={false}
            deleteKeyCode={null}
            minZoom={0.15}
            maxZoom={2.5}
            zoomOnScroll
            zoomOnPinch
            panOnDrag
            panOnScroll={false}
            selectionOnDrag={false}
            proOptions={{ hideAttribution: true }}
            className="theme-attribution"
            fitView={false}
          >
            <Background
              variant={BackgroundVariant.Dots}
              gap={20}
              size={1}
              color="hsl(var(--muted-foreground) / .22)"
            />
            {overview && (
              <MiniMap
                pannable
                zoomable
                nodeColor="hsl(var(--primary))"
                maskColor="hsl(var(--muted) / .6)"
                style={{
                  backgroundColor: "hsl(var(--card))",
                  width: 160,
                  height: 110,
                }}
              />
            )}
          </ReactFlow>
          {!nodes.length && (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center px-6">
              <div className="max-w-sm text-center">
                <Workflow size={28} className="mx-auto mb-4 text-primary" />
                <h2 className="text-lg font-semibold">
                  {translateUi("Build a workflow")}
                </h2>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  {translateUi(
                    "Add packages from the library, connect the stages, and review the plan before running.",
                  )}
                </p>
                <div className="pointer-events-auto mt-5 flex justify-center gap-2">
                  <Button
                    variant="outline"
                    disabled={readOnly}
                    onClick={() => setLibrary(true)}
                  >
                    {translateUi("Add a stage")}
                  </Button>
                  <Button
                    disabled={readOnly || packagesQuery.isLoading}
                    onClick={starter}
                  >
                    {translateUi("Use coding starter")}
                  </Button>
                </div>
              </div>
            </div>
          )}
          <div
            className="absolute bottom-4 left-4 flex items-center gap-0.5 rounded-lg border bg-card p-1 shadow-sm"
            role="group"
            aria-label={translateUi("Canvas view controls")}
          >
            <Button
              variant="ghost"
              size="icon"
              className="h-9 w-9"
              aria-label={translateUi("Zoom out")}
              onClick={() => void instance?.zoomOut({ duration: 150 })}
            >
              <Minus size={15} />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="w-14 px-1 tabular-nums"
              aria-label={translateUi("Reset zoom to 100 percent")}
              onClick={() => void instance?.zoomTo(1, { duration: 150 })}
            >
              {Math.round(zoom * 100)}%
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-9 w-9"
              aria-label={translateUi("Zoom in")}
              onClick={() => void instance?.zoomIn({ duration: 150 })}
            >
              <Plus size={15} />
            </Button>
            <span className="mx-1 h-5 border-l" />
            <Button
              variant="ghost"
              size="icon"
              className="h-9 w-9"
              aria-label={translateUi("Fit workflow to canvas")}
              onClick={() =>
                void instance?.fitView({
                  padding: 0.2,
                  maxZoom: 1.2,
                  duration: 200,
                })
              }
            >
              <Maximize2 size={15} />
            </Button>
            <Button
              variant={overview ? "secondary" : "ghost"}
              size="icon"
              className="h-9 w-9"
              aria-label={translateUi("Toggle canvas overview")}
              aria-pressed={overview}
              onClick={() => setOverview(!overview)}
            >
              <LayoutGrid size={15} />
            </Button>
          </div>
          <p className="pointer-events-none absolute bottom-5 right-4 hidden text-[10px] text-muted-foreground 2xl:block">
            {translateUi("Drag empty space to pan · Scroll or pinch to zoom")}
          </p>
        </div>
        {selected && inspector && !focus && (
          <StageInspector
            key={selected.id}
            node={selected}
            nodes={nodes}
            edges={edges}
            packages={packages}
            readOnly={readOnly}
            onClose={() => setInspector(false)}
            onDelete={remove}
            onConnect={connect}
            onRemoveEdge={(id) => {
              if (!readOnly) {
                snapshot();
                setEdges(edges.filter((e) => e.id !== id));
              }
            }}
            onDraft={(draft: AdlcAuthoringBlock) => {
              if (!readOnly) {
                snapshot();
                setNodes(
                  nodes.map((n) =>
                    n.id === selected.id
                      ? ({
                          ...n,
                          data: {
                            ...n.data,
                            adlcDraft: draft,
                            node: {
                              ...n.data.node,
                              display_name: draft.name,
                              description: draft.objective,
                            },
                          },
                        } as AllNodeType)
                      : n,
                  ),
                );
              }
            }}
            onStage={(stage) => {
              if (!readOnly) {
                snapshot();
                setNodes(
                  nodes.map((n) =>
                    n.id === selected.id
                      ? ({
                          ...n,
                          data: {
                            ...n.data,
                            adlc: stage,
                            node: createAdlcCompatibilityNode(stage),
                          },
                        } as AllNodeType)
                      : n,
                  ),
                );
              }
            }}
            onBindInput={(edge, input) => {
              if (readOnly) return;
              snapshot();
              const next = nodes.map((n) => {
                if (n.id !== edge.target || !isAdlcStageNode(n)) return n;
                const inputs = { ...n.data.adlc.inputs };
                delete inputs[input];
                return {
                  ...n,
                  data: { ...n.data, adlc: { ...n.data.adlc, inputs } },
                };
              });
              setGraph(
                next,
                edges.map((e) =>
                  e.id === edge.id
                    ? {
                        ...e,
                        data: {
                          ...e.data!,
                          adlc: {
                            ...e.data!.adlc!,
                            metadata: {
                              ...e.data!.adlc!.metadata,
                              authoring_input: input,
                            },
                          },
                        },
                      }
                    : e,
                ),
              );
            }}
          />
        )}
      </div>
      {notice && (
        <div
          role="status"
          className="flex shrink-0 items-center justify-between gap-3 border-t bg-card px-4 py-2 text-xs"
        >
          <span>{notice}</span>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            aria-label={translateUi("Dismiss canvas message")}
            onClick={() => setNotice(null)}
          >
            <X size={13} />
          </Button>
        </div>
      )}
      <footer className="flex h-7 shrink-0 items-center justify-between gap-3 border-t px-3 text-[10px] text-muted-foreground">
        <span>
          {wip
            ? translateUi("Design draft · WIP stages cannot enter execution")
            : translateUi(
                "Configuration and dependency changes require a reviewed plan",
              )}
        </span>
        <span className="hidden sm:inline">
          {translateUi("PokeDev · Workflow designer")}
        </span>
      </footer>
      <Dialog open={detailsOpen} onOpenChange={setDetailsOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{translateUi("Workflow details")}</DialogTitle>
            <DialogDescription>
              {translateUi("Name the work and describe its outcome.")}
            </DialogDescription>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={async (event) => {
              event.preventDefault();
              if (readOnly || !flow || !nameDraft.trim()) return;
              if (descriptionDraft !== flow.description)
                useAdlcBlueprintStore.getState().clearValidation();
              useFlowStore.getState().setCurrentFlow({
                ...flow,
                name: nameDraft.trim(),
                description: descriptionDraft,
              });
              try {
                await saveFlow();
                setDetailsOpen(false);
              } catch {
                /* Persistence errors are reported by the shared save hook. */
              }
            }}
          >
            <div className="space-y-2">
              <Label htmlFor="workflow-name">
                {translateUi("Workflow name")}
              </Label>
              <Input
                id="workflow-name"
                required
                maxLength={255}
                disabled={readOnly}
                value={nameDraft}
                onChange={(event) => setNameDraft(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="workflow-description">
                {translateUi("Outcome")}
              </Label>
              <Textarea
                id="workflow-description"
                disabled={readOnly}
                value={descriptionDraft}
                onChange={(event) => setDescriptionDraft(event.target.value)}
              />
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setDetailsOpen(false)}
              >
                {translateUi("Cancel")}
              </Button>
              <Button type="submit" loading={saving} disabled={readOnly}>
                {translateUi("Save workflow")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </section>
  );
}
