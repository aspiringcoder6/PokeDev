import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  ChevronDown,
  Download,
  GitCompareArrows,
  LoaderCircle,
  Play,
  RefreshCw,
  Repeat2,
} from "lucide-react";
import { useContext, useRef, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { nativeLoops, type NativeLoops } from "@/controllers/API/product-loop";
import { AuthContext } from "@/contexts/authContext";
import "./product-loop.css";

const active = (state: string) =>
  ["RESERVED", "RUNNING", "UNCONFIRMED"].includes(state);
const labels: Record<string, string> = {
  RESERVED: "Đã nhận yêu cầu",
  RUNNING: "Đang cải tiến",
  UNCONFIRMED: "Cần đối soát",
  SUCCEEDED: "Bản sửa đạt kiểm thử",
  FAILED: "Lượt chạy đã dừng",
};
function message(code?: string | null) {
  const messages: Record<string, string> = {
    LOOP_SUCCESSOR_EXECUTION_NOT_ENABLED:
      "Chu kỳ tiếp theo chưa mở thực thi. Hãy chọn chu kỳ đã có đầu vào được duyệt.",
    LOOP_APPROVED_INPUT_REQUIRED:
      "Cần một kế hoạch đã duyệt, có source và bộ kiểm thử cố định.",
    LOOP_RUNTIME_UNAVAILABLE:
      "Goal hoặc Task Loop trên platform chưa sẵn sàng.",
    LOOP_BUDGET_EXHAUSTED:
      "Đã hết số lượt sửa; xem kết quả kiểm thử để xác định phần còn thiếu.",
    LOOP_SOURCE_CHANGED:
      "Đầu vào đã đổi. Hãy tải lại và xem xét trước khi chạy.",
  };
  return code
    ? messages[code] ||
        `Chưa xác nhận lượt chạy (${code}). Kết quả đã nhận vẫn được lưu.`
    : "";
}

export function NativeLoopView({
  data,
  busy,
  error,
  canRun,
  onPrepare,
  onRefresh,
  onDownload,
}: {
  data?: NativeLoops;
  busy: boolean;
  error: string;
  canRun: boolean;
  onPrepare: () => void;
  onRefresh: () => void;
  onDownload: (diff: string) => void;
}) {
  const row = data?.loops[0];
  const pending = !!row && active(row.state);
  const latest = row?.iterations?.at(-1);
  return (
    <section className="dw-card pl-panel" aria-label="Vòng cải tiến vAI">
      <div className="pl-heading">
        <div>
          <h3>
            <Repeat2 size={19} /> Vòng cải tiến sản phẩm
          </h3>
          <p>
            Goal giữ tiến độ · Task Loop quản lý nhiệm vụ · Sandbox chạy test
            thật
          </p>
        </div>
        <button
          type="button"
          className="vs-refresh"
          onClick={onRefresh}
          aria-label="Cập nhật vòng cải tiến"
        >
          <RefreshCw size={14} />
        </button>
      </div>
      <div className="pl-intro">
        <div>
          <span className="pl-kicker">NATIVE TASK LOOP</span>
          <h4>
            {row ? labels[row.state] : "Từ source đến bản sửa có kiểm chứng"}
          </h4>
          <p>
            Chạy một bản thử riêng từ đầu vào đã duyệt. Kết quả gồm file thay
            đổi, test và trạng thái Goal để bạn xem xét.
          </p>
        </div>
        <button
          type="button"
          className="pl-start"
          disabled={
            !canRun ||
            busy ||
            pending ||
            !data?.context ||
            !data.capabilities?.ready
          }
          onClick={onPrepare}
        >
          {busy || pending ? (
            <LoaderCircle size={15} className="animate-spin" />
          ) : (
            <Play size={15} />
          )}
          {pending ? "Đang theo dõi" : "Chuẩn bị chạy"}
        </button>
      </div>
      {data?.capabilities && (
        <p className="pl-model">
          Model: {data.capabilities.model.model} · Tối đa{" "}
          {data.context?.max_iterations ?? 3} lượt sửa · Dừng để xem xét bản
          thay đổi
        </p>
      )}
      {(error || data?.error_code) && (
        <p className="pl-error" role="alert">
          {error || message(data?.error_code)}
        </p>
      )}
      {row && (
        <div className="pl-results">
          <div className="pl-metrics">
            <div>
              <span>Trước khi sửa</span>
              <strong>
                {row.baseline
                  ? row.baseline.passed
                    ? "Test đạt"
                    : "Test chưa đạt"
                  : row.state === "RUNNING"
                    ? "Đang kiểm tra"
                    : "Chưa chạy"}
              </strong>
            </div>
            <div>
              <span>Sau khi sửa</span>
              <strong className={latest?.passed ? "pl-pass" : ""}>
                {latest
                  ? latest.passed
                    ? "Test đạt"
                    : latest.state === "CHECKING"
                      ? "Đang kiểm tra"
                      : "Cần sửa tiếp"
                  : "Chưa có bản sửa"}
              </strong>
            </div>
            <div>
              <span>File thay đổi</span>
              <strong>{row.changed_paths?.length ?? 0}</strong>
            </div>
            <div>
              <span>Lượt sửa</span>
              <strong>
                {row.iterations?.length ?? 0}/
                {data?.context?.max_iterations ?? 3}
              </strong>
            </div>
          </div>
          <div className="pl-receipts">
            <span>
              Task Loop <b>{row.contract?.status ?? "Chưa tạo"}</b>
            </span>
            <span>
              Goal{" "}
              <b>
                {row.goal_state?.phase === "complete"
                  ? "Hoàn tất"
                  : (row.goal_state?.phase ?? "Chưa tạo")}
              </b>
            </span>
            {row.memory && (
              <span>
                Memory{" "}
                <b>
                  {row.memory.recalled
                    ? "Đã lấy ngữ cảnh phiên"
                    : "Chưa lấy được ngữ cảnh"}
                </b>
              </span>
            )}
          </div>
          {row.error_code && (
            <p className="pl-error">{message(row.error_code)}</p>
          )}
          {row.iterations?.map((iteration) => (
            <details className="pl-iteration" key={iteration.number}>
              <summary>
                <span>
                  {iteration.passed ? (
                    <CheckCircle2 size={15} />
                  ) : (
                    <Repeat2 size={15} />
                  )}{" "}
                  Lượt {iteration.number} ·{" "}
                  {iteration.passed
                    ? "Đạt kiểm thử"
                    : iteration.state === "CHECKING"
                      ? "Đang kiểm tra"
                      : "Cần sửa tiếp"}
                </span>
                <ChevronDown size={14} />
              </summary>
              <p>
                {iteration.protected_intact
                  ? "Bộ test được giữ nguyên."
                  : "Chưa xác nhận bộ test nguyên vẹn."}
              </p>
              {iteration.checks?.map((check) => (
                <div key={check.check_id}>
                  <b>
                    {check.check_id} · Exit {check.exit_code}
                  </b>
                  <pre>
                    {check.stderr}
                    {check.stdout}
                  </pre>
                </div>
              ))}
            </details>
          ))}
          {!!row.diff && (
            <details className="pl-diff">
              <summary>
                <span>
                  <GitCompareArrows size={16} /> Bản thay đổi ·{" "}
                  {row.changed_paths?.join(", ")}
                </span>
                <ChevronDown size={14} />
              </summary>
              <pre>{row.diff}</pre>
              <button
                type="button"
                className="vs-refresh"
                onClick={() => onDownload(row.diff)}
              >
                <Download size={14} /> Tải patch
              </button>
            </details>
          )}
          {row.summary && (
            <details className="pl-iteration">
              <summary>
                <span>Báo cáo của agent</span>
                <ChevronDown size={14} />
              </summary>
              <p className="pl-summary">{row.summary}</p>
            </details>
          )}
          <p className="pl-note">
            Bản thử này được lưu riêng để nghiệm thu tích hợp vAI; không thay
            trạng thái workflow/chu kỳ hiện tại. Bàn giao sản phẩm vẫn cần xem
            xét bản sửa.
          </p>
        </div>
      )}
    </section>
  );
}

export default function ProductLoopPanel({
  deliveryId,
  cycleId,
  canWrite,
}: {
  deliveryId: string;
  cycleId?: string;
  canWrite: boolean;
}) {
  const owner = useContext(AuthContext).userData?.id;
  const [review, setReview] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const inFlight = useRef(false);
  const queryClient = useQueryClient();
  const key = ["native-product-loop", owner, deliveryId, cycleId];
  const query = useQuery({
    queryKey: key,
    enabled: !!owner && !!cycleId,
    queryFn: () => nativeLoops.list(deliveryId, cycleId!),
    refetchInterval: (q) =>
      q.state.data?.loops.some((row) => active(row.state)) ? 2500 : false,
  });
  const start = async () => {
    if (inFlight.current || !cycleId || !query.data?.context) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    setReview(false);
    try {
      await nativeLoops.start(
        deliveryId,
        cycleId,
        query.data.context.context_digest,
        crypto.randomUUID(),
      );
    } catch {
      setError(
        "Chưa xác nhận yêu cầu. Hệ thống sẽ đối soát lượt đã gửi, không tự gửi thêm.",
      );
    } finally {
      await queryClient.invalidateQueries({ queryKey: key });
      inFlight.current = false;
      setBusy(false);
    }
  };
  const download = (diff: string) => {
    const url = URL.createObjectURL(
      new Blob([diff], { type: "text/x-patch;charset=utf-8" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "vaiplatform-candidate.patch";
    a.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return (
    <>
      <NativeLoopView
        data={query.data}
        busy={busy}
        canRun={canWrite}
        error={
          error ||
          (query.isError
            ? "Chưa tải được vòng cải tiến. Hãy cập nhật trạng thái."
            : "")
        }
        onPrepare={() => setReview(true)}
        onRefresh={() => void query.refetch()}
        onDownload={download}
      />
      <Dialog open={review} onOpenChange={setReview}>
        <DialogContent className="pl-review">
          <DialogTitle>Chạy Task Loop trên vAI</DialogTitle>
          <DialogDescription>
            Agent được sửa trong phạm vi dưới đây; PokeDev chạy lại bộ test cố
            định cho từng đề xuất. Bạn nhận bản sửa để xem xét.
          </DialogDescription>
          <dl>
            <dt>Baseline</dt>
            <dd>{query.data?.context?.base_commit.slice(0, 12)}</dd>
            <dt>Được sửa</dt>
            <dd>{query.data?.context?.writable_paths.join(", ")}</dd>
            <dt>Test bảo vệ</dt>
            <dd>
              {query.data?.context?.checks.map((c) => c.test_path).join(", ")}
            </dd>
            <dt>Model</dt>
            <dd>{query.data?.capabilities?.model.model}</dd>
          </dl>
          <p>
            Tối đa {query.data?.context?.max_iterations} lượt sửa và 8 phút cho
            phần agent. Profile native hiện giới hạn số lượt sửa và thời gian;
            chưa áp trần token hoặc chi phí model.
          </p>
          <button
            type="button"
            className="pl-start"
            disabled={busy}
            onClick={() => void start()}
          >
            <Play size={15} /> Bắt đầu lượt chạy này
          </button>
        </DialogContent>
      </Dialog>
    </>
  );
}
