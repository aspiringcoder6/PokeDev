import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { intakeError } from "@/controllers/API/document-intake";
import { slackNotificationConnection } from "@/controllers/API/workloop-integration";

export default function SlackNotificationSettings({
  identity,
}: {
  identity: string;
}) {
  const query = useQuery({
    queryKey: ["slack-notification-connection", identity],
    queryFn: slackNotificationConnection.read,
    retry: false,
  });
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const mutate = async (remove = false) => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      if (remove) await slackNotificationConnection.remove();
      else await slackNotificationConnection.save(token.trim());
      setToken("");
      await query.refetch();
    } catch (e) {
      setError(intakeError(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section
      className="wi-panel wi-slack-notifications"
      aria-label="Thông báo Slack chủ động"
    >
      <h2>Thông báo Slack chủ động</h2>
      <p>
        Nhận thông báo trong hội thoại gốc khi có kế hoạch cần duyệt, câu hỏi
        cần trả lời, lỗi hoặc kết quả hoàn tất. Bật riêng ở từng yêu cầu.
      </p>
      {query.data?.configured && (
        <p role="status">
          Đã kết nối bot <strong>{query.data.identity?.user}</strong> ·{" "}
          {query.data.identity?.team}
        </p>
      )}
      {query.isError && (
        <p role="alert">
          Chưa đọc được cấu hình thông báo. Kiểm tra kết nối rồi thử lại.
        </p>
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void mutate();
        }}
      >
        <label>
          Bot User OAuth Token
          <input
            type="password"
            aria-label="Mã bot Slack"
            autoComplete="new-password"
            placeholder="xoxb-…"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            disabled={busy}
          />
        </label>
        <p className="wi-hint">
          Mã được mã hóa ở máy chủ, không hiển thị lại. Dùng mã của bot hiện tại
          trong OAuth & Permissions; quyền gửi tin là chat:write.
        </p>
        <div className="wi-links">
          <button
            type="submit"
            disabled={busy || !token.trim().startsWith("xoxb-")}
          >
            {busy ? "Đang xử lý…" : "Kiểm tra và lưu kết nối"}
          </button>
          {query.data?.configured && (
            <button
              type="button"
              onClick={() => void mutate(true)}
              disabled={busy}
            >
              Ngắt gửi thông báo
            </button>
          )}
          <a
            href="https://api.slack.com/apps/A0CA54Q7FV3/oauth"
            target="_blank"
            rel="noopener noreferrer"
          >
            Mở cấu hình bot Slack ↗
          </a>
        </div>
      </form>
      {error && (
        <p role="alert" className="wi-notice">
          {error}
        </p>
      )}
    </section>
  );
}
