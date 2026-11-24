import { useQuery } from "@tanstack/react-query";
import {
  CheckCircle2,
  Copy,
  ExternalLink,
  MessageSquare,
  RefreshCw,
} from "lucide-react";
import { useContext, useState } from "react";
import { AuthContext } from "@/contexts/authContext";
import { liveWorkflows } from "@/controllers/API/live-workflows";
import { workloopIntegration } from "@/controllers/API/workloop-integration";
import "./workloop-integration.css";
import { documentUrl } from "@/controllers/API/document-intake";
import { useDocumentInbox } from "../delivery-workspace/document-intake-query";
import SlackNotificationSettings from "./slack-notification-settings";

export default function WorkloopIntegrationPage() {
  const { userData } = useContext(AuthContext);
  const identity = userData?.id || "pending";
  const canManage = !!userData?.is_superuser;
  const inbox = useDocumentInbox(undefined, canManage);
  const [projectId, setProjectId] = useState("");
  const [request, setRequest] = useState("");
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  const query = useQuery({
    queryKey: ["workloop-integration", identity],
    queryFn: workloopIntegration.read,
    enabled: canManage,
    retry: false,
    staleTime: 15000,
  });
  const projects = useQuery({
    queryKey: ["live-projects", identity],
    queryFn: liveWorkflows.projects,
    enabled: canManage,
    retry: false,
  });
  const status = (query.error as { response?: { status?: number } } | null)
    ?.response?.status;
  const data =
    query.isError && [401, 403, 404].includes(status || 0)
      ? undefined
      : query.data;
  const project = projects.data?.items.find(
    (item) => item.project_id === projectId,
  );
  const prompt = [
    project ? `Project: ${project.name}\nRepo: ${project.repository_url}` : "",
    request.trim() ||
      "Tôi muốn phát triển một tính năng mới. Hãy hỏi tôi để làm rõ mục tiêu, người sử dụng, phạm vi và tiêu chí nghiệm thu.",
    "Khi đủ thông tin, hãy soạn tài liệu yêu cầu và gửi link để tôi duyệt trước khi triển khai.",
  ]
    .filter(Boolean)
    .join("\n\n");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(prompt);
      setCopied(true);
      setCopyError(false);
    } catch {
      setCopied(false);
      setCopyError(true);
    }
  };
  return (
    <main className="wi-page">
      <header>
        <div>
          <span>PokeDev / KẾT NỐI</span>
          <h1>Slack & Workloop</h1>
          <p>
            Trao đổi với vai-orchestrator-agent và soạn tài liệu trước khi triển
            khai.
          </p>
        </div>
        {canManage && (
          <button
            onClick={() => void query.refetch()}
            disabled={query.isFetching}
          >
            <RefreshCw
              size={15}
              className={query.isFetching ? "animate-spin" : ""}
            />
            Kiểm tra kết nối
          </button>
        )}
      </header>
      {!canManage ? (
        <p role="status" className="wi-notice">
          Quản trị viên workspace quản lý kết nối Slack và Workloop.
        </p>
      ) : (
        <>
          {query.isPending && (
            <p role="status">Đang kiểm tra Workloop và MCP…</p>
          )}
          {query.isError && (
            <p className="wi-notice" role="alert">
              {data
                ? "Chưa cập nhật được. Đang giữ kết quả kiểm tra gần nhất."
                : "Chưa đọc được kết nối. Kiểm tra VPN rồi thử lại."}
            </p>
          )}
          {!!data?.errors.length && (
            <p className="wi-notice" role="status">
              Một số dịch vụ chưa kiểm tra được. Trạng thái chưa xác minh được
              hiển thị riêng bên dưới.
            </p>
          )}
          <section className="wi-statuses" aria-label="Trạng thái kết nối">
            <article>
              <span>Workloop</span>
              <strong className={data?.workloop.available ? "wi-good" : ""}>
                {!data
                  ? "Chưa xác minh"
                  : data.workloop.available
                    ? "Đã kết nối"
                    : "Chưa kết nối được"}
              </strong>
              <small>Dịch vụ đang dùng tại máy chủ VPN</small>
            </article>
            <article>
              <span>MCP</span>
              <strong className={data?.mcp.available ? "wi-good" : ""}>
                {!data
                  ? "Chưa xác minh"
                  : data.mcp.available
                    ? "Đã xác minh"
                    : "Chưa kết nối được"}
              </strong>
              <small>
                {data?.mcp.server?.name || "Kênh kết nối với Workloop"}
              </small>
            </article>
            <article>
              <span>Slack</span>
              <strong>
                {data?.slack.registered === true
                  ? "Đã có cấu hình"
                  : data?.slack.registered === false
                    ? "Chưa đăng ký"
                    : "Chưa xác minh"}
              </strong>
              <small>
                Phản hồi của bot cần được kiểm tra bằng hội thoại thực tế
              </small>
            </article>
          </section>
          <SlackNotificationSettings key={identity} identity={identity} />
          {data && (
            <p className="wi-updated">
              Kiểm tra lúc{" "}
              {new Date(data.checked_at).toLocaleString("vi-VN", {
                timeZone: "Asia/Ho_Chi_Minh",
              })}{" "}
              · GMT+7
            </p>
          )}
          <section className="wi-panel" aria-label="Nhận yêu cầu tự động">
            <h2>Nhận yêu cầu tự động trong PokeDev</h2>
            <p>
              {inbox.isError || inbox.data?.stale
                ? "Chưa đồng bộ được tài liệu. Kiểm tra VPN và Workloop rồi thử lại."
                : `Đã nhận ${inbox.data?.items.length || 0} tài liệu từ Workloop. Tài liệu mới tự xuất hiện trong hộp yêu cầu mỗi 10 giây khi nền tảng đang mở.`}
            </p>
            <p>
              Gắn tài liệu vào project, hoặc bật liên kết channel → project để
              các yêu cầu sau vào đúng nơi. Duyệt nội dung, chọn workflow và
              theo dõi thực hiện ngay trên web.
            </p>
            <div className="wi-links">
              <a className="wi-primary" href={documentUrl()}>
                Mở Yêu cầu & tài liệu <ExternalLink size={14} />
              </a>
            </div>
            {!!inbox.data?.checked_at && (
              <small>
                Lần nhận gần nhất:{" "}
                {new Date(inbox.data.checked_at).toLocaleString("vi-VN", {
                  timeZone: "Asia/Ho_Chi_Minh",
                })}{" "}
                · {inbox.data.rules.length} channel đã liên kết
              </small>
            )}
          </section>
          <div className="wi-grid">
            <section className="wi-panel" aria-label="Trò chuyện với bot">
              <MessageSquare size={25} />
              <h2>Bắt đầu trò chuyện</h2>
              <ol>
                <li>
                  Mở bot và chọn workspace <strong>adlcfactory</strong>.
                </li>
                <li>
                  Gửi DM cho <strong>vai-orchestrator-agent</strong>, hoặc mời
                  bot vào channel và @mention bot.
                </li>
                <li>
                  Trả lời các câu hỏi trong cùng một thread. Khi yêu cầu rõ, bot
                  soạn tài liệu và gửi link chờ bạn duyệt.
                </li>
              </ol>
              <div className="wi-links">
                {data?.slack.bot_url && (
                  <a
                    className="wi-primary"
                    href={data.slack.bot_url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Mở bot trên Slack <ExternalLink size={14} />
                  </a>
                )}
                {data && (
                  <a
                    href={data.workloop.integration_url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Kết nối trong Workloop <ExternalLink size={14} />
                  </a>
                )}
              </div>
              <p className="wi-hint">
                Bước này dùng bot Workloop hiện có để hỏi đáp và soạn tài liệu.
                Tài liệu được duyệt trước khi bạn triển khai.
              </p>
            </section>
            <section className="wi-panel" aria-label="Chuẩn bị yêu cầu cho bot">
              <h2>Chuẩn bị yêu cầu</h2>
              <p>Chọn project để đưa đúng tên và repo vào cuộc trao đổi.</p>
              <label>
                Project
                <select
                  value={projectId}
                  onChange={(event) => {
                    setProjectId(event.target.value);
                    setCopied(false);
                  }}
                >
                  <option value="">Trao đổi chung</option>
                  {projects.data?.items.map((item) => (
                    <option key={item.project_id} value={item.project_id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
              {projects.isError && (
                <p role="status">
                  Chưa đọc được project. Bạn vẫn có thể chuẩn bị yêu cầu chung.
                </p>
              )}
              <label>
                Ý tưởng hoặc tính năng
                <textarea
                  rows={4}
                  value={request}
                  onChange={(event) => {
                    setRequest(event.target.value);
                    setCopied(false);
                  }}
                  placeholder="Mục tiêu, người sử dụng, phạm vi và kết quả bạn mong muốn…"
                />
              </label>
              <details>
                <summary>Xem nội dung gửi bot</summary>
                <pre>{prompt}</pre>
              </details>
              <button className="wi-copy" onClick={() => void copy()}>
                {copied ? <CheckCircle2 size={14} /> : <Copy size={14} />}
                {copied ? "Đã sao chép" : "Sao chép yêu cầu"}
              </button>
              <p className="wi-hint">
                Sao chép rồi dán vào cuộc trò chuyện với bot.
              </p>
              {copyError && (
                <p role="alert">
                  Trình duyệt chưa cho phép sao chép. Mở “Xem nội dung gửi bot”
                  để chọn và sao chép thủ công.
                </p>
              )}
            </section>
          </div>
          {data && (
            <details className="wi-details">
              <summary>Thông tin kết nối</summary>
              <dl>
                <dt>Workloop</dt>
                <dd>{data.workloop.url}</dd>
                <dt>MCP</dt>
                <dd>{data.mcp.url}</dd>
                <dt>Slack App ID</dt>
                <dd>{data.slack.app_id || "Chưa cấu hình"}</dd>
              </dl>
              <p>
                Trạng thái cấu hình Slack và phản hồi thực tế của bot được kiểm
                tra riêng. Kết nối hiện có được giữ tại Workloop.
              </p>
            </details>
          )}
        </>
      )}
    </main>
  );
}
