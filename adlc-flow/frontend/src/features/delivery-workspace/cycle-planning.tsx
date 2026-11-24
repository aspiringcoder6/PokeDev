import {
  Check,
  FileCheck2,
  GitBranch,
  LoaderCircle,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  deliveryApi,
  deliveryError,
  type Delivery,
  type CyclePlanningContext,
  type CyclePlanningOperation,
} from "@/controllers/API/delivery";
import { boardTasks, type BoardTask } from "./model";
import TaskPlanView from "./task-plan-view";
import TaskDetails from "./task-details";

const phaseLabel = (phase?: string) =>
  ({
    RESERVED: "Đã ghi nhận yêu cầu",
    RUNNING: "Harness đang lập kế hoạch",
    UNCONFIRMED: "Cần đối soát kết nối",
    FAILED: "Lượt lập kế hoạch chưa thành công",
    REVISION_REQUIRED: "Cần chỉnh lại đề xuất",
    VALIDATED: "Graph đã kiểm tra · chờ bạn duyệt",
    ACCEPTED: "Đã duyệt graph cho chu kỳ này",
  })[phase || ""] || "Chưa có đề xuất";

export default function CyclePlanning({
  row,
  disabled,
  onRefresh,
  onAdvanced,
}: {
  row: Delivery;
  disabled: boolean;
  onRefresh: () => void;
  onAdvanced: (path: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [review, setReview] = useState<{
    kind: "freeze" | "generate" | "accept";
    row: Delivery;
    operation?: CyclePlanningOperation;
  } | null>(null);
  const [context, setContext] = useState<CyclePlanningContext | null>(null);
  const [commit, setCommit] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [selected, setSelected] = useState<BoardTask | undefined>();
  const inFlight = useRef(false);
  const command = useRef<string | null>(null);
  const current = row.cycle!;
  const latest = current.planning_operations?.[0] as
    | CyclePlanningOperation
    | undefined;
  const matching =
    latest?.spec_digest === current.spec_digest ? latest : undefined;
  const frozen = current.spec.planning_ready === true;
  const pending =
    latest?.status === "RESERVED" || latest?.status === "UNCONFIRMED";
  const locked = disabled || busy || !row.permissions.write;
  const accepted = matching?.phase === "ACCEPTED";
  const preview = accepted ? row.plan : (matching?.preview_plan ?? null);
  const previewRow: Delivery = {
    ...row,
    plan: preview,
    plan_id: preview?.execution_plan_id ?? null,
    plan_digest: matching?.plan_digest ?? null,
    plan_approved: accepted,
    run: null,
  };
  const tasks = boardTasks(previewRow);
  const scope = `${current.id}:${current.spec_digest}:${matching?.id}:${matching?.plan_digest}`;
  useEffect(() => {
    setReview(null);
    setContext(null);
    setSelected(undefined);
    setError("");
  }, [current.id]);
  useEffect(() => setSelected(undefined), [scope]);
  const stale =
    !!review &&
    (review.row.id !== row.id ||
      review.row.cycle?.id !== current.id ||
      review.row.revision !== row.revision ||
      review.row.cycle?.spec_digest !== current.spec_digest ||
      (review.kind === "accept" && review.operation?.id !== latest?.id));

  const perform = async (action: () => Promise<unknown>) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      await action();
      onRefresh();
    } catch (cause) {
      setError(deliveryError(cause));
      throw cause;
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };
  // Observe an already reserved generation only. This endpoint never submits a new prompt.
  useEffect(() => {
    if (latest?.status !== "RESERVED" || locked || review || error) return;
    const timer = window.setTimeout(() => {
      void perform(() => deliveryApi.reconcilePlanning(row, latest.id)).catch(
        () => {},
      );
    }, 3500);
    return () => window.clearTimeout(timer);
  }, [latest?.id, latest?.status, latest?.updated_at, locked, review, error]);
  const open = async (kind: "freeze" | "generate" | "accept") => {
    command.current = null;
    setConfirmed(false);
    if (kind === "freeze") {
      try {
        await perform(async () => {
          const value = await deliveryApi.planningContext(row);
          setContext(value);
          setCommit(value.base_commit);
          setReview({ kind, row });
        });
      } catch {
        /* explicit error; never invent repository or criteria */
      }
    } else setReview({ kind, row, operation: matching });
  };
  return (
    <section
      className="dw-panel dw-cycle-planning"
      aria-label="Kế hoạch chi tiết qua Harness"
    >
      <div className="dw-planning-heading">
        <div>
          <span className="dw-eyebrow">KẾ HOẠCH · CHU KỲ {current.number}</span>
          <h2>{phaseLabel(matching?.phase)}</h2>
          <p className="dw-muted">
            Chốt đầu vào → Harness đề xuất → kiểm tra graph → bạn duyệt.
          </p>
        </div>
        <span className="dw-small-tag">
          <GitBranch size={14} /> Workflow giữ nguyên
        </span>
      </div>
      <ol className="dw-planning-steps" aria-label="Trạng thái lập kế hoạch">
        <li className={frozen ? "is-done" : ""}>
          <span>1</span> Đầu vào {frozen ? "đã chốt" : "cần chốt"}
        </li>
        <li
          className={
            matching?.phase === "VALIDATED" || accepted ? "is-done" : ""
          }
        >
          <span>2</span> Graph chi tiết
        </li>
        <li className={accepted ? "is-done" : ""}>
          <span>3</span> Phê duyệt riêng
        </li>
      </ol>
      {error && (
        <p role="alert" className="dw-error">
          {error}
        </p>
      )}
      {pending && (
        <div role="status" className="dw-notice">
          <LoaderCircle
            className={latest?.status === "RESERVED" ? "dw-spin" : ""}
            size={17}
          />
          {phaseLabel(latest?.phase)}. Không tự gửi thêm lượt gọi AI.
        </div>
      )}
      <div className="dw-planning-facts">
        <span>
          <FileCheck2 size={15} /> {current.spec.acceptance_criteria.length}{" "}
          tiêu chí cố định
        </span>
        <span>
          {tasks.length} task trong graph {accepted ? "đã duyệt" : "đề xuất"}
        </span>
        <span>
          {current.planning_operations?.length ?? 0}/3 lượt lập kế hoạch
        </span>
      </div>
      {!!matching?.validation_errors?.length && (
        <details open className="dw-planning-findings">
          <summary>
            Cần xử lý {matching.validation_errors.length} vấn đề trước khi duyệt
          </summary>
          <ul>
            {matching.validation_errors.map((item, index) => (
              <li key={`${item.code}:${index}`}>{item.message}</li>
            ))}
          </ul>
        </details>
      )}
      {matching?.diff && (
        <p className="dw-muted dw-planning-diff" aria-label="Thay đổi graph">
          +{matching.diff.added.length} mới · {matching.diff.changed.length}{" "}
          thay đổi · {matching.diff.removed.length} bỏ ·{" "}
          {matching.diff.unchanged.length} giữ nguyên
        </p>
      )}
      {preview && (
        <TaskPlanView
          key={scope}
          row={previewRow}
          tasks={tasks}
          selectedTaskId={selected?.id}
          onSelect={setSelected}
        />
      )}
      {!preview && !pending && (
        <div className="dw-planning-empty">
          <GitBranch size={25} />
          <p>
            {frozen
              ? "Đầu vào đã chốt. Sẵn sàng tạo danh sách task và các nhánh phụ thuộc."
              : "Chọn commit nền và xem phạm vi, tiêu chí trước khi lập kế hoạch."}
          </p>
        </div>
      )}
      <div className="dw-panel-footer">
        <span>Chưa khởi chạy task, commit hoặc push.</span>
        <div className="dw-cycle-actions">
          {!accepted && !pending && (
            <button
              type="button"
              className="dw-button"
              disabled={locked}
              onClick={() => void open("freeze")}
            >
              {frozen ? "Xem / chốt lại đầu vào" : "Chốt đầu vào"}
            </button>
          )}
          {matching?.phase === "VALIDATED" && !accepted && !pending && (
            <button
              type="button"
              className="dw-button"
              disabled={
                locked || (current.planning_operations?.length ?? 0) >= 3
              }
              onClick={() => void open("generate")}
            >
              <Sparkles size={14} /> Đề xuất khác
            </button>
          )}
          {pending ? (
            <button
              type="button"
              className="dw-button"
              disabled={locked}
              onClick={() =>
                void perform(() =>
                  deliveryApi.reconcilePlanning(row, latest!.id),
                ).catch(() => {})
              }
            >
              <RefreshCw size={14} /> Đối soát trạng thái
            </button>
          ) : matching?.phase === "VALIDATED" ? (
            <button
              type="button"
              className="dw-button dw-primary"
              disabled={locked}
              onClick={() => void open("accept")}
            >
              <Check size={14} /> Duyệt graph này
            </button>
          ) : (
            !accepted && (
              <button
                type="button"
                className="dw-button dw-primary"
                disabled={
                  locked ||
                  !frozen ||
                  (current.planning_operations?.length ?? 0) >= 3
                }
                onClick={() => void open("generate")}
              >
                <Sparkles size={14} />{" "}
                {matching ? "Tạo đề xuất mới" : "Tạo task chi tiết"}
              </button>
            )
          )}
        </div>
      </div>
      {accepted && (
        <p className="dw-muted dw-planning-boundary">
          Graph và phê duyệt đã lưu riêng cho chu kỳ này. Thực thi chu kỳ tiếp
          theo cần cổng bàn giao mã nguồn/kết quả của chu kỳ trước; chưa tự mở
          quyền chạy.
        </p>
      )}
      <details className="dw-planning-advanced">
        <summary>Đầu vào, phiên bản & chẩn đoán</summary>
        <p>
          Model lập kế hoạch: my-codex / cx/gpt-5.6-luna · không có công cụ thực
          thi
        </p>
        {matching?.usage && (
          <p>
            Đã ghi nhận {matching.usage.total_tokens} token. Chưa có số liệu chi
            phí.
          </p>
        )}
        <pre className="dw-json">
          {JSON.stringify(
            {
              spec_digest: current.spec_digest,
              baseline: current.spec.baseline,
              acceptance_criteria: current.spec.acceptance_criteria,
              generation: matching
                ? { ...matching, preview_plan: undefined }
                : null,
            },
            null,
            2,
          )}
        </pre>
        {latest && !matching && (
          <p>
            Đề xuất trước thuộc đặc tả cũ, không được dùng để duyệt đặc tả này.
          </p>
        )}
      </details>
      <TaskDetails
        row={previewRow}
        task={tasks.find((task) => task.id === selected?.id)}
        tasks={tasks}
        onSelect={setSelected}
        onClose={() => setSelected(undefined)}
        onAdvanced={onAdvanced}
      />
      <Dialog
        open={!!review}
        onOpenChange={(open) => {
          if (!open && !busy) setReview(null);
        }}
      >
        <DialogContent className="delivery dw-modal dw-planning-modal">
          <DialogTitle>
            {review?.kind === "freeze"
              ? "Chốt đầu vào chu kỳ"
              : review?.kind === "generate"
                ? "Tạo task chi tiết qua Harness"
                : "Duyệt đúng graph đang xem"}
          </DialogTitle>
          <DialogDescription>
            {review?.kind === "freeze"
              ? "Lưu bản đặc tả mới. Không gọi model và không chọn candidate chưa duyệt làm mã nguồn nền."
              : review?.kind === "generate"
                ? "Một lượt Luna có tính phí sẽ đề xuất task graph từ đầu vào đã chốt. Không chạy các task."
                : "Phê duyệt chỉ áp dụng cho graph, đặc tả và chu kỳ này. Không bắt đầu thực thi hoặc phát hành."}
          </DialogDescription>
          {review?.kind === "freeze" && context && (
            <div className="dw-planning-context">
              <label htmlFor="dw-planning-commit">
                Commit nền · {context.repository_key}
              </label>
              <input
                id="dw-planning-commit"
                value={commit}
                onChange={(event) => {
                  setCommit(event.target.value);
                  setConfirmed(false);
                  command.current = null;
                }}
                maxLength={40}
                disabled={busy}
              />
              <p className="dw-muted">
                Chỉ đọc nội dung đã commit trong repository của project. Không
                đọc file thay đổi chưa commit.
              </p>
              <details>
                <summary>
                  Phạm vi gửi tới model · {context.paths.length} file
                </summary>
                <ul>
                  {context.paths.map((path) => (
                    <li key={path}>{path}</li>
                  ))}
                </ul>
              </details>
              <details>
                <summary>
                  {context.acceptance_criteria.length} tiêu chí từ workflow
                </summary>
                <ul>
                  {context.acceptance_criteria.map((item) => (
                    <li key={item.criterion_id}>
                      {item.description}{" "}
                      <small>
                        (
                        {item.kind === "LOCKED_CHECK"
                          ? "kiểm thử cố định"
                          : "đầu ra khai báo, chưa phải bằng chứng"}
                        )
                      </small>
                    </li>
                  ))}
                </ul>
              </details>
              <p className="dw-muted">
                Giới hạn: {context.limits.max_tasks} task,{" "}
                {context.limits.max_tasks_per_stage} task/giai đoạn. Task Loop
                và các cổng duyệt được giữ nguyên.
              </p>
            </div>
          )}
          {review?.kind === "accept" && (
            <p className="dw-planning-digest">
              {review.operation?.plan_digest}
            </p>
          )}
          {stale && (
            <p role="alert" className="dw-error">
              Dữ liệu vừa thay đổi. Đóng hộp thoại, tải lại và kiểm tra trước
              khi xác nhận.
            </p>
          )}
          <label className="dw-confirm">
            <input
              type="checkbox"
              checked={confirmed}
              disabled={busy || stale}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            {review?.kind === "freeze"
              ? "Tôi đã xem commit, phạm vi và tiêu chí của chu kỳ này."
              : review?.kind === "generate"
                ? "Tôi đồng ý tạo một đề xuất bằng Luna trong giới hạn trên."
                : "Tôi đã xem task graph, phạm vi và các tiêu chí cố định."}
          </label>
          <div className="dw-modal-actions">
            <button
              type="button"
              className="dw-button"
              disabled={busy}
              onClick={() => setReview(null)}
            >
              Hủy
            </button>
            <button
              type="button"
              className="dw-button dw-primary"
              disabled={
                busy ||
                stale ||
                !confirmed ||
                (review?.kind === "freeze" && !/^[a-f0-9]{40}$/.test(commit))
              }
              onClick={() => {
                if (!review || stale || !confirmed) return;
                command.current ||= crypto.randomUUID();
                void perform(() =>
                  review.kind === "freeze"
                    ? deliveryApi.freezePlanning(
                        review.row,
                        commit,
                        command.current!,
                      )
                    : review.kind === "generate"
                      ? deliveryApi.generateDetailed(
                          review.row,
                          command.current!,
                        )
                      : deliveryApi.acceptGraph(
                          review.row,
                          review.operation!,
                          command.current!,
                        ),
                )
                  .then(() => setReview(null))
                  .catch(() => {});
              }}
            >
              {busy
                ? "Đang lưu…"
                : review?.kind === "generate"
                  ? "Tạo đề xuất"
                  : "Xác nhận"}
            </button>
          </div>
        </DialogContent>
      </Dialog>
    </section>
  );
}
