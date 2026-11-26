import { useEffect, useState } from "react";
import { api } from "@/controllers/API/api";
import { getBaseUrl } from "@/customization/utils/urls";

type Entry = {
  id: string;
  received_at: string;
  chat_type: "p2p" | "group";
  message_id: string;
  parent_id: string | null;
  root_id: string | null;
  thread_id: string | null;
  text: string;
  action: "CREATED" | "APPENDED";
};
export type ConversationPage = {
  enabled: boolean;
  items: Entry[];
  total: number;
};
export const conversationApi = {
  get: async (
    requestId: string,
    offset: number,
    signal: AbortSignal,
  ): Promise<ConversationPage> =>
    (
      await api.get(
        `${getBaseUrl()}adlc/intake/lark/requests/${requestId}/conversation`,
        {
          params: { limit: 50, offset },
          signal,
        },
      )
    ).data,
};

export default function LarkConversationPanel({
  requestId,
  closed,
}: {
  requestId: string;
  closed: boolean;
}) {
  const [page, setPage] = useState<ConversationPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  useEffect(() => {
    setOffset(0);
  }, [requestId]);
  useEffect(() => {
    const controller = new AbortController();
    setPage(null);
    setError("");
    setBusy(true);
    conversationApi
      .get(requestId, offset, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setPage(value);
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setError(
            "Chưa tải được nguồn hội thoại. Bạn kiểm tra quyền truy cập rồi thử lại.",
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy(false);
      });
    return () => controller.abort();
  }, [requestId, offset, refresh]);
  if (busy || (page && !page.enabled)) return null;
  return (
    <section className="intake-panel" aria-label="Nguồn hội thoại Lark">
      <div className="intake-panel-title">
        <div>
          <h2>Nguồn hội thoại</h2>
          <p className="intake-muted">{page?.total ?? 0} tin từ Lark</p>
        </div>
        <button type="button" onClick={() => setRefresh((value) => value + 1)}>
          Cập nhật tin
        </button>
      </div>
      <p className="intake-muted">
        Tin bổ sung là nguồn để làm rõ yêu cầu. Brief chỉ đổi khi bạn lưu thay
        đổi hoặc xác nhận ở bước tiếp theo.
      </p>
      {error && (
        <p role="alert" className="intake-error">
          {error}
        </p>
      )}
      {!closed && page && (
        <details className="intake-conversation-command">
          <summary>Chọn đúng hồ sơ khi gửi qua Lark</summary>
          <p>
            Reply vào tin hoặc biên nhận đã theo dõi; trong nhóm hãy @bot. Khi
            cần chọn rõ hồ sơ này, dùng:
          </p>
          <code>/intake {requestId} nội dung bổ sung</code>
          <p className="intake-muted">
            Nhóm phải được cấu hình đúng dự án và tài khoản Lark phải là chủ hồ
            sơ đã liên kết.
          </p>
        </details>
      )}
      {page && !page.items.length && <p>Chưa có tin từ Lark cho hồ sơ này.</p>}
      <ol className="intake-conversation-list">
        {page?.items.map((entry) => (
          <li key={entry.id}>
            <div className="intake-conversation-meta">
              <strong>
                {entry.action === "CREATED" ? "Yêu cầu gốc" : "Tin bổ sung"}
              </strong>
              <span>
                {entry.chat_type === "group" ? "Nhóm Lark" : "DM Lark"} ·{" "}
                {new Date(entry.received_at).toLocaleString("vi-VN")}
              </span>
            </div>
            <p className="intake-conversation-text">{entry.text}</p>
            <details>
              <summary>Thông tin nguồn</summary>
              <dl>
                <dt>Message</dt>
                <dd>{entry.message_id}</dd>
                {entry.parent_id && (
                  <>
                    <dt>Parent</dt>
                    <dd>{entry.parent_id}</dd>
                  </>
                )}
                {entry.root_id && (
                  <>
                    <dt>Root</dt>
                    <dd>{entry.root_id}</dd>
                  </>
                )}
                {entry.thread_id && (
                  <>
                    <dt>Thread</dt>
                    <dd>{entry.thread_id}</dd>
                  </>
                )}
              </dl>
            </details>
          </li>
        ))}
      </ol>
      {page && page.total > 50 && (
        <div className="intake-actions">
          <button
            type="button"
            disabled={offset + 50 >= page.total}
            onClick={() => setOffset((value) => value + 50)}
          >
            Tin trước
          </button>
          <button
            type="button"
            disabled={offset === 0}
            onClick={() => setOffset(0)}
          >
            Tin mới nhất
          </button>
        </div>
      )}
    </section>
  );
}
