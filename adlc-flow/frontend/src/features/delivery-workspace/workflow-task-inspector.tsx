import { useEffect, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  CheckCheck,
  Copy,
  FileCode2,
  FolderSearch,
  GitBranch,
  ListOrdered,
  Plus,
  Search,
  Settings2,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  liveError,
  liveWorkflows,
  type LiveTask,
  type ProjectFileIndex,
  type WorkflowEdge,
  type WorkflowGraph,
} from "@/controllers/API/live-workflows";
import {
  connectionIssue,
  isTestPath,
  outputPorts,
  pathIssue,
  portLabels,
  taskKinds,
} from "./workflow-canvas-model";

function TaskList({
  title,
  noun,
  values,
  onChange,
  criteria = false,
}: {
  title: string;
  noun: string;
  values: string[];
  onChange: (values: string[]) => void;
  criteria?: boolean;
}) {
  const [bulk, setBulk] = useState(false);
  const move = (index: number, offset: number) => {
    const next = [...values];
    [next[index], next[index + offset]] = [next[index + offset], next[index]];
    onChange(next);
  };
  return (
    <section className="wc-task-list" aria-label={title}>
      <div className="wc-field-heading">
        <h4>
          {criteria ? <CheckCheck size={15} /> : <ListOrdered size={15} />}
          {title} <small>{values.filter((v) => v.trim()).length}/30</small>
        </h4>
        <button onClick={() => setBulk(!bulk)} aria-pressed={bulk}>
          {bulk ? "Từng mục" : "Nhập nhiều dòng"}
        </button>
      </div>
      <p className="wc-hint">
        {criteria
          ? "Mô tả kết quả có thể kiểm chứng, mỗi tiêu chí một mục."
          : "Chia công việc thành các bước cụ thể. Dùng mũi tên để đổi thứ tự."}
      </p>
      {bulk ? (
        <label className="wc-bulk-label">
          {title}
          <textarea
            rows={8}
            value={values.join("\n")}
            onChange={(e) => onChange(e.target.value.split("\n"))}
          />
          <small>
            Mỗi dòng là một mục. Nội dung được cập nhật trực tiếp vào bản nháp.
          </small>
        </label>
      ) : (
        <div className="wc-list-rows">
          {values.map((value, index) => (
            <div className="wc-list-row" key={index}>
              <span className={`wc-row-number ${criteria ? "criteria" : ""}`}>
                {criteria ? (
                  <CheckCheck size={12} />
                ) : (
                  String(index + 1).padStart(2, "0")
                )}
              </span>
              <textarea
                rows={2}
                aria-label={`${noun} ${index + 1}`}
                value={value}
                maxLength={3000}
                placeholder={
                  criteria ? "Kết quả mong đợi…" : "Cần thực hiện điều gì?"
                }
                onChange={(e) =>
                  onChange(
                    values.map((v, i) => (i === index ? e.target.value : v)),
                  )
                }
              />
              <div className="wc-row-actions">
                <button
                  aria-label={`Đưa ${noun.toLowerCase()} ${index + 1} lên`}
                  disabled={index === 0}
                  onClick={() => move(index, -1)}
                >
                  <ArrowUp size={12} />
                </button>
                <button
                  aria-label={`Đưa ${noun.toLowerCase()} ${index + 1} xuống`}
                  disabled={index === values.length - 1}
                  onClick={() => move(index, 1)}
                >
                  <ArrowDown size={12} />
                </button>
                <button
                  aria-label={`Xóa ${noun.toLowerCase()} ${index + 1}`}
                  onClick={() => onChange(values.filter((_, i) => i !== index))}
                >
                  <X size={12} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
      {(values.length > 30 ||
        values.some((v) => v.trim().length > 0 && v.trim().length < 5)) && (
        <p className="wc-validation">
          Tối đa 30 mục, mỗi mục cần ít nhất 5 ký tự để chạy workflow.
        </p>
      )}
      <button
        className="wc-add-row"
        disabled={values.length >= 30}
        onClick={() => onChange([...values, ""])}
      >
        <Plus size={13} />
        Thêm {noun.toLowerCase()}
      </button>
    </section>
  );
}

function FileScope({
  task,
  project,
  graph,
  onChange,
}: {
  task: LiveTask;
  project: string;
  graph: WorkflowGraph;
  onChange: (paths: string[]) => void;
}) {
  const [open, setOpen] = useState(false),
    [query, setQuery] = useState("");
  const [index, setIndex] = useState<ProjectFileIndex | null>(null),
    [error, setError] = useState("");
  const [loading, setLoading] = useState(false),
    [retry, setRetry] = useState(0);
  const paths = task.write_paths || [];
  useEffect(() => {
    setIndex(null);
    setError("");
  }, [project]);
  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoading(true);
    setError("");
    liveWorkflows
      .files(project)
      .then((data) => {
        if (active) setIndex(data);
      })
      .catch((failure) => {
        if (active) setError(liveError(failure));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [project, open, retry]);
  const issue = (path: string) =>
    pathIssue(path) ||
    (task.kind === "test" && !isTestPath(path)
      ? "Tester cần một đường dẫn file kiểm thử mới."
      : "") ||
    (task.kind === "implement" && isTestPath(path)
      ? "File kiểm thử thuộc phạm vi Tester."
      : "") ||
    (task.kind === "test" && index?.paths.includes(path)
      ? "Bộ test có sẵn được giữ nguyên. Chọn tên file kiểm thử mới."
      : "");
  const matches =
    index?.paths.filter((path) =>
      path.toLowerCase().includes(query.toLowerCase()),
    ) || [];
  const add = (path: string) => {
    if (!paths.includes(path) && paths.length < 40)
      onChange([...paths.filter(Boolean), path]);
  };
  if (task.kind === "review")
    return (
      <div className="wc-empty-panel">
        <ShieldCheck size={28} />
        <h4>Task chỉ đọc</h4>
        <p>
          Reviewer và các node điều khiển được đọc source, tiêu chí và kết quả
          kiểm chứng. Chúng không được sửa file.
        </p>
      </div>
    );
  return (
    <section className="wc-scope">
      <div className="wc-field-heading">
        <h4>
          <FileCode2 size={15} />
          File được phép sửa <small>{paths.filter(Boolean).length}/40</small>
        </h4>
      </div>
      <p className="wc-hint">
        {task.kind === "test"
          ? "Tester viết file kiểm thử mới. Bộ test có sẵn được giữ nguyên qua các vòng sửa."
          : "Chọn file trong project hoặc nhập đường dẫn file mới. Phạm vi này giới hạn những gì Developer được sửa."}
      </p>
      <button className="wc-repo-picker" onClick={() => setOpen(true)}>
        <FolderSearch size={16} />
        Duyệt file của project
      </button>
      <div className="wc-file-rows">
        {paths.map((path, i) => {
          const shared = graph.nodes.filter(
            (n) => n.id !== task.id && n.task.write_paths?.includes(path),
          );
          return (
            <div className="wc-file-row" key={i}>
              <div>
                <FileCode2 size={14} />
                <input
                  aria-label={`File được phép sửa ${i + 1}`}
                  value={path}
                  maxLength={300}
                  placeholder={
                    task.kind === "test"
                      ? "tests/test_feature.py"
                      : "src/feature.ts"
                  }
                  onChange={(e) =>
                    onChange(
                      paths.map((v, j) => (j === i ? e.target.value : v)),
                    )
                  }
                />
                <button
                  aria-label={`Bỏ file ${i + 1}`}
                  onClick={() => onChange(paths.filter((_, j) => j !== i))}
                >
                  <X size={13} />
                </button>
              </div>
              {path && issue(path) && (
                <p className="wc-validation">{issue(path)}</p>
              )}
              {path && shared.length > 0 && (
                <p className="wc-hint">
                  Cũng thuộc {shared.map((n) => n.id).join(", ")}. Các task sửa
                  cùng file cần chạy tuần tự.
                </p>
              )}
            </div>
          );
        })}
      </div>
      {!paths.length && (
        <p className="wc-empty-note">
          Chưa có file nào. Thêm phạm vi trước khi sử dụng workflow.
        </p>
      )}
      <button
        className="wc-add-row"
        disabled={paths.length >= 40}
        onClick={() => onChange([...paths, ""])}
      >
        <Plus size={13} />
        Thêm đường dẫn file
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="wc-dialog wc-files-dialog">
          <DialogTitle>File của project</DialogTitle>
          <DialogDescription>
            {task.kind === "test"
              ? "Danh sách để tham khảo. Tester chỉ thêm file kiểm thử mới bằng đường dẫn trong panel task."
              : "Chọn các file cụ thể để thêm vào phạm vi task. Bạn cũng có thể nhập đường dẫn file mới trong panel."}
          </DialogDescription>
          <div className="wc-search">
            <Search size={16} />
            <input
              aria-label="Tìm file trong project"
              placeholder="Tìm theo tên hoặc đường dẫn…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          {loading ? (
            <p role="status">Đang đọc danh sách file…</p>
          ) : error ? (
            <div role="alert">
              <p>{error}</p>
              <button onClick={() => setRetry((v) => v + 1)}>Thử lại</button>
            </div>
          ) : (
            <>
              <div className="wc-file-index-meta">
                <span>
                  {matches.length} file
                  {matches.length > 200
                    ? " · Hiện 200 kết quả đầu, hãy tìm cụ thể hơn"
                    : ""}
                </span>
                <code title={index?.commit}>
                  Commit {index?.commit.slice(0, 8)}
                </code>
              </div>
              <div className="wc-file-index">
                {matches.slice(0, 200).map((path) => {
                  const checked = paths.includes(path),
                    blocked = !!issue(path) || (!checked && paths.length >= 40);
                  return (
                    <label key={path} title={issue(path) || path}>
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={blocked && !checked}
                        onChange={(e) =>
                          e.target.checked
                            ? add(path)
                            : onChange(paths.filter((p) => p !== path))
                        }
                      />
                      <FileCode2 size={14} />
                      <span>{path}</span>
                      {isTestPath(path) && <small>Test có sẵn</small>}
                    </label>
                  );
                })}
                {!matches.length && (
                  <p className="wc-empty-note">Không tìm thấy file phù hợp.</p>
                )}
              </div>
              {index?.truncated && (
                <p>
                  Repo lớn: danh sách giới hạn 20.000 file. Có thể nhập đường
                  dẫn trực tiếp.
                </p>
              )}
            </>
          )}
          <div className="wc-dialog-actions">
            <span>{paths.filter(Boolean).length} file đã chọn</span>
            <button onClick={() => setOpen(false)}>Xong</button>
          </div>
        </DialogContent>
      </Dialog>
    </section>
  );
}

export default function WorkflowTaskInspector({
  task,
  graph,
  project,
  onChange,
  onConnect,
  onDisconnect,
  onRename,
  onDuplicate,
  onDelete,
}: {
  task: LiveTask;
  graph: WorkflowGraph;
  project: string;
  onChange: (changes: Partial<LiveTask>) => void;
  onConnect: (edge: {
    source: string;
    target: string;
    sourceHandle?: string;
  }) => void;
  onDisconnect: (edge: WorkflowEdge) => void;
  onRename: (id: string) => void;
  onDuplicate: () => void;
  onDelete: () => void;
}) {
  const [tab, setTab] = useState("content"),
    [newId, setNewId] = useState(task.id);
  const [from, setFrom] = useState(""),
    [port, setPort] = useState("done");
  const tabs = [
    ["content", "Nội dung", ListOrdered],
    ["scope", "Phạm vi", FileCode2],
    ["connections", "Kết nối", GitBranch],
    ["advanced", "Nâng cao", Settings2],
  ] as const;
  const incoming = graph.edges.filter((e) => e.target === task.id),
    outgoing = graph.edges.filter((e) => e.source === task.id);
  const sourceTask = graph.nodes.find((n) => n.id === from)?.task;
  const connectionError = from
    ? connectionIssue(graph, from, task.id, port as WorkflowEdge["port"])
    : "Chọn task nguồn";
  return (
    <>
      <div className="wc-inspector-title">
        <span className="lw-eyebrow">CHI TIẾT TASK · {task.id}</span>
        <div>
          <button
            aria-label="Nhân bản task"
            title="Nhân bản task"
            disabled={graph.nodes.length >= 20}
            onClick={onDuplicate}
          >
            <Copy size={14} />
          </button>
          <button
            aria-label="Xóa task"
            title="Xóa task và các kết nối"
            onClick={onDelete}
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>
      <nav className="wc-inspector-tabs" aria-label="Chỉnh sửa task">
        {tabs.map(([key, label, Icon]) => (
          <button
            key={key}
            aria-pressed={tab === key}
            onClick={() => setTab(key)}
          >
            <Icon size={13} />
            {label}
          </button>
        ))}
      </nav>
      <div className="wc-inspector-body" key={tab}>
        {tab === "content" && (
          <>
            <label>
              Tên task
              <input
                value={task.title}
                maxLength={300}
                onChange={(e) => onChange({ title: e.target.value })}
              />
            </label>
            {!task.control && (
              <label>
                Vai trò
                <select
                  value={task.kind}
                  onChange={(e) =>
                    onChange({
                      kind: e.target.value,
                      ...(e.target.value === "review"
                        ? { write_paths: [] }
                        : {}),
                    })
                  }
                >
                  {Object.entries(taskKinds).map(([key, value]) => (
                    <option value={key} key={key}>
                      {value.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {task.control?.type === "condition" && (
              <label>
                Điều kiện kiểm tra
                <select
                  value={task.control.predicate}
                  onChange={(e) =>
                    onChange({
                      control: {
                        type: "condition",
                        predicate: e.target.value as
                          | "status_done"
                          | "verification_passed"
                          | "review_approved",
                      },
                    })
                  }
                >
                  <option value="verification_passed">Kiểm thử đạt</option>
                  <option value="status_done">Task đã hoàn tất</option>
                  <option value="review_approved">Review đã duyệt</option>
                </select>
                <small>
                  Nhận một đầu vào; nối đủ nhánh Đúng và Không khớp trong mục
                  Kết nối.
                </small>
              </label>
            )}
            {task.control?.type === "gate" && (
              <>
                <label>
                  Người duyệt
                  <select
                    value={task.control.reviewer}
                    onChange={(e) =>
                      onChange({
                        control: {
                          ...(task.control as Extract<
                            NonNullable<LiveTask["control"]>,
                            { type: "gate" }
                          >),
                          reviewer: e.target.value as "human" | "agent",
                        },
                      })
                    }
                  >
                    <option value="human">Người dùng</option>
                    <option value="agent">Agent review độc lập</option>
                  </select>
                </label>
                <label>
                  Số vòng sửa tối đa
                  <input
                    type="number"
                    min={0}
                    max={3}
                    value={task.control.max_rounds}
                    onChange={(e) =>
                      onChange({
                        control: {
                          ...(task.control as Extract<
                            NonNullable<LiveTask["control"]>,
                            { type: "gate" }
                          >),
                          max_rounds: Math.max(
                            0,
                            Math.min(3, Number(e.target.value)),
                          ),
                        },
                      })
                    }
                  />
                  <small>
                    0: duyệt hoặc dừng. 1–3: nối nhánh Yêu cầu sửa về Developer
                    phía trước. Bộ test được giữ nguyên.
                  </small>
                </label>
              </>
            )}
            {task.control?.type === "verify" && (
              <p className="wc-info">
                Chạy các lệnh trong Kiểm chứng & preview sau tất cả Tester. Kết
                quả thực tế quyết định nhánh điều kiện tiếp theo.
              </p>
            )}
            <TaskList
              title="Các bước thực hiện"
              noun="Bước"
              values={task.steps || []}
              onChange={(steps) => onChange({ steps })}
            />
            <TaskList
              title="Tiêu chí nghiệm thu"
              noun="Tiêu chí"
              criteria
              values={task.acceptance || []}
              onChange={(acceptance) => onChange({ acceptance })}
            />
          </>
        )}
        {tab === "scope" && (
          <FileScope
            task={task}
            project={project}
            graph={graph}
            onChange={(write_paths) => onChange({ write_paths })}
          />
        )}
        {tab === "connections" && (
          <>
            <div className="wc-field-heading">
              <h4>
                <GitBranch size={15} />
                Luồng vào & ra
              </h4>
            </div>
            <p className="wc-hint">
              Kết nối tại đây hoặc kéo từ chấm đầu ra trên canvas. Mỗi nhánh
              điều kiện có ý nghĩa riêng.
            </p>
            <h4 className="wc-small-heading">Đầu vào · {incoming.length}</h4>
            {incoming.map((e) => (
              <div
                className="wc-connection"
                key={`${e.source}:${e.port || "done"}`}
              >
                <span>
                  <code>{e.source}</code>
                  <small>
                    {portLabels[e.port || "done"]}
                    {e.feedback ? " · vòng sửa" : ""}
                  </small>
                </span>
                <button
                  aria-label={`Bỏ kết nối ${e.source} ${e.port || "done"} đến ${e.target}`}
                  onClick={() => onDisconnect(e)}
                >
                  <X size={14} />
                </button>
              </div>
            ))}
            <h4 className="wc-small-heading">Đầu ra · {outgoing.length}</h4>
            {outgoing.map((e) => (
              <div
                className="wc-connection"
                key={`${e.target}:${e.port || "done"}`}
              >
                <span>
                  <code>{e.target}</code>
                  <small>
                    {portLabels[e.port || "done"]}
                    {e.feedback ? " · vòng sửa" : ""}
                  </small>
                </span>
                <button
                  aria-label={`Bỏ kết nối ${e.source} ${e.port || "done"} đến ${e.target}`}
                  onClick={() => onDisconnect(e)}
                >
                  <X size={14} />
                </button>
              </div>
            ))}
            <div className="wc-connect-form">
              <label>
                Nhận từ task
                <select
                  value={from}
                  onChange={(e) => {
                    setFrom(e.target.value);
                    const t = graph.nodes.find(
                      (n) => n.id === e.target.value,
                    )?.task;
                    setPort(t ? outputPorts(t)[0] : "done");
                  }}
                >
                  <option value="">Chọn task…</option>
                  {graph.nodes
                    .filter((n) => n.id !== task.id)
                    .map((n) => (
                      <option key={n.id} value={n.id}>
                        {n.id} · {n.task.title}
                      </option>
                    ))}
                </select>
              </label>
              {sourceTask && (
                <label>
                  Nhánh đầu ra
                  <select
                    value={port}
                    onChange={(e) => setPort(e.target.value)}
                  >
                    {outputPorts(sourceTask).map((p) => (
                      <option key={p} value={p}>
                        {portLabels[p]}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <button
                disabled={!!connectionError}
                title={connectionError || "Thêm kết nối"}
                onClick={() =>
                  onConnect({
                    source: from,
                    target: task.id,
                    sourceHandle: port,
                  })
                }
              >
                <Plus size={14} />
                Thêm kết nối
              </button>
              {from && connectionError && (
                <p className="wc-validation">{connectionError}</p>
              )}
            </div>
            <p className="wc-hint">
              Để thêm đầu ra, chọn task đích rồi chọn task này làm nguồn, hoặc
              nối trực tiếp trên canvas.
            </p>
          </>
        )}
        {tab === "advanced" && (
          <>
            <div className="wc-field-heading">
              <h4>
                <Settings2 size={15} />
                Thiết lập nâng cao
              </h4>
            </div>
            <label>
              Mã task
              <input
                value={newId}
                maxLength={31}
                onChange={(e) => setNewId(e.target.value.toUpperCase())}
              />
              <small>
                Mã duy nhất dùng trong kết nối. Đổi mã sẽ cập nhật toàn bộ liên
                kết liên quan.
              </small>
            </label>
            <button
              disabled={newId === task.id}
              onClick={() => onRename(newId)}
            >
              Đổi mã task
            </button>
            <label>
              Khi có nhiều đầu vào thường
              <select
                value={task.join || "all"}
                onChange={(e) =>
                  onChange({ join: e.target.value as "all" | "any" })
                }
              >
                <option value="all">Cần tất cả nhánh</option>
                <option value="any">Cần một nhánh</option>
              </select>
              <small>
                Áp dụng với workflow điều khiển (v2). Các nhánh điều kiện vẫn
                phải khớp đầu ra đã chọn.
              </small>
            </label>
            {graph.version === 1 && (
              <p className="wc-info">
                Thay đổi cách gộp nhánh sẽ chuyển workflow sang v2.
              </p>
            )}
            <p className="wc-hint">
              Vai trò quyết định quyền thực thi: Developer sửa source, Tester
              viết test mới, Reviewer chỉ đọc. Lệnh chạy dùng chung trong Kiểm
              chứng & preview.
            </p>
          </>
        )}
      </div>
    </>
  );
}
