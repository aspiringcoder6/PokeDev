import { useEffect, useState, type FormEvent } from "react";
import { api } from "@/controllers/API/api";
import { getBaseUrl } from "@/customization/utils/urls";

type LinkStatus = {
  enabled: boolean;
  username?: string;
  linked?: boolean;
  project_id?: string | null;
  linked_at?: string | null;
  conversations_enabled?: boolean;
};
const base = `${getBaseUrl()}adlc/intake/lark`;
export const larkLinkApi = {
  status: async (): Promise<LinkStatus> => (await api.get(`${base}/link`)).data,
  start: async (body: {
    password: string;
    project_id: string | null;
  }): Promise<{ command: string; expires_at: string }> =>
    (await api.post(`${base}/link`, body)).data,
  unlink: async (password: string) =>
    (await api.post(`${base}/unlink`, { password })).data,
};

export default function LarkLinkPanel({
  projects,
}: {
  projects: { id: string; name: string }[];
}) {
  const [status, setStatus] = useState<LinkStatus | null>(null);
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [project, setProject] = useState("");
  const [challenge, setChallenge] = useState<{
    command: string;
    expires_at: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let mounted = true;
    larkLinkApi
      .status()
      .then((value) => {
        if (mounted) setStatus(value);
      })
      .catch(() => {});
    return () => {
      mounted = false;
    };
  }, []);
  useEffect(() => {
    if (!challenge) return;
    const timer = window.setInterval(async () => {
      if (Date.now() >= new Date(challenge.expires_at).getTime()) {
        setChallenge(null);
        setError("Mã đã hết hạn. Bạn có thể tạo mã mới.");
        return;
      }
      try {
        const value = await larkLinkApi.status();
        setStatus(value);
        if (value.linked) {
          setChallenge(null);
          setOpen(false);
        }
      } catch {
        /* Keep the one-time code until its expiry or a confirmed link. */
      }
    }, 3000);
    return () => window.clearInterval(timer);
  }, [challenge]);
  if (!status?.enabled) return null;
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      if (status.linked) {
        await larkLinkApi.unlink(password);
        setStatus(await larkLinkApi.status());
        setOpen(false);
      } else {
        setChallenge(
          await larkLinkApi.start({ password, project_id: project || null }),
        );
      }
    } catch (e: any) {
      const code = e?.response?.data?.detail?.code;
      setError(
        code === "LARK_REAUTH_RATE_LIMIT"
          ? "Đã thử nhiều lần. Bạn đợi 5 phút rồi xác nhận lại."
          : code === "LARK_REAUTH_REQUIRED"
            ? "Mật khẩu PokeDev chưa đúng."
            : "Chưa hoàn tất thao tác. Bạn kiểm tra trạng thái liên kết trước khi thử lại.",
      );
    } finally {
      setPassword("");
      setBusy(false);
    }
  };
  return (
    <section className="intake-panel intake-lark" aria-label="Liên kết Lark">
      <div className="intake-panel-title">
        <div>
          <h2>Lark</h2>
          <p className="intake-muted">
            {status.linked ? "Đã liên kết" : "Chưa liên kết"} với tài khoản
            PokeDev <strong>{status.username}</strong>.
          </p>
        </div>
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            setOpen((value) => !value);
            setError("");
            setPassword("");
          }}
        >
          {open ? "Đóng" : status.linked ? "Gỡ liên kết" : "Liên kết Lark"}
        </button>
      </div>
      {status.linked && (
        <p className="intake-muted">
          Mỗi DM văn bản mới gửi bot PokeDev sẽ tạo một hồ sơ riêng.{" "}
          {status.conversations_enabled
            ? "Reply vào đúng tin hoặc biên nhận để bổ sung cho hồ sơ đó. Trong nhóm đã được cấu hình, hãy @bot khi gửi hoặc reply. Agent làm rõ sẽ được nối ở bước tiếp theo."
            : "Hội thoại làm rõ sẽ được bổ sung ở bước tiếp theo."}
        </p>
      )}
      {open && (
        <div>
          {error && (
            <p role="alert" className="intake-error">
              {error}
            </p>
          )}
          {challenge ? (
            <div role="status">
              <p>
                Gửi nguyên dòng này tới bot PokeDev trong DM để xác nhận liên
                kết với tài khoản <strong>{status.username}</strong>:
              </p>
              <pre className="intake-link-code">{challenge.command}</pre>
              <p className="intake-muted">
                Mã dùng một lần, hết hạn lúc{" "}
                {new Date(challenge.expires_at).toLocaleTimeString("vi-VN")}.
              </p>
            </div>
          ) : (
            <form onSubmit={submit} className="intake-link-form">
              <p>
                {status.linked
                  ? "Xác nhận mật khẩu PokeDev để dừng nhận yêu cầu qua liên kết này."
                  : "Xác nhận mật khẩu PokeDev để tạo mã liên kết. Tin nhắn Lark chỉ được gắn với tài khoản này sau khi bạn gửi mã cho bot."}
              </p>
              {!status.linked && (
                <label>
                  Dự án cho yêu cầu từ Lark
                  <select
                    value={project}
                    onChange={(event) => setProject(event.target.value)}
                    disabled={busy}
                  >
                    <option value="">Chưa gắn dự án</option>
                    {projects.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label>
                Mật khẩu PokeDev
                <input
                  type="password"
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  disabled={busy}
                />
              </label>
              <button type="submit" className="intake-primary" disabled={busy}>
                {busy
                  ? "Đang xác nhận…"
                  : status.linked
                    ? "Xác nhận gỡ liên kết"
                    : "Tạo mã liên kết"}
              </button>
            </form>
          )}
        </div>
      )}
    </section>
  );
}
