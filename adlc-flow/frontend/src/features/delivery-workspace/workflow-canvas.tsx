import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useNodesState,
  type NodeProps,
  type Node,
  type Connection,
  type ReactFlowInstance,
} from "@xyflow/react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Code2,
  FlaskConical,
  GitBranch,
  LayoutGrid,
  LoaderCircle,
  Plus,
  Redo2,
  Maximize2,
  Minimize2,
  PanelLeft,
  PanelRight,
  Scan,
  FileJson2,
  Shapes,
  Save,
  ShieldCheck,
  Trash2,
  Undo2,
  Workflow,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useBlocker } from "react-router-dom";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  liveCodeMessage,
  liveError,
  liveWorkflows,
  type LiveProject,
  type LiveTask,
  type ProjectWorkflow,
  type WorkflowGraph,
  type WorkflowEdge,
} from "@/controllers/API/live-workflows";
import {
  commandArgs,
  commandText,
  connectionIssue,
  newTask,
  taskKinds,
  controlKinds,
  outputPorts,
  portLabels,
  arrangeGraph,
  duplicateTask,
  nextTaskId,
  renameTask,
  templateGraph,
  workflowTemplates,
  templateSources,
  parseGraph,
} from "./workflow-canvas-model";
import WorkflowTaskInspector from "./workflow-task-inspector";
import WorkflowJsonEditor from "./workflow-json-editor";
import "@xyflow/react/dist/style.css";
import "./workflow-canvas.css";

type TaskNodeType = Node<{ task: LiveTask }, "projectTask">;
function TaskNode({ data, selected }: NodeProps<TaskNodeType>) {
  const kind =
    (data.task.control && controlKinds[data.task.control.type]) ||
    taskKinds[data.task.kind as keyof typeof taskKinds] ||
    taskKinds.implement;
  const Icon =
    data.task.kind === "test"
      ? FlaskConical
      : data.task.kind === "review"
        ? ShieldCheck
        : Code2;
  return (
    <div className={`wc-node ${kind.color} ${selected ? "selected" : ""}`}>
      <Handle type="target" position={Position.Left} />
      <div className="wc-node-top">
        <span>
          <Icon size={13} />
          {kind.name}
        </span>
        <code>{data.task.id}</code>
      </div>
      <strong>{data.task.title}</strong>
      <small>
        {data.task.kind === "review"
          ? "Chỉ đọc"
          : `${data.task.write_paths?.length || 0} file trong phạm vi`}
      </small>
      {outputPorts(data.task).map((port) => (
        <div className="wc-port" key={port}>
          {data.task.control && <span>{portLabels[port]}</span>}
          <Handle id={port} type="source" position={Position.Right} />
        </div>
      ))}
    </div>
  );
}
const nodeTypes = { projectTask: TaskNode };

type Props = {
  workflow: ProjectWorkflow;
  projects: LiveProject[];
  onClose: () => void;
  onSaved: (workflow: ProjectWorkflow) => void;
  onUse: (workflow: ProjectWorkflow) => Promise<void> | void;
  applying?: boolean;
};

export default function WorkflowCanvas(props: Props) {
  return (
    <ReactFlowProvider>
      <Canvas {...props} />
    </ReactFlowProvider>
  );
}

function Canvas({
  workflow,
  projects,
  onClose,
  onSaved,
  onUse,
  applying,
}: Props) {
  const [saved, setSaved] = useState(workflow);
  const [name, setName] = useState(workflow.name),
    [project, setProject] = useState(workflow.project_id);
  const [graph, setGraph] = useState<WorkflowGraph>(() =>
    structuredClone(workflow.graph),
  );
  const [selected, setSelected] = useState(graph.nodes[0]?.id || ""),
    [tab, setTab] = useState("canvas");
  const selectedRef = useRef(selected);
  const inspector = useRef<HTMLElement | null>(null);
  selectedRef.current = selected;
  useEffect(() => {
    if (inspector.current) inspector.current.scrollTop = 0;
  }, [selected]);
  const [nodes, setNodes, onNodesChange] = useNodesState<TaskNodeType>([]);
  useEffect(() => {
    // Keep React Flow's measured dimensions and drag state separate from the saved graph.
    setNodes((current) =>
      graph.nodes.map((node) => ({
        ...current.find((item) => item.id === node.id),
        id: node.id,
        position: node.position,
        type: "projectTask",
        data: { task: node.task },
        selected: selectedRef.current === node.id,
        ariaLabel: `${node.id}: ${node.task.title}`,
      })),
    );
  }, [graph.nodes, setNodes]);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [browserJson, setBrowserJson] = useState(
    JSON.stringify(graph.browser_checks, null, 2),
  );
  const [browserError, setBrowserError] = useState("");
  const [commandErrors, setCommandErrors] = useState<Record<string, string>>(
    {},
  );
  const [commandDrafts, setCommandDrafts] = useState<Record<string, string>>(
    {},
  );
  const [undo, setUndo] = useState<WorkflowGraph[]>([]);
  const [redo, setRedo] = useState<WorkflowGraph[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [snap, setSnap] = useState(true);
  const [templatesOpen, setTemplatesOpen] = useState(false);
  const [templateId, setTemplateId] = useState("parallel");
  const [keepChecks, setKeepChecks] = useState(true);
  const [jsonDraft, setJsonDraft] = useState<string | null>(null);
  const [jsonError, setJsonError] = useState("");
  const [closing, setClosing] = useState(false);
  const saving = useRef(false);
  const dragging = useRef(false);
  const allowLeave = useRef(false);
  const instance = useRef<ReactFlowInstance<TaskNodeType> | null>(null);
  const commandError = Object.values(commandErrors).find(Boolean) || "";
  const dirty =
    !saved.digest ||
    name !== saved.name ||
    project !== saved.project_id ||
    JSON.stringify(graph) !== JSON.stringify(saved.graph) ||
    !!browserError ||
    !!commandError ||
    jsonDraft !== null;
  const blocker = useBlocker(() => dirty && !allowLeave.current);
  useEffect(() => {
    const prevent = (event: BeforeUnloadEvent) => {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", prevent);
    return () => window.removeEventListener("beforeunload", prevent);
  }, [dirty]);
  useEffect(() => {
    if (!dirty && blocker.state === "blocked") blocker.proceed();
    if (dirty) allowLeave.current = false;
  }, [dirty, blocker]);
  const edit = (next: WorkflowGraph) => {
    setUndo((items) => [...items.slice(-29), graph]);
    setRedo([]);
    setGraph(next);
    setNotice("");
  };
  const resetDrafts = (next: WorkflowGraph) => {
    setCommandErrors({});
    setCommandDrafts({});
    setBrowserError("");
    setBrowserJson(JSON.stringify(next.browser_checks, null, 2));
    setJsonDraft(null);
    setJsonError("");
    setError("");
    setNotice("");
    if (!next.nodes.some((n) => n.id === selected))
      setSelected(next.nodes[0]?.id || "");
  };
  const history = (back: boolean) => {
    const entries = back ? undo : redo;
    if (!entries.length) return;
    const next = entries[entries.length - 1];
    if (back) {
      setUndo(undo.slice(0, -1));
      setRedo((items) => [...items.slice(-29), graph]);
    } else {
      setRedo(redo.slice(0, -1));
      setUndo((items) => [...items.slice(-29), graph]);
    }
    setGraph(next);
    resetDrafts(next);
  };
  const fit = () =>
    void instance.current?.fitView({ padding: 0.12, maxZoom: 1 });
  useEffect(() => {
    if (!expanded) return;
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !document.querySelector('[role="dialog"]'))
        setExpanded(false);
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [expanded]);
  const task = graph.nodes.find((node) => node.id === selected)?.task;
  const changeTask = (changes: Partial<LiveTask>) =>
    edit({
      ...graph,
      version: changes.join ? 2 : graph.version,
      nodes: graph.nodes.map((node) =>
        node.id === selected
          ? { ...node, task: { ...node.task, ...changes } }
          : node,
      ),
    });
  const connect = ({
    source,
    target,
    sourceHandle,
  }: Pick<Connection, "source" | "target"> & {
    sourceHandle?: string | null;
  }) => {
    const port = (sourceHandle || "done") as WorkflowEdge["port"];
    const issue = connectionIssue(graph, source, target, port);
    if (issue) {
      setError(issue);
      return;
    }
    setError("");
    edit({
      ...graph,
      edges: [
        ...graph.edges,
        {
          source,
          target,
          ...(graph.version === 2
            ? { port, feedback: port === "changes_requested" }
            : {}),
        },
      ],
    });
  };
  const save = async () => {
    if (saving.current || browserError || commandError || jsonDraft !== null)
      return;
    saving.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const normalized = {
        ...graph,
        title: name.trim(),
        nodes: graph.nodes.map((node) => ({
          ...node,
          task: {
            ...node.task,
            steps: (node.task.steps || []).map((s) => s.trim()).filter(Boolean),
            acceptance: (node.task.acceptance || [])
              .map((s) => s.trim())
              .filter(Boolean),
            write_paths: [
              ...new Set(
                (node.task.write_paths || [])
                  .map((s) => s.trim())
                  .filter(Boolean),
              ),
            ],
          },
        })),
      };
      const result = await liveWorkflows.saveWorkflow({
        workflow_id: saved.workflow_id,
        project_id: project,
        name: name.trim(),
        graph: normalized,
        ...(saved.digest ? { expected_digest: saved.digest } : {}),
      });
      setSaved(result);
      setName((current) => (current === name ? result.name : current));
      // A response must not erase edits made while this save was in flight.
      setGraph((current) => (current === graph ? result.graph : current));
      allowLeave.current = false;
      onSaved(result);
      setNotice(
        result.ready
          ? `Đã lưu phiên bản ${result.revision}. Workflow sẵn sàng cho yêu cầu mới.`
          : `Đã lưu bản nháp ${result.revision}. ${liveCodeMessage(result.error_code || "LIVE_WORKFLOW_INVALID")}`,
      );
      return result;
    } catch (e) {
      setError(liveError(e));
    } finally {
      saving.current = false;
      setBusy(false);
    }
  };
  const removeCommand = (index: number) => {
    edit({ ...graph, commands: graph.commands.filter((_, i) => i !== index) });
    const shift = (values: Record<string, string>) =>
      Object.fromEntries(
        Object.entries(values)
          .filter(([key]) => key !== String(index))
          .map(([key, value]) => [
            key !== "preview" && Number(key) > index
              ? String(Number(key) - 1)
              : key,
            value,
          ]),
      );
    setCommandErrors(shift);
    setCommandDrafts(shift);
  };
  const add = (kind: string, position?: { x: number; y: number }) => {
    if (graph.nodes.length >= 20 || busy) return;
    const id = nextTaskId(graph);
    edit({
      ...graph,
      version: kind in controlKinds ? 2 : graph.version,
      nodes: [
        ...graph.nodes,
        {
          id,
          position: position || {
            x: 40 + (graph.nodes.length % 3) * 290,
            y: 70 + Math.floor(graph.nodes.length / 3) * 160,
          },
          task: newTask(id, kind),
        },
      ],
    });
    setSelected(id);
    setInspectorOpen(true);
    setTab("canvas");
  };
  const use = async () => {
    if (saving.current) return;
    saving.current = true;
    setBusy(true);
    setError("");
    try {
      await onUse(saved);
    } catch (e) {
      setError(liveError(e));
    } finally {
      saving.current = false;
      setBusy(false);
    }
  };
  const edges = graph.edges.map((edge) => ({
    ...edge,
    id: `${edge.source}--${edge.target}--${edge.port || "done"}`,
    sourceHandle: edge.port || "done",
    label: edge.feedback
      ? `Sửa · tối đa ${graph.nodes.find((n) => n.id === edge.source)?.task.control?.type === "gate" ? (graph.nodes.find((n) => n.id === edge.source)!.task.control as { max_rounds: number }).max_rounds : 0} vòng`
      : edge.port && edge.port !== "done"
        ? portLabels[edge.port]
        : undefined,
    type: "smoothstep",
    labelStyle: { fill: "hsl(var(--foreground))", fontSize: 10 },
    labelBgStyle: { fill: "hsl(var(--background))", fillOpacity: 0.96 },
    markerEnd: { type: MarkerType.ArrowClosed },
    style: {
      stroke: edge.feedback ? "#c78035" : "hsl(var(--muted-foreground))",
      strokeWidth: 1.5,
      strokeDasharray: edge.feedback ? "6 4" : undefined,
    },
  }));
  return (
    <section
      className={`wc-editor ${expanded ? "wc-expanded" : ""}`}
      aria-label="Canvas workflow của project"
    >
      <header className="wc-header">
        <button
          className="wc-back"
          aria-label="Về danh sách workflow"
          onClick={() => (dirty ? setClosing(true) : onClose())}
        >
          <ArrowLeft size={17} />
        </button>
        <div className="wc-title">
          <span className="lw-eyebrow">WORKFLOW DESIGNER</span>
          <input
            aria-label="Tên workflow"
            value={name}
            maxLength={120}
            onChange={(e) => setName(e.target.value)}
          />
          <small>
            {dirty
              ? "Có thay đổi chưa lưu"
              : `Đã lưu · phiên bản ${saved.revision}`}{" "}
            · {graph.nodes.length} task · {graph.edges.length} kết nối
          </small>
        </div>
        <div className="wc-actions">
          <button
            disabled={
              busy ||
              !name.trim() ||
              !project ||
              !!browserError ||
              !!commandError ||
              jsonDraft !== null
            }
            onClick={() => void save()}
          >
            {busy ? (
              <LoaderCircle size={15} className="animate-spin" />
            ) : (
              <Save size={15} />
            )}{" "}
            Lưu workflow
          </button>
          <button
            className="lw-primary"
            disabled={busy || dirty || !saved.ready}
            onClick={() => void use()}
          >
            {applying ? "Áp dụng vào kế hoạch" : "Dùng cho yêu cầu mới"}
            <ArrowRight size={15} />
          </button>
        </div>
      </header>
      <div className="wc-toolbar">
        <div role="tablist" aria-label="Cấu hình workflow">
          <button
            role="tab"
            aria-selected={tab === "canvas"}
            disabled={jsonDraft !== null}
            onClick={() => setTab("canvas")}
          >
            <GitBranch size={14} />
            Canvas
          </button>
          <button
            role="tab"
            aria-selected={tab === "checks"}
            disabled={jsonDraft !== null}
            onClick={() => setTab("checks")}
          >
            <FlaskConical size={14} />
            Kiểm chứng & preview
          </button>
          <button
            role="tab"
            aria-selected={tab === "json"}
            onClick={() => setTab("json")}
            disabled={!!browserError || !!commandError}
          >
            <FileJson2 size={14} />
            JSON nâng cao
          </button>
          <button
            className="wc-template-trigger"
            disabled={
              busy || jsonDraft !== null || !!browserError || !!commandError
            }
            onClick={() => setTemplatesOpen(true)}
          >
            <Shapes size={14} />
            Mẫu workflow
          </button>
        </div>
        <div>
          <button
            disabled={!undo.length || busy || jsonDraft !== null}
            aria-label="Hoàn tác canvas"
            title="Hoàn tác"
            onClick={() => history(true)}
          >
            <Undo2 size={15} />
          </button>
          <button
            disabled={!redo.length || busy || jsonDraft !== null}
            aria-label="Làm lại canvas"
            title="Làm lại"
            onClick={() => history(false)}
          >
            <Redo2 size={15} />
          </button>
          {tab === "canvas" && (
            <>
              <button
                aria-label="Sắp xếp task tự động"
                title="Sắp xếp theo phụ thuộc"
                onClick={() => {
                  edit(arrangeGraph(graph));
                  requestAnimationFrame(fit);
                }}
              >
                <LayoutGrid size={15} />
              </button>
              <button
                aria-label="Vừa canvas"
                title="Xem toàn bộ workflow"
                onClick={fit}
              >
                <Scan size={15} />
              </button>
              <button
                aria-label="Bật tắt danh sách task"
                title="Danh sách task"
                aria-pressed={paletteOpen}
                onClick={() => setPaletteOpen(!paletteOpen)}
              >
                <PanelLeft size={15} />
              </button>
              <button
                aria-label="Bật tắt chi tiết task"
                title="Chi tiết task"
                aria-pressed={inspectorOpen}
                onClick={() => setInspectorOpen(!inspectorOpen)}
              >
                <PanelRight size={15} />
              </button>
            </>
          )}
          <button
            aria-label={
              expanded ? "Thu gọn trình thiết kế" : "Mở rộng trình thiết kế"
            }
            title={expanded ? "Thu gọn (Esc)" : "Mở rộng trình thiết kế"}
            aria-pressed={expanded}
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
          </button>
        </div>
      </div>
      {(error || notice || browserError || commandError) && (
        <div
          className={
            error || browserError || commandError
              ? "lw-alert wc-message"
              : "wc-message wc-notice"
          }
          role={error || browserError || commandError ? "alert" : "status"}
        >
          {error || browserError || commandError || notice}
        </div>
      )}
      {tab === "canvas" ? (
        <div
          className={`wc-layout ${paletteOpen ? "" : "wc-palette-compact"} ${inspectorOpen ? "" : "wc-inspector-hidden"}`}
        >
          <aside className="wc-palette" aria-label="Thêm task vào workflow">
            <span className="lw-eyebrow">THÊM TASK</span>
            {Object.entries(taskKinds).map(([kind, config]) => (
              <button
                key={kind}
                title={`${config.name} · ${config.description}. Bấm để thêm hoặc kéo vào canvas.`}
                aria-label={`Thêm ${config.name}`}
                draggable={!busy && graph.nodes.length < 20}
                onDragStart={(e) => {
                  e.dataTransfer.setData("application/pokedev-task", kind);
                  e.dataTransfer.effectAllowed = "copy";
                }}
                disabled={graph.nodes.length >= 20 || busy}
                onClick={() => add(kind)}
              >
                <span className={`wc-kind ${config.color}`}>
                  {kind === "implement" ? (
                    <Code2 size={17} />
                  ) : kind === "test" ? (
                    <FlaskConical size={17} />
                  ) : (
                    <ShieldCheck size={17} />
                  )}
                </span>
                <span>
                  <strong>{config.name}</strong>
                  <small>{config.description}</small>
                </span>
                <Plus size={13} />
              </button>
            ))}
            <span className="lw-eyebrow">ĐIỀU KHIỂN LUỒNG</span>
            {Object.entries(controlKinds).map(([kind, config]) => (
              <button
                key={kind}
                title={`${config.name} · ${config.description}. Bấm để thêm hoặc kéo vào canvas.`}
                aria-label={`Thêm ${config.name}`}
                draggable={!busy && graph.nodes.length < 20}
                onDragStart={(e) => {
                  e.dataTransfer.setData("application/pokedev-task", kind);
                  e.dataTransfer.effectAllowed = "copy";
                }}
                disabled={graph.nodes.length >= 20 || busy}
                onClick={() => add(kind)}
              >
                <span className={`wc-kind ${config.color}`}>
                  <GitBranch size={17} />
                </span>
                <span>
                  <strong>{config.name}</strong>
                  <small>{config.description}</small>
                </span>
                <Plus size={13} />
              </button>
            ))}
            <div className="wc-help">
              <Workflow size={22} />
              <h3>Canvas quyết định lượt chạy</h3>
              <p>
                Kéo từ chấm bên phải sang task tiếp theo để thêm phụ thuộc. Các
                nhánh độc lập có thể chạy đồng thời.
              </p>
              <p>
                Điều kiện có hai nhánh. Cổng duyệt có thể quay về Developer với
                tối đa 3 vòng sửa; Tester giữ nguyên bộ test. Hết giới hạn sẽ
                hỏi người dùng.
              </p>
            </div>
          </aside>
          <div
            className="wc-canvas"
            onDragOver={(e) => {
              e.preventDefault();
              e.dataTransfer.dropEffect = "copy";
            }}
            onDrop={(e) => {
              e.preventDefault();
              const kind = e.dataTransfer.getData("application/pokedev-task");
              if (!(kind in taskKinds) && !(kind in controlKinds)) return;
              const position = instance.current?.screenToFlowPosition(
                { x: e.clientX, y: e.clientY },
                { snapToGrid: snap },
              );
              if (position) add(kind, position);
            }}
          >
            <ReactFlow<TaskNodeType>
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              onInit={(value) => {
                instance.current = value;
              }}
              fitView
              fitViewOptions={{ maxZoom: 0.9, minZoom: 0.45, padding: 0.12 }}
              minZoom={0.2}
              maxZoom={2}
              connectionRadius={30}
              snapToGrid={snap}
              snapGrid={[20, 20]}
              onNodeClick={(_, node) => {
                setSelected(node.id);
                setInspectorOpen(true);
              }}
              onNodeDragStart={() => {
                dragging.current = true;
                setUndo((items) => [...items.slice(-29), graph]);
                setRedo([]);
              }}
              onNodesChange={(changes) => {
                onNodesChange(changes);
                const choice = changes.find(
                  (change) => change.type === "select" && change.selected,
                );
                if (choice?.type === "select") setSelected(choice.id);
                if (!dragging.current) {
                  const positions = new Map(
                    changes.flatMap((change) =>
                      change.type === "position" &&
                      change.dragging === false &&
                      change.position
                        ? [[change.id, change.position] as const]
                        : [],
                    ),
                  );
                  if (
                    positions.size &&
                    graph.nodes.some((n) => {
                      const p = positions.get(n.id);
                      return (
                        p && (p.x !== n.position.x || p.y !== n.position.y)
                      );
                    })
                  )
                    edit({
                      ...graph,
                      nodes: graph.nodes.map((node) =>
                        positions.has(node.id)
                          ? { ...node, position: positions.get(node.id)! }
                          : node,
                      ),
                    });
                }
              }}
              onNodeDragStop={(_, moved, movedNodes) => {
                dragging.current = false;
                const positions = new Map(
                  (movedNodes?.length ? movedNodes : [moved]).map((n) => [
                    n.id,
                    n.position,
                  ]),
                );
                setGraph((current) => ({
                  ...current,
                  nodes: current.nodes.map((node) =>
                    positions.has(node.id)
                      ? { ...node, position: positions.get(node.id)! }
                      : node,
                  ),
                }));
              }}
              onConnect={connect}
              onEdgesDelete={(removed) =>
                edit({
                  ...graph,
                  edges: graph.edges.filter(
                    (edge) =>
                      !removed.some(
                        (r) =>
                          r.source === edge.source &&
                          r.target === edge.target &&
                          (r.sourceHandle || "done") === (edge.port || "done"),
                      ),
                  ),
                })
              }
              onNodesDelete={(removed) => {
                const ids = new Set(removed.map((node) => node.id));
                edit({
                  ...graph,
                  nodes: graph.nodes.filter((node) => !ids.has(node.id)),
                  edges: graph.edges.filter(
                    (edge) => !ids.has(edge.source) && !ids.has(edge.target),
                  ),
                });
              }}
              deleteKeyCode={null}
              aria-label="Thiết kế task và phụ thuộc"
            >
              <Background variant={BackgroundVariant.Dots} gap={22} size={1} />
              <Controls showInteractive={false} />
              <MiniMap
                pannable
                zoomable
                nodeColor="hsl(var(--primary) / 0.5)"
              />
            </ReactFlow>
            <div className="wc-canvas-dock">
              <button
                aria-pressed={snap}
                title="Căn vị trí theo lưới 20px"
                onClick={() => setSnap(!snap)}
              >
                <LayoutGrid size={13} />
                Bám lưới
              </button>
              {selected && (
                <button
                  onClick={() =>
                    void instance.current?.fitView({
                      nodes: [{ id: selected }],
                      padding: 0.5,
                      maxZoom: 1,
                    })
                  }
                >
                  <Scan size={13} />
                  Tập trung task
                </button>
              )}
            </div>
            {!nodes.length && (
              <div className="wc-canvas-empty">
                Thêm Developer và Tester từ danh sách bên trái để bắt đầu.
              </div>
            )}
          </div>
          <aside className="wc-inspector" ref={inspector}>
            {task ? (
              <WorkflowTaskInspector
                key={task.id}
                task={task}
                graph={graph}
                project={project}
                onChange={changeTask}
                onConnect={connect}
                onDisconnect={(edge) =>
                  edit({
                    ...graph,
                    edges: graph.edges.filter((item) => item !== edge),
                  })
                }
                onRename={(id) => {
                  try {
                    edit(renameTask(graph, task.id, id));
                    setSelected(id);
                    setError("");
                  } catch (failure) {
                    setError((failure as Error).message);
                  }
                }}
                onDuplicate={() => {
                  const next = duplicateTask(graph, task.id);
                  edit(next);
                  setSelected(next.nodes[next.nodes.length - 1].id);
                  setNotice(
                    "Đã nhân bản nội dung. Chọn lại phạm vi file và kết nối cho task mới.",
                  );
                }}
                onDelete={() => {
                  edit({
                    ...graph,
                    nodes: graph.nodes.filter((node) => node.id !== task.id),
                    edges: graph.edges.filter(
                      (edge) =>
                        edge.source !== task.id && edge.target !== task.id,
                    ),
                  });
                  setSelected("");
                }}
              />
            ) : (
              <div className="wc-help">
                <GitBranch size={24} />
                <h3>Chọn một task</h3>
                <p>
                  Chỉnh nội dung, phạm vi file và kết nối. Kéo task từ thanh bên
                  để thêm vào canvas.
                </p>
              </div>
            )}
          </aside>
        </div>
      ) : tab === "json" ? (
        <WorkflowJsonEditor
          graph={graph}
          draft={jsonDraft}
          error={jsonError}
          onDraft={(text) => {
            setJsonDraft(text === JSON.stringify(graph, null, 2) ? null : text);
            setJsonError("");
          }}
          onError={setJsonError}
          onDiscard={() => {
            setJsonDraft(null);
            setJsonError("");
          }}
          onApply={() => {
            try {
              const next = parseGraph(jsonDraft || "");
              edit({ ...next, title: name.trim() });
              resetDrafts(next);
              setTab("canvas");
              setNotice(
                "Đã áp dụng JSON vào bản nháp. Lưu workflow để kiểm tra khả năng thực thi.",
              );
            } catch (failure) {
              setJsonError((failure as Error).message);
            }
          }}
        />
      ) : (
        <div className="wc-settings">
          <section>
            <span className="lw-eyebrow">NGỮ CẢNH</span>
            <h3>Project & mô tả</h3>
            <label>
              Project của workflow
              <select
                value={project}
                onChange={(e) => setProject(e.target.value)}
              >
                {projects.map((p) => (
                  <option key={p.project_id} value={p.project_id}>
                    {p.repository}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Mô tả workflow
              <textarea
                rows={3}
                value={graph.summary}
                onChange={(e) => edit({ ...graph, summary: e.target.value })}
              />
            </label>
            <p>
              Phiên bản đã lưu được chụp riêng cho mỗi lượt chạy. Chỉnh workflow
              không thay đổi các lượt đã bắt đầu.
            </p>
          </section>
          <section>
            <span className="lw-eyebrow">KIỂM CHỨNG</span>
            <h3>Lệnh test & build</h3>
            <p>
              Lệnh chạy trong Sandbox Linux, theo thứ tự bên dưới. Dùng dấu
              ngoặc kép cho đối số có khoảng trắng.
            </p>
            {graph.commands.map((command, index) => (
              <div className="wc-command" key={index}>
                <label>
                  Tên kiểm tra
                  <input
                    value={command.label}
                    onChange={(e) =>
                      edit({
                        ...graph,
                        commands: graph.commands.map((c, i) =>
                          i === index ? { ...c, label: e.target.value } : c,
                        ),
                      })
                    }
                  />
                </label>
                <CommandInput
                  draft={commandDrafts[String(index)]}
                  onDraft={(text) =>
                    setCommandDrafts((drafts) => ({
                      ...drafts,
                      [String(index)]: text,
                    }))
                  }
                  invalid={(message) =>
                    setCommandErrors((errors) => ({
                      ...errors,
                      [String(index)]: message,
                    }))
                  }
                  label={`Lệnh kiểm tra ${index + 1}`}
                  argv={command.argv}
                  change={(argv) =>
                    edit({
                      ...graph,
                      commands: graph.commands.map((c, i) =>
                        i === index ? { ...c, argv } : c,
                      ),
                    })
                  }
                />
                <label>
                  Thời gian chờ (giây)
                  <input
                    type="number"
                    min={5}
                    max={600}
                    value={command.timeout ?? 180}
                    onChange={(e) =>
                      edit({
                        ...graph,
                        commands: graph.commands.map((c, i) =>
                          i === index
                            ? { ...c, timeout: Number(e.target.value) }
                            : c,
                        ),
                      })
                    }
                  />
                </label>
                <button
                  aria-label={`Xóa lệnh ${index + 1}`}
                  onClick={() => removeCommand(index)}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
            <button
              disabled={graph.commands.length >= 8}
              onClick={() =>
                edit({
                  ...graph,
                  commands: [
                    ...graph.commands,
                    { label: "Kiểm thử", argv: [], timeout: 180 },
                  ],
                })
              }
            >
              <Plus size={14} />
              Thêm lệnh kiểm tra
            </button>
          </section>
          <section>
            <span className="lw-eyebrow">PREVIEW</span>
            <h3>Chạy thử sản phẩm</h3>
            <label>
              Loại ứng dụng
              <select
                value={
                  !graph.preview
                    ? "none"
                    : graph.preview.path
                      ? "static"
                      : "server"
                }
                onChange={(e) => {
                  setCommandErrors((errors) => ({ ...errors, preview: "" }));
                  setCommandDrafts((drafts) => {
                    const next = { ...drafts };
                    delete next.preview;
                    return next;
                  });
                  if (e.target.value === "none") {
                    setBrowserJson("[]");
                    setBrowserError("");
                  }
                  edit({
                    ...graph,
                    preview:
                      e.target.value === "none"
                        ? null
                        : e.target.value === "static"
                          ? { path: "." }
                          : { argv: ["python", "app.py"] },
                    ...(e.target.value === "none"
                      ? { browser_checks: [] }
                      : {}),
                  });
                }}
              >
                <option value="none">Không có preview</option>
                <option value="static">Trang tĩnh (HTML / CSS / JS)</option>
                <option value="server">Ứng dụng có server</option>
              </select>
            </label>
            {graph.preview?.path && (
              <label>
                Thư mục chứa index.html
                <input
                  value={graph.preview.path}
                  onChange={(e) =>
                    edit({ ...graph, preview: { path: e.target.value } })
                  }
                />
              </label>
            )}
            {graph.preview?.argv && (
              <>
                <CommandInput
                  draft={commandDrafts.preview}
                  onDraft={(text) =>
                    setCommandDrafts((drafts) => ({ ...drafts, preview: text }))
                  }
                  invalid={(message) =>
                    setCommandErrors((errors) => ({
                      ...errors,
                      preview: message,
                    }))
                  }
                  label="Lệnh chạy preview"
                  argv={graph.preview.argv}
                  change={(argv) => edit({ ...graph, preview: { argv } })}
                />
                <p>Ứng dụng đọc PORT=8088 và HOST=0.0.0.0.</p>
              </>
            )}
            <details>
              <summary>Kiểm tra trình duyệt (JSON)</summary>
              <p>
                Hành động hỗ trợ: goto, text, visible, fill, click. Các kiểm tra
                hiện có được giữ nguyên khi sửa canvas.
              </p>
              <textarea
                aria-label="Kiểm tra trình duyệt"
                rows={12}
                value={browserJson}
                onChange={(e) => {
                  setBrowserJson(e.target.value);
                  try {
                    const value = JSON.parse(e.target.value);
                    if (!Array.isArray(value)) throw new Error();
                    edit({ ...graph, browser_checks: value });
                    setBrowserError("");
                  } catch {
                    setBrowserError(
                      "Danh sách kiểm tra trình duyệt cần là JSON hợp lệ.",
                    );
                  }
                }}
              />
            </details>
          </section>
        </div>
      )}
      <footer className="wc-footer">
        <span>
          <span className={`lw-dot ${saved.ready && !dirty ? "ok" : ""}`} />
          {dirty
            ? "Lưu workflow để kiểm tra cấu hình"
            : saved.ready
              ? "Sẵn sàng sử dụng"
              : "Bản nháp — cần hoàn thiện phạm vi file và lệnh kiểm chứng"}
        </span>
        <span>
          {projects.find((p) => p.project_id === project)?.repository ||
            "Chọn project"}
        </span>
      </footer>
      <Dialog
        open={closing || blocker.state === "blocked"}
        onOpenChange={(open) => {
          if (!open) {
            setClosing(false);
            if (blocker.state === "blocked") blocker.reset();
          }
        }}
      >
        <DialogContent>
          <DialogTitle>Lưu thay đổi trước khi rời canvas?</DialogTitle>
          <DialogDescription>
            Workflow đang có thay đổi chưa lưu. Các lượt chạy đã lưu vẫn dùng
            phiên bản trước.
          </DialogDescription>
          <div className="wc-actions">
            <button
              onClick={() => {
                setClosing(false);
                if (blocker.state === "blocked") blocker.reset();
              }}
            >
              Tiếp tục chỉnh sửa
            </button>
            <button
              onClick={() => {
                setClosing(false);
                allowLeave.current = true;
                if (blocker.state === "blocked") blocker.proceed();
                else onClose();
              }}
            >
              Bỏ thay đổi
            </button>
            <button
              disabled={
                busy || !!browserError || !!commandError || jsonDraft !== null
              }
              onClick={() =>
                void save().then((result) => {
                  if (result) {
                    setClosing(false);
                    if (blocker.state !== "blocked") onClose();
                  }
                })
              }
            >
              <Check size={14} />
              Lưu & tiếp tục
            </button>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog open={templatesOpen} onOpenChange={setTemplatesOpen}>
        <DialogContent className="wc-dialog wc-template-dialog">
          <DialogTitle>Bắt đầu từ một mẫu workflow</DialogTitle>
          <DialogDescription>
            Áp dụng mẫu sẽ thay nội dung và kết nối của bản nháp hiện tại. Bạn
            có thể hoàn tác; chỉ khi lưu thì phiên bản mới được ghi lại.
          </DialogDescription>
          <div className="wc-template-grid">
            {workflowTemplates.map((template) => (
              <button
                key={template.id}
                className={templateId === template.id ? "selected" : ""}
                aria-pressed={templateId === template.id}
                onClick={() => setTemplateId(template.id)}
              >
                <span>
                  <GitBranch size={18} />
                  <small>{template.count} task</small>
                </span>
                <strong>{template.name}</strong>
                <p>{template.description}</p>
                <code>{template.flow}</code>
                {templateSources[template.id] && (
                  <small className="wc-template-source">
                    Tham khảo factory-wilson
                  </small>
                )}
              </button>
            ))}
          </div>
          {templateSources[templateId] && (
            <p className="wc-template-origin">
              Mẫu được chuyển sang hợp đồng PokeDev từ{" "}
              <a
                href={templateSources[templateId].url}
                target="_blank"
                rel="noreferrer"
              >
                {templateSources[templateId].label}
              </a>
              . Các công cụ riêng và thao tác deploy trong bản gốc không được tự
              thêm vào lượt chạy.
            </p>
          )}
          <label className="wc-check-label">
            <input
              type="checkbox"
              checked={keepChecks}
              onChange={(e) => setKeepChecks(e.target.checked)}
            />
            Giữ lệnh kiểm chứng, preview và kiểm tra trình duyệt hiện tại
          </label>
          <div className="wc-dialog-actions">
            <p>Mỗi mẫu cần chọn lại phạm vi file phù hợp với repo của bạn.</p>
            <button
              className="lw-primary"
              onClick={() => {
                const next = {
                  ...templateGraph(templateId),
                  title: name.trim(),
                  ...(keepChecks
                    ? {
                        commands: structuredClone(graph.commands),
                        preview: structuredClone(graph.preview),
                        browser_checks: structuredClone(graph.browser_checks),
                      }
                    : {}),
                };
                edit(next);
                resetDrafts(next);
                setSelected(next.nodes[0]?.id || "");
                setTab("canvas");
                setTemplatesOpen(false);
                setNotice(
                  "Đã áp dụng mẫu vào bản nháp. Chọn file cho từng task và kiểm tra lệnh test trước khi lưu.",
                );
                requestAnimationFrame(fit);
              }}
            >
              <Check size={14} />
              Áp dụng mẫu
            </button>
          </div>
        </DialogContent>
      </Dialog>
    </section>
  );
}

function CommandInput({
  argv,
  label,
  change,
  invalid,
  draft,
  onDraft,
}: {
  argv: string[];
  label: string;
  change: (argv: string[]) => void;
  invalid: (message: string) => void;
  draft?: string;
  onDraft: (text: string) => void;
}) {
  return (
    <label>
      {label}
      <input
        aria-label={label}
        value={draft ?? commandText(argv)}
        onChange={(event) => {
          onDraft(event.target.value);
          try {
            change(commandArgs(event.target.value));
            invalid("");
          } catch (failure) {
            invalid((failure as Error).message);
          }
        }}
      />
    </label>
  );
}
