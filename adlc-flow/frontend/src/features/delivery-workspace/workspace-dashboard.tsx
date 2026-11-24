import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Clock3,
  FolderGit2,
  Inbox,
  Layers,
  ListFilter,
  LoaderCircle,
  RefreshCw,
  Search,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { liveError } from "@/controllers/API/live-workflows";
import {
  workspaceDashboard,
  type WorkspaceDashboardData,
} from "@/controllers/API/workspace-dashboard";
import {
  actionKinds,
  dashboardHistoryUrl,
  dashboardStates,
  waitingAge,
} from "./workspace-dashboard-model";
import "./workspace-dashboard.css";

const runLabels: Record<string, string> = {
  PLANNING: "Đang lập kế hoạch",
  PLAN_READY: "Chờ duyệt kế hoạch",
  RUNNING: "Đang thực hiện",
  SUCCEEDED: "Hoàn tất",
  FAILED: "Gặp lỗi",
  UNCONFIRMED: "Cần đối soát",
};
const roleLabels: Record<string, string> = {
  developer: "Developer",
  tester: "Tester",
  reviewer: "Reviewer",
  control: "Điều phối & kiểm chứng",
  other: "Khác",
};
const groups: Record<string, string[]> = {
  inputs: ["question", "permission", "gate"],
  approvals: ["plan", "advanced"],
  issues: ["issue"],
  recovery: ["recovery", "failed"],
  handover: ["handover"],
};
const localTime = (value: string) =>
  new Date(value).toLocaleTimeString("vi-VN", {
    timeZone: "Asia/Ho_Chi_Minh",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
const shortDate = (day: string) => `${day.slice(8, 10)}/${day.slice(5, 7)}`;

export default function WorkspaceDashboard({ identity }: { identity: string }) {
  const [days, setDays] = useState<7 | 28>(28),
    [project, setProject] = useState("");
  const options = useRef<WorkspaceDashboardData["projects"]>([]);
  const [group, setGroup] = useState("all"),
    [search, setSearch] = useState(""),
    [limit, setLimit] = useState(8);
  const query = useQuery({
    queryKey: ["workspace-dashboard", identity, project, days],
    queryFn: () => workspaceDashboard.read(days, project || undefined),
    enabled: identity !== "pending",
    retry: false,
    refetchInterval: 10000,
    staleTime: 3000,
  });
  const errorStatus = (query.error as { response?: { status?: number } } | null)
    ?.response?.status;
  const data =
    query.isError && [401, 403, 404].includes(errorStatus || 0)
      ? undefined
      : query.data;
  if (data) options.current = data.projects;
  useEffect(() => setLimit(8), [group, search, project]);
  const href = (status?: string, day?: string, current = false) =>
    dashboardHistoryUrl(
      project || undefined,
      current ? undefined : data?.range,
      status,
      day,
    );
  const pending = !data && query.isPending;
  const queue =
    data?.attention.filter(
      (item) =>
        (group === "all" || groups[group]?.includes(item.kind)) &&
        `${item.title} ${item.run_title} ${item.project_name} ${item.reason}`
          .toLowerCase()
          .includes(search.toLowerCase()),
    ) || [];
  const partial = !!data?.sources.errors.length;
  const total = data?.totals;
  const maxDay = Math.max(1, ...(data?.daily.map((d) => d.total) || []));
  const statusParts = data?.statuses.filter((s) => s.count > 0) || [];
  let angle = 0;
  const gradient = statusParts
    .map((s) => {
      const start = angle;
      angle += (s.count / (total?.runs || 1)) * 100;
      return `${dashboardStates[s.state]?.color || "#898b95"} ${start}% ${angle}%`;
    })
    .join(", ");
  const maxRole = Math.max(1, ...(data?.roles.map((r) => r.total) || []));
  const cards = [
    {
      label: `Lượt tạo trong ${days} ngày`,
      value: total?.runs,
      note: "Mỗi lượt PokeDev chỉ tính một lần",
      icon: Layers,
      to: href(),
    },
    {
      label: "Tỷ lệ thành công",
      value: total
        ? total.success_rate === null
          ? "—"
          : `${Math.round(total.success_rate * 100)}%`
        : undefined,
      note: total?.finished
        ? `${total.succeeded}/${total.finished} lượt đã kết thúc · không tính lượt đang chờ`
        : "Chưa có lượt thành công hoặc thất bại",
      icon: CheckCircle2,
      to: href("SUCCEEDED"),
    },
    {
      label: "Đang thực hiện",
      value: total?.active_now,
      note: "Hiện tại · gồm lập kế hoạch và chờ phản hồi",
      icon: Activity,
      to: href("active", undefined, true),
    },
    {
      label: "Cần bạn xử lý",
      value: total
        ? partial
          ? total.attention_now
            ? `≥ ${total.attention_now}`
            : "—"
          : total.attention_now
        : undefined,
      note: "Hàng chờ hiện tại · bao gồm cả lượt cũ",
      icon: Inbox,
      to: "#workspace-attention",
    },
  ];
  return (
    <section className="wd-dashboard" aria-label="Dashboard workspace">
      <header className="wd-heading">
        <div>
          <span className="lw-eyebrow">ĐIỀU HÀNH WORKSPACE</span>
          <h2>Tổng quan hoạt động</h2>
          <p>Theo dõi tiến độ và những việc cần bạn quyết định.</p>
        </div>
        <div className="wd-controls">
          <label className="wd-project">
            <FolderGit2 size={14} />
            <select
              aria-label="Project trên dashboard"
              value={project}
              onChange={(e) => setProject(e.target.value)}
            >
              <option value="">Tất cả project</option>
              {options.current.map((p) => (
                <option key={p.project_id} value={p.project_id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          <div className="wd-period" aria-label="Khoảng thời gian">
            {([7, 28] as const).map((value) => (
              <button
                key={value}
                aria-pressed={days === value}
                onClick={() => setDays(value)}
              >
                {value} ngày
              </button>
            ))}
          </div>
          <button
            className="wd-refresh"
            title="Cập nhật dashboard"
            aria-label="Cập nhật dashboard"
            disabled={query.isFetching}
            onClick={() => void query.refetch()}
          >
            <RefreshCw
              size={15}
              className={query.isFetching ? "animate-spin" : ""}
            />
          </button>
        </div>
      </header>
      <div className="wd-meta">
        <span>
          {total
            ? `${total.projects} project · ${total.workflows} workflow đã lưu`
            : "Đang đọc workspace…"}
        </span>
        <span>
          {data
            ? `Cập nhật ${localTime(data.generated_at)} · GMT+7${query.isFetching ? " · đang cập nhật…" : ""}`
            : ""}
        </span>
      </div>
      {query.isError && (
        <div className="wd-alert" role="alert">
          {data
            ? "Không thể cập nhật. Đang giữ số liệu ở lần đọc gần nhất. "
            : "Chưa đọc được dashboard. "}
          {liveError(query.error)}{" "}
          <button onClick={() => void query.refetch()}>Thử lại</button>
        </div>
      )}
      {partial && (
        <div className="wd-alert" role="status">
          Một số nguồn yêu cầu chờ chưa cập nhật được. Danh sách bên dưới là
          những việc đã xác nhận; chưa thể kết luận toàn bộ hàng chờ đã trống.
        </div>
      )}
      {!!total?.active_now && !data?.sources.native_connected && (
        <div className="wd-alert" role="status">
          Kết nối nhận yêu cầu trực tiếp từ Harness đang gián đoạn. Các yêu cầu
          đã lưu vẫn được giữ lại; kiểm tra trạng thái khi mở lượt chạy.
        </div>
      )}
      <div className="wd-stats">
        {cards.map(({ label, value, note, icon: Icon, to }, index) => (
          <Link
            className={`wd-stat wd-stat-${index}`}
            key={label}
            to={to}
            aria-label={`${label}: ${value ?? "đang tải"}`}
          >
            <div>
              <span className="wd-stat-icon">
                <Icon size={18} />
              </span>
              <ArrowRight size={14} />
            </div>
            <span>{label}</span>
            <strong>
              {value === undefined ? (
                <span className="wd-skeleton">—</span>
              ) : (
                value
              )}
            </strong>
            <small>{note}</small>
          </Link>
        ))}
      </div>
      {pending && (
        <p className="wd-loading" role="status">
          <LoaderCircle size={15} className="animate-spin" />
          Đang đọc số liệu và hàng chờ…
        </p>
      )}
      <div className="wd-analytics">
        <section className="wd-panel wd-activity">
          <div className="wd-panel-heading">
            <div>
              <h3>Nhịp độ công việc</h3>
              <p>
                Nhóm theo ngày tạo lượt ·{" "}
                {data
                  ? `${shortDate(data.range.from)} – ${shortDate(data.range.to)}`
                  : `${days} ngày`}
              </p>
            </div>
            <div className="wd-legend">
              <span>
                <i className="success" />
                Đã thành công
              </span>
              <span>
                <i />
                Các trạng thái khác
              </span>
            </div>
          </div>
          {data && total?.runs ? (
            <>
              <div className="wd-bars" aria-label="Hoạt động theo ngày">
                {data.daily.map((day) => (
                  <Link
                    key={day.date}
                    to={href(undefined, day.date)}
                    title={`${shortDate(day.date)}: ${day.total} lượt tạo, ${day.succeeded} đã thành công`}
                    aria-label={`${day.date}: ${day.total} lượt, ${day.succeeded} thành công`}
                  >
                    <div className="wd-bar-track">
                      <div
                        className="wd-bar"
                        style={{
                          height: `${Math.max(day.total ? 3 : 0, (day.total / maxDay) * 100)}%`,
                        }}
                      >
                        <span
                          style={{
                            height: `${day.total ? (day.succeeded / day.total) * 100 : 0}%`,
                          }}
                        />
                      </div>
                    </div>
                    <small>
                      {days === 7 ||
                      [0, 6, 13, 20, 27].includes(data.daily.indexOf(day))
                        ? shortDate(day.date)
                        : ""}
                    </small>
                  </Link>
                ))}
              </div>
              <p className="wd-chart-note">
                Bấm một ngày để mở lịch sử tương ứng. Màu xanh là số lượt đã
                thành công trong nhóm đó.
              </p>
            </>
          ) : (
            <div className="wd-empty">
              <Activity size={25} />
              <strong>
                {data
                  ? "Chưa có lượt tạo trong khoảng này"
                  : "Chưa có số liệu để hiển thị"}
              </strong>
              <p>
                {data
                  ? "Đổi khoảng thời gian hoặc xem toàn bộ lịch sử của workspace."
                  : "Dữ liệu sẽ xuất hiện khi đọc được workspace."}
              </p>
              {data && (
                <Link to={dashboardHistoryUrl(project || undefined)}>
                  Xem toàn bộ lịch sử <ArrowRight size={13} />
                </Link>
              )}
            </div>
          )}
        </section>
        <section className="wd-panel">
          <div className="wd-panel-heading">
            <div>
              <h3>Trạng thái lượt chạy</h3>
              <p>Cùng khoảng thời gian đang chọn</p>
            </div>
          </div>
          <div
            className="wd-ring"
            role="img"
            aria-label={`${total?.runs ?? "Chưa rõ"} lượt theo trạng thái`}
            style={{
              background: gradient
                ? `conic-gradient(${gradient})`
                : "var(--lw-line)",
            }}
          >
            <div>
              <strong>{total?.runs ?? "—"}</strong>
              <span>lượt PokeDev</span>
            </div>
          </div>
          <div className="wd-status-list">
            {data?.statuses.map((s) => (
              <Link key={s.state} to={href(dashboardStates[s.state].status)}>
                <i style={{ background: dashboardStates[s.state].color }} />
                <span>{dashboardStates[s.state].label}</span>
                <strong>{s.count}</strong>
              </Link>
            ))}
          </div>
        </section>
      </div>
      <div className="wd-work-grid">
        <section
          className="wd-panel wd-inbox"
          id="workspace-attention"
          aria-label="Cần bạn xử lý"
        >
          <div className="wd-panel-heading">
            <div>
              <h3>
                Cần bạn xử lý{" "}
                <span className="wd-count">{total?.attention_now ?? "—"}</span>
              </h3>
              <p>Hàng chờ hiện tại, không giới hạn theo ngày tạo lượt</p>
            </div>
            <Clock3 size={17} />
          </div>
          <div className="wd-inbox-controls">
            <label>
              <Search size={14} />
              <input
                aria-label="Tìm trong hàng chờ"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Tìm công việc hoặc project…"
              />
            </label>
            <label>
              <ListFilter size={14} />
              <select
                aria-label="Loại việc cần xử lý"
                value={group}
                onChange={(e) => setGroup(e.target.value)}
              >
                <option value="all">Tất cả loại việc</option>
                <option value="inputs">Câu hỏi & xin quyền</option>
                <option value="approvals">Kế hoạch & cổng duyệt</option>
                <option value="issues">Issue Gitea</option>
                <option value="recovery">Lỗi & đối soát</option>
                <option value="handover">Bàn giao PR</option>
              </select>
            </label>
          </div>
          <div className="wd-action-list">
            {queue.slice(0, limit).map((item) => (
              <article className="wd-action" key={item.id}>
                <span
                  className={`wd-action-mark ${item.priority === 0 ? "urgent" : ""}`}
                >
                  <Inbox size={16} />
                </span>
                <div className="wd-action-copy">
                  <div>
                    <span className="wd-type">
                      {actionKinds[item.kind] || item.kind}
                    </span>
                    <span className="wd-action-project">
                      {item.project_name}
                    </span>
                  </div>
                  <h4>{item.title}</h4>
                  <p>{item.run_title}</p>
                  {item.reason && <small>{item.reason}</small>}
                  <span
                    className="wd-age"
                    title={
                      item.since
                        ? new Date(item.since).toLocaleString("vi-VN", {
                            timeZone: "Asia/Ho_Chi_Minh",
                          })
                        : "Không có thời điểm bắt đầu chờ được xác nhận"
                    }
                  >
                    <Clock3 size={11} />
                    {waitingAge(item.since)}
                  </span>
                </div>
                <Link className="wd-action-link" to={item.href}>
                  {item.action_label}
                  <ArrowRight size={13} />
                </Link>
              </article>
            ))}
          </div>
          {!queue.length && (
            <div className="wd-empty">
              <Inbox size={27} />
              <strong>
                {!data
                  ? "Chưa đọc được hàng chờ"
                  : search || group !== "all"
                    ? "Không có việc khớp bộ lọc"
                    : partial
                      ? "Chưa xác nhận được toàn bộ hàng chờ"
                      : "Không có việc nào đang cần bạn xử lý"}
              </strong>
              <p>
                {search || group !== "all"
                  ? "Thử đổi loại việc hoặc từ khóa tìm kiếm."
                  : "Câu hỏi, yêu cầu duyệt, issue và việc cần đối soát sẽ xuất hiện tại đây."}
              </p>
            </div>
          )}
          {queue.length > limit && (
            <button
              className="wd-more"
              onClick={() => setLimit((value) => value + 8)}
            >
              Xem thêm {Math.min(8, queue.length - limit)} việc · đang hiện{" "}
              {limit}/{queue.length}
            </button>
          )}
        </section>
        <section className="wd-panel wd-roles">
          <div className="wd-panel-heading">
            <div>
              <h3>Công việc theo vai trò</h3>
              <p>Task thực thi trong các lượt đã chọn</p>
            </div>
          </div>
          {data?.roles.some((r) => r.total) ? (
            <>
              <div className="wd-role-legend">
                <span>Hoàn tất / Chạy / Chờ / Khác</span>
                <span>Tổng task</span>
              </div>
              {data.roles
                .filter((r) => r.total > 0)
                .map((role) => (
                  <div className="wd-role" key={role.role}>
                    <div>
                      <strong>{roleLabels[role.role]}</strong>
                      <span>
                        {role.done} / {role.active} / {role.waiting} /{" "}
                        {Math.max(
                          0,
                          role.total - role.done - role.active - role.waiting,
                        )}
                      </span>
                      <b>{role.total}</b>
                    </div>
                    <div className="wd-role-track">
                      <span
                        style={{ width: `${(role.total / maxRole) * 100}%` }}
                      />
                    </div>
                  </div>
                ))}
              <p className="wd-chart-note">
                Task mới được ghi nhận trong các lượt đã chọn. “Khác” gồm bước
                bị chặn, bỏ qua hoặc trạng thái khác.
              </p>
            </>
          ) : (
            <div className="wd-empty">
              <Layers size={25} />
              <strong>Chưa có task thực thi</strong>
              <p>
                Kế hoạch chưa chạy không được tính thành công việc agent đã thực
                hiện.
              </p>
            </div>
          )}
        </section>
      </div>
      <section className="wd-panel wd-recent">
        <div className="wd-panel-heading">
          <div>
            <h3>Lượt chạy gần đây</h3>
            <p>Trong khoảng thời gian và project đang chọn</p>
          </div>
          <Link to={href()}>
            Xem lịch sử <ArrowRight size={13} />
          </Link>
        </div>
        {data?.recent_runs.length ? (
          <div>
            {data.recent_runs.map((run) => (
              <Link key={run.run_id} to={run.href}>
                <span>
                  <strong>{run.title}</strong>
                  <small>
                    {run.project_name} ·{" "}
                    {new Date(run.created_at).toLocaleDateString("vi-VN", {
                      timeZone: "Asia/Ho_Chi_Minh",
                    })}
                  </small>
                </span>
                <span className={`lw-state ${run.state.toLowerCase()}`}>
                  {runLabels[run.state] || run.state}
                </span>
                <ArrowRight size={14} />
              </Link>
            ))}
          </div>
        ) : (
          <p className="wd-recent-empty">
            Chưa có lượt chạy trong phạm vi này.
          </p>
        )}
      </section>
      {!!data?.quality.invalid_timestamps && (
        <p className="wd-quality">
          {data.quality.invalid_timestamps} lượt thiếu mốc tạo hợp lệ không được
          đưa vào biểu đồ theo ngày.
        </p>
      )}
    </section>
  );
}
