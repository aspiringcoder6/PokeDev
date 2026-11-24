import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ExternalLink,
  GitMerge,
  GitPullRequest,
  RefreshCw,
} from "lucide-react";
import { useContext, useRef, useState } from "react";
import { AuthContext } from "@/contexts/authContext";
import {
  liveCodeMessage,
  liveError,
  type LiveRun,
} from "@/controllers/API/live-workflows";
import { projectLifecycle } from "@/controllers/API/project-lifecycle";
import "./project-lifecycle.css";

function linkURL(value: string | undefined) {
  try {
    const url = new URL(value || "");
    return ["http:", "https:"].includes(url.protocol) &&
      !url.username &&
      !url.password
      ? url.href
      : undefined;
  } catch {
    return undefined;
  }
}

export function RunRecovery({
  run,
  busy,
  action,
}: {
  run: LiveRun;
  busy: string;
  action: (name: string, work: () => Promise<unknown>) => void;
}) {
  const intent = useRef<{ generation: number; command: string } | null>(null);
  const stopIntent = useRef<string | null>(null);
  const [stopConfirmed, setStopConfirmed] = useState(false);
  const status = run.recovery_status;
  if (!status?.available && !status?.stopping) return null;
  return (
    <section
      className="pl-recovery"
      id="run-recovery"
      tabIndex={-1}
      aria-label="Phục hồi lượt chạy"
    >
      <h3>Tiếp tục từ tiến trình đã lưu</h3>
      <p>
        Đã lưu {status.completed_tasks || 0} bước
        {status.saved_at
          ? ` lúc ${new Date(status.saved_at * 1000).toLocaleString("vi-VN")}`
          : ""}
        . PokeDev giữ phiên Agent, bộ test và cổng duyệt gắn với đúng source.
        Phiên chưa xác nhận nhận yêu cầu cần được đối soát.
      </p>
      {status.available && (
        <button
          className="lw-primary"
          disabled={!!busy}
          onClick={() => {
            const generation = status.generation || 0;
            if (intent.current?.generation !== generation)
              intent.current = { generation, command: crypto.randomUUID() };
            action("Đang phục hồi lượt chạy", () =>
              projectLifecycle.recover(
                run.run_id,
                intent.current!.command,
                generation,
                run.approved_plan_digest,
              ),
            );
          }}
        >
          <RefreshCw size={15} />
          Tiếp tục lượt này
        </button>
      )}
      <label>
        <input
          type="checkbox"
          checked={stopConfirmed}
          onChange={(event) => setStopConfirmed(event.target.checked)}
        />
        Dừng các phiên của lượt này và giữ kết quả để xem lại.
      </label>
      <button
        disabled={!!busy || !stopConfirmed}
        onClick={() => {
          stopIntent.current ||= crypto.randomUUID();
          action("Đang đối soát và dừng lượt gián đoạn", () =>
            projectLifecycle.stopRecovery(
              run.run_id,
              stopIntent.current!,
              status.generation || 0,
            ),
          );
        }}
      >
        {status.stopping ? "Đối soát dừng" : "Dừng và giữ kết quả"}
      </button>
    </section>
  );
}

export default function RunHandover({ run }: { run: LiveRun }) {
  const { userData } = useContext(AuthContext);
  const identity = userData?.id || "pending",
    client = useQueryClient();
  const [previewing, setPreviewing] = useState(false),
    [busy, setBusy] = useState("");
  const [error, setError] = useState(""),
    [confirmed, setConfirmed] = useState(false);
  const [acceptNoCI, setAcceptNoCI] = useState(false),
    [closeIssue, setCloseIssue] = useState(false);
  const inFlight = useRef(false),
    createIntent = useRef<string | null>(null),
    mergeIntent = useRef<string | null>(null);
  const handover = useQuery({
    queryKey: ["run-handover", identity, run.run_id],
    queryFn: () => projectLifecycle.handover(run.run_id),
    enabled: !!run.published,
    retry: false,
    refetchInterval: 20000,
  });
  const preview = useQuery({
    queryKey: ["handover-preview", identity, run.run_id],
    queryFn: () => projectLifecycle.handoverPreview(run.run_id),
    enabled: previewing,
    retry: false,
  });
  const value = handover.data || run.handover;
  const pull = value?.pull,
    readiness = value?.readiness;
  const perform = async (label: string, work: () => Promise<unknown>) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(label);
    setError("");
    try {
      await work();
      setConfirmed(false);
    } catch (e) {
      setError(liveError(e));
    } finally {
      inFlight.current = false;
      setBusy("");
      await client.invalidateQueries({
        queryKey: ["run-handover", identity, run.run_id],
      });
      await client.invalidateQueries({
        queryKey: ["live-run", identity, run.run_id],
      });
    }
  };
  if (run.legacy) return null;
  if (!run.published)
    return (
      <div className="pl-handover">
        <h3>Bàn giao qua Gitea</h3>
        <p className="pl-note">
          Khi lượt chạy đã kiểm thử thành công, xuất kết quả thành nhánh Gitea
          trong tab Thay đổi source. Sau đó bạn có thể xem nội dung và tạo PR ở
          đây.
        </p>
      </div>
    );
  return (
    <section className="pl-handover" aria-label="Bàn giao Gitea">
      <header>
        <div>
          <h3>
            {pull
              ? `Pull Request #${pull.number}`
              : "Tạo Pull Request từ kết quả đã kiểm thử"}
          </h3>
          <p className="pl-note">
            {run.published.branch} @{run.published.commit.slice(0, 12)}
            {pull ? ` → ${pull.base}` : ""}
          </p>
        </div>
        <button
          disabled={!!busy || handover.isFetching}
          onClick={() => void handover.refetch()}
        >
          <RefreshCw size={14} />
          Cập nhật Gitea
        </button>
      </header>
      {(error || handover.error || preview.error) && (
        <p className="lw-alert" role="alert">
          {error || liveError(handover.error || preview.error)}
        </p>
      )}
      {pull && linkURL(pull.url) && (
        <a href={linkURL(pull.url)} target="_blank" rel="noopener noreferrer">
          {pull.title} <ExternalLink size={14} />
        </a>
      )}
      {value?.state === "MERGED" ? (
        <>
          <p className="pl-badge ok">Đã merge trên Gitea</p>
          {pull?.merge_commit && (
            <p className="pl-note">Commit {pull.merge_commit}</p>
          )}
          {value.issue_update && (
            <p>
              {value.issue_update.state === "CLOSED"
                ? `Issue #${value.issue_update.number} đã đóng.`
                : `Code đã merge; chưa xác nhận đóng issue #${value.issue_update.number}.`}
            </p>
          )}
          {value.issue_update && value.issue_update.state !== "CLOSED" && (
            <button
              disabled={!!busy}
              onClick={() =>
                void perform("Đang kiểm tra issue", () =>
                  projectLifecycle.merge(
                    run.run_id,
                    run.published!.commit,
                    pull!.base_commit,
                    mergeIntent.current || crypto.randomUUID(),
                    true,
                    true,
                  ),
                )
              }
            >
              Kiểm tra và đóng lại issue
            </button>
          )}
        </>
      ) : pull ? (
        <>
          {readiness && (
            <>
              <p className="pl-note">
                Review hợp lệ: {readiness.approvals || 0}/
                {readiness.required_approvals || 0} bắt buộc.{" "}
                {readiness.checked_at
                  ? `Kiểm tra lúc ${new Date(readiness.checked_at).toLocaleTimeString("vi-VN")}.`
                  : ""}
              </p>
              {readiness.ci.length > 0 && (
                <table className="pl-ci">
                  <thead>
                    <tr>
                      <th>Kiểm tra CI</th>
                      <th>Trạng thái</th>
                    </tr>
                  </thead>
                  <tbody>
                    {readiness.ci.map((check) => (
                      <tr key={check.context}>
                        <td>
                          {linkURL(check.url) ? (
                            <a
                              href={linkURL(check.url)}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              {check.context}
                            </a>
                          ) : (
                            check.context
                          )}
                        </td>
                        <td>
                          {(
                            {
                              success: "Đạt",
                              pending: "Đang chạy",
                              failure: "Không đạt",
                              error: "Có lỗi",
                            } as Record<string, string>
                          )[check.state] || check.state}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {readiness.reasons.length > 0 && (
                <ul>
                  {readiness.reasons.map((reason) => (
                    <li key={reason}>{liveCodeMessage(reason)}</li>
                  ))}
                </ul>
              )}
              {readiness.no_ci && (
                <label>
                  <input
                    type="checkbox"
                    checked={acceptNoCI}
                    onChange={(e) => setAcceptNoCI(e.target.checked)}
                  />
                  Repo chưa có CI trên commit này. Tôi đã xem bằng chứng kiểm
                  thử Sandbox và chấp nhận merge.
                </label>
              )}
            </>
          )}
          {run.issue && (
            <label>
              <input
                type="checkbox"
                checked={closeIssue}
                onChange={(e) => setCloseIssue(e.target.checked)}
              />
              Đóng issue #{run.issue.number} sau khi xác nhận merge thành công.
            </label>
          )}
          <label>
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            Tôi đã xem thay đổi và đồng ý merge PR #{pull.number} vào{" "}
            {pull.base}.
          </label>
          {value?.merge_intent && (
            <p className="pl-note">
              Đã gửi yêu cầu merge. Dùng Cập nhật Gitea để đối soát; ứng dụng
              giữ yêu cầu cũ để tránh gửi lặp.
            </p>
          )}
          <button
            className="lw-primary"
            disabled={
              !!busy ||
              !!value?.merge_intent ||
              !confirmed ||
              !readiness?.can_merge ||
              (readiness.no_ci && !acceptNoCI)
            }
            onClick={() =>
              void perform("Đang merge trên Gitea", () => {
                mergeIntent.current ||= crypto.randomUUID();
                return projectLifecycle.merge(
                  run.run_id,
                  pull.head,
                  pull.base_commit,
                  mergeIntent.current,
                  acceptNoCI,
                  closeIssue,
                );
              })
            }
          >
            <GitMerge size={15} />
            Duyệt và merge
          </button>
        </>
      ) : (
        <>
          <p className="pl-note">
            PR sẽ chứa liên kết yêu cầu, phạm vi file và bằng chứng kiểm thử.
            Gitea tiếp tục áp dụng các quy tắc review và CI của nhánh đích.
          </p>
          {!previewing ? (
            <button onClick={() => setPreviewing(true)}>
              <GitPullRequest size={15} />
              Xem nội dung PR
            </button>
          ) : (
            <>
              <pre className="pl-pr-preview">
                {preview.data
                  ? `${preview.data.title}\n\n${preview.data.body}`
                  : "Đang chuẩn bị nội dung PR…"}
              </pre>
              <label>
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(e) => setConfirmed(e.target.checked)}
                />
                Tạo PR với nội dung này từ nhánh đã xuất.
              </label>
              <button
                className="lw-primary"
                disabled={!!busy || !confirmed || !preview.data}
                onClick={() =>
                  void perform("Đang tạo PR", () => {
                    createIntent.current ||= crypto.randomUUID();
                    return projectLifecycle.createPull(
                      run.run_id,
                      run.published!.commit,
                      createIntent.current,
                    );
                  })
                }
              >
                <GitPullRequest size={15} />
                Tạo Pull Request
              </button>
            </>
          )}
          {value?.state === "UNCONFIRMED" && (
            <p className="pl-note">
              Yêu cầu tạo PR đang cần đối soát. Nút tạo lại kiểm tra PR hiện có
              trước khi gửi thêm.
            </p>
          )}
        </>
      )}
      {busy && (
        <p className="pl-note" role="status">
          {busy}…
        </p>
      )}
    </section>
  );
}
