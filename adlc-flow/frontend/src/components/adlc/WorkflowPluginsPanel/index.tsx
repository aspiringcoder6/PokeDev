import axios from "axios";
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  workflowPluginApi,
  type WorkflowPluginRecord,
  type WorkflowPluginView,
} from "@/controllers/API/workflow-plugins";

const titles = {
  HEALTH: "Kết nối plugin",
  MEMORY_CONTEXT: "AgentMemory · Ngữ cảnh project",
  TESTFORGE_REPLAY: "TestForge · Replay",
};
const states: Record<string, string> = {
  SUCCEEDED: "Hoàn tất",
  FAILED: "Không thành công",
  DISPATCHING: "Đang gửi yêu cầu",
  RUNNING: "Đang chạy",
  UNKNOWN: "Chưa xác nhận kết quả",
  CANCEL_REQUESTED: "Đã dừng theo dõi tại workflow",
};
const errors: Record<string, string> = {
  WORKFLOW_PLUGIN_PROJECT_NOT_CONFIGURED:
    "Chưa gắn tenant/dataset hoặc session replay với workflow này.",
  WORKFLOW_PLUGIN_AUTH_REQUIRED:
    "Dịch vụ yêu cầu thông tin xác thực. Cần cấu hình credential tại backend.",
  WORKFLOW_PLUGIN_CONNECTION_LOST:
    "Mất kết nối tới dịch vụ. Kiểm tra VPN và trạng thái backend.",
  WORKFLOW_PLUGIN_MEMORY_SCOPE_UNSUPPORTED:
    "Backend memory chưa hỗ trợ đầy đủ phạm vi tenant và dataset của workflow.",
  WORKFLOW_PLUGIN_DISPATCH_UNCONFIRMED:
    "Chưa xác nhận job đã được tạo. Hệ thống giữ nguyên yêu cầu để tránh chạy trùng.",
  WORKFLOW_PLUGIN_JOB_STILL_RUNNING:
    "Đã hết thời gian theo dõi; job bên TestForge có thể vẫn đang chạy.",
  WORKFLOW_PLUGIN_QUERY_REQUIRED: "Node AgentMemory cần câu truy vấn ngữ cảnh.",
  WORKFLOW_PLUGIN_CONNECTION_CHANGED:
    "Kết nối đã thay đổi sau khi node bắt đầu; cần một lượt chạy mới.",
  WORKFLOW_PLUGIN_PREVIOUS_JOB_UNCONFIRMED:
    "Lần gọi trước chưa xác nhận đã kết thúc. Hệ thống chặn tạo job mới để tránh chạy trùng.",
};

export function pluginRecordFromOutput(
  value: unknown,
): WorkflowPluginRecord | undefined {
  if (!value || typeof value !== "object") return;
  const outputs = (value as { outputs?: unknown }).outputs;
  if (!outputs || typeof outputs !== "object") return;
  const record = (outputs as { plugin_result?: WorkflowPluginRecord })
    .plugin_result;
  return record &&
    typeof record.id === "string" &&
    typeof record.state === "string" &&
    ["HEALTH", "MEMORY_CONTEXT", "TESTFORGE_REPLAY"].includes(
      record.operation,
    ) &&
    record.verification_evidence === false
    ? record
    : undefined;
}

function message(error: unknown): string {
  const code = axios.isAxiosError(error)
    ? error.response?.data?.detail?.code
    : undefined;
  return (
    errors[code] ?? "Không tải được kết quả plugin. Bạn có thể thử tải lại."
  );
}

export function PluginResult({ record }: { record: WorkflowPluginRecord }) {
  return (
    <article
      className="rounded-lg border p-3"
      aria-label={titles[record.operation]}
    >
      <div className="flex flex-wrap justify-between gap-2">
        <strong>{titles[record.operation]}</strong>
        <span>{states[record.state] ?? record.state}</span>
      </div>
      {record.job_id && (
        <p className="break-all text-xs">Job TestForge: {record.job_id}</p>
      )}
      {record.error_code && (
        <p role="alert">{errors[record.error_code] ?? record.error_code}</p>
      )}
      {record.operation === "HEALTH" &&
        record.data &&
        Object.entries(record.data).map(([name, value]) => {
          const health = value as { status?: string; error_code?: string };
          return (
            <p key={name}>
              {name === "testforge" ? "TestForge" : "AgentMemory"}:{" "}
              {health.status === "ok"
                ? "Kết nối thành công"
                : (errors[health.error_code ?? ""] ?? "Chưa kết nối được")}
            </p>
          );
        })}
      {record.operation === "MEMORY_CONTEXT" &&
        typeof record.data?.context === "string" && (
          <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded bg-muted p-3 text-sm">
            {record.data.context ||
              "Không tìm thấy ngữ cảnh trong dataset đã chọn."}
          </pre>
        )}
      <details className="mt-2">
        <summary className="cursor-pointer text-xs">Xem dữ liệu trả về</summary>
        <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded bg-muted p-3 text-xs">
          {JSON.stringify(record.data, null, 2)}
        </pre>
      </details>
      {record.operation !== "HEALTH" && (
        <p className="mt-2 text-xs text-muted-foreground">
          Kết quả tham khảo từ dịch vụ; chưa phải phán quyết Verify độc lập.
        </p>
      )}
    </article>
  );
}

export default function WorkflowPluginsPanel({
  runId,
  taskResults = [],
}: {
  runId: string;
  taskResults?: WorkflowPluginRecord[];
}) {
  const [view, setView] = useState<WorkflowPluginView>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [health, setHealth] = useState<WorkflowPluginRecord>();
  const load = useCallback(async () => {
    try {
      setView(await workflowPluginApi.view(runId));
      setError("");
    } catch (err) {
      setError(message(err));
    }
  }, [runId]);
  useEffect(() => {
    setView(undefined);
    setHealth(undefined);
    void load();
  }, [load]);
  const check = async () => {
    setBusy(true);
    setError("");
    try {
      setHealth(await workflowPluginApi.health(runId, crypto.randomUUID()));
      await load();
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
    }
  };
  const records = new Map<string, WorkflowPluginRecord>();
  for (const record of [
    ...taskResults,
    ...(view?.records ?? []),
    ...(health ? [health] : []),
  ])
    records.set(record.id, record);
  return (
    <section
      aria-label="Plugin trong workflow"
      className="space-y-3 rounded-lg border p-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">AgentMemory & TestForge</h3>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => void load()}>
            Tải lại
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={busy || !view?.enabled}
            onClick={() => void check()}
          >
            {busy ? "Đang kiểm tra…" : "Kiểm tra kết nối"}
          </Button>
        </div>
      </div>
      <p className="text-sm text-muted-foreground">
        Thêm node AgentMemory hoặc TestForge vào workflow để tự chạy theo kế
        hoạch đã duyệt. Kết quả được lưu theo từng lượt chạy.
      </p>
      {view && !view.enabled && (
        <p>Tích hợp plugin chưa được bật tại backend.</p>
      )}
      {view?.configuration_error && (
        <p role="alert">Cấu hình kết nối project chưa hợp lệ.</p>
      )}
      {view?.enabled && !view.connections.length && (
        <p className="text-sm">
          Chưa gắn dataset AgentMemory và session TestForge với workflow này.
          Bước kiểm tra kết nối vẫn sử dụng được.
        </p>
      )}
      {view?.connections.map((connection) => (
        <div key={connection.connection} className="text-sm">
          <strong>Kết nối {connection.connection}</strong>
          <p>
            AgentMemory:{" "}
            {connection.memory_configured
              ? connection.memory_dataset
              : "Chưa cấu hình dataset"}
          </p>
          <p>
            TestForge:{" "}
            {connection.replay_configured
              ? `${connection.replay_session} · ${connection.replay_target}`
              : "Chưa cấu hình session và môi trường test"}
          </p>
        </div>
      ))}
      {error && <p role="alert">{error}</p>}
      {[...records.values()].map((record) => (
        <PluginResult key={record.id} record={record} />
      ))}
      {!records.size && (
        <p className="text-sm text-muted-foreground">
          Chưa có kết quả plugin trong lượt chạy này.
        </p>
      )}
    </section>
  );
}
