import { type FormEvent, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import {
  intakeApi,
  type IntakeContent,
  type IntakeHistory,
  type IntakeRequest,
} from "./api";
import "./intake.css";
import LarkLinkPanel from "./lark-link-panel";

const empty = (): IntakeContent => ({
  title: "",
  description: "",
  scope_in: [],
  scope_out: [],
  constraints: [],
  acceptance_criteria: [],
  assumptions: [],
});
const fields = [
  ["scope_in", "Phạm vi cần làm"],
  ["scope_out", "Chưa làm trong đợt này"],
  ["constraints", "Ràng buộc"],
  ["acceptance_criteria", "Tiêu chí nghiệm thu"],
  ["assumptions", "Giả định cần làm rõ"],
] as const;
const date = (value: string) => new Date(value).toLocaleString("vi-VN");
const errorMessage = (error: any) => {
  const code = error?.response?.data?.detail?.code;
  if (code === "INTAKE_DISABLED")
    return "Tiếp nhận yêu cầu chưa được bật trên máy chủ.";
  if (code === "INTAKE_REVISION_CONFLICT")
    return "Yêu cầu đã có phiên bản mới. Nội dung bạn đang sửa vẫn được giữ lại.";
  if (error?.response?.status === 404)
    return "Không tìm thấy yêu cầu hoặc bạn không còn quyền truy cập.";
  if (error?.response?.status === 422)
    return "Hãy kiểm tra nội dung: mỗi mục tối đa 50 dòng, mỗi dòng tối đa 2.000 ký tự.";
  if (!error?.response || error.response.status >= 500)
    return "Chưa xác nhận được kết quả. Hãy thử lại cùng thao tác để đối soát.";
  return "Không thể hoàn tất thao tác. Nội dung bạn đang nhập vẫn được giữ lại.";
};

export default function IntakePage() {
  const { requestId } = useParams();
  const navigate = useCustomNavigate();
  const [items, setItems] = useState<IntakeRequest[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [projects, setProjects] = useState<{ id: string; name: string }[]>([]);
  const [project, setProject] = useState("");
  const [current, setCurrent] = useState<IntakeRequest | null>(null);
  const [draft, setDraft] = useState(empty);
  const [history, setHistory] = useState<IntakeHistory[]>([]);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [uncertain, setUncertain] = useState(false);
  const [reload, setReload] = useState(0);
  const pending = useRef<{ key: string; command: string } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      intakeApi.list(offset, controller.signal),
      intakeApi.projects(controller.signal),
    ])
      .then(([list, catalog]) => {
        if (!controller.signal.aborted) {
          setItems(list.items);
          setTotal(list.total);
          setProjects(catalog);
        }
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(errorMessage(e));
      });
    return () => controller.abort();
  }, [offset, reload]);

  useEffect(() => {
    const controller = new AbortController();
    setError("");
    setNotice("");
    setDirty(false);
    setUncertain(false);
    pending.current = null;
    if (!requestId) {
      setCurrent(null);
      setDraft(empty());
      setProject("");
      setHistory([]);
      setLoading(false);
      return () => controller.abort();
    }
    setLoading(true);
    Promise.all([
      intakeApi.get(requestId, controller.signal),
      intakeApi.history(requestId, controller.signal),
    ])
      .then(([row, revisions]) => {
        if (controller.signal.aborted) return;
        setCurrent(row);
        setDraft(row.content);
        setProject(row.project_id ?? "");
        setHistory(revisions.items);
      })
      .catch((e) => {
        if (!controller.signal.aborted) {
          setCurrent(null);
          setError(errorMessage(e));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [requestId]);

  const choose = (id?: string) => {
    if (busy || uncertain) return;
    if (
      dirty &&
      !window.confirm("Bỏ phần nội dung chưa lưu để chuyển yêu cầu?")
    )
      return;
    if (!id && !requestId) {
      setDraft(empty());
      setProject("");
      setDirty(false);
      pending.current = null;
    } else navigate(id ? `/intake/${id}` : "/intake");
  };
  const change = (key: keyof IntakeContent, value: string | string[]) => {
    setDraft((old) => ({ ...old, [key]: value }));
    setDirty(true);
    setNotice("");
  };
  const apply = async (row: IntakeRequest) => {
    setCurrent(row);
    setDraft(row.content);
    setDirty(false);
    setUncertain(false);
    pending.current = null;
    setError("");
    setNotice(`Đã lưu phiên bản ${row.revision}.`);
    setReload((v) => v + 1);
    if (requestId !== row.id) navigate(`/intake/${row.id}`);
    else {
      // A replay receipt may predate edits made in another tab.
      const [latest, revisions] = await Promise.all([
        intakeApi.get(row.id),
        intakeApi.history(row.id),
      ]);
      setCurrent(latest);
      setDraft(latest.content);
      setHistory(revisions.items);
    }
  };
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (busy || loading || (requestId && !current)) return;
    const content = { ...draft };
    for (const [key] of fields)
      content[key] = content[key].map((s) => s.trim()).filter(Boolean);
    const key = JSON.stringify({
      id: current?.id,
      revision: current?.revision,
      project,
      content,
    });
    if (pending.current?.key !== key)
      pending.current = { key, command: crypto.randomUUID() };
    setBusy(true);
    setError("");
    let confirmed = false;
    try {
      const result = current
        ? await intakeApi.update(current.id, {
            command_id: pending.current.command,
            expected_revision: current.revision,
            content,
          })
        : await intakeApi.create({
            command_id: pending.current.command,
            project_id: project || null,
            content,
          });
      confirmed = true;
      await apply(result.request);
    } catch (e: any) {
      setError(
        confirmed
          ? "Đã lưu yêu cầu nhưng chưa tải lại được lịch sử. Bạn có thể mở lại hồ sơ."
          : errorMessage(e),
      );
      if (!confirmed) setUncertain(!e?.response || e.response.status >= 500);
    } finally {
      setBusy(false);
    }
  };
  const loadLatest = async () => {
    if (
      !current ||
      (dirty &&
        !window.confirm(
          "Tải bản mới sẽ thay phần nội dung chưa lưu. Bạn muốn tiếp tục?",
        ))
    )
      return;
    setBusy(true);
    try {
      await apply(await intakeApi.get(current.id));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const closed = current?.status === "CANCELLED";
  return (
    <main className="intake-page">
      <header className="intake-heading">
        <div>
          <p className="intake-eyebrow">POKEDEV / TIẾP NHẬN</p>
          <h1>Yêu cầu</h1>
          <p>Lưu ý tưởng, phạm vi và các thay đổi trước khi lập đặc tả.</p>
        </div>
        <button
          type="button"
          className="intake-primary"
          disabled={busy || uncertain}
          onClick={() => choose()}
        >
          Yêu cầu mới
        </button>
      </header>
      <LarkLinkPanel projects={projects} />
      <div className="intake-layout">
        <aside
          className="intake-panel intake-list"
          aria-label="Danh sách yêu cầu"
        >
          <div className="intake-panel-title">
            <h2>Hồ sơ của bạn</h2>
            <span>{total}</span>
          </div>
          {!items.length && (
            <p className="intake-muted">
              Yêu cầu mới sẽ xuất hiện ở đây sau khi lưu.
            </p>
          )}
          {items.map((row) => (
            <button
              type="button"
              key={row.id}
              disabled={busy || uncertain}
              className={`intake-list-item ${requestId === row.id ? "is-active" : ""}`}
              onClick={() => choose(row.id)}
            >
              <strong>{row.content.title}</strong>
              <span>
                {row.status === "CANCELLED" ? "Đã hủy" : "Mới nhận"} · Phiên bản{" "}
                {row.revision}
              </span>
              <small>{date(row.updated_at)}</small>
            </button>
          ))}
          {total > 50 && (
            <div className="intake-pagination">
              <button
                disabled={offset === 0}
                onClick={() => setOffset((v) => Math.max(0, v - 50))}
              >
                Trước
              </button>
              <span>{Math.floor(offset / 50) + 1}</span>
              <button
                disabled={offset + 50 >= total}
                onClick={() => setOffset((v) => v + 50)}
              >
                Sau
              </button>
            </div>
          )}
        </aside>
        <section className="intake-editor" aria-label="Nội dung yêu cầu">
          {error && (
            <div role="alert" className="intake-error">
              {error}
              {current && !uncertain && (
                <button type="button" disabled={busy} onClick={loadLatest}>
                  Tải bản mới
                </button>
              )}
            </div>
          )}
          {notice && (
            <p role="status" className="intake-success">
              {notice}
            </p>
          )}
          {loading ? (
            <p role="status">Đang tải hồ sơ…</p>
          ) : (
            (!requestId || current) && (
              <form className="intake-panel" onSubmit={save}>
                <div className="intake-panel-title">
                  <h2>{current ? "Nội dung yêu cầu" : "Yêu cầu mới"}</h2>
                  <span>
                    {current ? `Phiên bản ${current.revision}` : "Chưa lưu"}
                  </span>
                </div>
                <p className="intake-muted">
                  Chỉ bạn xem và chỉnh sửa hồ sơ này. Các giả định vẫn cần được
                  làm rõ.
                </p>
                <fieldset disabled={busy || uncertain || closed}>
                  <label>
                    Tiêu đề
                    <input
                      required
                      maxLength={200}
                      value={draft.title}
                      onChange={(e) => change("title", e.target.value)}
                      placeholder="Ví dụ: Xuất báo cáo doanh thu theo tháng"
                    />
                  </label>
                  <label>
                    Mô tả yêu cầu
                    <textarea
                      required
                      maxLength={20000}
                      rows={5}
                      value={draft.description}
                      onChange={(e) => change("description", e.target.value)}
                      placeholder="Bạn muốn đạt điều gì? Ai sẽ sử dụng và hiện đang gặp vấn đề gì?"
                    />
                  </label>
                  <label>
                    Dự án
                    <select
                      value={project}
                      disabled={!!current}
                      onChange={(e) => {
                        setProject(e.target.value);
                        setDirty(true);
                      }}
                    >
                      <option value="">Chưa gắn dự án</option>
                      {projects.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="intake-fields">
                    {fields.map(([key, label]) => (
                      <label key={key}>
                        {label}
                        <textarea
                          rows={3}
                          value={draft[key].join("\n")}
                          onChange={(e) =>
                            change(key, e.target.value.split("\n"))
                          }
                          placeholder="Mỗi ý trên một dòng"
                        />
                      </label>
                    ))}
                  </div>
                </fieldset>
                <div className="intake-actions">
                  <span>
                    {closed
                      ? "Hồ sơ đã hủy, lịch sử vẫn được giữ lại."
                      : dirty
                        ? "Có thay đổi chưa lưu"
                        : "Thông tin được lưu theo từng phiên bản."}
                  </span>
                  {!closed && (
                    <button
                      className="intake-primary"
                      type="submit"
                      disabled={busy || (!dirty && !!current)}
                    >
                      {busy
                        ? "Đang lưu…"
                        : uncertain
                          ? "Thử lại để đối soát"
                          : current
                            ? "Lưu thay đổi"
                            : "Lưu yêu cầu"}
                    </button>
                  )}
                </div>
              </form>
            )
          )}
          {!!history.length && (
            <section className="intake-panel" aria-label="Lịch sử yêu cầu">
              <h2>Lịch sử phiên bản</h2>
              <div className="intake-history">
                {history.map((entry) => (
                  <details key={entry.revision}>
                    <summary>
                      Phiên bản {entry.revision}{" "}
                      <span>{date(entry.created_at)}</span>
                    </summary>
                    <h3>{entry.snapshot.content.title}</h3>
                    <p>{entry.snapshot.content.description}</p>
                    {fields.map(
                      ([key, label]) =>
                        entry.snapshot.content[key].length > 0 && (
                          <div key={key}>
                            <strong>{label}</strong>
                            <ul>
                              {entry.snapshot.content[key].map((line, i) => (
                                <li key={i}>{line}</li>
                              ))}
                            </ul>
                          </div>
                        ),
                    )}
                  </details>
                ))}
              </div>
            </section>
          )}
        </section>
      </div>
    </main>
  );
}
