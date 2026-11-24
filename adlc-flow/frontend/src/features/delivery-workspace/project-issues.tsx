import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  Check,
  CircleDot,
  ExternalLink,
  LoaderCircle,
  RefreshCw,
  Settings2,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { SanitizedMarkdown } from "@/components/core/sanitizedMarkdown";
import {
  liveWorkflows,
  type LiveProject,
} from "@/controllers/API/live-workflows";
import {
  issueCodeMessage,
  issueError,
  projectIssues,
  type IssueProposal,
  type ProjectIssueSettings,
} from "@/controllers/API/project-issues";
import "./project-issues.css";
import IssueAssessment, { IssueAuditTrail } from "./issue-assessment";

const states: Record<string, string> = {
  DETECTED: "Đề xuất mới",
  STARTING: "Đang chuẩn bị",
  PLANNING: "Đang lập kế hoạch",
  PLAN_READY: "Kế hoạch đã sẵn sàng",
  RUNNING: "Đang thực hiện",
  SUCCEEDED: "Hoàn tất",
  FAILED: "Cần xử lý",
  UNCONFIRMED: "Cần đối soát",
  ERROR: "Cần kiểm tra",
  IGNORED: "Đã bỏ qua",
  CLOSED: "Issue đã đóng",
  FILTERED: "Ngoài bộ lọc",
  NEEDS_CONTEXT: "Chờ bạn bổ sung",
  NEEDS_SPEC: "Cần chốt đặc tả",
};
const timestamp = (value: string | null) =>
  value ? new Date(value).toLocaleString("vi-VN") : "Chưa quét";

function IssueSettings({
  settings,
  identity,
  onSaved,
}: {
  settings: ProjectIssueSettings;
  identity: string;
  onSaved: () => Promise<void>;
}) {
  const [draft, setDraft] = useState(settings),
    [labels, setLabels] = useState(settings.labels.join(", "));
  const [paths, setPaths] = useState(
    (settings.auto_allowed_paths || ["docs/**", "tests/**"]).join("\n"),
  );
  const [confirmed, setConfirmed] = useState(false),
    [busy, setBusy] = useState(false);
  const [error, setError] = useState(""),
    [saved, setSaved] = useState(false);
  const inFlight = useRef(false);
  const workflows = useQuery({
    queryKey: ["project-workflows", identity, settings.project_id],
    queryFn: () => liveWorkflows.workflows(settings.project_id),
    retry: false,
  });
  const needsConfirmation = draft.watch_issues && draft.mode !== "review";
  return (
    <form
      className="pi-settings"
      onSubmit={async (event) => {
        event.preventDefault();
        if (inFlight.current || (needsConfirmation && !confirmed)) return;
        inFlight.current = true;
        setBusy(true);
        setError("");
        setSaved(false);
        try {
          const value = await projectIssues.save(settings.project_id, {
            expected_revision: draft.revision,
            watch_issues: draft.watch_issues,
            mode: draft.mode,
            labels: labels
              .split(",")
              .map((x) => x.trim())
              .filter(Boolean),
            workflow_id: draft.workflow_id,
            auto_confirmed: confirmed,
            auto_allowed_paths: paths
              .split("\n")
              .map((x) => x.trim())
              .filter(Boolean),
            auto_max_runs_per_day: draft.auto_max_runs_per_day ?? 3,
            auto_max_active_minutes: draft.auto_max_active_minutes ?? 20,
          });
          setDraft(value);
          setLabels(value.labels.join(", "));
          setConfirmed(false);
          setSaved(true);
          await onSaved();
        } catch (e) {
          setError(issueError(e));
        } finally {
          inFlight.current = false;
          setBusy(false);
        }
      }}
    >
      <div className="pi-settings-heading">
        <Settings2 size={21} />
        <div>
          <h2>Tự động hóa từ issue</h2>
          <p>Cài đặt chỉ áp dụng cho project này.</p>
        </div>
      </div>
      <label className="pi-toggle">
        <input
          type="checkbox"
          checked={draft.watch_issues}
          onChange={(e) => {
            setDraft({ ...draft, watch_issues: e.target.checked });
            setSaved(false);
          }}
        />
        <span>
          <strong>Theo dõi issue Gitea</strong>
          <small>
            Tự kiểm tra issue mở mỗi {settings.poll_seconds} giây và tạo đề xuất
            trong PokeDev.
          </small>
        </span>
      </label>
      <fieldset className="pi-modes">
        <legend>Khi phát hiện issue phù hợp</legend>
        <label className={draft.mode === "review" ? "selected" : ""}>
          <input
            type="radio"
            name="issue-mode"
            value="review"
            checked={draft.mode === "review"}
            onChange={() => {
              setDraft({ ...draft, mode: "review" });
              setConfirmed(false);
              setSaved(false);
            }}
          />
          <span>
            <strong>Chờ tôi duyệt</strong>
            <small>
              Hiện đề xuất. Bạn chọn lập kế hoạch, xem rồi duyệt thực hiện.
            </small>
          </span>
        </label>
        <label className={draft.mode === "risk" ? "selected" : ""}>
          <input
            type="radio"
            name="issue-mode"
            value="risk"
            checked={draft.mode === "risk"}
            onChange={() => {
              setDraft({ ...draft, mode: "risk" });
              setConfirmed(false);
              setSaved(false);
            }}
          />
          <span>
            <strong>Tự làm việc ít rủi ro</strong>
            <small>
              Chỉ tự duyệt R0–R1 trong phạm vi file được chọn. Kế hoạch ngoài
              phạm vi hoặc rủi ro cao chờ bạn duyệt.
            </small>
          </span>
        </label>
        <label className={draft.mode === "auto" ? "selected" : ""}>
          <input
            type="radio"
            name="issue-mode"
            value="auto"
            checked={draft.mode === "auto"}
            onChange={() => {
              setDraft({ ...draft, mode: "auto" });
              setConfirmed(false);
              setSaved(false);
            }}
          />
          <span>
            <strong>Tự duyệt và thực hiện</strong>
            <small>
              Tự lập kế hoạch và thực hiện các issue rõ ràng, rủi ro thấp. R2–R3
              và lệnh tùy ý vẫn chờ bạn duyệt.
            </small>
          </span>
        </label>
      </fieldset>
      <div className="pi-risk-guide">
        <strong>Mức rủi ro được kiểm tra trên cả issue và kế hoạch</strong>
        <p>
          R0: chỉ đọc · R1: thay đổi nhỏ, có thể hoàn tác · R2: ảnh hưởng hệ
          thống dùng chung · R3: quyền, bí mật, dữ liệu nhạy cảm hoặc phát hành.
        </p>
        <p>
          Issue chưa rõ sẽ hỏi bạn trước khi lập kế hoạch. Các quyết định và câu
          trả lời đều được lưu lại.
        </p>
      </div>
      {draft.mode !== "review" && (
        <fieldset className="pi-auto-limits">
          <legend>Giới hạn tự động cho project</legend>
          {draft.mode === "risk" && (
            <label className="pi-field">
              File hoặc thư mục được tự sửa
              <textarea
                rows={3}
                value={paths}
                onChange={(e) => {
                  setPaths(e.target.value);
                  setSaved(false);
                }}
                placeholder={"docs/**\ntests/**\nsrc/components/Counter.tsx"}
              />
              <small>
                Mỗi dòng một file chính xác hoặc thư mục kết thúc bằng /**. File
                nhạy cảm vẫn cần người duyệt.
              </small>
            </label>
          )}
          <div className="pi-limit-fields">
            <label className="pi-field">
              Số lượt tự động tối đa trong 24 giờ
              <input
                type="number"
                min={1}
                max={50}
                value={draft.auto_max_runs_per_day ?? 3}
                onChange={(e) => {
                  setDraft({
                    ...draft,
                    auto_max_runs_per_day: Number(e.target.value),
                  });
                  setSaved(false);
                }}
              />
            </label>
            <label className="pi-field">
              Thời gian làm việc mỗi lượt (phút)
              <input
                type="number"
                min={5}
                max={60}
                value={draft.auto_max_active_minutes ?? 20}
                onChange={(e) => {
                  setDraft({
                    ...draft,
                    auto_max_active_minutes: Number(e.target.value),
                  });
                  setSaved(false);
                }}
              />
            </label>
          </div>
          <small>
            Tính tổng thời gian lập kế hoạch và thực hiện, không tính thời gian
            chờ bạn phản hồi. Lượt lỗi vẫn được tính vào số lượt đã nhận.
          </small>
        </fieldset>
      )}
      <label className="pi-field">
        Nhãn bắt buộc
        <input
          value={labels}
          onChange={(e) => {
            setLabels(e.target.value);
            setSaved(false);
          }}
          placeholder="Ví dụ: ready, pokedev"
        />
        <small>
          Phân cách bằng dấu phẩy. Issue phải có đủ các nhãn này. Để trống để
          nhận mọi issue mở.
        </small>
      </label>
      <label className="pi-field">
        Workflow thực hiện
        <select
          value={draft.workflow_id || ""}
          onChange={(e) => {
            setDraft({ ...draft, workflow_id: e.target.value || null });
            setSaved(false);
          }}
        >
          <option value="">AI lập kế hoạch theo issue</option>
          {workflows.data?.items
            .filter((w) => w.ready)
            .map((w) => (
              <option key={w.workflow_id} value={w.workflow_id}>
                {w.name} · v{w.revision}
              </option>
            ))}
        </select>
        <small>
          Có thể chọn workflow đã tạo trong canvas của project. Mỗi lượt giữ một
          bản chụp của workflow.
        </small>
      </label>
      {workflows.error && (
        <p role="alert">
          Chưa tải được danh sách workflow. {issueError(workflows.error)}
        </p>
      )}
      <div className="pi-note">
        Câu hỏi và quyền công cụ vẫn cần bạn phản hồi qua thông báo. Việc xuất
        bản kết quả giữ bước duyệt hiện có; chế độ này không tự đóng issue hay
        tự merge code.
      </div>
      {needsConfirmation && (
        <label className="pi-confirm">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
          />
          <span>
            Tôi cho phép project tự lập kế hoạch, duyệt và thực hiện các issue
            phù hợp với cài đặt trên.
          </span>
        </label>
      )}
      {error && (
        <div role="alert" className="lw-alert">
          {error}
          {error.includes("Cài đặt đã") && (
            <button
              type="button"
              onClick={() => {
                setDraft(settings);
                setLabels(settings.labels.join(", "));
                setPaths(
                  (settings.auto_allowed_paths || ["docs/**", "tests/**"]).join(
                    "\n",
                  ),
                );
                setConfirmed(false);
                setError("");
              }}
            >
              Tải cài đặt mới
            </button>
          )}
        </div>
      )}
      <footer>
        <span>
          {saved ? (
            <span role="status">
              <Check size={14} />
              Đã lưu cài đặt
            </span>
          ) : (
            `Cài đặt đã lưu · phiên bản ${settings.revision}`
          )}
        </span>
        <button
          className="lw-primary"
          disabled={busy || (needsConfirmation && !confirmed)}
          type="submit"
        >
          {busy && <LoaderCircle size={15} className="animate-spin" />}Lưu cài
          đặt
        </button>
      </footer>
    </form>
  );
}

export default function ProjectIssues({
  project,
  identity,
  section,
  selectedProposal,
  onOpenRun,
  onSettings,
}: {
  project?: LiveProject;
  identity: string;
  section: "issues" | "settings";
  selectedProposal?: string;
  onOpenRun: (run: string) => void;
  onSettings: () => void;
}) {
  const client = useQueryClient(),
    projectId = project?.project_id || "";
  const [filter, setFilter] = useState("active"),
    [error, setError] = useState(""),
    [busy, setBusy] = useState("");
  const inFlight = useRef(false);
  const query = useQuery({
    queryKey: ["project-issues", identity, projectId],
    queryFn: () => projectIssues.list(projectId),
    enabled: !!projectId,
    retry: false,
    refetchInterval: 5000,
  });
  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({
        queryKey: ["project-issues", identity, projectId],
      }),
      client.invalidateQueries({ queryKey: ["human-attention"] }),
      client.invalidateQueries({ queryKey: ["live-runs", identity] }),
      client.invalidateQueries({
        queryKey: ["issue-audit", identity, projectId],
      }),
    ]);
  };
  const perform = async (key: string, operation: () => Promise<unknown>) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(key);
    setError("");
    try {
      await operation();
    } catch (e) {
      setError(issueError(e));
    } finally {
      inFlight.current = false;
      setBusy("");
      await refresh();
    }
  };
  useEffect(() => {
    if (selectedProposal && query.data)
      document
        .getElementById(`issue-${selectedProposal}`)
        ?.scrollIntoView?.({ block: "center", behavior: "smooth" });
  }, [selectedProposal, query.data?.items.length]);
  if (!project)
    return (
      <div className="pi-empty">
        <CircleDot size={30} />
        <h2>Chọn project để tiếp tục</h2>
        <p>
          Mỗi project có danh sách issue và chế độ duyệt riêng. Chọn một project
          ở thanh bên.
        </p>
      </div>
    );
  if (query.isLoading)
    return (
      <div className="pi-empty" role="status">
        <LoaderCircle className="animate-spin" />
        Đang tải issue và cài đặt…
      </div>
    );
  if (!query.data)
    return (
      <div className="lw-alert" role="alert">
        {query.error ? issueError(query.error) : "Chưa tải được cài đặt."}
        <button onClick={() => void query.refetch()}>Thử lại</button>
      </div>
    );
  const { items, settings } = query.data;
  const visible = items.filter(
    (item) =>
      selectedProposal === item.proposal_id ||
      filter === "all" ||
      (filter === "ignored"
        ? item.state === "IGNORED"
        : !["IGNORED", "CLOSED", "FILTERED", "SUCCEEDED"].includes(item.state)),
  );
  return (
    <div className="pi-page">
      {section === "settings" ? (
        <IssueSettings
          key={projectId}
          settings={settings}
          identity={identity}
          onSaved={refresh}
        />
      ) : (
        <>
          <header className="pi-header">
            <div>
              <span className="lw-eyebrow">TỪ REPO ĐẾN CÔNG VIỆC</span>
              <h2>Issue Gitea</h2>
              <p>Issue mở được đưa về đây để bạn xem và bắt đầu công việc.</p>
            </div>
            <button
              onClick={() =>
                void perform("scan", async () => {
                  await projectIssues.scan(projectId);
                })
              }
              disabled={!!busy}
            >
              <RefreshCw
                size={15}
                className={busy === "scan" ? "animate-spin" : ""}
              />
              Quét ngay
            </button>
          </header>
          <div className="pi-policy">
            <span
              className={`pi-policy-dot ${settings.watch_issues ? "on" : ""}`}
            />
            <div>
              <strong>
                {!settings.watch_issues
                  ? "Đang tạm dừng theo dõi"
                  : settings.mode === "auto"
                    ? "Tự duyệt và thực hiện"
                    : settings.mode === "risk"
                      ? "Tự làm việc ít rủi ro"
                      : "Chờ bạn duyệt"}
              </strong>
              <small>
                {settings.labels.length
                  ? `Nhãn: ${settings.labels.join(", ")} · `
                  : ""}
                Lần kiểm tra gần nhất: {timestamp(settings.last_scan_at)}
              </small>
            </div>
            <button onClick={onSettings}>
              <Settings2 size={15} />
              Cài đặt
            </button>
          </div>
          {query.data.automation_usage && settings.mode !== "review" && (
            <p className="pi-usage">
              Đã nhận {query.data.automation_usage.used}/
              {query.data.automation_usage.limit} lượt tự động trong 24 giờ gần
              nhất
              {query.data.automation_usage.next_available_at
                ? ` · Có lượt mới sau ${new Date(query.data.automation_usage.next_available_at * 1000).toLocaleString("vi-VN")}`
                : ""}
              .
            </p>
          )}
          {(settings.scan_error || query.error) && (
            <div className="lw-alert" role="alert">
              Chưa cập nhật được từ Gitea.{" "}
              {settings.scan_error
                ? issueCodeMessage(settings.scan_error)
                : issueError(query.error)}{" "}
              Dữ liệu đã nhận vẫn được giữ.
            </div>
          )}
          {settings.scan_truncated && (
            <p className="pi-note">
              Lần quét có hơn 1.000 issue. Danh sách mới chỉ hiển thị 1.000
              issue nhận được; xem danh sách đầy đủ trên Gitea.
            </p>
          )}
          {error && (
            <div className="lw-alert" role="alert">
              {error}
            </div>
          )}
          <div className="pi-filters" role="group" aria-label="Lọc đề xuất">
            {[
              ["active", "Cần theo dõi"],
              ["all", "Tất cả"],
              ["ignored", "Đã bỏ qua"],
            ].map(([id, label]) => (
              <button
                key={id}
                aria-pressed={filter === id}
                onClick={() => setFilter(id)}
              >
                {label}
              </button>
            ))}
            <span>{visible.length} đề xuất</span>
          </div>
          <div className="pi-list">
            {visible.map((item: IssueProposal) => (
              <article
                id={`issue-${item.proposal_id}`}
                className={`pi-card ${selectedProposal === item.proposal_id ? "highlight" : ""}`}
                key={item.proposal_id}
              >
                <div className="pi-card-top">
                  <span className={`pi-state ${item.state.toLowerCase()}`}>
                    {states[item.state] || item.state}
                  </span>
                  <span>
                    #{item.issue.number} ·{" "}
                    {item.issue.author || project.repository}
                  </span>
                </div>
                <h3>
                  <a
                    href={item.issue.url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {item.issue.title}
                    <ExternalLink size={14} />
                  </a>
                </h3>
                {!!item.issue.labels.length && (
                  <div className="pi-labels">
                    {item.issue.labels.map((label) => (
                      <span key={label}>{label}</span>
                    ))}
                  </div>
                )}
                {item.issue.body && (
                  <details className="pi-body">
                    <summary>Nội dung issue</summary>
                    <SanitizedMarkdown
                      chatMessage={item.issue.body}
                      isEmpty={false}
                    />
                  </details>
                )}
                {item.review_reason && (
                  <p className="pi-note">
                    {issueCodeMessage(item.review_reason)}
                  </p>
                )}
                <IssueAssessment item={item} onChange={refresh} />
                {(item.error_code || item.run_error) && (
                  <p role="status" className="pi-note">
                    {issueCodeMessage(item.error_code || item.run_error || "")}
                  </p>
                )}
                <footer>
                  <span>
                    Bản issue {item.revision}
                    {item.run_state && item.state === "CLOSED"
                      ? ` · Công việc: ${states[item.run_state] || item.run_state}`
                      : ""}
                  </span>
                  <div>
                    {item.run_id ? (
                      <button
                        className="lw-primary"
                        onClick={() => onOpenRun(item.run_id!)}
                      >
                        Xem công việc
                        <ArrowRight size={14} />
                      </button>
                    ) : item.state === "IGNORED" ? (
                      <button
                        disabled={!!busy}
                        onClick={() =>
                          void perform(item.proposal_id, () =>
                            projectIssues.act(projectId, item, "restore"),
                          )
                        }
                      >
                        Đưa lại vào đề xuất
                      </button>
                    ) : [
                        "DETECTED",
                        "ERROR",
                        "NEEDS_CONTEXT",
                        "NEEDS_SPEC",
                      ].includes(item.state) ? (
                      <>
                        <button
                          disabled={!!busy}
                          onClick={() =>
                            void perform(item.proposal_id, () =>
                              projectIssues.act(projectId, item, "ignore"),
                            )
                          }
                        >
                          Bỏ qua
                        </button>
                        {(!item.triage || item.triage.action === "ready") && (
                          <button
                            className="lw-primary"
                            disabled={!!busy}
                            onClick={() =>
                              void perform(item.proposal_id, async () => {
                                const result = await projectIssues.act(
                                  projectId,
                                  item,
                                  "plan",
                                );
                                if (result.run_id) onOpenRun(result.run_id);
                              })
                            }
                          >
                            {busy === item.proposal_id && (
                              <LoaderCircle
                                size={14}
                                className="animate-spin"
                              />
                            )}
                            Lập kế hoạch
                            <ArrowRight size={14} />
                          </button>
                        )}
                      </>
                    ) : null}
                  </div>
                </footer>
                {item.triage && (
                  <IssueAuditTrail item={item} identity={identity} />
                )}
                {!!item.previous_runs.length && (
                  <details className="pi-history">
                    <summary>
                      Các lượt theo nội dung trước ({item.previous_runs.length})
                    </summary>
                    {item.previous_runs.map((r) => (
                      <button
                        key={r.run_id}
                        onClick={() => onOpenRun(r.run_id)}
                      >
                        Bản issue {r.revision} · {r.run_id.slice(0, 8)}
                        <ArrowRight size={12} />
                      </button>
                    ))}
                  </details>
                )}
              </article>
            ))}
          </div>
          {!visible.length && (
            <div className="pi-empty">
              <CircleDot size={30} />
              <h3>
                {items.length
                  ? "Không có đề xuất trong bộ lọc này"
                  : "Chưa có issue mở"}
              </h3>
              <p>
                {items.length
                  ? "Chọn Tất cả để xem các issue đã xử lý hoặc không khớp nhãn."
                  : "Khi repo có issue mới, PokeDev sẽ đưa đề xuất về đây. Bạn có thể mở Gitea để tạo issue."}
              </p>
              <a
                href={`${project.repository_url}/issues`}
                target="_blank"
                rel="noopener noreferrer"
              >
                Mở issue trên Gitea
                <ExternalLink size={14} />
              </a>
            </div>
          )}
        </>
      )}
    </div>
  );
}
