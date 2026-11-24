import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Box,
  BrainCircuit,
  Check,
  ChevronDown,
  FlaskConical,
  LoaderCircle,
  Play,
  RefreshCw,
  X,
} from "lucide-react";
import { useContext, useRef, useState } from "react";
import {
  serviceError,
  serviceNames,
  type VaiCheck,
  type VaiChecks,
  type VaiService,
  vaiServices,
} from "@/controllers/API/vai-services";
import { AuthContext } from "@/contexts/authContext";
import "./vai-services.css";

const info = {
  sandbox: {
    name: "Sandbox",
    icon: Box,
    description: "Môi trường thực thi",
    action: "Ghi, đọc tệp và chạy Python trong phiên riêng.",
    accent: "blue",
  },
  memory: {
    name: "Memory",
    icon: BrainCircuit,
    description: "Bộ nhớ workflow",
    action: "Lưu rồi tìm lại ngữ cảnh mẫu trong phiên riêng.",
    accent: "violet",
  },
  testforge: {
    name: "TestForge",
    icon: FlaskConical,
    description: "Kiểm thử giao diện",
    action: "Kiểm tra dashboard TNQD bằng thao tác chỉ đọc.",
    accent: "amber",
  },
};
export const isActiveCheck = (row?: VaiCheck) =>
  !!row && ["RESERVED", "RUNNING", "UNCONFIRMED"].includes(row.state);
const string = (value: unknown) => (typeof value === "string" ? value : "");
const time = (value: string) =>
  new Date(value).toLocaleString("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
    day: "2-digit",
    month: "2-digit",
  });

export function ServicesView({
  data,
  loading,
  failed,
  busy,
  canWrite,
  error,
  onStart,
  onRefresh,
}: {
  data?: VaiChecks;
  loading: boolean;
  failed: boolean;
  busy: VaiService[];
  canWrite: boolean;
  error: string;
  onStart: (service: VaiService) => void;
  onRefresh: () => void;
}) {
  const ready = serviceNames.filter(
    (service) => data?.capabilities?.services[service]?.available,
  );
  const latest = serviceNames.map((service) =>
    data?.checks.find((row) => row.service === service),
  );
  const completed = latest.filter((row) => row?.state === "SUCCEEDED").length;
  return (
    <section className="dw-panel vs-panel" aria-label="Dịch vụ vAI">
      <header className="vs-heading">
        <div>
          <p className="dw-eyebrow">KẾT NỐI & THỰC THI</p>
          <h3>
            Dịch vụ vAI{" "}
            <span className="vs-count">{completed}/3 dịch vụ hoạt động</span>
          </h3>
          <p className="vs-subtitle">
            Thử trực tiếp các dịch vụ đang kết nối với PokeDev.
          </p>
        </div>
        <button
          className="vs-refresh"
          onClick={onRefresh}
          aria-label="Cập nhật trạng thái dịch vụ"
        >
          <RefreshCw size={15} /> Cập nhật
        </button>
      </header>
      {(error || failed || data?.error_code) && (
        <p className="vs-notice" role="alert">
          {error || serviceError(data?.error_code)}
        </p>
      )}
      <div className="vs-grid">
        {serviceNames.map((service) => {
          const item = info[service],
            Icon = item.icon;
          const row = data?.checks.find((check) => check.service === service);
          const active = isActiveCheck(row) || busy.includes(service);
          const available = ready.includes(service);
          const state = active
            ? row?.state === "UNCONFIRMED"
              ? "Chờ đối soát"
              : "Đang kiểm tra"
            : row?.state === "SUCCEEDED"
              ? "Đã có kết quả"
              : row?.state === "FAILED"
                ? "Cần kiểm tra"
                : loading
                  ? "Đang kết nối"
                  : available
                    ? "Sẵn sàng"
                    : "Chưa kết nối";
          const tone = active
            ? "running"
            : row?.state === "SUCCEEDED"
              ? "success"
              : row?.state === "FAILED"
                ? "failure"
                : "idle";
          return (
            <article
              key={service}
              className={`vs-card vs-${item.accent}`}
              aria-label={item.name}
            >
              <div className="vs-card-top">
                <span className="vs-icon">
                  <Icon size={22} />
                </span>
                <span className={`vs-status vs-${tone}`}>
                  {active ? (
                    <LoaderCircle size={12} className="vs-spin" />
                  ) : tone === "success" ? (
                    <Check size={12} />
                  ) : tone === "failure" ? (
                    <X size={12} />
                  ) : null}
                  {state}
                </span>
              </div>
              <h4>{item.name}</h4>
              <p className="vs-description">{item.description}</p>
              <p className="vs-message">
                {row?.error_code
                  ? serviceError(row.error_code)
                  : string(row?.summary?.message) || item.action}
              </p>
              <ServiceResult service={service} row={row} />
              <div className="vs-card-footer">
                <span>
                  {row ? time(row.updated_at) : "Chưa có lượt kiểm tra"}
                </span>
                <button
                  onClick={() => onStart(service)}
                  disabled={!canWrite || !available || active}
                  aria-label={`Thử ${item.name}`}
                >
                  {active ? (
                    <LoaderCircle size={13} className="vs-spin" />
                  ) : (
                    <Play size={12} />
                  )}{" "}
                  {row ? "Thử lại" : "Thử dịch vụ"}
                </button>
              </div>
              {row && (
                <details className="vs-details">
                  <summary>
                    Chi tiết kết quả <ChevronDown size={13} />
                  </summary>
                  <p>Mã lượt: {row.check_id}</p>
                  {row.job_id && <p>Job: {row.job_id}</p>}
                  {row.session_id && <p>Phiên: {row.session_id}</p>}
                  {row.dataset && <p>Dataset: {row.dataset}</p>}
                  {row.error && <pre>{row.error}</pre>}
                  {row.steps?.map((step, index) => (
                    <details key={index}>
                      <summary>
                        {step.tool} · {(step.duration_ms / 1000).toFixed(1)}s
                      </summary>
                      <pre>{JSON.stringify(step.result, null, 2)}</pre>
                    </details>
                  ))}
                </details>
              )}
            </article>
          );
        })}
      </div>
      {!!data?.checks.length && data.checks.length > 3 && (
        <details className="vs-history">
          <summary>Lịch sử kiểm tra · {data.checks.length} lượt</summary>
          {data.checks.slice(0, 12).map((row) => (
            <div key={row.check_id} className="vs-history-row">
              <strong>{info[row.service].name}</strong>
              <span>{time(row.created_at)}</span>
              <span>
                {isActiveCheck(row)
                  ? "Chưa kết thúc"
                  : row.state === "SUCCEEDED"
                    ? "Thành công"
                    : "Chưa đạt"}
              </span>
              <p>
                {string(row.summary?.message) || serviceError(row.error_code)}
              </p>
            </div>
          ))}
        </details>
      )}
      <footer className="vs-footer">
        <span>
          <span className={`vs-dot ${ready.length === 3 ? "is-ready" : ""}`} />
          {ready.length}/3 dịch vụ sẵn sàng
        </span>
        <p>
          Kết quả thử dịch vụ được lưu theo công việc và chu kỳ. Verify độc lập
          được theo dõi riêng.
        </p>
      </footer>
    </section>
  );
}

function ServiceResult({
  service,
  row,
}: {
  service: VaiService;
  row?: VaiCheck;
}) {
  const result = row?.summary;
  if (!result)
    return (
      <div className="vs-result-placeholder">
        {isActiveCheck(row)
          ? "Đang chờ phản hồi từ dịch vụ…"
          : "Kết quả sẽ hiển thị tại đây"}
      </div>
    );
  const report =
    result.report && typeof result.report === "object"
      ? (result.report as Record<string, unknown>)
      : null;
  const checks = Array.isArray(report?.checks)
    ? report.checks.filter((item) => item && typeof item === "object")
    : [];
  return (
    <div className="vs-result">
      {service === "sandbox" && (
        <>
          <div className="vs-metrics">
            <span>
              Chạy Python
              <strong>{result.exit_code === 0 ? "Exit 0" : "Chưa đạt"}</strong>
            </span>
            <span>
              Ghi / đọc tệp
              <strong>
                {result.file_round_trip === true
                  ? "Thành công"
                  : "Chưa xác nhận"}
              </strong>
            </span>
          </div>
          {!!result.stdout && (
            <pre className="vs-output">{string(result.stdout)}</pre>
          )}
        </>
      )}
      {service === "memory" && (
        <>
          <div className="vs-metrics">
            <span>
              Lưu & tìm lại
              <strong>
                {result.marker_found === true ? "Thành công" : "Chưa xác nhận"}
              </strong>
            </span>
            <span>
              Phạm vi
              <strong>
                {result.mode === "SESSION_CACHE"
                  ? "Phiên workflow"
                  : "Dataset riêng"}
              </strong>
            </span>
          </div>
          {!!result.context && (
            <p className="vs-context">{string(result.context).slice(0, 700)}</p>
          )}
          {result.mode === "SESSION_CACHE" && (
            <p className="vs-target">
              Bộ nhớ phiên đang hoạt động. Chưa bật lưu tri thức dài hạn.
            </p>
          )}
        </>
      )}
      {service === "testforge" && (
        <>
          <div className="vs-metrics">
            <span>
              Job kiểm thử
              <strong>
                {result.backend_status === "completed"
                  ? "Đã hoàn tất"
                  : string(result.backend_status) || "Chưa hoàn tất"}
              </strong>
            </span>
            <span>
              Kết luận ứng dụng
              <strong>
                {string(result.application_verdict) || "Xem báo cáo"}
              </strong>
            </span>
          </div>
          <p className="vs-target">Dashboard TNQD · Kiểm tra chỉ đọc</p>
          {typeof result.checks_total === "number" && (
            <p className="vs-target">
              {Number(result.checks_passed)}/{result.checks_total} kiểm tra đạt
              · Đăng nhập nhanh Dev
            </p>
          )}
          {Array.isArray(result.findings) &&
            result.findings.slice(0, 2).map((finding, index) => (
              <p className="vs-finding" key={index}>
                {string(finding?.label)}: {string(finding?.error).slice(0, 220)}
              </p>
            ))}
          {!!checks.length && (
            <details className="vs-native-checks">
              <summary>{checks.length} kiểm tra đã chạy</summary>
              <ul>
                {checks.map((check, index) => (
                  <li key={index}>
                    {check.status === "GROUNDED" ? (
                      <Check size={12} />
                    ) : (
                      <X size={12} />
                    )}
                    <span>{string(check.label)}</span>
                    <strong>
                      {check.status === "GROUNDED" ? "Đạt" : "Chưa đạt"}
                    </strong>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </div>
  );
}

export default function ServiceChecksPanel({
  deliveryId,
  cycleId,
  canWrite,
}: {
  deliveryId: string;
  cycleId?: string;
  canWrite: boolean;
}) {
  const owner = useContext(AuthContext).userData?.id;
  const client = useQueryClient();
  const key = [
    "delivery-vai-services",
    owner ?? "unknown",
    deliveryId,
    cycleId,
  ];
  const [busy, setBusy] = useState<VaiService[]>([]);
  const [error, setError] = useState("");
  const commands = useRef<Record<string, string>>({});
  const query = useQuery({
    queryKey: key,
    queryFn: () => vaiServices.list(deliveryId, cycleId!),
    enabled: !!cycleId,
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.checks.some(isActiveCheck) ? 2500 : false,
  });
  async function start(service: VaiService) {
    if (!cycleId || busy.includes(service)) return;
    const scope = `${deliveryId}:${cycleId}:${service}`;
    if (!commands.current[scope]) commands.current[scope] = crypto.randomUUID();
    const checkId = commands.current[scope];
    setError("");
    setBusy((old) => [...old, service]);
    try {
      await vaiServices.start(deliveryId, cycleId, service, checkId);
      delete commands.current[scope];
    } catch (failure) {
      setError(
        serviceError(
          (failure as { response?: { data?: { detail?: { code?: string } } } })
            ?.response?.data?.detail?.code,
        ),
      );
    } finally {
      setBusy((old) => old.filter((item) => item !== service));
      await client.invalidateQueries({ queryKey: key });
    }
  }
  return (
    <ServicesView
      data={query.data}
      loading={query.isPending}
      failed={query.isError}
      busy={busy}
      canWrite={canWrite && !!cycleId}
      error={error}
      onStart={start}
      onRefresh={() => {
        setError("");
        void query.refetch();
      }}
    />
  );
}
