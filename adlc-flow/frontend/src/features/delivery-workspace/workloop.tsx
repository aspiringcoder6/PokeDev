import { useQuery } from "@tanstack/react-query";
import {
  CheckCircle2,
  ChevronDown,
  ExternalLink,
  FlaskConical,
  GitBranch,
  Globe,
  LoaderCircle,
  Play,
  RefreshCw,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { useContext, useRef, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { workloop, type WorkloopListing } from "@/controllers/API/workloop";
import { AuthContext } from "@/contexts/authContext";
import "./workloop.css";

const active = (s: string) =>
  ["RESERVED", "RUNNING", "UNCONFIRMED"].includes(s);
const stateLabel: Record<string, string> = {
  RESERVED: "Đã nhận",
  RUNNING: "Đang chạy",
  UNCONFIRMED: "Cần đối soát",
  SUCCEEDED: "Hoàn tất",
  FAILED: "Cần kiểm tra",
  DONE: "Đạt",
  DONE_WITH_CONCERNS: "Đạt, còn lưu ý",
  BLOCKED: "Chưa đạt",
};
const nodeLabel: Record<string, string> = {
  source: "Đối chiếu bản sửa",
  test: "Chạy test bảo vệ",
  preview: "Triển khai & kiểm chứng HTTP",
};
const stamp = (s: string) =>
  new Date(s).toLocaleString("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
    day: "2-digit",
    month: "2-digit",
  });

export function WorkloopView({
  data,
  busy,
  error,
  canWrite,
  onStart,
  onRefresh,
}: {
  data?: WorkloopListing;
  busy: boolean;
  error: string;
  canWrite: boolean;
  onStart: (factory: string, workflow: string) => void;
  onRefresh: () => void;
}) {
  const [tab, setTab] = useState<"preview" | "checks" | "history">("preview");
  const [frame, setFrame] = useState(false);
  const [selection, setSelection] = useState("pokedev/candidate-preview");
  const [runChoice, setRunChoice] = useState("");
  const [factory, workflowId] = selection.split("/");
  const row = data?.runs.find((r) => r.run_id === runChoice) ?? data?.runs[0];
  const preview = row?.preview;
  const live = preview?.state === "LIVE" && !!preview.url;
  const pending = data?.runs.some((r) => active(r.state)) ?? false;
  const plannedNodes =
    row?.factory === "pokedev"
      ? ["source", "test", "preview"].map((id) => ({ id }))
      : (data?.context.factories
          .find((f) => f.id === row?.factory)
          ?.workflows.find((w) => w.id === row?.workflow)?.nodes ?? []);
  const displayedNodes = plannedNodes.map(
    (n) =>
      row?.nodes.find((r) => r.id === n.id) ?? { id: n.id, state: "PENDING" },
  );
  const chosen = data?.context.factories
    .find((f) => f.id === factory)
    ?.workflows.find((w) => w.id === workflowId);
  const available =
    factory === "pokedev"
      ? !!data?.context.candidate && !!data?.capabilities.preview_ready
      : !!chosen?.enabled;
  const done =
    row?.nodes.filter((n) => ["DONE", "DONE_WITH_CONCERNS"].includes(n.state))
      .length ?? 0;
  const protectedChecks = preview?.tests?.checks ?? [];
  const testTotal = protectedChecks.reduce((total, check) => {
    const count = `${check.stdout}\n${check.stderr}`.match(
      /\bRan (\d+) tests? in\b/,
    );
    return total + (count ? Number(count[1]) : 0);
  }, 0);
  const httpChecks = preview?.http?.checks ?? [];
  // Only a distinct app origin can be embedded; never embed the PokeDev or Harness control plane.
  let embed = false;
  if (live) {
    try {
      const url = new URL(preview.url!);
      embed =
        ["http:", "https:"].includes(url.protocol) &&
        url.origin !== window.location.origin &&
        url.origin !== "http://10.0.10.195:3080" &&
        url.origin !== "http://117.5.151.111:9982" &&
        url.origin !== "http://117.5.151.111:9980" &&
        !url.username &&
        !url.password &&
        !url.search;
    } catch {
      /* invalid endpoint remains unavailable */
    }
  }
  return (
    <section
      className="dw-card wl-panel"
      aria-label="Workloop và ứng dụng Sandbox"
    >
      <div className="wl-heading">
        <div>
          <span className="wl-kicker">WORKLOOP</span>
          <h3>Workflow & ứng dụng chạy thử</h3>
          <p>Theo dõi từng bước, kiểm thử và mở sản phẩm ngay tại đây.</p>
        </div>
        <button
          className="vs-refresh"
          type="button"
          onClick={onRefresh}
          aria-label="Cập nhật Workloop"
        >
          <RefreshCw size={15} />
        </button>
      </div>
      <div className="wl-launch">
        <label>
          Luồng thực thi
          <select
            aria-label="Chọn workflow Workloop"
            value={selection}
            onChange={(e) => setSelection(e.target.value)}
          >
            <option value="pokedev/candidate-preview">
              PokeDev · Kiểm thử & chạy bản sửa
            </option>
            {data?.context.factories.map((f) => (
              <optgroup label={f.id} key={f.id}>
                {f.workflows.map((w) => (
                  <option key={w.id} value={`${f.id}/${w.id}`}>
                    {w.id}
                    {w.enabled ? "" : " · cần thiết lập"}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </label>
        <button
          className="pl-start"
          type="button"
          disabled={
            !canWrite ||
            busy ||
            pending ||
            !available ||
            !data?.capabilities.ready
          }
          onClick={() => {
            setRunChoice("");
            setFrame(false);
            onStart(factory, workflowId);
          }}
        >
          {busy || pending ? (
            <LoaderCircle className="animate-spin" size={15} />
          ) : (
            <Play size={15} />
          )}
          {pending
            ? "Đang theo dõi"
            : factory === "pokedev"
              ? "Tạo bản chạy thử"
              : "Chạy workflow"}
        </button>
      </div>
      <p className="wl-help">
        {factory === "pokedev"
          ? "Dùng bản sửa đã đạt test; kiểm tra lại trong Sandbox mới và tạo link xem ứng dụng trong 1 giờ. Không gọi thêm model."
          : chosen?.enabled
            ? `${chosen.nodes.length} bước · ${data?.capabilities.model.model} · workspace riêng cho từng lượt chạy.`
            : chosen?.reason}
      </p>
      {error && (
        <p className="pl-error" role="alert">
          {error}
        </p>
      )}
      {data && !data.capabilities.ready && (
        <p className="pl-error">Workloop chưa sẵn sàng trên máy chủ PokeDev.</p>
      )}
      {!data && <p className="wl-help">Đang tải Workloop…</p>}
      {data && factory === "pokedev" && !data.context.candidate && (
        <p className="wl-help">
          Cần một bản sửa đạt kiểm thử trong vòng cải tiến bên dưới.
        </p>
      )}
      {row && (
        <>
          {data && data.runs.length > 1 && (
            <label className="wl-run-picker">
              Lượt chạy
              <select
                aria-label="Chọn lượt chạy Workloop"
                value={runChoice || data.runs[0].run_id}
                onChange={(e) => {
                  setRunChoice(e.target.value);
                  setFrame(false);
                }}
              >
                {data.runs.map((r) => (
                  <option value={r.run_id} key={r.run_id}>
                    {stamp(r.created_at)} · {r.factory} / {r.workflow} ·{" "}
                    {stateLabel[r.state] ?? r.state}
                  </option>
                ))}
              </select>
            </label>
          )}
          <div className="wl-run-heading">
            <span
              className={`wl-status ${row.state === "SUCCEEDED" ? "is-pass" : ""}`}
            >
              {stateLabel[row.state] ?? row.state}
            </span>
            <span>
              {row.factory} / {row.workflow}
            </span>
            <time>{stamp(row.created_at)}</time>
          </div>
          <div className="wl-steps" aria-label="Các bước Workloop">
            {displayedNodes.map((node) => (
              <div
                className={`wl-step ${node.state === "DONE" ? "is-pass" : ""}`}
                key={node.id}
              >
                {node.state === "DONE" ? (
                  <CheckCircle2 size={17} />
                ) : node.state === "RUNNING" ? (
                  <LoaderCircle size={17} className="animate-spin" />
                ) : (
                  <GitBranch size={17} />
                )}
                <div>
                  <strong>{nodeLabel[node.id] ?? node.id}</strong>
                  <span>{stateLabel[node.state] ?? "Đang chờ"}</span>
                </div>
              </div>
            ))}
          </div>
          <div
            className="wl-tabs"
            role="tablist"
            aria-label="Nội dung kết quả Workloop"
          >
            <button
              role="tab"
              aria-selected={tab === "preview"}
              onClick={() => setTab("preview")}
            >
              <Globe size={14} />
              Ứng dụng
            </button>
            <button
              role="tab"
              aria-selected={tab === "checks"}
              onClick={() => setTab("checks")}
            >
              <ShieldCheck size={14} />
              Test & Verify
            </button>
            <button
              role="tab"
              aria-selected={tab === "history"}
              onClick={() => setTab("history")}
            >
              <GitBranch size={14} />
              Nhật ký · {done} bước đạt
            </button>
          </div>
          {tab === "preview" && (
            <div className="wl-preview" role="tabpanel">
              <div className="wl-preview-summary">
                <div className="wl-preview-icon">
                  <Globe size={24} />
                </div>
                <div>
                  <h4>
                    {live
                      ? "Ứng dụng đã chạy trong Sandbox"
                      : preview?.state === "EXPIRED"
                        ? "Bản chạy thử đã hết hạn"
                        : pending
                          ? "Đang chuẩn bị ứng dụng"
                          : "Chưa có bản triển khai để xem"}
                  </h4>
                  <p>
                    {live
                      ? `Đã kiểm tra HTTP · dùng đến ${stamp(preview.expires_at)}`
                      : preview?.state === "EXPIRED"
                        ? "Kết quả kiểm thử được giữ lại. Tạo bản chạy thử mới để mở ứng dụng."
                        : "Link ứng dụng xuất hiện sau khi kiểm thử và khởi động thành công."}
                  </p>
                </div>
              </div>
              {live && (
                <div className="wl-preview-actions">
                  <a
                    className="pl-start"
                    href={preview.url!}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <ExternalLink size={14} />
                    Mở ứng dụng
                  </a>
                  {embed && (
                    <button
                      type="button"
                      className="wl-secondary"
                      onClick={() => setFrame(!frame)}
                    >
                      {frame ? "Đóng xem trước" : "Xem trong PokeDev"}
                    </button>
                  )}
                </div>
              )}
              {live && frame && embed && (
                <iframe
                  title="Ứng dụng triển khai trong Sandbox"
                  src={preview.url!}
                  sandbox="allow-scripts allow-forms allow-same-origin"
                  referrerPolicy="no-referrer"
                />
              )}
              {preview && (
                <details className="wl-details">
                  <summary>
                    Thông tin bản triển khai
                    <ChevronDown size={14} />
                  </summary>
                  <dl>
                    <dt>Sandbox</dt>
                    <dd>{preview.sandbox_id}</dd>
                    <dt>Source</dt>
                    <dd>{preview.source_sha256.slice(0, 16)}</dd>
                    <dt>Thời hạn</dt>
                    <dd>{stamp(preview.expires_at)}</dd>
                  </dl>
                </details>
              )}
            </div>
          )}
          {tab === "checks" && (
            <div className="wl-checks" role="tabpanel">
              <div className="wl-check-card">
                <div>
                  <FlaskConical size={18} />
                  <h4>Test bảo vệ</h4>
                  <span className={preview?.tests?.passed ? "is-pass" : ""}>
                    {preview?.tests
                      ? preview.tests.passed
                        ? testTotal
                          ? `${testTotal}/${testTotal} đạt`
                          : "Đạt"
                        : "Chưa đạt"
                      : "Chưa chạy"}
                  </span>
                </div>
                <p>
                  {preview?.tests?.protected_intact
                    ? "Bộ test giữ nguyên, chạy lại trong Sandbox mới."
                    : "Kết quả chỉ xuất hiện khi runner trả bằng chứng."}
                </p>
                {protectedChecks.map((check) => (
                  <details key={check.check_id} className="wl-details">
                    <summary>
                      {check.check_id}
                      <span>Exit {check.exit_code}</span>
                    </summary>
                    <pre>
                      {check.stderr}
                      {check.stdout}
                    </pre>
                  </details>
                ))}
              </div>
              <div className="wl-check-card">
                <div>
                  <ShieldCheck size={18} />
                  <h4>Verify qua HTTP</h4>
                  <span className={preview?.http?.passed ? "is-pass" : ""}>
                    {httpChecks.length
                      ? `${httpChecks.filter((c) => c.passed).length}/${httpChecks.length} đạt`
                      : "Chưa chạy"}
                  </span>
                </div>
                <p>Kiểm tra trực tiếp ứng dụng đang phục vụ trong Sandbox.</p>
                {httpChecks.map((check) => (
                  <div className="wl-http-check" key={check.id}>
                    {check.passed ? (
                      <CheckCircle2 size={14} className="is-pass" />
                    ) : (
                      <XCircle size={14} />
                    )}
                    {check.label}
                  </div>
                ))}
              </div>
              <p className="wl-help">
                Đây là kết quả trong phạm vi test và HTTP smoke. Phê duyệt bàn
                giao của chu kỳ được thực hiện riêng.
              </p>
            </div>
          )}
          {tab === "history" && (
            <div className="wl-history" role="tabpanel">
              {row.nodes.map((node) => (
                <details className="wl-details" key={node.id}>
                  <summary>
                    {nodeLabel[node.id] ?? node.id}
                    <span>{stateLabel[node.state] ?? node.state}</span>
                  </summary>
                  <p>{node.summary ?? "Bước này chưa có báo cáo cuối."}</p>
                  {node.session_id && <code>Session: {node.session_id}</code>}
                </details>
              ))}
              <p className="wl-help">
                Lượt chạy {row.run_id}
                {row.job_id ? ` · Workloop ${row.job_id}` : ""}
              </p>
            </div>
          )}
          {row.error_code && (
            <p className="pl-error">
              Lượt chạy cần kiểm tra ({row.error_code}). Các kết quả đã nhận
              được giữ lại; hệ thống không tự gửi lại yêu cầu.
            </p>
          )}
        </>
      )}
      <details className="wl-catalog">
        <summary>
          Factory & plugin đang kết nối
          <ChevronDown size={14} />
        </summary>
        <div className="wl-catalog-grid">
          {data?.context.factories.map((f) => (
            <div key={f.id}>
              <strong>{f.id}</strong>
              <p>
                {f.workflows.length} workflow · {f.revision.slice(0, 8)}
              </p>
              <p>
                {f.id === "factory-test"
                  ? "Kiểm thử Workloop; cần source và môi trường riêng."
                  : "Workflow mẫu phát triển và review sản phẩm."}
              </p>
            </div>
          ))}
        </div>
        <div className="wl-plugins">
          {data?.inventory.plugins.map((p) => (
            <span
              key={p.name}
              className={p.loaded || p.runtime_tools ? "" : "is-muted"}
            >
              <i />
              {p.name}
              {p.version ? ` ${p.version}` : ""}
              {!p.loaded
                ? p.runtime_tools
                  ? " · tools có sẵn"
                  : " · chưa nạp"
                : ""}
            </span>
          ))}
        </div>
        {data?.inventory.error_code && (
          <p className="wl-help">Chưa cập nhật được danh sách plugin.</p>
        )}
      </details>
    </section>
  );
}

export default function WorkloopPanel({
  deliveryId,
  cycleId,
  canWrite,
}: {
  deliveryId: string;
  cycleId?: string;
  canWrite: boolean;
}) {
  const owner = useContext(AuthContext).userData?.id;
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [review, setReview] = useState<{
    factory: string;
    workflow: string;
  } | null>(null);
  const inFlight = useRef(false);
  const query = useQuery({
    queryKey: ["workloop", owner, deliveryId, cycleId],
    enabled: !!owner && !!cycleId,
    queryFn: () => workloop.list(deliveryId, cycleId!),
    refetchIntervalInBackground: true,
    refetchInterval: (q) =>
      q.state.data?.runs.some((r) => active(r.state)) ? 2500 : false,
  });
  const start = async () => {
    if (inFlight.current || !review || !cycleId || !query.data) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    const choice = review;
    setReview(null);
    try {
      await workloop.start(deliveryId, {
        cycle_id: cycleId,
        run_id: crypto.randomUUID(),
        ...choice,
        context_digest: query.data.context.context_digest,
      });
    } catch {
      setError(
        "Chưa xác nhận yêu cầu. Hãy cập nhật trạng thái; không tự gửi thêm lượt chạy.",
      );
    } finally {
      inFlight.current = false;
      setBusy(false);
      await query.refetch();
    }
  };
  return (
    <>
      <WorkloopView
        data={query.data}
        busy={busy}
        error={
          error ||
          (query.isError
            ? "Chưa tải được Workloop. Hãy cập nhật trạng thái."
            : "")
        }
        canWrite={canWrite}
        onStart={(factory, workflow) => setReview({ factory, workflow })}
        onRefresh={() => void query.refetch()}
      />
      <Dialog
        open={!!review}
        onOpenChange={(open) => {
          if (!open) setReview(null);
        }}
      >
        <DialogContent className="pl-review">
          <DialogTitle>
            {review?.factory === "pokedev"
              ? "Tạo bản chạy thử trong Sandbox"
              : "Chạy workflow Workloop"}
          </DialogTitle>
          <DialogDescription>
            {review?.factory === "pokedev"
              ? "Đối chiếu candidate đã đạt test, chạy lại bộ test và triển khai bản thử trong 1 giờ. Không gọi thêm model và không thay quyết định phê duyệt chu kỳ."
              : `Chạy ${review?.factory} / ${review?.workflow} bằng ${query.data?.capabilities.model.model}. Mỗi lượt có workspace riêng, tối đa 6 bước và 15 phút. Chưa có trần token hoặc chi phí model.`}
          </DialogDescription>
          <button
            type="button"
            className="pl-start"
            disabled={busy}
            onClick={() => void start()}
          >
            <Play size={15} />
            Bắt đầu lượt này
          </button>
        </DialogContent>
      </Dialog>
    </>
  );
}
