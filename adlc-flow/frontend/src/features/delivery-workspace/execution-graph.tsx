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
  useReactFlow,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import {
  CheckCircle2,
  Circle,
  Focus,
  LayoutGrid,
  List,
  LoaderCircle,
  Maximize2,
  Minimize2,
  Workflow,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  executionLayout,
  executionState,
  executionTime,
  taskTone,
  type ExecutionEdge,
  type ExecutionTask,
  type JourneyStep,
} from "./execution-model";
import "@xyflow/react/dist/style.css";
import "./execution-graph.css";

type RunningNode = Node<{ task: ExecutionTask; dimmed: boolean }, "execution">;
function ExecutionNode({ data }: NodeProps<RunningNode>) {
  const tone = taskTone(data.task.state);
  return (
    <div className={`eg-node eg-${tone} ${data.dimmed ? "eg-dimmed" : ""}`}>
      <Handle type="target" position={Position.Left} />
      <div className="eg-node-top">
        <span>{data.task.role || "Task"}</span>
        <code>{data.task.id}</code>
      </div>
      <strong>{data.task.title}</strong>
      <span className="eg-node-status">
        {tone === "running" ? (
          <LoaderCircle size={13} className="animate-spin" />
        ) : tone === "done" ? (
          <CheckCircle2 size={13} />
        ) : (
          <Circle size={11} />
        )}
        {executionState[data.task.state] || data.task.state}
      </span>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
const nodeTypes = { execution: ExecutionNode };

export function reconcileExecutionNodes(
  old: RunningNode[],
  tasks: ExecutionTask[],
  layout: ReturnType<typeof executionLayout>,
  selected: string,
  filter: string,
  topologyChanged: boolean,
): RunningNode[] {
  const next = tasks.map((task): RunningNode => {
    const previous = old.find((node) => node.id === task.id);
    const position = (!topologyChanged && previous?.position) || {
      x: layout.find((point) => point.id === task.id)?.x || 0,
      y: layout.find((point) => point.id === task.id)?.y || 0,
    };
    const dimmed = filter !== "all" && taskTone(task.state) !== filter;
    if (
      previous &&
      previous.selected === (selected === task.id) &&
      previous.position.x === position.x &&
      previous.position.y === position.y &&
      previous.data.dimmed === dimmed &&
      JSON.stringify(previous.data.task) === JSON.stringify(task)
    ) {
      return previous;
    }
    return {
      ...previous,
      id: task.id,
      type: "execution",
      ariaLabel: `${task.id}: ${task.title}`,
      ariaRole: "button",
      selected: selected === task.id,
      position,
      data: { task, dimmed },
    };
  });
  return next.length === old.length &&
    next.every((node, index) => node === old[index])
    ? old
    : next;
}

function Graph({
  tasks,
  edges,
  selected,
  select,
}: {
  tasks: ExecutionTask[];
  edges: ExecutionEdge[];
  selected: string;
  select: (id: string) => void;
}) {
  const [list, setList] = useState(false),
    [expanded, setExpanded] = useState(false),
    [filter, setFilter] = useState("all");
  const [nodes, setNodes, onNodesChange] = useNodesState<RunningNode>([]);
  const flow = useReactFlow();
  const selectedRef = useRef(selected);
  useEffect(() => {
    selectedRef.current = selected;
  }, [selected]);
  const choose = useCallback(
    (id: string) => {
      // React Flow can repeat selection notifications before URL/parent state
      // acknowledges the first one. Do not feed them back into parent renders.
      if (selectedRef.current === id) return;
      selectedRef.current = id;
      select(id);
    },
    [select],
  );
  const topology =
    tasks.map((t) => t.id).join("|") +
    edges.map((e) => `${e.source}>${e.target}`).join("|");
  const layout = useMemo(() => executionLayout(tasks, edges), [topology]);
  const previous = useRef("");
  useEffect(() => {
    const changed = previous.current !== topology;
    previous.current = topology;
    setNodes((old) =>
      reconcileExecutionNodes(old, tasks, layout, selected, filter, changed),
    );
  }, [tasks, topology, layout, selected, filter, setNodes]);
  useEffect(() => {
    if (!expanded) return;
    const exit = (e: KeyboardEvent) => {
      if (e.key === "Escape") setExpanded(false);
    };
    window.addEventListener("keydown", exit);
    return () => window.removeEventListener("keydown", exit);
  }, [expanded]);
  const edgeSignature = JSON.stringify(edges);
  const stateSignature = tasks
    .map((task) => `${task.id}:${task.state}`)
    .join("|");
  const graphEdges = useMemo(() => edges
    .filter(
      (e) =>
        tasks.some((t) => t.id === e.source) &&
        tasks.some((t) => t.id === e.target),
    )
    .map((e, i) => ({
      id: `edge-${i}`,
      ...e,
      type: "smoothstep",
      animated:
        taskTone(tasks.find((t) => t.id === e.target)?.state || "") ===
        "running",
      markerEnd: { type: MarkerType.ArrowClosed },
      style: {
        stroke: e.feedback ? "#d6a846" : "#8794a8",
        strokeWidth: 1.4,
        strokeDasharray: e.feedback ? "5 4" : undefined,
      },
      labelStyle: { fill: "#8794a8", fontSize: 11 },
    })), [edgeSignature, stateSignature]);
  const focus = () => {
    const active = tasks.filter((t) =>
      ["running", "waiting", "failed"].includes(taskTone(t.state)),
    );
    if (active[0]) choose(active[0].id);
    void flow.fitView({
      nodes: active.length ? active : nodes,
      padding: 0.35,
      duration: 250,
      maxZoom: 1.1,
    });
  };
  return (
    <section
      className={`eg-shell ${expanded ? "eg-expanded" : ""}`}
      aria-label="Sơ đồ thực thi"
    >
      <header className="eg-toolbar">
        <span>
          <Workflow size={15} /> Tiến trình task
        </span>
        <div>
          <select
            aria-label="Làm nổi bật trạng thái task"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="all">Tất cả trạng thái</option>
            <option value="running">Đang chạy</option>
            <option value="waiting">Cần phản hồi / lưu ý</option>
            <option value="failed">Cần xử lý</option>
            <option value="done">Hoàn tất</option>
          </select>
          <button
            title="Tập trung task đang chạy hoặc cần xử lý"
            onClick={focus}
          >
            <Focus size={15} />
            Theo dõi
          </button>
          <button
            aria-label={list ? "Xem sơ đồ" : "Xem danh sách task"}
            onClick={() => setList(!list)}
          >
            {list ? <LayoutGrid size={15} /> : <List size={15} />}
          </button>
          <button
            aria-label={expanded ? "Thu nhỏ sơ đồ" : "Mở rộng sơ đồ"}
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
          </button>
        </div>
      </header>
      {!tasks.length ? (
        <p className="eg-empty">Task sẽ xuất hiện khi kế hoạch sẵn sàng.</p>
      ) : list ? (
        <div className="eg-list">
          {tasks.map((t) => (
            <button
              key={t.id}
              aria-label={`${t.id}: ${t.title}`}
              aria-pressed={selected === t.id}
              className={`eg-${taskTone(t.state)}`}
              onClick={() => choose(t.id)}
            >
              <code>{t.id}</code>
              <strong>{t.title}</strong>
              <span>{executionState[t.state] || t.state}</span>
            </button>
          ))}
        </div>
      ) : (
        <div className="eg-canvas">
          <ReactFlow
            nodes={nodes}
            edges={graphEdges}
            nodeTypes={nodeTypes}
            onNodesChange={(changes) => {
              onNodesChange(changes);
              const choice = changes.find(
                (change) => change.type === "select" && change.selected,
              );
              if (choice?.type === "select") choose(choice.id);
            }}
            onNodeClick={(_, node) => choose(node.id)}
            nodesConnectable={false}
            deleteKeyCode={null}
            fitView
            fitViewOptions={{ padding: 0.2, maxZoom: 1 }}
            minZoom={0.15}
            maxZoom={1.8}
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
            <Controls showInteractive={false} />
            <MiniMap
              pannable
              zoomable
              nodeColor={(n) =>
                ({
                  done: "#3ba88e",
                  running: "#7c9df3",
                  waiting: "#e0b44d",
                  failed: "#db6e76",
                  idle: "#667083",
                  skipped: "#404755",
                })[taskTone((n.data.task as ExecutionTask).state)]
              }
            />
          </ReactFlow>
        </div>
      )}
      <footer>
        <span className="eg-legend">
          <i className="eg-dot running" />
          Đang chạy <i className="eg-dot done" />
          Hoàn tất <i className="eg-dot waiting" />
          Cần phản hồi <i className="eg-dot failed" />
          Cần xử lý
        </span>
        <small>Kéo task để bố trí · cuộn để thu phóng</small>
      </footer>
    </section>
  );
}
export default function ExecutionGraph(props: Parameters<typeof Graph>[0]) {
  return (
    <ReactFlowProvider>
      <Graph {...props} />
    </ReactFlowProvider>
  );
}
export function WorkJourney({
  steps,
  select,
}: {
  steps: JourneyStep[];
  select: (tab: string) => void;
}) {
  return (
    <nav className="ej-journey" aria-label="Hành trình công việc">
      {steps.map((s, i) => (
        <button
          key={s.id}
          className={`ej-${s.state}`}
          aria-current={s.state === "current" ? "step" : undefined}
          onClick={() => select(s.tab)}
        >
          <span>
            {s.state === "done" ? (
              <CheckCircle2 size={16} />
            ) : (
              String(i + 1).padStart(2, "0")
            )}
          </span>
          <div>
            <strong>{s.title}</strong>
            <small>{s.detail}</small>
          </div>
        </button>
      ))}
    </nav>
  );
}
export function ExecutionTimeline({
  tasks,
  select,
}: {
  tasks: ExecutionTask[];
  select: (id: string) => void;
}) {
  const events = tasks
    .flatMap((t) => [
      ...(t.started_at ? [{ task: t, at: t.started_at, text: "Bắt đầu" }] : []),
      ...(t.completed_at
        ? [
            {
              task: t,
              at: t.completed_at,
              text: executionState[t.state] || t.state,
            },
          ]
        : []),
    ])
    .sort((a, b) => b.at - a.at);
  return (
    <section className="eg-timeline">
      <header>
        <h3>Diễn biến thực hiện</h3>
        <small>Giờ Việt Nam · UTC+7</small>
      </header>
      {events.length ? (
        <ol>
          {events.map((e, i) => (
            <li key={`${e.task.id}-${i}`}>
              <time>{executionTime(e.at)}</time>
              <button onClick={() => select(e.task.id)}>
                <span className={`eg-dot ${taskTone(e.task.state)}`} />
                <strong>{e.task.title}</strong>
                <span>{e.text}</span>
              </button>
            </li>
          ))}
        </ol>
      ) : (
        <p className="lw-muted">
          Chưa có mốc thời gian thực thi được ghi nhận.
        </p>
      )}
    </section>
  );
}
