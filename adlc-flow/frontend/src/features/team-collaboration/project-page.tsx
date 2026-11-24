import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CheckCircle2,
  FileCheck2,
  Layers,
  LockKeyhole,
  Users,
} from "lucide-react";
import { useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import * as api from "@/controllers/API/collaboration";
import { teamProject, teamProjects } from "@/controllers/API/team-access";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import useAuthStore from "@/stores/authStore";

const labels: Record<api.SharedResource["kind"], string> = {
  CONTRACT: "Yêu cầu & contract",
  WORKFLOW: "Workflow",
  PLAN: "Kế hoạch kỹ thuật",
  RUN: "Run",
  ARTIFACT: "Artifact",
  CANDIDATE: "Candidate",
  VERIFICATION: "Bằng chứng Verify",
  TEST_SUITE: "Test suite",
};
const status: Record<string, string> = {
  DRAFT: "Bản nháp",
  SUBMITTED: "Chờ duyệt",
  APPROVED: "Đã duyệt",
  CHANGES_REQUESTED: "Cần chỉnh sửa",
  FROZEN: "Đã khóa",
  RETAINED: "Đã lưu",
};
const records = (value: unknown) =>
  z.array(z.record(z.unknown())).safeParse(value).data || [];
const text = (value: unknown) => (typeof value === "string" ? value : "");
const inputClass = "w-full rounded-lg border bg-background px-3 py-2 text-sm";
const panel = "rounded-xl border bg-card p-5";
type Operation = () => Promise<api.SharedResource | void>;

export default function TeamProjectPage() {
  const identity = useAuthStore((store) => store.userData?.id);
  const [params, setParams] = useSearchParams();
  const [selected, setSelected] = useState("");
  const [offset, setOffset] = useState(0);
  const [tab, setTab] = useState("all");
  const [enableReview, setEnableReview] = useState<number | null>(null);
  const client = useQueryClient();
  const key = ["team-collaboration", identity];
  const projects = useQuery({
    queryKey: [...key, "projects"],
    queryFn: teamProjects,
    enabled: !!identity,
  });
  const pid =
    params.get("project") || projects.data?.projects[0]?.project_id || "";
  const base = useQuery({
    queryKey: [...key, pid, "access"],
    queryFn: () => teamProject(pid),
    enabled: !!identity && !!pid,
    refetchInterval: 30000,
  });
  const ready = base.data?.mode === "COLLABORATION" && !base.isError;
  const space = useQuery({
    queryKey: [...key, pid, "overview", offset],
    queryFn: () => api.workspace(pid, offset),
    enabled: !!identity && !!pid && ready,
    refetchInterval: 15000,
  });
  const detail = useQuery({
    queryKey: [...key, pid, "resource", selected],
    queryFn: () => api.sharedResource(pid, selected),
    enabled: !!identity && !!selected && ready,
    refetchInterval: 15000,
  });
  const refresh = async () => {
    await client.invalidateQueries({ queryKey: key });
  };
  const action = useMutation({
    mutationFn: (operation: Operation) => operation(),
    onSuccess: async (result) => {
      if (result) setSelected(result.id);
      await refresh();
    },
    onError: () => refresh(),
  });
  const enabling = useMutation({
    mutationFn: (revision: number) => api.enableCollaboration(pid, revision),
    onSuccess: async () => {
      setEnableReview(null);
      await refresh();
    },
    onError: () => refresh(),
  });
  const blocked =
    action.isPending ||
    space.isFetching ||
    space.isError ||
    base.isError ||
    !space.data;
  const can = (permission: string) =>
    !blocked && space.data?.effective.permissions[permission]?.allowed === true;
  const granted = (permission: string) =>
    space.data?.effective.permissions[permission]?.allowed === true;
  const items =
    space.data?.resources.filter((item) =>
      tab === "runs"
        ? item.kind === "RUN"
        : tab === "inbox"
          ? space.data?.inbox.some((gate) => gate.resource_id === item.id)
          : true,
    ) || [];
  return (
    <main className="h-full overflow-auto p-5 lg:p-8">
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="mb-2 flex items-center gap-2 text-xs text-primary">
              <Users size={16} /> PokeDev · Team workspace
            </p>
            <h1 className="text-2xl font-semibold">Không gian nhóm</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              Một project, cùng yêu cầu và kế hoạch — mỗi quyết định có người
              chịu trách nhiệm.
            </p>
          </div>
          <div className="min-w-56">
            <label
              htmlFor="collaboration-project"
              className="mb-1 block text-xs"
            >
              Project
            </label>
            <select
              id="collaboration-project"
              className={inputClass}
              value={pid}
              disabled={action.isPending || enabling.isPending}
              onChange={(event) => {
                setParams({ project: event.target.value });
                setSelected("");
                setOffset(0);
              }}
            >
              <option value="" disabled>
                Chọn project
              </option>
              {projects.data?.projects.map((item) => (
                <option key={item.project_id} value={item.project_id}>
                  {item.name}
                </option>
              ))}
            </select>
          </div>
        </header>
        <div className="flex gap-3 rounded-xl border bg-muted/30 p-4 text-sm">
          <LockKeyhole className="shrink-0 text-primary" size={19} />
          <div>
            <p className="font-medium">
              Cộng tác và phê duyệt đã mở; thực thi agent chưa mở
            </p>
            <p className="mt-1 text-muted-foreground">
              Chuẩn bị run không gọi model, sandbox, Verify worker hoặc GitHub.
              Quyền thực thi và delegation được bổ sung ở H7C.
            </p>
          </div>
        </div>
        {(projects.isLoading || base.isLoading) && (
          <p role="status">Đang xác minh quyền project…</p>
        )}
        {(projects.isError || base.isError) && (
          <p role="alert" className="text-destructive">
            {api.collaborationError(projects.error || base.error)}
          </p>
        )}
        {projects.data?.projects.length === 0 && (
          <div className={panel}>
            Chưa có project được cấp. Admin có thể khởi tạo và phân quyền tại{" "}
            <a href="/team-access/" className="underline">
              Thành viên & quyền
            </a>
            .
          </div>
        )}
        {base.data && !base.isError && !ready && (
          <div className={panel}>
            <h2 className="font-semibold">Project chưa mở cộng tác</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              Chỉ bật cho project rỗng. Dữ liệu private và lịch sử cũ không tự
              động chuyển sang team.
            </p>
            {base.data.can_manage && (
              <Button
                className="mt-4"
                disabled={base.isFetching || enabling.isPending}
                onClick={() => setEnableReview(base.data!.revision)}
              >
                Thiết lập cộng tác cho project này
              </Button>
            )}
          </div>
        )}
        {space.isError && (
          <p role="alert" className="text-destructive">
            {api.collaborationError(space.error)}
          </p>
        )}
        {action.error && (
          <p role="alert" className="text-destructive">
            {api.collaborationError(action.error)}
          </p>
        )}
        {ready && space.data && !space.isError && (
          <>
            <div className="grid gap-3 sm:grid-cols-3">
              {[
                ["Tài nguyên chia sẻ", space.data.total],
                ["Chờ bạn duyệt", space.data.inbox.length],
                ["Chính sách hiện tại", `v${space.data.policy_revision}`],
              ].map(([name, value]) => (
                <div key={name} className={panel}>
                  <p className="text-xs text-muted-foreground">{name}</p>
                  <p className="mt-2 text-2xl font-semibold">{value}</p>
                </div>
              ))}
            </div>
            <div className="grid items-start gap-5 xl:grid-cols-[350px_minmax(0,1fr)]">
              <aside className="space-y-4">
                <div className={panel}>
                  <div className="mb-4 flex gap-2">
                    {[
                      ["all", "Tất cả"],
                      ["inbox", "Chờ duyệt"],
                      ["runs", "Run"],
                    ].map(([id, name]) => (
                      <Button
                        key={id}
                        variant={tab === id ? "secondary" : "ghost"}
                        size="sm"
                        onClick={() => setTab(id)}
                      >
                        {name}
                      </Button>
                    ))}
                  </div>
                  <div className="space-y-2">
                    {items.map((item) => (
                      <button
                        type="button"
                        key={item.id}
                        onClick={() => setSelected(item.id)}
                        className={`w-full rounded-lg border p-3 text-left ${selected === item.id ? "border-primary bg-primary/5" : "hover:bg-muted/40"}`}
                      >
                        <p className="text-[10px] text-muted-foreground">
                          {labels[item.kind]} · v{item.revision}
                        </p>
                        <p className="mt-1 text-sm font-medium">{item.title}</p>
                        <p className="mt-2 text-xs text-primary">
                          {status[item.status] || item.status}
                        </p>
                      </button>
                    ))}
                    {items.length === 0 && (
                      <p className="text-sm text-muted-foreground">
                        Chưa có mục trong trang này.
                      </p>
                    )}
                  </div>
                  <div className="mt-4 flex items-center justify-between text-xs">
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={!offset || blocked}
                      onClick={() => setOffset(Math.max(0, offset - 50))}
                    >
                      Trang trước
                    </Button>
                    <span>
                      {offset + 1}–{Math.min(offset + 50, space.data.total)}
                    </span>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={offset + 50 >= space.data.total || blocked}
                      onClick={() => setOffset(offset + 50)}
                    >
                      Trang sau
                    </Button>
                  </div>
                </div>
                {granted("requirement:write") && (
                  <NewContract
                    policy={space.data.policy_revision}
                    project={pid}
                    busy={blocked}
                    run={(op) => action.mutate(op)}
                  />
                )}
                {(granted("flow:create") || granted("test_suite:write")) && (
                  <AuthoringForm
                    key={pid}
                    data={space.data}
                    canWorkflow={granted("flow:create")}
                    canSuite={granted("test_suite:write")}
                    busy={blocked}
                    run={(op) => action.mutate(op)}
                  />
                )}
                {granted("policy:manage") && granted("run:read") && (
                  <ImportRun
                    project={pid}
                    busy={blocked}
                    run={(op) => action.mutate(op)}
                  />
                )}
              </aside>
              <section className="min-w-0">
                {selected && detail.isLoading && (
                  <p role="status">Đang tải phiên bản và quyền hiện tại…</p>
                )}
                {detail.isError && (
                  <p
                    role="alert"
                    className="rounded-xl border p-5 text-destructive"
                  >
                    {api.collaborationError(detail.error)}
                  </p>
                )}
                {detail.data &&
                  !detail.isError &&
                  detail.data.project_id === pid && (
                    <ResourceDetail
                      key={`${identity}:${pid}:${detail.data.id}`}
                      item={detail.data}
                      busy={blocked || detail.isFetching}
                      can={can}
                      run={(op) => action.mutate(op)}
                    />
                  )}
                {!selected && (
                  <div
                    className={`${panel} grid min-h-72 place-content-center text-center`}
                  >
                    <Layers size={32} className="mx-auto mb-4 text-primary" />
                    <h2 className="font-semibold">
                      Cùng làm việc trên một phiên bản
                    </h2>
                    <p className="mt-2 max-w-md text-sm text-muted-foreground">
                      BA soạn và gửi contract. Developer lập workflow và kế
                      hoạch. Người duyệt độc lập kiểm tra đúng revision trước
                      khi chuẩn bị run.
                    </p>
                  </div>
                )}
              </section>
            </div>
          </>
        )}
        <Dialog
          open={enableReview !== null}
          onOpenChange={(open) => {
            if (!open && !enabling.isPending) setEnableReview(null);
          }}
        >
          <DialogContent>
            <DialogTitle>Mở cộng tác cho {base.data?.name}</DialogTitle>
            <DialogDescription>
              Chỉ áp dụng cho project rỗng. Không chia sẻ dữ liệu cũ hoặc mở
              quyền gọi agent/push GitHub.
            </DialogDescription>
            <p className="text-sm">Chính sách đã xem: v{enableReview}</p>
            {enabling.error && (
              <p role="alert">{api.collaborationError(enabling.error)}</p>
            )}
            <Button
              disabled={
                enabling.isPending ||
                base.isFetching ||
                base.isError ||
                enableReview !== base.data?.revision
              }
              onClick={() => enabling.mutate(enableReview!)}
            >
              Xác nhận mở cộng tác
            </Button>
          </DialogContent>
        </Dialog>
      </div>
    </main>
  );
}

function NewContract({
  policy,
  project,
  busy,
  run,
}: {
  policy: number;
  project: string;
  busy: boolean;
  run: (op: Operation) => void;
}) {
  const [title, setTitle] = useState("");
  const [objective, setObjective] = useState("");
  return (
    <form
      className={panel}
      onSubmit={(event) => {
        event.preventDefault();
        run(async () => {
          const item = await api.contractTool(
            project,
            policy,
            "skilltree_init",
            {
              idempotency_key: crypto.randomUUID(),
              title,
              scope: { objective },
            },
          );
          setTitle("");
          setObjective("");
          return item;
        });
      }}
    >
      <h2 className="mb-3 font-semibold">Soạn yêu cầu</h2>
      <label className="mb-3 block text-xs">
        Tên contract
        <input
          className={`${inputClass} mt-1`}
          required
          maxLength={200}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
      </label>
      <label className="mb-3 block text-xs">
        Mục tiêu
        <textarea
          className={`${inputClass} mt-1`}
          required
          maxLength={4000}
          rows={3}
          value={objective}
          onChange={(e) => setObjective(e.target.value)}
        />
      </label>
      <Button type="submit" disabled={busy}>
        Tạo bản nháp bằng công cụ Skilltree
      </Button>
    </form>
  );
}

function AuthoringForm({
  data,
  canWorkflow,
  canSuite,
  busy,
  run,
}: {
  data: api.TeamWorkspace;
  canWorkflow: boolean;
  canSuite: boolean;
  busy: boolean;
  run: (op: Operation) => void;
}) {
  const [contract, setContract] = useState("");
  const [name, setName] = useState("");
  const [mode, setMode] = useState(canWorkflow ? "workflow" : "suite");
  const [contractVersion, setContractVersion] = useState<{
    revision: number;
    digest: string;
    policy: number;
  } | null>(null);
  const [body, setBody] = useState("");
  const [error, setError] = useState("");
  const approved = data.resources.filter(
    (item) => item.kind === "CONTRACT" && item.status === "APPROVED",
  );
  const selected = approved.find((item) => item.id === contract);
  const staleContract =
    !!contractVersion &&
    (!selected ||
      selected.revision !== contractVersion.revision ||
      selected.content_digest !== contractVersion.digest ||
      data.policy_revision !== contractVersion.policy);
  function submit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    if (!selected || staleContract || !contractVersion) return;
    let value: unknown;
    try {
      value = body ? JSON.parse(body) : undefined;
    } catch {
      setError("JSON chưa hợp lệ; chưa có dữ liệu nào được lưu.");
      return;
    }
    const common = {
      policy_revision: contractVersion.policy,
      name,
      contract_id: selected.id,
      contract_revision: contractVersion.revision,
      contract_digest: contractVersion.digest,
    };
    if (mode === "suite") {
      if (!Array.isArray(value)) {
        setError(
          "Suite cần một danh sách case gắn node/criterion của contract.",
        );
        return;
      }
      run(() =>
        api.createSharedSuite(data.project_id, { ...common, cases: value }),
      );
    } else {
      const stages = value || [
        {
          stage_id: crypto.randomUUID(),
          stage_type: "IMPLEMENTATION",
          name: "Coding Agent",
          objective: "Thực hiện contract đã khóa",
          inputs: { requirement: "Được server gắn với contract đã duyệt" },
          expected_outputs: ["source_patch"],
          package_ref: { package_id: "coding-agent", version: "0.3.0" },
          configuration_overrides: {},
          execution_profile_overrides: {},
          policy_overrides: {},
          secret_refs: {},
          position: { x: 0, y: 0 },
          metadata: {},
        },
      ];
      if (!Array.isArray(stages)) {
        setError("Workflow cần một danh sách stage.");
        return;
      }
      run(() =>
        api.saveSharedWorkflow(data.project_id, {
          ...common,
          stages,
          edges: [],
        }),
      );
    }
  }
  return (
    <form className={panel} onSubmit={submit}>
      <h2 className="mb-3 font-semibold">Từ contract đã duyệt</h2>
      <label className="mb-3 block text-xs">
        Contract
        <select
          required
          className={`${inputClass} mt-1`}
          value={contract}
          onChange={(e) => {
            setContract(e.target.value);
            const item = approved.find((row) => row.id === e.target.value);
            setContractVersion(
              item
                ? {
                    revision: item.revision,
                    digest: item.content_digest,
                    policy: data.policy_revision,
                  }
                : null,
            );
          }}
        >
          <option value="">Chọn phiên bản đã duyệt</option>
          {approved.map((item) => (
            <option key={item.id} value={item.id}>
              {item.title} · v{item.revision}
            </option>
          ))}
        </select>
      </label>
      <label className="mb-3 block text-xs">
        Loại
        <select
          className={`${inputClass} mt-1`}
          value={mode}
          onChange={(e) => setMode(e.target.value)}
        >
          {canWorkflow && <option value="workflow">Workflow kỹ thuật</option>}
          {canSuite && <option value="suite">Test suite khai báo</option>}
        </select>
      </label>
      <label className="mb-3 block text-xs">
        Tên
        <input
          required
          maxLength={200}
          className={`${inputClass} mt-1`}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      <details className="mb-3">
        <summary className="cursor-pointer text-xs">
          {mode === "suite"
            ? "Case JSON (bắt buộc)"
            : "Stage JSON nâng cao (tùy chọn)"}
        </summary>
        <textarea
          aria-label="Cấu trúc authoring JSON"
          className={`${inputClass} mt-2 font-mono`}
          rows={7}
          value={body}
          onChange={(e) => setBody(e.target.value)}
        />
        <p className="mt-2 text-xs text-muted-foreground">
          Không nhận task thực thi hay kết quả PASS từ JSON. Server kiểm tra
          schema và compile bằng compiler hiện có.
        </p>
      </details>
      {staleContract && (
        <p role="alert" className="mb-2 text-xs text-destructive">
          Contract hoặc policy đã đổi. Chọn lại và đọc đúng revision trước khi
          tạo.
        </p>
      )}
      {error && (
        <p role="alert" className="mb-2 text-xs text-destructive">
          {error}
        </p>
      )}
      <Button
        type="submit"
        disabled={
          busy ||
          !selected ||
          staleContract ||
          (mode === "workflow" ? !canWorkflow : !canSuite)
        }
      >
        Tạo {mode === "suite" ? "suite" : "workflow"}
      </Button>
    </form>
  );
}

export function ResourceDetail({
  item,
  busy,
  can,
  run,
}: {
  item: api.SharedResource;
  busy: boolean;
  can: (permission: string) => boolean;
  run: (operation: Operation) => void;
}) {
  const [review, setReview] = useState<{
    item: api.SharedResource;
    result: "APPROVE" | "REQUEST_CHANGES";
  } | null>(null);
  const [comment, setComment] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState("");
  const [nodeTitle, setNodeTitle] = useState("");
  const [criterion, setCriterion] = useState("");
  const [compileIssues, setCompileIssues] = useState<string[]>([]);
  const [editJson, setEditJson] = useState<string | null>(null);
  const [editSource, setEditSource] = useState<api.SharedResource | null>(null);
  const editStale =
    !!editSource &&
    (editSource.revision !== item.revision ||
      editSource.content_digest !== item.content_digest ||
      editSource.policy_revision !== item.policy_revision);
  const navigate = useCustomNavigate();
  const stale =
    review &&
    (review.item.revision !== item.revision ||
      review.item.policy_revision !== item.policy_revision ||
      review.item.content_digest !== item.content_digest ||
      !item.can_decide);
  async function decide() {
    if (!review) return;
    try {
      await api.decideShared(review.item, review.result, comment);
      setReview(null);
    } catch (e) {
      setError(api.collaborationError(e));
      throw e;
    }
  }
  const writable =
    item.kind === "CONTRACT"
      ? can("requirement:write")
      : item.kind === "TEST_SUITE"
        ? can("test_suite:write")
        : false;
  const canAccept =
    item.kind !== "VERIFICATION" ||
    text(
      (item.payload.report as Record<string, unknown> | undefined)?.verdict,
    ) === "PASS";
  return (
    <article className="space-y-4">
      <header className={panel}>
        <div className="flex flex-wrap justify-between gap-3">
          <div>
            <p className="text-xs text-primary">
              {labels[item.kind]} · v{item.revision}
            </p>
            <h2 className="mt-1 text-xl font-semibold">{item.title}</h2>
          </div>
          <span className="h-fit rounded-full border px-3 py-1 text-xs">
            {status[item.status] || item.status}
          </span>
        </div>
        <p className="mt-3 break-all font-mono text-xs text-muted-foreground">
          {item.content_digest}
        </p>
        <p className="mt-2 text-xs text-muted-foreground">
          Policy v{item.policy_revision} · Người chịu trách nhiệm:{" "}
          {item.responsible_ids.join(", ")}
        </p>
        {item.stale_dependencies && (
          <p role="alert" className="mt-3 text-sm text-destructive">
            Nguồn hoặc phê duyệt đã thay đổi. Bản này vẫn được giữ để đối chiếu
            nhưng không thể tiếp tục dùng để duyệt/thực thi.
          </p>
        )}
        <div className="mt-4 flex flex-wrap gap-2">
          {item.status === "DRAFT" &&
            ((item.kind === "CONTRACT" && can("contract:submit")) ||
              (item.kind === "TEST_SUITE" && can("test_suite:write"))) && (
              <Button
                disabled={busy}
                onClick={() => run(() => api.submitShared(item))}
              >
                {item.kind === "CONTRACT"
                  ? "Gửi duyệt nghiệp vụ"
                  : "Khóa test suite"}
              </Button>
            )}
          {writable && item.status !== "DRAFT" && (
            <Button
              disabled={busy}
              variant="outline"
              onClick={() => run(() => api.reviseShared(item))}
            >
              Tạo revision chỉnh sửa
            </Button>
          )}
          {item.kind === "WORKFLOW" && can("flow:write") && (
            <>
              <Button
                disabled={busy || item.stale_dependencies}
                onClick={() =>
                  run(async () => {
                    const result = await api.compileShared(item);
                    if (result.valid) {
                      setCompileIssues([]);
                      return result.resource;
                    }
                    setCompileIssues(
                      result.plan.validation_errors.map(
                        (issue) => `${issue.code}: ${issue.message}`,
                      ),
                    );
                  })
                }
              >
                Compile và gửi duyệt kỹ thuật
              </Button>
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => {
                  setEditSource(item);
                  setEditJson(
                    JSON.stringify(
                      {
                        stages: item.payload.stages,
                        edges: item.payload.edges,
                      },
                      null,
                      2,
                    ),
                  );
                }}
              >
                Chỉnh workflow
              </Button>
            </>
          )}
          {item.kind === "PLAN" &&
            item.status === "APPROVED" &&
            can("flow:write") && (
              <Button
                disabled={busy || item.stale_dependencies}
                onClick={() => run(() => api.prepareSharedRun(item))}
              >
                Chuẩn bị run · không dispatch
              </Button>
            )}
          {item.kind === "RUN" && (
            <Button
              variant="outline"
              onClick={() =>
                navigate(
                  `/collaboration/runs/${item.id}/?project=${item.project_id}`,
                )
              }
            >
              Mở Run Detail
            </Button>
          )}
          {item.can_decide && (
            <>
              <Button
                disabled={busy || !canAccept}
                onClick={() => {
                  setReview({ item, result: "APPROVE" });
                  setConfirm(false);
                  setComment("");
                  setError("");
                }}
              >
                Duyệt đúng phiên bản
              </Button>
              <Button
                disabled={busy}
                variant="outline"
                onClick={() => {
                  setReview({ item, result: "REQUEST_CHANGES" });
                  setConfirm(false);
                  setComment("");
                  setError("");
                }}
              >
                Yêu cầu chỉnh sửa
              </Button>
            </>
          )}
        </div>
        {item.status === "SUBMITTED" && (
          <p className="mt-3 text-xs text-muted-foreground">
            Người duyệt đủ điều kiện:{" "}
            {item.reviewers.map((person) => person.username).join(", ") ||
              "Chưa có người độc lập đủ quyền"}
            . Người tạo hoặc người điều khiển task không tự duyệt.
          </p>
        )}
      </header>
      {compileIssues.length > 0 && (
        <div role="alert" className={`${panel} text-sm text-destructive`}>
          {compileIssues.map((issue) => (
            <p key={issue}>{issue}</p>
          ))}
        </div>
      )}
      {item.kind === "CONTRACT" && (
        <div className={panel}>
          <h3 className="font-semibold">Mục tiêu và tiêu chí nghiệm thu</h3>
          <p className="mt-3 whitespace-pre-wrap text-sm">
            {text(
              (item.payload.scope as Record<string, unknown> | undefined)
                ?.objective,
            )}
          </p>
          <div className="mt-4 space-y-3">
            {records(item.payload.nodes).map((node) => (
              <div key={text(node.node_id)} className="rounded-lg border p-3">
                <p className="text-sm font-medium">{text(node.title)}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {text(node.node_id)}
                </p>
                {records(node.acceptance_criteria).map((entry, index) => (
                  <p
                    key={`${text(node.node_id)}:${index}`}
                    className="mt-2 text-sm"
                  >
                    {index + 1}. {text(entry.description)}{" "}
                    <span className="text-xs text-muted-foreground">
                      · {text(entry.verification)}
                    </span>
                  </p>
                ))}
              </div>
            ))}
          </div>
          {item.status === "DRAFT" && writable && (
            <form
              className="mt-4 space-y-3 border-t pt-4"
              onSubmit={(e) => {
                e.preventDefault();
                run(async () => {
                  const result = await api.contractTool(
                    item.project_id,
                    item.policy_revision,
                    "skilltree_upsert_node",
                    {
                      idempotency_key: crypto.randomUUID(),
                      contract_id: item.id,
                      expected_revision: item.revision,
                      node: {
                        title: nodeTitle,
                        acceptance_criteria: [
                          { description: criterion, verification: "HUMAN" },
                        ],
                      },
                    },
                  );
                  setNodeTitle("");
                  setCriterion("");
                  return result;
                });
              }}
            >
              <label className="block text-xs">
                Task trong contract
                <input
                  required
                  maxLength={200}
                  className={`${inputClass} mt-1`}
                  value={nodeTitle}
                  onChange={(e) => setNodeTitle(e.target.value)}
                />
              </label>
              <label className="block text-xs">
                Tiêu chí nghiệm thu
                <textarea
                  required
                  maxLength={4000}
                  className={`${inputClass} mt-1`}
                  value={criterion}
                  onChange={(e) => setCriterion(e.target.value)}
                />
              </label>
              <Button type="submit" variant="outline" disabled={busy}>
                Thêm task bằng công cụ
              </Button>
            </form>
          )}
        </div>
      )}
      {item.kind === "RUN" && <RunContents payload={item.payload} />}
      {item.kind === "PLAN" && (
        <div className={panel}>
          <h3 className="mb-3 font-semibold">Task từ compiler</h3>
          {records(item.payload.tasks).map((task) => (
            <div
              key={text(task.plan_task_id)}
              className="border-t py-3 text-sm"
            >
              <p>{text(task.name) || text(task.task_type)}</p>
              <p className="mt-1 break-all font-mono text-xs text-muted-foreground">
                {text(task.resolved_node_digest)}
              </p>
            </div>
          ))}
        </div>
      )}
      {item.kind === "VERIFICATION" && (
        <div className={panel}>
          <h3 className="flex items-center gap-2 font-semibold">
            <FileCheck2 size={17} /> Verify có bằng chứng
          </h3>
          <p className="mt-3 text-sm">
            Kết luận:{" "}
            {text(
              (item.payload.report as Record<string, unknown> | undefined)
                ?.verdict,
            ) || "Chưa xác minh"}
          </p>
          <p className="mt-2 break-all font-mono text-xs">
            {text(item.payload.evidence_digest)}
          </p>
          <p className="mt-3 text-xs text-muted-foreground">
            Nghiệm thu chỉ ghi quyết định của người kiểm thử, không sửa report
            hoặc đổi FAIL thành PASS. Kết luận chỉ áp dụng cho các tiêu chí
            trong report, không chứng nhận toàn bộ contract.
          </p>
        </div>
      )}
      <details className={panel}>
        <summary className="cursor-pointer text-sm">
          JSON nguồn bất biến và thông tin đối chiếu
        </summary>
        <pre className="mt-4 max-h-[32rem] overflow-auto whitespace-pre-wrap break-all text-xs">
          {JSON.stringify(item.payload, null, 2)}
        </pre>
      </details>
      <section className={panel}>
        <h3 className="font-semibold">
          Lịch sử quyết định & yêu cầu chỉnh sửa
        </h3>
        {item.decisions.length === 0 && (
          <p className="mt-3 text-sm text-muted-foreground">
            Chưa có quyết định.
          </p>
        )}
        {item.decisions.map((entry) => (
          <div key={entry.id} className="mt-3 border-t pt-3 text-sm">
            <p className="font-medium">
              {entry.decision === "APPROVE" ? "Đã duyệt" : "Yêu cầu chỉnh sửa"}{" "}
              · v{entry.resource_revision}
            </p>
            <p className="mt-1 whitespace-pre-wrap">{entry.comment}</p>
            <p className="mt-2 break-all text-xs text-muted-foreground">
              Actor {entry.decided_by} · policy v{entry.policy_revision} ·{" "}
              {entry.content_digest}
            </p>
          </div>
        ))}
      </section>
      <Dialog
        open={review !== null}
        onOpenChange={(open) => {
          if (!open && !busy) setReview(null);
        }}
      >
        <DialogContent>
          <DialogTitle>
            {review?.result === "APPROVE"
              ? "Duyệt đúng revision"
              : "Gửi yêu cầu chỉnh sửa"}
          </DialogTitle>
          <DialogDescription>
            Quyết định gắn với tài liệu, digest và quyền hiện tại; không gọi
            runtime hay publish.
          </DialogDescription>
          <p className="break-all font-mono text-xs">
            v{review?.item.revision} · policy v{review?.item.policy_revision}
            <br />
            {review?.item.content_digest}
          </p>
          <label className="text-sm">
            Nhận xét bắt buộc
            <textarea
              className={`${inputClass} mt-2`}
              maxLength={2000}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
          </label>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={confirm}
              onChange={(e) => setConfirm(e.target.checked)}
            />
            Tôi đã đọc đúng phiên bản này và chịu trách nhiệm về quyết định.
          </label>
          {stale && (
            <p role="alert" className="text-sm text-destructive">
              Dữ liệu hoặc quyền đã đổi. Đóng cửa sổ và xem lại phiên bản hiện
              tại.
            </p>
          )}
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <Button
            disabled={
              busy || !!stale || !confirm || !comment.trim() || !item.can_decide
            }
            onClick={() =>
              run(async () => {
                await decide();
              })
            }
          >
            Xác nhận quyết định
          </Button>
        </DialogContent>
      </Dialog>
      <Dialog
        open={editJson !== null}
        onOpenChange={(open) => {
          if (!open && !busy) setEditJson(null);
        }}
      >
        <DialogContent>
          <DialogTitle>Chỉnh workflow · tạo revision mới</DialogTitle>
          <DialogDescription>
            Giữ nguyên bản đã compile; kế hoạch mới cần được duyệt lại.
          </DialogDescription>
          <textarea
            aria-label="Workflow stages và edges"
            className={`${inputClass} min-h-64 font-mono`}
            value={editJson || ""}
            onChange={(e) => setEditJson(e.target.value)}
          />
          <Button
            disabled={busy || editStale || !editSource || !can("flow:write")}
            onClick={() => {
              let body: Record<string, unknown>;
              try {
                body = JSON.parse(editJson || "");
              } catch {
                setError("JSON chưa hợp lệ.");
                return;
              }
              run(async () => {
                const source = editSource!;
                const ref = source.dependencies.contract;
                const updated = await api.saveSharedWorkflow(
                  source.project_id,
                  {
                    name: source.title,
                    policy_revision: source.policy_revision,
                    contract_id: ref.resource_id,
                    contract_revision: ref.revision,
                    contract_digest: ref.content_digest,
                    stages: body.stages,
                    edges: body.edges,
                  },
                  source,
                );
                setEditJson(null);
                return updated;
              });
            }}
          >
            Lưu revision workflow
          </Button>
          {error && <p role="alert">{error}</p>}
          {editStale && (
            <p role="alert">
              Revision hoặc policy đã đổi. Bản nháp không tự ghi đè phiên bản
              mới.
            </p>
          )}
        </DialogContent>
      </Dialog>
    </article>
  );
}

export function RunContents({ payload }: { payload: Record<string, unknown> }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <section className={panel}>
        <h3 className="font-semibold">Task · {text(payload.status)}</h3>
        {records(payload.tasks).map((task) => (
          <div key={text(task.id)} className="mt-3 rounded-lg border p-3">
            <p className="text-sm font-medium">{text(task.name)}</p>
            <p className="mt-1 text-xs text-primary">{text(task.status)}</p>
            <p className="mt-2 text-xs text-muted-foreground">
              Executor:{" "}
              {text(
                (task.executor as Record<string, unknown> | undefined)?.service,
              )}
            </p>
          </div>
        ))}
      </section>
      <section className={panel}>
        <h3 className="font-semibold">Timeline từ coordinator</h3>
        {records(payload.events).map((event) => (
          <div
            key={text(event.event_id)}
            className="mt-4 border-l-2 border-primary/40 pl-3 text-xs"
          >
            <p className="font-mono">{text(event.event_type)}</p>
            <p className="mt-1 text-muted-foreground">
              {text(event.status)} · {text(event.occurred_at)}
            </p>
          </div>
        ))}
      </section>
    </div>
  );
}

function ImportRun({
  project,
  busy,
  run,
}: {
  project: string;
  busy: boolean;
  run: (operation: Operation) => void;
}) {
  const [runId, setRunId] = useState("");
  const [preview, setPreview] = useState<z.infer<
    typeof api.importPreviewSchema
  > | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  return (
    <section className={panel}>
      <h2 className="font-semibold">Chia sẻ snapshot lịch sử</h2>
      <p className="mt-2 text-xs text-muted-foreground">
        Chỉ người tạo gốc kiêm Admin project được chuyển run đã kết thúc. Không
        chuyển credential hoặc phiên đang chạy.
      </p>
      <form
        className="mt-3 space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          run(async () => {
            setPreview(await api.previewSharedImport(project, runId));
            setConfirmed(false);
          });
        }}
      >
        <label className="block text-xs">
          Run ID
          <input
            required
            className={`${inputClass} mt-1`}
            value={runId}
            onChange={(e) => setRunId(e.target.value)}
          />
        </label>
        <Button type="submit" variant="outline" disabled={busy}>
          Xem phạm vi sẽ chia sẻ
        </Button>
      </form>
      <Dialog
        open={preview !== null}
        onOpenChange={(open) => {
          if (!open && !busy) setPreview(null);
        }}
      >
        <DialogContent>
          <DialogTitle>Chia sẻ đúng snapshot vào project</DialogTitle>
          <DialogDescription>{preview?.warning}</DialogDescription>
          <p className="text-sm">
            {preview?.name} · {preview?.status}
            <br />
            {preview?.task_count} task · {preview?.artifact_count} artifact
            <br />
            {preview?.contract_count} contract · {preview?.plan_count} kế hoạch
            · {preview?.verification_count} report Verify
          </p>
          <p className="break-all font-mono text-xs">
            Target {project}
            <br />
            {preview?.content_digest}
          </p>
          <details>
            <summary className="text-xs">
              Manifest chính xác sẽ được chia sẻ
            </summary>
            <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-all text-xs">
              {JSON.stringify(preview?.manifest, null, 2)}
            </pre>
          </details>
          <label className="flex gap-2 text-sm">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            Tôi cho phép các thành viên đủ quyền của project xem snapshot này.
          </label>
          <Button
            disabled={busy || !confirmed}
            onClick={() =>
              run(async () => {
                const result = await api.importSharedRun(project, preview!);
                setPreview(null);
                return result;
              })
            }
          >
            Xác nhận chia sẻ snapshot
          </Button>
        </DialogContent>
      </Dialog>
    </section>
  );
}

export function TeamRunDetailPage() {
  const { runId } = useParams();
  const [params] = useSearchParams();
  const pid = params.get("project") || "";
  const identity = useAuthStore((store) => store.userData?.id);
  const navigate = useCustomNavigate();
  const result = useQuery({
    queryKey: ["team-run-detail", identity, pid, runId],
    queryFn: () => api.sharedResource(pid, runId!),
    enabled: !!identity && !!pid && !!runId,
    refetchInterval: 15000,
  });
  return (
    <main className="h-full overflow-auto p-5 lg:p-8">
      <div className="mx-auto max-w-6xl space-y-5">
        <Button
          variant="ghost"
          onClick={() => navigate(`/collaboration/?project=${pid}`)}
        >
          <ArrowLeft size={15} className="mr-2" />
          Về project
        </Button>
        <h1 className="text-2xl font-semibold">Run Detail · team</h1>
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <CheckCircle2 size={16} />
          Scope được kiểm tra lại khi tải. Chưa cấp delegation để chạy agent.
        </p>
        {(!pid || !runId) && <p role="alert">Thiếu scope project/run.</p>}
        {result.isLoading && <p role="status">Đang kiểm tra quyền…</p>}
        {result.isError && (
          <p role="alert">{api.collaborationError(result.error)}</p>
        )}
        {result.data && !result.isError && result.data.kind === "RUN" && (
          <>
            <h2 className="font-semibold">{result.data.title}</h2>
            <RunContents payload={result.data.payload} />
            <details className={panel}>
              <summary>Snapshot và provenance</summary>
              <pre className="mt-3 overflow-auto whitespace-pre-wrap break-all text-xs">
                {JSON.stringify(result.data.payload, null, 2)}
              </pre>
            </details>
          </>
        )}
      </div>
    </main>
  );
}
