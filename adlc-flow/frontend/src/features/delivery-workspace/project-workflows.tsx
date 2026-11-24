import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  CheckCircle2,
  ExternalLink,
  GitBranch,
  LoaderCircle,
  Plus,
  Workflow,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  liveError,
  liveWorkflows,
  type LiveProject,
  type ProjectWorkflow,
} from "@/controllers/API/live-workflows";
import WorkflowCanvas from "./workflow-canvas";
import {
  graphFromPlan,
  starterGraph,
  controlledStarterGraph,
} from "./workflow-canvas-model";

export default function ProjectWorkflows({
  identity,
  projectId,
  projects,
  onUse,
  onApplied,
}: {
  identity: string;
  projectId: string;
  projects: LiveProject[];
  onUse: (workflow: ProjectWorkflow) => void;
  onApplied: (runId: string, projectId: string) => void;
}) {
  const [params, setParams] = useSearchParams(),
    client = useQueryClient();
  const selected = params.get("workflow"),
    editRun = params.get("edit_run") || params.get("from_run"),
    applying = !!params.get("edit_run");
  const [error, setError] = useState("");
  const workflows = useQuery({
    queryKey: ["project-workflows", identity, projectId],
    queryFn: () => liveWorkflows.workflows(projectId || undefined),
    retry: false,
  });
  const packages = useQuery({
    queryKey: ["package-workflows", identity, projectId],
    queryFn: () => liveWorkflows.packageWorkflows(projectId || undefined),
    enabled: !selected,
    retry: false,
  });
  const detail = useQuery({
    queryKey: ["project-workflow", identity, selected],
    queryFn: () => liveWorkflows.workflow(selected!),
    enabled: !!selected && selected !== "new",
    retry: false,
  });
  const run = useQuery({
    queryKey: ["live-run", identity, editRun],
    queryFn: () => liveWorkflows.read(editRun!),
    enabled: !!editRun,
    retry: false,
  });
  const fresh = useMemo<ProjectWorkflow>(
    () => ({
      workflow_id: crypto.randomUUID(),
      project_id:
        run.data?.project_id || projectId || projects[0]?.project_id || "",
      name: run.data?.plan
        ? `${run.data.title.slice(0, 95)} · workflow`
        : params.get("template") === "controls"
          ? "Workflow có duyệt kết quả"
          : "Workflow mới",
      digest: "",
      revision: 0,
      ready: false,
      graph: run.data?.plan
        ? graphFromPlan(run.data.plan)
        : params.get("template") === "controls"
          ? controlledStarterGraph()
          : starterGraph(),
    }),
    [
      projectId,
      projects[0]?.project_id,
      run.data?.run_id,
      params.get("template"),
    ],
  );
  const editing = selected === "new" ? fresh : detail.data;
  const close = () =>
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      next.delete("workflow");
      next.delete("edit_run");
      next.delete("from_run");
      next.delete("template");
      return next;
    });
  if (selected) {
    if (
      (selected === "new" && editRun && !run.data) ||
      (selected !== "new" && !detail.data)
    )
      return (
        <div className="lw-empty">
          {detail.error || run.error ? (
            <>
              <p role="alert">{liveError(detail.error || run.error)}</p>
              <button onClick={close}>Về danh sách workflow</button>
            </>
          ) : (
            <>
              <LoaderCircle className="animate-spin" />
              <p>Đang mở canvas…</p>
            </>
          )}
        </div>
      );
    return (
      <WorkflowCanvas
        key={editing!.workflow_id}
        workflow={editing!}
        projects={projects}
        onClose={close}
        applying={applying}
        onSaved={(saved) => {
          client.setQueryData(
            ["project-workflow", identity, saved.workflow_id],
            saved,
          );
          void client.invalidateQueries({
            queryKey: ["project-workflows", identity],
          });
          if (selected === "new")
            setParams(
              (previous) => {
                const next = new URLSearchParams(previous);
                next.set("workflow", saved.workflow_id);
                next.set("project", saved.project_id);
                return next;
              },
              { replace: true },
            );
        }}
        onUse={async (saved) => {
          if (applying && run.data) {
            const result = await liveWorkflows.applyWorkflow(run.data, saved);
            client.setQueryData(["live-run", identity, result.run_id], result);
            onApplied(result.run_id, result.project_id!);
          } else onUse(saved);
        }}
      />
    );
  }
  return (
    <section className="pw-library">
      <header className="pw-heading">
        <div>
          <span className="lw-eyebrow">
            THIẾT KẾ MỘT LẦN · DÙNG CHO NHIỀU YÊU CẦU
          </span>
          <h2>Workflow của project</h2>
          <p>
            Thiết kế cách Agent làm việc. Mỗi lượt dùng một phiên bản đã lưu của
            canvas.
          </p>
        </div>
        <button
          className="lw-primary"
          disabled={!projects.length}
          onClick={() =>
            setParams((previous) => {
              const next = new URLSearchParams(previous);
              next.set("view", "workflows");
              next.set("workflow", "new");
              next.delete("run");
              return next;
            })
          }
        >
          <Plus size={15} />
          Tạo workflow
        </button>
      </header>
      <button
        className="pw-control-template"
        disabled={!projects.length}
        onClick={() =>
          setParams((previous) => {
            const next = new URLSearchParams(previous);
            next.set("view", "workflows");
            next.set("workflow", "new");
            next.set("template", "controls");
            next.delete("run");
            return next;
          })
        }
      >
        <GitBranch size={15} /> Tạo workflow có điều kiện & duyệt kết quả
      </button>
      {(error || workflows.error) && (
        <p role="alert" className="lw-alert">
          {error || liveError(workflows.error)}
        </p>
      )}
      <div className="pw-explainer">
        <div>
          <span>01</span>
          <strong>Thiết kế canvas</strong>
          <p>Thêm task, vai trò, file và kết nối.</p>
        </div>
        <ArrowRight size={16} />
        <div>
          <span>02</span>
          <strong>Chọn khi tạo yêu cầu</strong>
          <p>Workflow gắn với repo của project.</p>
        </div>
        <ArrowRight size={16} />
        <div>
          <span>03</span>
          <strong>Duyệt & theo dõi</strong>
          <p>Cùng một kế hoạch từ canvas đến kết quả.</p>
        </div>
      </div>
      <div className="pw-grid">
        {workflows.data?.items.map((workflow) => (
          <article className="pw-card" key={workflow.workflow_id}>
            <div className="pw-card-top">
              <span className="pw-icon">
                <Workflow size={21} />
              </span>
              <span className={`lw-state ${workflow.ready ? "done" : ""}`}>
                {workflow.ready ? (
                  <>
                    <CheckCircle2 size={11} />
                    Sẵn sàng
                  </>
                ) : (
                  "Bản nháp"
                )}
              </span>
            </div>
            <h3>{workflow.name}</h3>
            <p>
              {workflow.graph.summary ||
                "Workflow được thiết kế cho project của bạn."}
            </p>
            <div className="pw-card-meta">
              <span>
                <GitBranch size={12} />
                {workflow.graph.nodes.length} task ·{" "}
                {workflow.graph.edges.length} kết nối
              </span>
              <span>v{workflow.revision}</span>
            </div>
            <small>
              {projects.find(
                (project) => project.project_id === workflow.project_id,
              )?.repository || workflow.project_id}
            </small>
            <footer>
              <button
                onClick={() =>
                  setParams((previous) => {
                    const next = new URLSearchParams(previous);
                    next.set("workflow", workflow.workflow_id);
                    return next;
                  })
                }
              >
                Chỉnh sửa canvas
                <ArrowRight size={13} />
              </button>
              <button
                disabled={!workflow.ready}
                onClick={() => {
                  setError("");
                  onUse(workflow);
                }}
              >
                Sử dụng
              </button>
            </footer>
          </article>
        ))}
      </div>
      {!workflows.data?.items.length && (
        <div className="pw-empty">
          <Workflow size={34} />
          <h3>
            {workflows.isFetching
              ? "Đang tải workflow…"
              : "Tạo cách làm việc của project"}
          </h3>
          <p>
            Bắt đầu với Developer, Tester và Reviewer. Bạn có thể thêm task,
            thay đổi thứ tự và chỉnh phạm vi trước khi lưu.
          </p>
          <button
            disabled={!projects.length || workflows.isFetching}
            onClick={() =>
              setParams((previous) => {
                const next = new URLSearchParams(previous);
                next.set("workflow", "new");
                return next;
              })
            }
          >
            <Plus size={15} />
            Thiết kế workflow đầu tiên
          </button>
        </div>
      )}
      <div className="pw-advanced">
        <div>
          <h3>Canvas gói & công cụ hiện có</h3>
          <p>
            Các workflow gói, thư viện, duyệt hợp đồng và chu kỳ phát triển vẫn
            có trong cùng workspace.
          </p>
        </div>
        <a href={projectId ? `/all/folder/${projectId}` : "/flows"}>
          Mở canvas gói
          <ExternalLink size={14} />
        </a>
        <button
          onClick={() =>
            setParams((previous) => {
              const next = new URLSearchParams(previous);
              next.set("view", "advanced");
              if (projectId) next.set("project_id", projectId);
              return next;
            })
          }
        >
          Công cụ
          <ArrowRight size={14} />
        </button>
      </div>
      {packages.error && (
        <p role="alert" className="lw-alert">
          {liveError(packages.error)}
        </p>
      )}
      {!!packages.data?.length && (
        <div className="pw-package-list">
          {packages.data.map((flow) => (
            <a href={`/flow/${flow.id}`} key={flow.id}>
              <span className="pw-icon">
                <Workflow size={17} />
              </span>
              <span>
                <strong>{flow.name}</strong>
                <small>
                  Canvas gói ·{" "}
                  {projects.find((p) => p.project_id === flow.folder_id)
                    ?.repository || "Project từ thư mục"}
                </small>
              </span>
              <ArrowRight size={15} />
            </a>
          ))}
        </div>
      )}
    </section>
  );
}
