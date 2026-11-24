import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  Archive,
  Check,
  ExternalLink,
  FileText,
  Inbox,
  LoaderCircle,
  MessageSquare,
  RefreshCw,
  RotateCcw,
  Search,
  Settings2,
  X,
} from "lucide-react";
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { SanitizedMarkdown } from "@/components/core/sanitizedMarkdown";
import {
  documentIntake,
  documentState,
  documentUrl,
  intakeError,
  type IntakeDocument,
} from "@/controllers/API/document-intake";
import {
  liveWorkflows,
  type LiveProject,
  type LiveRun,
} from "@/controllers/API/live-workflows";
import "./document-intake.css";
import { documentNeedsReview, useDocumentInbox } from "./document-intake-query";
const time = (value?: string) =>
  value
    ? new Date(value).toLocaleString("vi-VN", {
        timeZone: "Asia/Ho_Chi_Minh",
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "Chưa cập nhật";
const runLabel = (state?: string) =>
  ({
    PLANNING: "Đang lập kế hoạch",
    PLAN_READY: "Chờ duyệt kế hoạch",
    RUNNING: "Đang thực hiện",
    SUCCEEDED: "Hoàn tất",
    FAILED: "Cần xử lý",
    UNCONFIRMED: "Cần đối soát",
  })[state || ""] || "Đang cập nhật";
const denied = (error: unknown) =>
  [401, 403, 404].includes(
    (error as { response?: { status?: number } })?.response?.status || 0,
  );

export function DocumentInboxSummary() {
  const inbox = useDocumentInbox();
  const data = denied(inbox.error) ? undefined : inbox.data;
  const pending = data?.items.filter(documentNeedsReview) || [];
  return (
    <section className="di-summary">
      <Inbox size={20} />
      <div>
        <h3>Yêu cầu từ Slack</h3>
        <p>
          {inbox.isError || data?.stale
            ? "Đang chờ kết nối lại với Workloop"
            : pending.length
              ? `${pending.length} tài liệu cần gắn project hoặc duyệt`
              : `${data?.items.length || 0} tài liệu đã nhận · tự cập nhật khi có yêu cầu mới`}
        </p>
      </div>
      <Link to={documentUrl()}>
        Mở hộp yêu cầu <ArrowRight size={14} />
      </Link>
    </section>
  );
}

export default function DocumentIntake({
  identity,
  projectId,
  projects,
  selectedId,
  onSelect,
  onOpenRun,
  onConnectProject,
}: {
  identity: string;
  projectId?: string;
  projects: LiveProject[];
  selectedId?: string;
  onSelect: (id: string) => void;
  onOpenRun: (run: Pick<LiveRun, "project_id" | "run_id">) => void;
  onConnectProject: () => void;
}) {
  const [search, setSearch] = useState(""),
    [filter, setFilter] = useState("all"),
    [rulesError, setRulesError] = useState("");
  const inbox = useDocumentInbox(projectId, true, filter === "archived"),
    client = useQueryClient();
  const [removing, setRemoving] = useState("");
  const data = denied(inbox.error) ? undefined : inbox.data;
  const items = data?.items || [];
  const visible = items.filter(
    (doc) =>
      (filter === "archived" ? !!doc.archived_at : !doc.archived_at) &&
      (filter !== "review" || documentNeedsReview(doc)) &&
      `${doc.title} ${doc.repository || ""} ${doc.lifecycle_id}`
        .toLocaleLowerCase()
        .includes(search.toLocaleLowerCase()),
  );
  const detail = useQuery({
    queryKey: ["intake-document", identity, selectedId],
    queryFn: () => documentIntake.read(selectedId!),
    enabled: !!selectedId && !!identity && !!data,
    retry: false,
    staleTime: 5000,
    refetchInterval: 15000,
  });
  const selected = denied(detail.error) ? undefined : detail.data;
  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ["document-intake", identity] }),
      client.invalidateQueries({
        queryKey: ["intake-document", identity, selectedId],
      }),
      client.invalidateQueries({ queryKey: ["live-runs", identity] }),
      client.invalidateQueries({ queryKey: ["workspace-dashboard", identity] }),
    ]);
  };
  return (
    <section className="di-page" aria-label="Yêu cầu & tài liệu">
      <header className="di-header">
        <div>
          <span className="di-eyebrow">SLACK → CONFLUENCE → PROJECT</span>
          <h2>Yêu cầu & tài liệu</h2>
          <p>
            Tài liệu bot tạo tự xuất hiện tại đây. Chọn project, duyệt nội dung
            rồi lập kế hoạch.
          </p>
        </div>
        <div className="di-header-actions">
          <Link to="/settings/integrations">
            <Settings2 size={14} /> Slack & Workloop
          </Link>
          {data?.bot_url && (
            <a href={data.bot_url} target="_blank" rel="noopener noreferrer">
              <MessageSquare size={14} /> Mở bot Slack
            </a>
          )}
          <button
            aria-label="Đồng bộ tài liệu"
            onClick={() => void refresh()}
            disabled={inbox.isFetching}
          >
            <RefreshCw
              size={15}
              className={inbox.isFetching ? "animate-spin" : ""}
            />
          </button>
        </div>
      </header>
      <div className="di-connection" role="status">
        <span
          className={inbox.isError || data?.stale ? "di-dot stale" : "di-dot"}
        />
        {data?.stale || inbox.isError
          ? "Chưa đồng bộ được · đang giữ dữ liệu đã nhận"
          : `Tự cập nhật mỗi 10 giây · ${time(data?.checked_at)}`}
        <span>
          {filter === "archived"
            ? `${visible.length} yêu cầu đã lưu trữ`
            : `${items.length} tài liệu · ${items.filter(documentNeedsReview).length} cần xử lý`}
        </span>
      </div>
      {data?.limit_reached && (
        <p className="di-notice">
          Đã nhận 200 tài liệu gần nhất và giữ lịch sử đã lưu. Workloop hiện
          giới hạn số tài liệu mỗi lần đọc.
        </p>
      )}
      {inbox.isError && !data && (
        <p role="alert" className="di-notice">
          {intakeError(inbox.error)}
        </p>
      )}
      <div className={`di-layout ${selectedId ? "with-document" : ""}`}>
        <div className="di-list">
          <div className="di-filters">
            <label>
              <Search size={15} />
              <input
                aria-label="Tìm tài liệu"
                placeholder="Tìm yêu cầu, project…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </label>
            <select
              aria-label="Lọc tài liệu"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            >
              <option value="all">Tất cả</option>
              <option value="review">Cần xử lý</option>
              <option value="archived">Đã lưu trữ</option>
            </select>
          </div>
          {inbox.isPending && (
            <p role="status" className="di-empty">
              Đang nhận tài liệu từ Workloop…
            </p>
          )}
          {visible.map((doc) => (
            <button
              key={doc.document_id}
              className={`di-item ${selectedId === doc.document_id ? "selected" : ""}`}
              onClick={() => onSelect(doc.document_id)}
              aria-pressed={selectedId === doc.document_id}
            >
              <FileText size={18} />
              <div>
                <strong>{doc.title || `Tài liệu #${doc.document_id}`}</strong>
                <small>
                  {projects.find((p) => p.project_id === doc.project_id)
                    ?.name || "Chưa gắn project"}{" "}
                  · {time(doc.created_at)}
                </small>
                <span className={`di-badge ${doc.state.toLowerCase()}`}>
                  {doc.run_state && doc.run_state !== "UNAVAILABLE"
                    ? `Lượt chạy: ${runLabel(doc.run_state)}`
                    : documentState[doc.state] || doc.state}
                </span>
                {doc.run_id && documentNeedsReview(doc) && (
                  <span className="di-badge changed">Có thay đổi cần xem</span>
                )}
              </div>
              <ArrowRight size={14} />
            </button>
          ))}
          {!inbox.isPending && !visible.length && !denied(inbox.error) && (
            <div className="di-empty">
              <Inbox size={30} />
              <h3>
                {filter === "archived"
                  ? "Chưa có yêu cầu lưu trữ"
                  : items.length
                    ? "Không có kết quả phù hợp"
                    : "Chờ yêu cầu từ Slack"}
              </h3>
              <p>
                {items.length
                  ? "Thử đổi bộ lọc hoặc từ khóa."
                  : "Nhắn bot vai-orchestrator-agent. Khi bot tạo tài liệu Confluence, tài liệu sẽ xuất hiện ở đây."}
              </p>
              {!data?.can_manage && (
                <p>Quản trị viên cần gắn tài liệu với project của bạn trước.</p>
              )}
            </div>
          )}
          {!!data?.rules.length && (
            <details className="di-rules">
              <summary>Tự gắn channel → project ({data.rules.length})</summary>
              {data.rules.map((rule) => (
                <div key={rule.channel}>
                  <span>
                    <strong>{rule.channel}</strong>
                    <small>
                      {projects.find((p) => p.project_id === rule.project_id)
                        ?.name || rule.repository}
                    </small>
                  </span>
                  {data.can_manage && (
                    <button
                      aria-label={`Bỏ liên kết channel ${rule.channel}`}
                      disabled={!!removing}
                      onClick={async () => {
                        setRemoving(rule.channel);
                        setRulesError("");
                        try {
                          await documentIntake.removeRule(rule.channel);
                          await refresh();
                        } catch (e) {
                          setRulesError(intakeError(e));
                        } finally {
                          setRemoving("");
                        }
                      }}
                    >
                      <X size={14} />
                    </button>
                  )}
                </div>
              ))}
              <p>Bỏ liên kết chỉ áp dụng cho tài liệu nhận sau này.</p>
              {rulesError && <p role="alert">{rulesError}</p>}
            </details>
          )}
        </div>
        {selectedId && (
          <div className="di-detail" aria-label="Chi tiết tài liệu">
            {detail.isPending && (
              <p role="status">Đang đọc tài liệu Confluence…</p>
            )}
            {detail.isError && (
              <p role="alert" className="di-notice">
                {intakeError(detail.error)}
              </p>
            )}
            {selected && (
              <DocumentDetail
                key={`${selected.document_id}:${selected.project_id}:${selected.instructions}`}
                doc={{
                  ...selected,
                  run_state: items.find(
                    (item) => item.document_id === selectedId,
                  )?.run_state,
                }}
                identity={identity}
                projects={projects}
                canManage={!!data?.can_manage}
                stale={
                  !!selected.stale ||
                  detail.isError ||
                  inbox.isError ||
                  !!data?.stale
                }
                refresh={refresh}
                onOpenRun={onOpenRun}
                onConnectProject={onConnectProject}
              />
            )}
          </div>
        )}
        {!selectedId && !!items.length && (
          <div className="di-placeholder">
            <FileText size={32} />
            <h3>Chọn một yêu cầu</h3>
            <p>
              Xem tài liệu, quyết định phạm vi và theo dõi hành trình triển khai
              tại đây.
            </p>
          </div>
        )}
      </div>
    </section>
  );
}

function DocumentDetail({
  doc,
  identity,
  projects,
  canManage,
  stale,
  refresh,
  onOpenRun,
  onConnectProject,
}: {
  doc: IntakeDocument;
  identity: string;
  projects: LiveProject[];
  canManage: boolean;
  stale: boolean;
  refresh: () => Promise<void>;
  onOpenRun: (run: Pick<LiveRun, "run_id" | "project_id">) => void;
  onConnectProject: () => void;
}) {
  const [project, setProject] = useState(doc.project_id || ""),
    [instructions, setInstructions] = useState(doc.instructions || ""),
    [automatic, setAutomatic] = useState(false);
  const [workflow, setWorkflow] = useState(""),
    [busy, setBusy] = useState(""),
    [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [legacyInvocation, setLegacyInvocation] = useState("");
  const revisionIntent = useRef<{ key: string; id: string } | undefined>(
    undefined,
  );
  const revisionPending = [
    "SENDING",
    "SENT",
    "UNCONFIRMED",
    "PROCESSING",
  ].includes(doc.revision_request?.state || "");
  const sending = useRef(false),
    intent = useRef<{ key: string; id: string } | undefined>(undefined);
  const workflows = useQuery({
    queryKey: ["project-workflows", identity, doc.project_id],
    queryFn: () => liveWorkflows.workflows(doc.project_id!),
    enabled: !!doc.project_id && !doc.archived_at,
    retry: false,
    staleTime: 5000,
  });
  const dirty =
    project !== (doc.project_id || "") ||
    instructions !== (doc.instructions || "");
  const currentCommand =
    doc.plan_command?.digest === doc.digest ? doc.plan_command : undefined;
  const lockedDecision = !!currentCommand;
  const hasRun =
    !!doc.run_started_at ||
    (!!doc.run_state && doc.run_state !== "UNAVAILABLE");
  const newerRevision = hasRun && doc.plan_command?.digest !== doc.digest;
  const approved =
    doc.state === "APPROVED" &&
    doc.approval?.decision === "approve" &&
    doc.approval?.digest === doc.digest;
  const blocked = !!busy || stale || dirty || !doc.digest;
  const selectedWorkflow = workflows.data?.items.find(
    (w) => w.workflow_id === workflow,
  );
  const act = async (name: string, operation: () => Promise<unknown>) => {
    if (sending.current) return;
    sending.current = true;
    setBusy(name);
    setError("");
    try {
      await operation();
    } catch (e) {
      setError(intakeError(e));
    } finally {
      sending.current = false;
      setBusy("");
      await refresh();
    }
  };
  const start = () =>
    act("plan", async () => {
      const chosen = currentCommand?.workflow_id || workflow || undefined;
      const digest =
        currentCommand?.workflow_digest || selectedWorkflow?.digest;
      const key = JSON.stringify([doc.document_id, doc.digest, chosen, digest]);
      if (!intent.current || intent.current.key !== key)
        intent.current = { key, id: crypto.randomUUID() };
      const run = await documentIntake.plan(doc.document_id, {
        digest: doc.digest!,
        command_id: currentCommand?.id || intent.current.id,
        ...(chosen ? { workflow_id: chosen, workflow_digest: digest } : {}),
      });
      onOpenRun(run);
    });
  if (doc.archived_at) {
    return (
      <section className="di-revision" aria-label="Yêu cầu đã lưu trữ">
        <span className="di-eyebrow">
          YÊU CẦU #{doc.document_id} · ĐÃ LƯU TRỮ
        </span>
        <h2>{doc.title}</h2>
        <p>
          Lưu trữ lúc {time(doc.archived_at)}. Thông báo và đồng bộ tiến độ của
          yêu cầu này đã dừng.
        </p>
        <p>
          Khôi phục để xem lại phạm vi và duyệt phiên bản tài liệu mới trước khi
          thực hiện.
        </p>
        {error && <p role="alert">{error}</p>}
        <button
          className="di-primary"
          disabled={!!busy}
          onClick={() =>
            void act("restore", () => documentIntake.restore(doc.document_id))
          }
        >
          <RotateCcw size={14} /> Khôi phục yêu cầu
        </button>
        {!!doc.body && <SanitizedMarkdown chatMessage={doc.body} />}
      </section>
    );
  }
  return (
    <>
      <div className="di-document-header">
        <span className="di-eyebrow">
          YÊU CẦU #{doc.document_id} · {doc.doc_type || "SPEC"}
        </span>
        <h2>{doc.title}</h2>
        <div className="di-source-links">
          {doc.slack_url && (
            <a href={doc.slack_url} target="_blank" rel="noopener noreferrer">
              <MessageSquare size={14} /> Hội thoại Slack{" "}
              <ExternalLink size={12} />
            </a>
          )}
          {doc.confluence_url && (
            <a
              href={doc.confluence_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              <FileText size={14} /> Confluence <ExternalLink size={12} />
            </a>
          )}
          <span>
            Workloop:{" "}
            {doc.source_status === "approved"
              ? "đã duyệt ở nguồn"
              : doc.source_status}
          </span>
          <button
            className="di-archive"
            disabled={
              !!busy ||
              revisionPending ||
              (!!currentCommand && !doc.run_started_at) ||
              (!!doc.run_id &&
                !["SUCCEEDED", "FAILED"].includes(doc.run_state || ""))
            }
            onClick={() =>
              void act("archive", () => documentIntake.archive(doc.document_id))
            }
          >
            <Archive size={14} /> Lưu trữ yêu cầu
          </button>
        </div>
      </div>
      <ol className="di-journey" aria-label="Hành trình yêu cầu">
        {[
          { title: "Nhận từ Slack", done: true },
          { title: "Tài liệu", done: !!doc.body },
          { title: "Duyệt project", done: approved },
          { title: "Kế hoạch & task", done: hasRun },
          { title: "Chạy & kiểm chứng", done: doc.run_state === "SUCCEEDED" },
        ].map((step, index) => (
          <li key={step.title} className={step.done ? "done" : ""}>
            <span>{step.done ? <Check size={12} /> : index + 1}</span>
            {step.title}
          </li>
        ))}
      </ol>
      <section className="di-progress" aria-label="Tiến độ cho bot Slack">
        <div>
          <h3>Tiến độ cho bot Slack</h3>
          <p>
            {doc.progress?.enabled
              ? doc.progress.error_code
                ? intakeError({
                    response: {
                      data: { detail: { code: doc.progress.error_code } },
                    },
                  })
                : doc.progress.state === "SYNCED"
                  ? `Đã cập nhật báo cáo · ${time(doc.progress.synced_at)}`
                  : "Đang chuẩn bị báo cáo tiến độ trên Confluence…"
              : "Bật đồng bộ để bot tra cứu tiến độ của yêu cầu trong cùng thread Slack."}
          </p>
          <small>
            Báo cáo tiến độ được lưu riêng trên Confluence và cập nhật định kỳ.{" "}
            {doc.progress?.enabled
              ? "Tài liệu mới tự gắn từ channel có thể dùng cùng cài đặt này."
              : ""}
          </small>
        </div>
        <div className="di-actions">
          {doc.progress?.link && (
            <a
              href={doc.progress.link}
              target="_blank"
              rel="noopener noreferrer"
            >
              Xem báo cáo <ExternalLink size={13} />
            </a>
          )}
          {canManage && (
            <button
              disabled={!!busy || doc.progress?.state === "SYNCING"}
              onClick={() =>
                void act("progress", () =>
                  documentIntake.progress(
                    doc.document_id,
                    !doc.progress?.enabled,
                  ),
                )
              }
            >
              {doc.progress?.enabled ? "Ngừng đồng bộ" : "Bật đồng bộ tiến độ"}
            </button>
          )}
          {canManage && doc.progress?.enabled && doc.progress.error_code && (
            <button
              disabled={!!busy}
              onClick={() =>
                void act("progress", () =>
                  documentIntake.progress(doc.document_id, true),
                )
              }
            >
              Kiểm tra lại báo cáo
            </button>
          )}
        </div>
      </section>
      <section
        className="di-progress"
        aria-label="Thông báo trong hội thoại Slack"
      >
        <div>
          <h3>Thông báo trong hội thoại Slack</h3>
          <p>
            {!doc.notifications?.enabled
              ? "Bật để nhận thông báo khi cần duyệt, trả lời, xử lý lỗi hoặc xem kết quả."
              : doc.notifications.state === "NEEDS_CONFIGURATION"
                ? "Đã bật cho yêu cầu này · cần lưu mã bot trong Cài đặt → Slack & Workloop."
                : doc.notifications.error_code
                  ? intakeError({
                      response: {
                        data: {
                          detail: { code: doc.notifications.error_code },
                        },
                      },
                    })
                  : doc.notifications.state === "SENT"
                    ? "Thông báo gần nhất đã được gửi vào thread gốc."
                    : "Đang theo dõi · thông báo sẽ gửi vào thread Slack gốc khi có thay đổi cần biết."}
          </p>
          <small>
            Chỉ gửi mốc cần chú ý, không gửi lại theo mỗi lần cập nhật sơ đồ.
          </small>
        </div>
        <div className="di-actions">
          <Link to="/settings/integrations">Cài đặt bot</Link>
          {doc.notifications?.last_message_url && (
            <a
              href={doc.notifications.last_message_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              Mở thông báo đã gửi
            </a>
          )}
          {canManage && (
            <button
              disabled={!!busy}
              onClick={() =>
                void act("notifications", () =>
                  documentIntake.notifications(
                    doc.document_id,
                    !doc.notifications?.enabled,
                  ),
                )
              }
            >
              {doc.notifications?.enabled
                ? "Tắt thông báo Slack"
                : "Bật thông báo Slack"}
            </button>
          )}
        </div>
      </section>
      {stale && (
        <p role="alert" className="di-notice">
          {doc.error_code
            ? intakeError({
                response: { data: { detail: { code: doc.error_code } } },
              })
            : "Đang hiển thị nội dung đã lưu. Cần kết nối lại để duyệt và lập kế hoạch."}
        </p>
      )}
      {doc.state === "CHANGED" && (
        <p role="status" className="di-notice">
          Tài liệu đã có phiên bản mới. Lượt chạy cũ giữ nguyên nội dung đã
          duyệt; phiên bản này cần được xem lại.
        </p>
      )}
      <section className="di-scope">
        <h3>Project & phạm vi triển khai</h3>
        <div className="di-project-row">
          <label>
            Project
            <select
              aria-label="Project nhận yêu cầu"
              value={project}
              onChange={(e) => setProject(e.target.value)}
              disabled={!!busy || !!doc.run_id}
            >
              <option value="">Chọn project…</option>
              {projects.map((p) => (
                <option key={p.project_id} value={p.project_id}>
                  {p.name} · {p.repository}
                </option>
              ))}
            </select>
          </label>
          <button onClick={onConnectProject} disabled={!!busy}>
            Kết nối repo
          </button>
        </div>
        <label>
          Chỉ dẫn bổ sung
          <textarea
            rows={3}
            aria-label="Chỉ dẫn bổ sung"
            placeholder="Phạm vi, quy tắc hoặc thông tin đã thống nhất với nhóm…"
            maxLength={16000}
            value={instructions}
            disabled={!!busy || (!!doc.plan_command && !doc.run_started_at)}
            onChange={(e) => setInstructions(e.target.value)}
          />
        </label>
        {canManage && doc.slack_channel && (
          <label className="di-checkbox">
            <input
              type="checkbox"
              checked={automatic}
              disabled={!!busy}
              onChange={(e) => setAutomatic(e.target.checked)}
            />{" "}
            Tự gắn tài liệu mới từ channel {doc.slack_channel} vào project này
          </label>
        )}
        {(dirty || automatic || !doc.project_id) && (
          <button
            className="di-primary"
            disabled={
              !project || !!busy || (!!doc.plan_command && !doc.run_started_at)
            }
            onClick={() =>
              void act("save", () =>
                documentIntake.assign(
                  doc.document_id,
                  project,
                  instructions,
                  automatic,
                  canManage ? !!doc.progress?.enabled : undefined,
                ),
              )
            }
          >
            {busy === "save" && (
              <LoaderCircle size={14} className="animate-spin" />
            )}{" "}
            Lưu phạm vi
          </button>
        )}
        {dirty && (
          <p className="di-help">
            Lưu thay đổi trước khi duyệt. Thay đổi phạm vi sẽ yêu cầu duyệt lại.
          </p>
        )}
      </section>
      <section className="di-content">
        <header>
          <h3>Nội dung Confluence</h3>
          <span>
            Phiên bản {doc.page_version ?? "—"} ·{" "}
            {time(doc.page_checked_at_iso)}
          </span>
        </header>
        <div className="di-markdown">
          {doc.body ? (
            <SanitizedMarkdown chatMessage={doc.body} isEmpty={false} />
          ) : (
            <p>Chưa có nội dung tài liệu để duyệt.</p>
          )}
        </div>
      </section>
      <section className="di-decision">
        <div>
          <h3>{documentState[doc.state] || doc.state}</h3>
          <p>
            {doc.approval
              ? `Quyết định cho project · ${time(doc.approval.at)} · tài liệu v${doc.approval.page_version}`
              : "Duyệt cho project đã chọn sau khi đọc tài liệu và phạm vi."}
          </p>
          <small>
            Quyết định tại đây cho phép lập kế hoạch trong PokeDev. Trạng
            thái duyệt ở Workloop được hiển thị riêng.
          </small>
          {lockedDecision && (
            <p>
              Quyết định của phiên bản này đã gắn với lượt chạy. Mở lượt chạy để
              phản hồi hoặc điều khiển.
            </p>
          )}
        </div>
        <div className="di-actions">
          <button
            disabled={
              blocked ||
              !doc.project_id ||
              lockedDecision ||
              approved ||
              revisionPending ||
              doc.source_status === "rejected" ||
              doc.source_status === "cancelled"
            }
            className="di-primary"
            onClick={() =>
              void act("approve", () =>
                documentIntake.decide(doc.document_id, doc.digest!, "approve"),
              )
            }
          >
            <Check size={15} /> Duyệt cho project
          </button>
          <button
            disabled={
              blocked ||
              !doc.project_id ||
              lockedDecision ||
              doc.state === "REJECTED" ||
              revisionPending
            }
            onClick={() =>
              void act("reject", () =>
                documentIntake.decide(doc.document_id, doc.digest!, "reject"),
              )
            }
          >
            <X size={15} /> Từ chối
          </button>
        </div>
      </section>
      {canManage && (
        <section className="di-revision" aria-label="Yêu cầu bot sửa tài liệu">
          <h3>Yêu cầu bot sửa tài liệu</h3>
          <p>
            Gửi góp ý về đúng hội thoại Slack. Khi tài liệu có phiên bản mới,
            bạn có thể đọc lại và duyệt trên web.
          </p>
          {doc.revision_request && (
            <div className="di-revision-status" role="status">
              <strong>
                {{
                  SENDING: "Đang gửi yêu cầu sửa",
                  SENT: "Workloop đã nhận · đang chờ bot cập nhật",
                  PROCESSING: "Bot đang cập nhật tài liệu",
                  UNCONFIRMED: "Chưa xác nhận việc tiếp nhận",
                  UPDATED: "Tài liệu đã có phiên bản mới",
                  ERROR: "Chưa gửi được yêu cầu sửa",
                  FAILED: "Bot chưa cập nhật được tài liệu",
                }[doc.revision_request.state] || doc.revision_request.state}
              </strong>
              <p>{doc.revision_request.feedback}</p>
              <small>
                Góp ý cho tài liệu v{doc.revision_request.page_version} ·{" "}
                {time(doc.revision_request.at)}
              </small>
              {doc.revision_request.error_code && (
                <p role="alert">
                  {intakeError({
                    response: {
                      data: {
                        detail: { code: doc.revision_request.error_code },
                      },
                    },
                  })}
                </p>
              )}
              {doc.revision_request.invocation_id && (
                <button
                  disabled={!!busy}
                  onClick={() =>
                    void act("revision-status", () =>
                      documentIntake.checkRevision(doc.document_id, {
                        request_id: doc.revision_request!.id,
                      }),
                    )
                  }
                >
                  Kiểm tra tiến độ cập nhật
                </button>
              )}
              {revisionPending &&
                !doc.revision_request.invocation_id &&
                (doc.revision_request.transport !== "native-spec" ||
                  doc.revision_request.state === "UNCONFIRMED") && (
                  <details>
                    <summary>Đối soát lượt chưa có biên nhận</summary>
                    <p>
                      Nhập mã lượt bot đã trả trong đúng thread Slack để xem kết
                      quả xử lý.
                    </p>
                    <input
                      aria-label="Mã lượt bot"
                      value={legacyInvocation}
                      onChange={(e) => setLegacyInvocation(e.target.value)}
                      placeholder="ag-…"
                      disabled={!!busy}
                    />
                    <button
                      disabled={
                        !!busy ||
                        !/^ag-[A-Za-z0-9-]{1,100}$/.test(
                          legacyInvocation.trim(),
                        )
                      }
                      onClick={() =>
                        void act("revision-link", () =>
                          documentIntake.checkRevision(doc.document_id, {
                            request_id: doc.revision_request!.id,
                            invocation_id: legacyInvocation.trim(),
                          }),
                        )
                      }
                    >
                      Kiểm tra lượt bot đã chọn
                    </button>
                  </details>
                )}
              {doc.revision_request.state === "UNCONFIRMED" &&
                !doc.revision_request.invocation_id && (
                  <button
                    disabled={!!busy}
                    onClick={() =>
                      void act("revision-check", () =>
                        documentIntake.revise(doc.document_id, {
                          digest: doc.revision_request!.digest,
                          request_id: doc.revision_request!.id,
                          feedback: doc.revision_request!.feedback,
                        }),
                      )
                    }
                  >
                    Kiểm tra tiếp nhận
                  </button>
                )}
            </div>
          )}
          <label>
            Nội dung cần sửa
            <textarea
              aria-label="Góp ý sửa tài liệu"
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              rows={4}
              maxLength={6000}
              disabled={!!busy || revisionPending}
              placeholder="Nêu phần chưa đúng, thông tin cần bổ sung và kết quả mong muốn…"
            />
          </label>
          <button
            className="di-primary"
            disabled={
              blocked ||
              revisionPending ||
              feedback.trim().length < 10 ||
              (!!doc.plan_command && !doc.run_started_at)
            }
            onClick={() =>
              void act("revision", async () => {
                const key = JSON.stringify([doc.digest, feedback.trim()]);
                if (revisionIntent.current?.key !== key)
                  revisionIntent.current = { key, id: crypto.randomUUID() };
                const result = await documentIntake.revise(doc.document_id, {
                  digest: doc.digest!,
                  request_id: revisionIntent.current.id,
                  feedback: feedback.trim(),
                });
                if (
                  ["SENT", "PROCESSING"].includes(
                    result.revision_request?.state || "",
                  )
                )
                  setFeedback("");
              })
            }
          >
            Gửi yêu cầu sửa về bot
          </button>
        </section>
      )}
      {approved && (!hasRun || newerRevision) && (
        <section className="di-plan">
          <h3>Lập kế hoạch triển khai</h3>
          <label>
            Workflow
            <select
              aria-label="Workflow triển khai"
              value={currentCommand?.workflow_id || workflow}
              disabled={!!busy || !!currentCommand}
              onChange={(e) => setWorkflow(e.target.value)}
            >
              <option value="">Agent đề xuất theo tài liệu</option>
              {workflows.data?.items.map((w) => (
                <option
                  key={w.workflow_id}
                  value={w.workflow_id}
                  disabled={!w.ready}
                >
                  {w.name} · v{w.revision}
                  {w.ready ? "" : " · cần kiểm tra"}
                </option>
              ))}
            </select>
          </label>
          {workflows.isError && (
            <p role="alert">
              Chưa đọc được workflow. Làm mới trước khi chọn workflow có sẵn.
            </p>
          )}
          <p>
            Agent tạo kế hoạch và task từ nội dung đã duyệt. Bạn có thể chỉnh
            canvas và duyệt kế hoạch trước khi thực hiện.
          </p>
          <div className="di-source-links">
            <Link
              to={`/work?${new URLSearchParams({ project: doc.project_id!, view: "workflows" })}`}
            >
              Tạo / chỉnh workflow <ArrowRight size={12} />
            </Link>
            <Link
              to={`/work?${new URLSearchParams({ project: doc.project_id!, view: "environment" })}`}
            >
              Cấu hình môi trường & kiểm thử <ArrowRight size={12} />
            </Link>
          </div>
          <button
            className="di-primary"
            disabled={
              blocked ||
              (!!workflow && (!selectedWorkflow?.ready || workflows.isError)) ||
              (newerRevision &&
                !["SUCCEEDED", "FAILED"].includes(doc.run_state || ""))
            }
            onClick={() => void start()}
          >
            {busy === "plan" ? (
              <LoaderCircle size={15} className="animate-spin" />
            ) : (
              <ArrowRight size={15} />
            )}{" "}
            {currentCommand
              ? "Tiếp tục lập kế hoạch"
              : newerRevision
                ? "Lập kế hoạch phiên bản mới"
                : "Lập kế hoạch"}
          </button>
          {newerRevision &&
            !["SUCCEEDED", "FAILED"].includes(doc.run_state || "") && (
              <p>
                Hoàn tất hoặc xử lý lượt chạy trước khi bắt đầu phiên bản mới.
              </p>
            )}
        </section>
      )}
      {!!doc.plan_command && !hasRun && (
        <div className="di-pending">
          <p>
            Yêu cầu lập kế hoạch đã được ghi nhận. Thử tiếp tục sẽ sử dụng cùng
            một lượt chạy.
          </p>
          <button
            disabled={!!busy || stale}
            onClick={() =>
              void act("clear", () => documentIntake.clearPlan(doc.document_id))
            }
          >
            Bỏ yêu cầu lập kế hoạch chưa bắt đầu
          </button>
        </div>
      )}
      {doc.run_id && hasRun && (
        <div className="di-open-run">
          <div>
            <strong>Lượt chạy của yêu cầu</strong>
            <p>
              {runLabel(doc.run_state)} · theo dõi sơ đồ task, phản hồi, kiểm
              thử và bàn giao
            </p>
          </div>
          <button
            className="di-primary"
            onClick={() =>
              onOpenRun({
                project_id: doc.project_id || null,
                run_id: doc.run_id!,
              })
            }
          >
            Mở lượt chạy <ArrowRight size={15} />
          </button>
        </div>
      )}
      {!!doc.previous_runs?.length && (
        <details className="di-history">
          <summary>
            Lượt chạy các phiên bản trước ({doc.previous_runs.length})
          </summary>
          {doc.previous_runs.map((run) => (
            <a
              key={run.run_id}
              href={`/work?${new URLSearchParams({ project: doc.project_id || "", run: run.run_id })}`}
            >
              Tài liệu v{run.page_version} · {run.run_id.slice(0, 8)}{" "}
              <ArrowRight size={12} />
            </a>
          ))}
        </details>
      )}
      {error && (
        <p className="di-notice" role="alert">
          {error}
        </p>
      )}
    </>
  );
}
