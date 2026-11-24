import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowUpRight,
  Clock3,
  Coins,
  GitBranch,
  RefreshCw,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { liveError, type LiveProject } from "@/controllers/API/live-workflows";
import {
  projectMetrics,
  type ModelRate,
  type ProjectMetricSummary,
} from "@/controllers/API/project-metrics";
import "./project-metrics.css";

export const metricDuration = (seconds: number | null) => {
  if (seconds === null) return "Chưa có dữ liệu";
  if (seconds < 60) return `${Math.round(seconds)} giây`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} phút`;
  return `${(seconds / 3600).toLocaleString("vi-VN", { maximumFractionDigits: 1 })} giờ`;
};
const count = (value: number | null) =>
  value === null ? "Chưa có dữ liệu" : value.toLocaleString("vi-VN");
const money = (value: number | null) =>
  value === null
    ? "Chưa có dữ liệu"
    : value.toLocaleString("en-US", {
        style: "currency",
        currency: "USD",
        minimumFractionDigits: 2,
        maximumFractionDigits: 6,
      });
const runStates: Record<string, string> = {
  SUCCEEDED: "Thành công",
  FAILED: "Thất bại",
  UNCONFIRMED: "Cần đối soát",
  PLAN_READY: "Chờ duyệt kế hoạch",
  RUNNING: "Đang chạy",
  PLANNING: "Đang lập kế hoạch",
};

export default function ProjectMetrics({
  identity,
  project,
}: {
  identity: string;
  project?: LiveProject;
}) {
  const [days, setDays] = useState(30),
    [error, setError] = useState(""),
    [refreshing, setRefreshing] = useState(false);
  const client = useQueryClient();
  const key = ["project-metrics", identity, project?.project_id, days];
  const query = useQuery({
    queryKey: key,
    queryFn: () => projectMetrics.read(project!.project_id, days),
    enabled: !!project,
    retry: false,
    refetchInterval: (q) => (q.state.data?.refresh.running ? 3000 : 30000),
  });
  if (!project)
    return (
      <div className="lw-empty">
        <Activity size={28} />
        <h2>Chọn một project để xem thống kê</h2>
        <p>Số liệu gắn với repo, workflow và lịch sử thực hiện của project.</p>
      </div>
    );
  const data = query.data;
  const refresh = async () => {
    if (refreshing) return;
    setRefreshing(true);
    setError("");
    try {
      await projectMetrics.refresh(project.project_id);
      await client.invalidateQueries({ queryKey: key });
    } catch (e) {
      setError(liveError(e));
    } finally {
      setRefreshing(false);
    }
  };
  return (
    <section className="pm-dashboard" aria-label="Thống kê project">
      <header className="pm-heading">
        <div>
          <span className="lw-eyebrow">TỪ YÊU CẦU ĐẾN KẾT QUẢ</span>
          <h2>Hiệu quả thực hiện</h2>
          <p>
            {project.name} · {project.repository}
          </p>
        </div>
        <div>
          <select
            aria-label="Khoảng thời gian thống kê"
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
          >
            <option value={7}>7 ngày gần đây</option>
            <option value={30}>30 ngày gần đây</option>
            <option value={90}>90 ngày gần đây</option>
          </select>
          <button
            disabled={refreshing || data?.refresh.running}
            onClick={() => void refresh()}
          >
            <RefreshCw
              size={14}
              className={
                refreshing || data?.refresh.running ? "animate-spin" : ""
              }
            />{" "}
            Cập nhật số liệu
          </button>
        </div>
      </header>
      {(error || query.error) && (
        <p className="lw-alert" role="alert">
          {error || liveError(query.error)}
        </p>
      )}
      {!data ? (
        <p role="status">Đang tổng hợp bằng chứng của project…</p>
      ) : (
        <>
          <div className="pm-cards">
            <article>
              <ShieldCheck size={18} />
              <span>Tỷ lệ thành công</span>
              <strong>
                {data.totals.success_rate === null
                  ? "Chưa có kết quả"
                  : `${Math.round(data.totals.success_rate * 100)}%`}
              </strong>
              <small>
                {data.totals.succeeded}/{data.totals.finished} lượt đã kết thúc
                · {data.totals.unconfirmed} cần đối soát
              </small>
            </article>
            <article>
              <Clock3 size={18} />
              <span>Thời gian làm việc trung bình</span>
              <strong>
                {metricDuration(data.totals.average_active_seconds)}
              </strong>
              <small>Loại thời gian chờ trả lời và chờ duyệt kế hoạch</small>
            </article>
            <article>
              <UserRound size={18} />
              <span>Chờ người dùng trả lời</span>
              <strong>{metricDuration(data.totals.human_wait_seconds)}</strong>
              <small>
                {data.totals.human_interventions} lần cần người tham gia
              </small>
            </article>
            <article>
              <GitBranch size={18} />
              <span>Lượt sửa đã thực hiện</span>
              <strong>{count(data.totals.repair_rounds)}</strong>
              <small>Đếm task sửa thực tế, gồm vòng duyệt trên canvas</small>
            </article>
            <article>
              <Activity size={18} />
              <span>Token Harness ghi nhận</span>
              <strong>{count(data.usage.tokens)}</strong>
              <small>
                {data.usage.measured_sessions}/{data.usage.sessions} session có
                số liệu · không đếm lại session tái sử dụng
              </small>
            </article>
            <article>
              <Coins size={18} />
              <span>Chi phí ước tính</span>
              <strong>{money(data.usage.cost_usd)}</strong>
              <small>
                {data.usage.priced_sessions}/{data.usage.sessions} session có
                đơn giá và số liệu
              </small>
            </article>
          </div>
          <div className="pm-source" role="status">
            <span className="pm-dot" />{" "}
            {data.refresh.running
              ? "Đang đọc số liệu session từ Harness…"
              : data.refresh.error_code
                ? "Chưa đọc được số liệu mới từ Harness. Số đã ghi nhận được giữ lại."
                : data.usage.sessions > 0 && data.usage.measured_sessions === 0
                  ? "Harness chưa trả số liệu cho các session cũ của project. Số liệu của lượt mới sẽ được ghi nhận khi có."
                  : "Token lấy từ session thực; chi phí là ước tính theo bảng giá bạn cung cấp."}
            {data.usage.last_measured_at && (
              <small>
                Ghi nhận gần nhất:{" "}
                {new Date(data.usage.last_measured_at).toLocaleString("vi-VN")}
              </small>
            )}
          </div>
          <div className="pm-notes">
            Thời gian làm việc được tính từ mốc thực hiện, hoặc đồng hồ hoạt
            động nếu có; lượt cần đối soát được để riêng. Thiếu token hoặc đơn
            giá sẽ hiện “Chưa có dữ liệu”. Tổng có thể chỉ bao gồm những session
            đã ghi nhận, không phải hóa đơn nhà cung cấp.
          </div>
          <div className="pm-lineage">
            <header>
              <div>
                <h3>Lịch sử & nguồn bằng chứng</h3>
                <p>
                  {data.totals.runs} lượt trong {days} ngày · mở lượt chạy để
                  xem diff, kiểm thử và quyết định duyệt
                </p>
              </div>
            </header>
            {!data.runs.length ? (
              <div className="lw-empty">
                Chưa có lượt chạy trong khoảng thời gian này.
              </div>
            ) : (
              <div className="pm-table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Yêu cầu · Issue</th>
                      <th>Workflow</th>
                      <th>Kết quả</th>
                      <th>Làm việc / chờ người</th>
                      <th>Sửa / kiểm chứng</th>
                      <th>Token / ước tính</th>
                      <th>Bằng chứng</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.runs.map((run) => (
                      <tr key={run.run_id}>
                        <td>
                          <strong>{run.title}</strong>
                          <small>
                            {new Date(run.created_at).toLocaleString("vi-VN")}
                          </small>
                          {run.issue && (
                            <Link
                              to={`/work?${new URLSearchParams({ project: project.project_id, view: "issues", issue: (run.issue as { proposal_id?: string }).proposal_id || "" })}`}
                            >
                              Issue #{run.issue.number}
                            </Link>
                          )}
                        </td>
                        <td>
                          {run.workflow?.name ? (
                            <Link
                              to={`/work?${new URLSearchParams({ project: project.project_id, view: "workflows", workflow: run.workflow.workflow_id || "" })}`}
                            >
                              {run.workflow.name}
                              <small>
                                Phiên bản v{run.workflow.revision} trong lượt
                                chạy
                              </small>
                            </Link>
                          ) : (
                            <span>AI lập kế hoạch</span>
                          )}
                        </td>
                        <td>
                          <span
                            className={`lw-state ${run.state === "SUCCEEDED" ? "done" : ""}`}
                          >
                            {runStates[run.state] || run.state}
                          </span>
                        </td>
                        <td>
                          {metricDuration(run.timing.active_seconds)}
                          <small>
                            Chờ người:{" "}
                            {metricDuration(run.timing.human_wait_seconds)}
                          </small>
                          <small>
                            Chờ duyệt kế hoạch:{" "}
                            {metricDuration(run.timing.approval_wait_seconds)}
                          </small>
                        </td>
                        <td>
                          {run.timing.repair_rounds} sửa
                          <small>
                            {run.timing.verification_attempts} lần kiểm chứng
                          </small>
                        </td>
                        <td>
                          {count(run.usage.tokens)}
                          <small>{money(run.usage.cost_usd)}</small>
                          <small>
                            {run.usage.measured_sessions}/{run.usage.sessions}{" "}
                            session đo được
                          </small>
                        </td>
                        <td>
                          <Link
                            className="pm-run-link"
                            to={`/work?${new URLSearchParams({ project: project.project_id, run: run.run_id })}`}
                          >
                            Xem lượt <ArrowUpRight size={13} />
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
          <Pricing
            key={`${project.project_id}:${data.pricing.revision}`}
            project={project.project_id}
            data={data}
            onSaved={() =>
              client.invalidateQueries({
                queryKey: ["project-metrics", identity, project.project_id],
              })
            }
          />
        </>
      )}
    </section>
  );
}

function Pricing({
  project,
  data,
  onSaved,
}: {
  project: string;
  data: ProjectMetricSummary;
  onSaved: () => Promise<unknown>;
}) {
  const [rates, setRates] = useState(
    data.pricing.rates.map((r) => ({
      ...r,
      input: String(r.input),
      cache_read: String(r.cache_read),
      cache_write: String(r.cache_write),
      output: String(r.output),
    })),
  );
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const valid = rates.every(
    (r) =>
      r.provider.trim() &&
      r.model.trim() &&
      r.source.trim() &&
      [r.input, r.cache_read, r.cache_write, r.output].every(
        (v) =>
          v.trim() &&
          Number.isFinite(Number(v)) &&
          Number(v) >= 0 &&
          Number(v) <= 10000,
      ),
  );
  return (
    <details className="pm-pricing">
      <summary>
        <Coins size={17} /> Bảng giá dùng để ước tính{" "}
        <small>
          {data.pricing.rates.length
            ? `${data.pricing.rates.length} model đã cấu hình`
            : "Chưa cấu hình"}
        </small>
      </summary>
      <p>
        Nhập giá USD cho mỗi 1 triệu token theo hợp đồng hoặc trang giá của bạn.
        Điền đủ bốn loại; chỉ nhập 0 khi loại đó được miễn phí. Cấu hình này
        không thay đổi model đang sử dụng.
      </p>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          if (busy || !valid) return;
          setBusy(true);
          setError("");
          try {
            await projectMetrics.savePricing(
              project,
              data.pricing.revision,
              rates.map((r) => ({
                ...r,
                input: Number(r.input),
                cache_read: Number(r.cache_read),
                cache_write: Number(r.cache_write),
                output: Number(r.output),
              })) as ModelRate[],
            );
            await onSaved();
          } catch (e) {
            setError(liveError(e));
          } finally {
            setBusy(false);
          }
        }}
      >
        {rates.map((rate, i) => (
          <fieldset key={i}>
            <legend>Model {i + 1}</legend>
            <div className="pm-price-row">
              {(
                [
                  ["provider", "Nhà cung cấp"],
                  ["model", "Tên model"],
                  ["source", "Nguồn / ngày áp dụng giá"],
                ] as const
              ).map(([key, label]) => (
                <label key={key}>
                  {label}
                  <input
                    required
                    value={rate[key]}
                    maxLength={300}
                    onChange={(e) =>
                      setRates((rows) =>
                        rows.map((r, j) =>
                          i === j ? { ...r, [key]: e.target.value } : r,
                        ),
                      )
                    }
                  />
                </label>
              ))}
            </div>
            <div className="pm-price-row">
              {(
                [
                  ["input", "Đầu vào thường"],
                  ["cache_read", "Đọc cache"],
                  ["cache_write", "Ghi cache"],
                  ["output", "Đầu ra"],
                ] as const
              ).map(([key, label]) => (
                <label key={key}>
                  {label}
                  <input
                    required
                    type="number"
                    step="any"
                    min={0}
                    max={10000}
                    value={rate[key]}
                    onChange={(e) =>
                      setRates((rows) =>
                        rows.map((r, j) =>
                          i === j ? { ...r, [key]: e.target.value } : r,
                        ),
                      )
                    }
                  />
                </label>
              ))}
              <button
                type="button"
                onClick={() =>
                  setRates((rows) => rows.filter((_, j) => j !== i))
                }
              >
                Xóa giá
              </button>
            </div>
          </fieldset>
        ))}
        <div className="pm-price-actions">
          <button
            type="button"
            disabled={rates.length >= 10 || busy}
            onClick={() => {
              const model = data.models.find(
                (m) =>
                  !rates.some(
                    (r) => r.provider === m.provider && r.model === m.model,
                  ),
              );
              setRates((rows) => [
                ...rows,
                {
                  provider: model?.provider || "",
                  model: model?.model || "",
                  source: "",
                  input: "",
                  cache_read: "",
                  cache_write: "",
                  output: "",
                },
              ]);
            }}
          >
            Thêm giá model
          </button>
          <button
            className="lw-primary"
            disabled={!valid || busy}
            type="submit"
          >
            {busy ? "Đang lưu…" : "Lưu bảng giá"}
          </button>
        </div>
        {error && (
          <p className="lw-alert" role="alert">
            {error}
          </p>
        )}
      </form>
    </details>
  );
}
