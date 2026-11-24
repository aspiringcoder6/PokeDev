import { useQuery } from "@tanstack/react-query";
import {
  CheckCircle2,
  Circle,
  ExternalLink,
  FileText,
  GitBranch,
  Layers,
  LoaderCircle,
  Play,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { useContext, useMemo, useRef, useState } from "react";
import { SanitizedMarkdown } from "@/components/core/sanitizedMarkdown";
import {
  tnqdDemo,
  type TnqdRun,
  type TnqdTask,
} from "@/controllers/API/tnqd-demo";
import { AuthContext } from "@/contexts/authContext";
import "./tnqd-workflow.css";

const labels: Record<string, string> = {
  PLANNING: "Đang lập tài liệu & kế hoạch",
  PLAN_READY: "Kế hoạch sẵn sàng",
  RUNNING: "Đang thực hiện",
  SUCCEEDED: "Đã hoàn tất",
  FAILED: "Cần xử lý",
  UNCONFIRMED: "Cần đối soát",
  DONE: "Hoàn tất",
  PENDING: "Chờ phụ thuộc",
  WAITING_SLOT: "Chờ lượt thực hiện",
  BLOCKED: "Đang bị chặn",
};
const live = (state: string) =>
  ["PLANNING", "RUNNING", "RESERVED", "UNCONFIRMED"].includes(state);
const agentRoles: Record<string, string> = {
  developer: "Dev",
  coder: "Dev",
  tester: "Tester",
  reviewer: "Review",
  BA: "BA",
};
export function safeTnqdPreview(value?: TnqdRun["preview"]) {
  if (
    !value?.url ||
    value.state !== "LIVE" ||
    !Number.isFinite(Date.parse(value.expires_at)) ||
    Date.parse(value.expires_at) <= Date.now()
  )
    return false;
  try {
    const parsed = new URL(value.url);
    return (
      parsed.protocol === "http:" &&
      parsed.hostname === "localhost" &&
      Number(parsed.port) > 1024 &&
      ![7860, 9982].includes(Number(parsed.port)) &&
      parsed.pathname === "/" &&
      !parsed.username &&
      !parsed.password &&
      !parsed.search &&
      !parsed.hash
    );
  } catch {
    return false;
  }
}
const time = (value: number) =>
  new Date(value * 1000).toLocaleTimeString("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
function splitLabel(value: string) {
  const words = value.split(" "),
    lines: string[] = [];
  let line = "";
  for (const word of words) {
    if ((line + word).length > 28 && lines.length < 2) {
      lines.push(line);
      line = "";
    }
    line += (line ? " " : "") + word;
  }
  lines.push(line.length > 29 ? line.slice(0, 28) + "…" : line);
  return lines.slice(0, 3);
}

function Dag({
  run,
  selected,
  onSelect,
}: {
  run: TnqdRun;
  selected: string;
  onSelect: (id: string) => void;
}) {
  const tasks =
    run.plan?.tasks ??
    run.nodes.map((n) => ({
      id: n.id,
      title: n.title ?? n.id,
      depends_on: n.depends_on ?? [],
      role: n.role ?? "Agent",
    }));
  const positions = useMemo(() => {
    const ranks: Record<string, number> = {},
      output: Record<string, { x: number; y: number }> = {};
    for (let iteration = 0; iteration <= tasks.length; iteration++)
      for (const task of tasks)
        ranks[task.id] = task.depends_on.length
          ? Math.max(...task.depends_on.map((id) => ranks[id] ?? 0)) + 1
          : 0;
    const levels = new Map<number, typeof tasks>();
    for (const task of tasks)
      levels.set(ranks[task.id], [...(levels.get(ranks[task.id]) ?? []), task]);
    let cursor = 20;
    for (const [, entries] of [...levels].sort((a, b) => a[0] - b[0])) {
      entries.forEach((task, index) => {
        output[task.id] = {
          x: 16 + (index % 3) * 234,
          y: cursor + Math.floor(index / 3) * 86,
        };
      });
      cursor += Math.ceil(entries.length / 3) * 86 + 24;
    }
    return output;
  }, [tasks]);
  const height = Math.max(
    180,
    ...Object.values(positions).map((p) => p.y + 90),
  );
  return (
    <div className="tn-dag-scroll">
      <svg
        viewBox={`0 0 720 ${height}`}
        role="img"
        aria-label="DAG task TNQD và các cạnh phụ thuộc"
      >
        <defs>
          <marker
            id="tn-arrow"
            markerWidth="8"
            markerHeight="8"
            refX="7"
            refY="3"
            orient="auto"
          >
            <path d="M0,0 L0,6 L7,3 z" fill="currentColor" />
          </marker>
        </defs>
        {tasks.flatMap((task) =>
          task.depends_on.map((parent) => {
            const a = positions[parent],
              b = positions[task.id];
            if (!a || !b) return null;
            return (
              <path
                key={`${parent}-${task.id}`}
                className="tn-edge"
                d={`M${a.x + 104},${a.y + 68} C${a.x + 104},${a.y + 86} ${b.x + 104},${b.y - 20} ${b.x + 104},${b.y}`}
                markerEnd="url(#tn-arrow)"
              />
            );
          }),
        )}
        {tasks.map((task) => {
          const p = positions[task.id];
          const status =
            run.nodes.find((n) => n.id === task.id)?.state ?? "PENDING";
          return (
            <g
              key={task.id}
              className={`tn-dag-node ${status.toLowerCase()} ${selected === task.id ? "selected" : ""}`}
              role="button"
              tabIndex={0}
              aria-label={`${task.id}: ${task.title}`}
              onClick={() => onSelect(task.id)}
              onKeyDown={(event) => {
                if (["Enter", " "].includes(event.key)) {
                  event.preventDefault();
                  onSelect(task.id);
                }
              }}
              transform={`translate(${p.x},${p.y})`}
            >
              <rect width="208" height="68" rx="9" />
              <text x="12" y="17" className="tn-node-id">
                {task.id} · {task.role}
              </text>
              {splitLabel(task.title).map((line, i) => (
                <text key={i} x="12" y={33 + i * 12} className="tn-node-title">
                  {line}
                </text>
              ))}
              <circle cx="193" cy="15" r="4" />
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function TaskDetail({ task, run }: { task?: TnqdTask; run: TnqdRun }) {
  const node = run.nodes.find((n) => n.id === task?.id);
  if (!task)
    return (
      <div className="tn-detail-empty">
        <GitBranch size={25} />
        <p>Chọn task để xem các bước, đầu vào, đầu ra và phụ thuộc.</p>
      </div>
    );
  return (
    <div className="tn-task-detail">
      <span className="tn-eyebrow">
        {task.id} · {task.role}
      </span>
      <h4>{task.title}</h4>
      <span className={`tn-state ${(node?.state ?? "PENDING").toLowerCase()}`}>
        {labels[node?.state ?? "PENDING"] ?? node?.state}
      </span>
      <p className="tn-dependency">
        Phụ thuộc: {task.depends_on.join(", ") || "Không có"}
      </p>
      <ol>
        {task.steps.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
      <h5>Điều kiện hoàn tất</h5>
      <ul>
        {task.acceptance.map((value) => (
          <li key={value}>{value}</li>
        ))}
      </ul>
      <div className="tn-io">
        <div>
          <h5>Đầu vào</h5>
          {task.inputs.map((value) => (
            <span key={value}>{value}</span>
          ))}
        </div>
        <div>
          <h5>Đầu ra</h5>
          {task.outputs.map((value) => (
            <span key={value}>{value}</span>
          ))}
        </div>
      </div>
      {!!task.write_paths.length && (
        <>
          <h5>File được thay đổi</h5>
          {task.write_paths.map((value) => (
            <code className="tn-path" key={value}>
              {value}
            </code>
          ))}
        </>
      )}
      <div className="tn-tags">
        {task.requirements.map((r) => (
          <span key={r}>{r}</span>
        ))}
      </div>
      {node?.error_code && (
        <p role="alert" className="tn-error">
          {node.error_code}
        </p>
      )}
      {node?.session_id && (
        <details>
          <summary>Context và phiên agent</summary>
          <code>{node.session_id}</code>
          <p>Snapshot: {Object.keys(node.context_receipt ?? {}).join(", ")}</p>
          {node.started_at && (
            <p>
              Bắt đầu {time(node.started_at)}
              {node.completed_at
                ? ` · Kết thúc ${time(node.completed_at)}`
                : ""}
            </p>
          )}
        </details>
      )}
    </div>
  );
}

function Timeline({ run }: { run: TnqdRun }) {
  const nodes = run.nodes.filter((n) => n.started_at),
    start = Math.min(...nodes.map((n) => n.started_at!));
  const end = Math.max(
    ...nodes.map((n) => n.completed_at ?? Date.now() / 1000),
    start + 1,
  );
  return (
    <div className="tn-timeline">
      <p>Thời gian từ backend; mỗi hàng gắn với một task thực tế.</p>
      {nodes.map((node) => (
        <div className="tn-time-row" key={node.id}>
          <span>
            {node.id} ·{" "}
            {node.session_id
              ? (agentRoles[node.role ?? ""] ?? node.role ?? "Agent")
              : "Runner"}
          </span>
          <div className="tn-time-track">
            <div
              className={`tn-time-bar ${node.state.toLowerCase()}`}
              style={{
                left: `${(100 * (node.started_at! - start)) / (end - start)}%`,
                width: `${Math.max(1, (100 * ((node.completed_at ?? Date.now() / 1000) - node.started_at!)) / (end - start))}%`,
              }}
              title={`${node.title ?? node.id} · ${time(node.started_at!)}`}
            />
          </div>
          <small>
            {Math.round(
              (node.completed_at ?? Date.now() / 1000) - node.started_at!,
            )}
            s
          </small>
        </div>
      ))}
    </div>
  );
}

export default function TnqdWorkflowPanel({
  deliveryId,
  cycleId,
  canWrite,
}: {
  deliveryId: string;
  cycleId?: string;
  canWrite: boolean;
}) {
  const { userData } = useContext(AuthContext);
  const [tab, setTab] = useState("dag"),
    [selected, setSelected] = useState(""),
    [docId, setDocId] = useState("");
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const query = useQuery({
    queryKey: ["tnqd-workflow", userData?.id, deliveryId, cycleId],
    enabled: !!userData?.id && !!cycleId,
    queryFn: () => tnqdDemo.list(deliveryId, cycleId!),
    refetchIntervalInBackground: true,
    refetchInterval: (q) =>
      q.state.data?.runs.some((r) => live(r.state)) ? 2500 : false,
  });
  const run = query.data?.runs[0];
  const tasks = [...(run?.plan?.tasks ?? []), ...(run?.followup_tasks ?? [])];
  const task = tasks.find((t) => t.id === selected) ?? tasks[0];
  const done = run?.nodes.filter((n) => n.state === "DONE").length ?? 0;
  const document =
    run?.documents.find((d) => d.id === docId) ?? run?.documents[0];
  const memoryMode = run?.memory?.at(-1)?.mode;
  const documentReceipt = (run?.memory ?? [])
    .slice()
    .reverse()
    .find(
      (receipt) =>
        receipt.document_id === document?.id &&
        receipt.revision === document?.revision &&
        receipt.sha256 === document?.sha256 &&
        receipt.content_verified &&
        receipt.caller_context_id !== "publication-check",
    );
  const command = async (action: "plan" | "execute" | "resume") => {
    if (inFlight.current || !cycleId) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      if (action === "resume" && run)
        await tnqdDemo.resume(deliveryId, {
          cycle_id: cycleId,
          run_id: run.run_id,
        });
      else if (action === "execute" && run?.plan)
        await tnqdDemo.execute(deliveryId, {
          cycle_id: cycleId,
          run_id: run.run_id,
          plan_digest: run.plan.digest,
        });
      else
        await tnqdDemo.plan(deliveryId, {
          cycle_id: cycleId,
          run_id: crypto.randomUUID(),
        });
    } catch {
      setError(
        "Chưa xác nhận yêu cầu. Hãy cập nhật trạng thái trước khi tạo lượt khác.",
      );
    } finally {
      inFlight.current = false;
      setBusy(false);
      await query.refetch();
    }
  };
  return (
    <section className="dw-card tn-panel" aria-label="TNQD Workloop chi tiết">
      <header className="tn-heading">
        <div>
          <span className="tn-eyebrow">MILITARY YOUTH · WORKLOOP</span>
          <h3>Từ nghiệp vụ đến bản cải tiến</h3>
          <p>Tài liệu có nguồn, task cụ thể và bằng chứng từ lượt chạy thật.</p>
        </div>
        <button
          className="vs-refresh"
          aria-label="Cập nhật demo TNQD"
          onClick={() => void query.refetch()}
        >
          <RefreshCw size={16} />
        </button>
      </header>
      <div className="tn-summary">
        <div>
          <Layers size={17} />
          <strong>{tasks.length}</strong>
          <span>task cụ thể</span>
        </div>
        <div>
          <GitBranch size={17} />
          <strong>2</strong>
          <span>agent tối đa cùng lúc</span>
        </div>
        <div>
          <FileText size={17} />
          <strong>{run?.documents.length ?? 0}</strong>
          <span>tài liệu nghiệp vụ</span>
        </div>
        <div>
          <ShieldCheck size={17} />
          <strong>
            {done}/{run?.nodes.length ?? 0}
          </strong>
          <span>bước hoàn tất</span>
        </div>
      </div>
      <div className="tn-toolbar">
        <span className={`tn-state ${run?.state.toLowerCase() ?? "pending"}`}>
          {run ? (labels[run.state] ?? run.state) : "Chưa có lượt chạy"}
        </span>
        <span className="tn-source">tnqd-sut · 791910a9</span>
        {run?.state === "PLAN_READY" ? (
          <button
            disabled={!canWrite || busy}
            className="pl-start"
            onClick={() => void command("execute")}
          >
            <Play size={14} />
            Chạy kế hoạch {run.plan?.tasks.length} task
          </button>
        ) : (
          <button
            disabled={
              !canWrite ||
              busy ||
              query.isPending ||
              query.isError ||
              (!!run && live(run.state))
            }
            className="pl-start"
            onClick={() => void command("plan")}
          >
            {busy || (run && live(run.state)) ? (
              <LoaderCircle size={14} className="animate-spin" />
            ) : (
              <Play size={14} />
            )}
            Tạo spec & kế hoạch
          </button>
        )}
        {run && ["FAILED", "UNCONFIRMED"].includes(run.state) && (
          <button
            className="pl-start"
            disabled={!canWrite || busy}
            onClick={() => void command("resume")}
          >
            <RefreshCw size={14} />
            Tiếp tục lượt chạy
          </button>
        )}
      </div>
      {(error || query.isError || run?.error_code) && (
        <p className="tn-error" role="alert">
          {error || run?.error_code || "Chưa tải được dữ liệu demo TNQD."}
        </p>
      )}
      {memoryMode && (
        <p className="tn-memory-caption">
          {memoryMode === "POKEDEV_PROJECT_DOCUMENT_STORE"
            ? "Memory tài liệu theo project của PokeDev · Cognee trên Harness chưa sẵn sàng"
            : "Đã đọc và đối chiếu nội dung tài liệu qua Memory trên Harness"}
        </p>
      )}
      {run?.parallel && (
        <div
          className={`tn-parallel ${run.parallel.verified ? "verified" : ""}`}
        >
          <GitBranch size={16} />
          <strong>
            {run.parallel.verified
              ? "Đã kiểm chứng chạy song song"
              : "Chưa đủ bằng chứng song song"}
          </strong>
          <span>
            {run.parallel.tasks.join(" + ")} · chồng{" "}
            {run.parallel.overlap_seconds.toFixed(1)} giây
          </span>
        </div>
      )}
      <nav className="tn-tabs" aria-label="Nội dung demo TNQD">
        {[
          ["dag", "Task & DAG"],
          ["timeline", "Chạy song song"],
          ["docs", "Tài liệu & Memory"],
          ["checks", "Test & Verify"],
          ["preview", "Ứng dụng"],
          ["handover", "Bàn giao"],
        ].map(([id, label]) => (
          <button key={id} aria-pressed={tab === id} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </nav>
      {!run && (
        <p className="tn-empty">
          Sẵn sàng chạy live từ source gốc. Bấm “Tạo spec & kế hoạch”, xem ba
          tài liệu và DAG được tạo mới, rồi bấm “Chạy kế hoạch”. Kết quả sẽ xuất
          hiện theo lượt thực hiện của bạn. Các lượt đã cất và Memory vẫn được giữ.
        </p>
      )}
      {run && tab === "dag" && (
        <>
          <p className="tn-plan-summary">
            {run.plan?.summary ??
              "BA đang đọc ngữ cảnh Memory và điền ba mẫu tài liệu. Planner sẽ phân rã spec thành các task có phạm vi và phụ thuộc rõ ràng."}
          </p>
          {!!run.followup_tasks?.length && (
            <section
              className="tn-followups"
              aria-label="TaskLoop xử lý phát hiện TestForge"
            >
              <h4>TaskLoop · xử lý phát hiện từ TestForge</h4>
              <p>
                {run.plan?.tasks.length} task kế hoạch +{" "}
                {run.followup_tasks.length} task phát sinh. Bộ test và yêu cầu
                gốc được giữ nguyên.
              </p>
              <div>
                {run.followup_tasks.map((followup) => (
                  <button
                    key={followup.id}
                    className={selected === followup.id ? "selected" : ""}
                    onClick={() => setSelected(followup.id)}
                    aria-label={`Xem task phát sinh ${followup.id}: ${followup.title}`}
                  >
                    <b>
                      {followup.id} · {followup.role}
                    </b>
                    <span>{followup.title}</span>
                    <small>
                      {
                        labels[
                          run.nodes.find((node) => node.id === followup.id)
                            ?.state ?? "PENDING"
                        ]
                      }
                    </small>
                  </button>
                ))}
              </div>
            </section>
          )}
          <div className="tn-workspace">
            <Dag
              run={run}
              selected={task?.id ?? selected}
              onSelect={setSelected}
            />
            <TaskDetail task={task} run={run} />
          </div>
        </>
      )}
      {run && tab === "timeline" && <Timeline run={run} />}
      {run && tab === "docs" && (
        <div className="tn-documents">
          <div className="tn-doc-picker">
            {run.documents.map((doc) => (
              <button
                key={doc.id}
                aria-pressed={document?.id === doc.id}
                onClick={() => setDocId(doc.id)}
              >
                <FileText size={16} />
                <span>
                  {doc.title}
                  <small>{doc.revision}</small>
                </span>
              </button>
            ))}
          </div>
          {document ? (
            <article className="tn-document">
              <div className="tn-doc-meta">
                <span>{document.revision}</span>
                <span>SHA {document.sha256.slice(0, 12)}</span>
                {documentReceipt && (
                  <span className="tn-memory-verified">
                    ✓ Đã đọc lại từ Memory
                  </span>
                )}
              </div>
              {documentReceipt && (
                <details className="tn-prior">
                  <summary>Nguồn và context tài liệu</summary>
                  <p>
                    {documentReceipt.source_ref ||
                      "Tài liệu theo project của PokeDev"}
                  </p>
                  <p>
                    Đọc lúc{" "}
                    {new Date(documentReceipt.retrieved_at).toLocaleString(
                      "vi-VN",
                    )}
                  </p>
                  <code>{documentReceipt.caller_context_id}</code>
                </details>
              )}
              {document.previous_body && (
                <details className="tn-prior">
                  <summary>Xem phiên bản trước khi phát triển</summary>
                  <SanitizedMarkdown
                    chatMessage={document.previous_body}
                    isEmpty={false}
                  />
                </details>
              )}
              <SanitizedMarkdown chatMessage={document.body} isEmpty={false} />
            </article>
          ) : (
            <p className="tn-empty">
              Tài liệu sẽ xuất hiện khi BA trả kết quả và nội dung được kiểm
              tra.
            </p>
          )}
        </div>
      )}
      {run && tab === "checks" && (
        <div className="tn-checks">
          {run.checks
            ?.slice()
            .sort(
              (a, b) =>
                [
                  "baseline",
                  "candidate",
                  "testforge-attempt-1",
                  "testforge",
                ].indexOf(a.id) -
                [
                  "baseline",
                  "candidate",
                  "testforge-attempt-1",
                  "testforge",
                ].indexOf(b.id),
            )
            .map((group) => (
              <article key={group.id}>
                <details
                  className="tn-check-group"
                  open={group.id === "testforge"}
                >
                  <summary>
                    <ShieldCheck size={18} />
                    <h4>{group.title}</h4>
                    <strong
                      className={
                        group.passed === group.total ? "tn-pass" : "tn-finding"
                      }
                    >
                      {group.passed}/{group.total}
                    </strong>
                  </summary>
                  <p>{group.kind}</p>
                  {group.tests?.map((check) => (
                    <details key={check.id}>
                      <summary>
                        {check.status === "PASS" ? (
                          <CheckCircle2 size={14} />
                        ) : (
                          <Circle size={14} />
                        )}
                        <span>
                          {check.id} · {check.label}
                        </span>
                        <b>{check.status}</b>
                      </summary>
                      {check.error && <p className="tn-error">{check.error}</p>}
                    </details>
                  ))}
                </details>
              </article>
            ))}
          {!run.checks?.length && (
            <p className="tn-empty">
              Chưa có kết quả kiểm thử. Các số liệu được lấy từ runner thực tế.
            </p>
          )}
        </div>
      )}
      {run && tab === "preview" && (
        <div className="tn-preview">
          {run.preview && safeTnqdPreview(run.preview) ? (
            <>
              <div className="tn-preview-heading">
                <div>
                  <strong>TNQD · Bản cải tiến trong Sandbox</strong>
                  <p>
                    45 hồ sơ mẫu · {run.preview.data_mode} · Hết hạn{" "}
                    {new Date(run.preview.expires_at).toLocaleString("vi-VN")}
                  </p>
                </div>
                <a href={run.preview.url!} target="_blank" rel="noreferrer">
                  <ExternalLink size={15} />
                  Mở ứng dụng
                </a>
              </div>
              <iframe
                title="Ứng dụng TNQD trong Sandbox"
                src={run.preview.url!}
                sandbox="allow-scripts allow-same-origin allow-forms"
              />
            </>
          ) : (
            <p className="tn-empty">
              {run.preview?.state === "DEPLOYING"
                ? `Đang đưa bản cải tiến vào Sandbox${run.preview.uploaded_chunks ? ` · Đã chuyển ${run.preview.uploaded_chunks} phần của bản build` : ""}.`
                : "Preview sẽ mở sau khi source đạt kiểm thử và build thành công."}
            </p>
          )}
        </div>
      )}
      {run && tab === "handover" && (
        <div className="tn-handover">
          {run.handover ? (
            <>
              <h4>{run.handover.summary}</h4>
              <h5>File thay đổi</h5>
              {run.handover.changed_files.map((file) => (
                <code className="tn-path" key={file}>
                  {file}
                </code>
              ))}
              <h5>Phạm vi và lưu ý</h5>
              <ul>
                {run.handover.limitations.map((value) => (
                  <li key={value}>{value}</li>
                ))}
              </ul>
              <details>
                <summary>Đối chiếu source, test và lượt chạy</summary>
                <p>Run {run.run_id}</p>
                <p>Source {run.handover.source_digest}</p>
                <p>Suite {run.handover.test_suite_digest}</p>
              </details>
            </>
          ) : (
            <p className="tn-empty">
              Bàn giao được tổng hợp sau Verify, TestForge và cập nhật tài liệu.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
