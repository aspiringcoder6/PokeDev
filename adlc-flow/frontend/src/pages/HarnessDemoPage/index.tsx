import { translateUi, useUiLocale } from "@/i18n/ui";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import {
  type HarnessDemoCapabilities,
  type HarnessDemoRun,
  harnessDemoApi,
} from "@/controllers/API/harness-demo";
import CreateGithubWorkflow from "@/features/adlc-workspace/create-github-workflow";
import CreatePluginWorkflow from "@/features/adlc-workspace/create-plugin-workflow";

const labels: Record<string, string> = {
  DRAFT: "Yêu cầu đã lưu",
  PLANNING: "Orchestrator đang soạn kế hoạch",
  AWAITING_PLAN_APPROVAL: "Chờ duyệt kế hoạch",
  RUNNING: "Agent đang thực hiện task loop",
  AWAITING_MERGE_APPROVAL: "Chờ duyệt commit để merge/push",
  PUBLISHING: "Orchestrator đang merge/push",
  SUCCEEDED: "Hoàn tất",
  FAILED: "Dừng vì lỗi",
};

const eventLabels: Record<string, string> = {
  native_diagnostics: "Chẩn đoán lượt native",
  demo_context: "Ngữ cảnh công việc",
  demo_write_task_plan: "Kế hoạch của orchestrator",
  demo_load_skill: "Skill đã nạp",
  demo_memory_recall: "Ngữ cảnh từ memory",
  demo_write_task_brief: "Task brief của agent",
  demo_sandbox_read: "Đọc source trong sandbox",
  demo_sandbox_write: "Cập nhật source trong sandbox",
  demo_sandbox_checks: "Kiểm tra của agent",
  demo_report_iteration: "Báo cáo iteration",
  demo_report_task: "Báo cáo công việc",
  demo_commit_candidate: "Commit đã xác minh",
};

function diagnosticMessage(code: string): string {
  const messages: Record<string, string> = {
    DEMO_NATIVE_ACTIVITY_INVALID:
      "Phiên model có hoạt động không phù hợp với chính sách đã khóa. Lượt này chưa được chấp nhận; xem chẩn đoán phiên.",
    DEMO_NATIVE_BINDING_MISMATCH:
      "Phiên Harness không khớp bản runtime hoặc yêu cầu đã khóa. Chưa chấp nhận kết quả.",
    DEMO_NATIVE_DIAGNOSTICS_INVALID:
      "Dữ liệu chẩn đoán không đúng hợp đồng; không hiển thị payload ngoài phạm vi.",
    DEMO_DISABLED: "Phiên Harness chưa được bật trên backend.",
    DEMO_HARNESS_NOT_READY: "Harness chưa sẵn sàng.",
    DEMO_HARNESS_NOT_CONFIGURED: "Chưa cấu hình kết nối Harness.",
    DEMO_HARNESS_UNAVAILABLE:
      "Harness từ chối khởi động lượt. Kiểm tra kết nối và khóa writer trước khi tạo phiên mới.",
    DEMO_HARNESS_WRITER_LEASE_BLOCKED:
      "Harness còn khóa writer. Người vận hành cần kiểm tra tiến trình cũ trước khi khôi phục; không tự gọi lại model.",
    DEMO_NOT_READY: "Harness chưa sẵn sàng khởi động lượt.",
    DEMO_UNAUTHENTICATED: "Thông tin xác thực giữa ADLC và Harness chưa khớp.",
    DEMO_RESTART_UNCONFIRMED:
      "Yêu cầu tạo phiên mới chưa được xác nhận. Cần kiểm tra checkpoint trước khi thử lại.",
    DEMO_RESTART_REPOSITORY_CHANGED:
      "Repository đã đổi. Không tự chuyển issue cũ sang repository khác.",
    TASK_LOOP_PROTECTED_TEST_CHANGED:
      "Byte của test bảo vệ không khớp bản đã khóa. Cần kiểm tra checkout và định dạng xuống dòng; chưa chấp nhận candidate.",
    TASK_LOOP_CHECKOUT_NOT_EXACT:
      "Checkout không tái hiện đúng candidate đã khóa. Chưa bắt đầu lượt gọi model.",
    DEMO_DOCKER_IMAGE_UNAVAILABLE: "Không tìm thấy image sandbox đã cấu hình.",
    DEMO_PREFLIGHT_FAILED: "Kết nối chưa sẵn sàng; chưa bắt đầu gọi model.",
    DEMO_APPROVAL_DIGEST_MISMATCH:
      "Kết quả cần duyệt đã thay đổi. Hãy tải lại và kiểm tra.",
    DEMO_STATE_CONFLICT:
      "Trạng thái phiên đã thay đổi. Hãy tải lại trước khi thao tác.",
    DEMO_GITHUB_DISABLED: "Chưa bật quyền phát hành lên GitHub.",
    CONTRACT_EXPLICIT_LOGIN_REQUIRED:
      "Bạn cần đăng nhập để tạo hoặc duyệt phiên.",
  };
  return (
    messages[code] ??
    "Không thể hoàn tất thao tác. Kiểm tra kết nối và chẩn đoán phiên."
  );
}

export function SessionJson({
  title,
  value,
}: {
  title: string;
  value: unknown;
}) {
  return (
    <details className="rounded-lg border bg-card p-4">
      <summary className="cursor-pointer text-sm font-medium">{title}</summary>
      <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-words text-xs leading-relaxed text-muted-foreground">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  );
}

function errorCode(error: unknown): string {
  const e = error as { response?: { data?: { detail?: { code?: string } } } };
  const code = e.response?.data?.detail?.code;
  return code
    ? diagnosticMessage(code)
    : "Không kết nối được Harness API. Kiểm tra backend và cấu hình kết nối.";
}

export default function HarnessDemoPage() {
  useUiLocale();
  const [params, setParams] = useSearchParams();
  const id = params.get("run");
  const [capabilities, setCapabilities] =
    useState<HarnessDemoCapabilities | null>(null);
  const [run, setRun] = useState<HarnessDemoRun | null>(null);
  const [history, setHistory] = useState<HarnessDemoRun[]>([]);
  const [requirement, setRequirement] = useState("");
  const [error, setError] = useState("");
  const [issueUrl, setIssueUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [approval, setApproval] = useState(false);

  useEffect(() => {
    let live = true;
    Promise.all([harnessDemoApi.capabilities(), harnessDemoApi.list()])
      .then(([c, h]) => {
        if (!live) return;
        setCapabilities(c);
        setRequirement(c.requirement);
        setHistory(h);
      })
      .catch((e) => live && setError(errorCode(e)));
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    if (!issueUrl) return;
    let live = true;
    const timer = window.setInterval(() => {
      harnessDemoApi
        .list()
        .then((items) => live && setHistory(items))
        .catch((e) => live && setError(errorCode(e)));
    }, 3000);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [issueUrl]);

  useEffect(() => {
    if (!id) {
      setRun(null);
      return;
    }
    let live = true;
    setApproval(false);
    const refresh = () =>
      harnessDemoApi
        .get(id)
        .then((r) => live && setRun(r))
        .catch((e) => live && setError(errorCode(e)));
    void refresh();
    const timer = window.setInterval(refresh, 1500);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [id]);

  useEffect(() => {
    setApproval(false);
  }, [run?.plan_digest, run?.handoff_digest, run?.status]);

  async function act(action: () => Promise<HarnessDemoRun>) {
    setBusy(true);
    setError("");
    setApproval(false);
    try {
      const result = await action();
      setRun(result);
      setParams({ run: result.id });
      setHistory(await harnessDemoApi.list());
    } catch (e) {
      setError(errorCode(e));
    } finally {
      setBusy(false);
    }
  }

  const visibleHistory = history.map((item) =>
    run && item.id === run.id ? run : item,
  );
  const gate =
    !run?.workflow_run_id && run?.status === "AWAITING_PLAN_APPROVAL"
      ? "plan"
      : !run?.workflow_run_id && run?.status === "AWAITING_MERGE_APPROVAL"
        ? "merge"
        : null;
  const gateDigest = gate === "plan" ? run?.plan_digest : run?.handoff_digest;

  return (
    <main className="mx-auto w-full max-w-6xl overflow-auto p-6 lg:p-10">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <CreateGithubWorkflow />
        <CreatePluginWorkflow />
        <div>
          <p className="text-xs uppercase tracking-wider text-primary">
            {translateUi("ADLC · Agent Harness")}
          </p>
          <h1 className="mt-2 text-2xl font-semibold">
            Phiên làm việc có kiểm chứng
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
            my-codex / cx/gpt-5.6-luna · thực thi biệt lập · phê duyệt của người
            dùng. Hồ sơ hiện tại: Python pagination, một tệp source và bốn kiểm
            tra bảo vệ. Kết quả xác minh áp dụng cho hồ sơ này, không phải toàn
            bộ repository.
          </p>
        </div>
        <label className="text-sm">
          Session đã lưu
          <select
            aria-label="Session đã lưu"
            value={id ?? ""}
            onChange={(e) =>
              setParams(e.target.value ? { run: e.target.value } : {})
            }
            className="mt-2 block max-w-72 rounded-md border bg-background p-2 text-xs"
          >
            <option value="">Session mới</option>
            {visibleHistory.map((r) => (
              <option key={r.id} value={r.id}>
                {r.id.slice(0, 8)} · {labels[r.status] ?? r.status}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && (
        <p
          role="alert"
          className="mb-4 rounded-md border border-destructive p-3 text-sm text-destructive"
        >
          {error}
        </p>
      )}
      {capabilities && (
        <section
          aria-label="Kết nối dịch vụ"
          className="mb-5 grid gap-3 rounded-xl border bg-card p-4 text-sm md:grid-cols-3"
        >
          <div>
            <p className="font-medium">{translateUi("Harness & sandbox")}</p>
            <p className="mt-1 text-muted-foreground">
              {capabilities.ready
                ? "Đã kiểm tra kết nối & sandbox"
                : capabilities.blockers.map(diagnosticMessage).join(" · ")}
            </p>
          </div>
          <div>
            <p className="font-medium">{translateUi("Memory")}</p>
            <p className="mt-1 text-muted-foreground">
              {capabilities.memory_mode === "CURATED_LOCAL"
                ? "Bộ nhớ cục bộ · chưa kết nối backend"
                : "Backend theo project · nguồn được ghi trong receipt"}
            </p>
          </div>
          <div>
            <p className="font-medium">{translateUi("GitHub")}</p>
            <p className="mt-1 text-muted-foreground">
              {capabilities.github_repository} ·{" "}
              {capabilities.github_writes_enabled
                ? "nhánh làm việc riêng; không ghi trực tiếp lên main"
                : "Chưa bật phát hành GitHub · dùng local bare mirror"}
            </p>
          </div>
        </section>
      )}

      {!run && (
        <section className="mb-5 rounded-xl border bg-card p-5">
          <label htmlFor="harness-requirement" className="font-medium">
            1. Soạn yêu cầu
          </label>
          <p className="my-2 text-sm text-muted-foreground">
            Phạm vi được khóa: app.py và bốn kiểm tra phân trang. Repository
            được tạo riêng; nội dung yêu cầu không tự mở rộng quyền của agent.
          </p>
          <textarea
            id="harness-requirement"
            value={requirement}
            maxLength={8192}
            onChange={(e) => setRequirement(e.target.value)}
            rows={6}
            className="w-full rounded-lg border bg-background p-3 text-sm"
          />
          <div className="mt-4 flex flex-wrap gap-3">
            <Button
              disabled={busy || !requirement || !capabilities}
              onClick={() => void act(() => harnessDemoApi.create(requirement))}
            >
              Lưu yêu cầu · tạo session
            </Button>
            <Button
              variant="outline"
              disabled={
                busy || !capabilities?.github_writes_enabled || !requirement
              }
              onClick={async () => {
                setBusy(true);
                setError("");
                try {
                  const r = await harnessDemoApi.issue(requirement);
                  setIssueUrl(r.issue_url);
                } catch (e) {
                  setError(errorCode(e));
                } finally {
                  setBusy(false);
                }
              }}
            >
              Tạo GitHub issue → webhook
            </Button>
          </div>
          {issueUrl && (
            <p className="mt-3 text-sm">
              <a
                className="text-primary underline"
                href={issueUrl}
                target="_blank"
                rel="noreferrer"
              >
                Mở issue vừa tạo
              </a>{" "}
              · chờ webhook, rồi chọn session từ danh sách.
            </p>
          )}
        </section>
      )}

      {run && (
        <section className="mb-5 rounded-xl border bg-card p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="font-semibold">
                {labels[run.status] ?? run.status}
              </h2>
              <p className="mt-1 break-all font-mono text-xs text-muted-foreground">
                {translateUi("Session")} {run.id}
              </p>
            </div>
            {!run.workflow_run_id && run.status === "DRAFT" && (
              <Button
                disabled={busy || !capabilities?.ready}
                onClick={() => void act(() => harnessDemoApi.plan(run.id))}
              >
                Chạy orchestrator soạn plan (model thật)
              </Button>
            )}
            {!run.workflow_run_id && run.status === "FAILED" && (
              <Button
                disabled={busy}
                onClick={() => void act(() => harnessDemoApi.restart(run.id))}
              >
                {run.restart_run_id
                  ? "Mở phiên chạy lại"
                  : "Tạo phiên mới từ yêu cầu này"}
              </Button>
            )}
          </div>
          {(run.error_code || run.interrupted) && (
            <p role="alert" className="mt-3 text-sm text-destructive">
              {run.error_code
                ? diagnosticMessage(run.error_code)
                : "Session bị gián đoạn. Không tự gọi lại model hoặc push; hãy tạo session mới."}
            </p>
          )}
          <p className="mt-4 whitespace-pre-wrap text-sm">{run.requirement}</p>
          {run.workflow_run_id && (
            <p className="mt-3 text-sm">
              Phiên này do workflow điều phối. Phê duyệt và điều khiển tại{" "}
              <a
                className="text-primary underline"
                href={`/runs/${run.workflow_run_id}`}
              >
                Run của workflow
              </a>
              .
            </p>
          )}
          {run.restart_of && (
            <p className="mt-3 text-sm text-muted-foreground">
              Phiên mới từ {run.restart_of}. Chưa kế thừa phê duyệt, candidate
              hay commit của phiên cũ.
            </p>
          )}
          {gate && gateDigest && !run.interrupted && (
            <div className="mt-5 rounded-lg border border-primary/40 p-4">
              <SessionJson
                title={
                  gate === "plan"
                    ? "Kế hoạch cần duyệt"
                    : "Commit, candidate, bằng chứng và target cần duyệt"
                }
                value={gate === "plan" ? run.plan : run.handoff}
              />
              <label className="mt-4 flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={approval}
                  onChange={(e) => setApproval(e.target.checked)}
                />
                <span>
                  {gate === "plan"
                    ? "Tôi đã đọc kế hoạch và đồng ý giao task cho agent."
                    : `Tôi đã xem diff/bằng chứng và đồng ý merge, push ${run.github ? "nhánh GitHub đã chỉ định (không phải main)" : "vào local bare mirror"}.`}
                </span>
              </label>
              <p className="mt-2 break-all font-mono text-xs text-muted-foreground">
                Duyệt đúng digest: {gateDigest}
              </p>
              <Button
                className="mt-3"
                disabled={busy || !approval}
                onClick={() =>
                  void act(() =>
                    harnessDemoApi.approve(run.id, gate, gateDigest),
                  )
                }
              >
                {gate === "plan"
                  ? "Duyệt plan · bắt đầu task loop"
                  : "Duyệt commit · orchestrator merge/push"}
              </Button>
            </div>
          )}
        </section>
      )}

      <div className="grid items-start gap-5 lg:grid-cols-[1fr_2fr]">
        <section
          aria-label="Quy trình thực thi"
          className="rounded-xl border bg-card p-5"
        >
          <h2 className="mb-4 font-semibold">
            {translateUi("Workflow & input/output")}
          </h2>
          <ol className="space-y-4">
            {capabilities?.workflow.stages.map((s, i) => (
              <li key={s.id} className="border-l-2 border-primary/30 pl-3">
                <p className="text-sm font-medium">
                  {i + 1}. {s.id} · {s.actor}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  IN: {s.input}
                  <br />
                  OUT: {s.output}
                </p>
              </li>
            ))}
          </ol>
        </section>
        <section aria-label="Bằng chứng session" className="space-y-3">
          <h2 className="font-semibold">
            Input/output và bằng chứng được lưu lại
          </h2>
          {run && (
            <SessionJson
              title="Chẩn đoán phiên"
              value={{
                session_id: run.id,
                status: run.status,
                error_code: run.error_code ?? null,
                interrupted: run.interrupted ?? false,
                restart_of: run.restart_of ?? null,
                plan_digest: run.plan_digest ?? null,
                handoff_digest: run.handoff_digest ?? null,
                native_diagnostics: run.native_diagnostics ?? null,
              }}
            />
          )}
          {run?.commit && (
            <p className="break-all rounded-lg border p-3 font-mono text-xs">
              {translateUi("Agent commit:")} {run.commit}
            </p>
          )}
          {run?.candidate != null && (
            <SessionJson
              title="Candidate · nội dung source / diff để review"
              value={run.candidate}
            />
          )}
          {run?.verification != null && (
            <SessionJson
              title="Verify độc lập · kết quả nhị phân và số test thực thi"
              value={run.verification}
            />
          )}
          {run?.task_report != null && (
            <SessionJson
              title={translateUi("Agent task report (advisory)")}
              value={run.task_report}
            />
          )}
          {run?.publish_receipt != null && (
            <SessionJson
              title={translateUi("Orchestrator merge/push receipt")}
              value={run.publish_receipt}
            />
          )}
          {run?.events.map((e) => (
            <SessionJson
              key={e.seq}
              title={`#${e.seq} · ${eventLabels[e.stage] ?? e.stage} · ${new Date(e.at).toLocaleTimeString()}`}
              value={e.output}
            />
          ))}
          {!run?.events.length && (
            <p className="text-sm text-muted-foreground">
              Chưa có thực thi. Kết quả chỉ xuất hiện khi service thực sự chạy.
            </p>
          )}
        </section>
      </div>
    </main>
  );
}
