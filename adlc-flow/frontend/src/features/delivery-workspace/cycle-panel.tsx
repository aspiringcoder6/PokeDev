import { ArrowRight, History, Plus, Target } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import type { Delivery, ProductCycle } from "@/controllers/API/delivery";
import { label, time } from "./model";

export const cycleLabel = (cycle: ProductCycle) =>
  cycle.state === "DRAFT"
    ? "Bản nháp"
    : cycle.run_status
      ? label(cycle.run_status)
      : cycle.dispatch_plan_id
        ? "Chờ đối soát"
        : "Đang lập kế hoạch";

export type CycleActions = {
  onSelectCycle?: (id: string) => void;
  onPrepareCycle?: (
    row: Delivery,
    goal: string,
    command: string,
  ) => Promise<void>;
  onUpdateCycle?: (
    row: Delivery,
    goal: string,
    command: string,
  ) => Promise<void>;
};

export default function CyclePanel({
  row,
  disabled,
  onAdvanced,
  onSelectCycle,
  onPrepareCycle,
  onUpdateCycle,
}: {
  row: Delivery;
  disabled: boolean;
  onAdvanced: (path: string) => void;
} & CycleActions) {
  const [edit, setEdit] = useState<{
    row: Delivery;
    mode: "prepare" | "update";
  } | null>(null);
  const [goal, setGoal] = useState("");
  const command = useRef<string | null>(null);
  useEffect(() => {
    setEdit(null);
    command.current = null;
  }, [row.id, row.cycle?.id]);
  const current = row.cycle;
  if (!current || !row.cycles?.length) return null;
  const draft = current.state === "DRAFT" && !current.is_initial;
  const planningPending = current.planning_operations?.some(
    (operation) =>
      operation.status === "RESERVED" || operation.status === "UNCONFIRMED",
  );
  const goalPreview = current.goal.split(/\n\s*\n/)[0].slice(0, 320);
  const shortenedGoal = goalPreview.length < current.goal.length;
  const latest = row.cycles.find((cycle) => cycle.is_latest);
  const pendingDraft = latest?.state === "DRAFT" && !latest.is_initial;
  const canPrepare =
    current.is_latest &&
    !pendingDraft &&
    row.cycle_capabilities?.prepare &&
    !!onPrepareCycle;
  const open = (mode: "prepare" | "update") => {
    setEdit({ row, mode });
    setGoal(mode === "update" ? current.goal : "");
    command.current = null;
  };
  const stale =
    !!edit &&
    (edit.row.id !== row.id ||
      edit.row.cycle?.id !== current.id ||
      edit.row.revision !== row.revision);
  return (
    <section className="dw-cycle-panel" aria-label="Chu kỳ phát triển">
      <div className="dw-cycle-toolbar">
        <div className="dw-cycle-selector">
          <History size={16} aria-hidden="true" />
          <label className="dw-sr" htmlFor="dw-cycle">
            Chu kỳ đang xem
          </label>
          <select
            id="dw-cycle"
            value={current.id}
            onChange={(event) => onSelectCycle?.(event.target.value)}
            disabled={disabled || !onSelectCycle}
          >
            {row.cycles.map((cycle) => (
              <option key={cycle.id} value={cycle.id}>
                Chu kỳ {cycle.number} · {cycleLabel(cycle)}
              </option>
            ))}
          </select>
          <span className="dw-small-tag">
            {current.plan_version
              ? `Kế hoạch v${current.plan_version}`
              : "Chưa có kế hoạch"}
          </span>
        </div>
        <div className="dw-cycle-actions">
          {draft && onUpdateCycle && (
            <button
              type="button"
              className="dw-button"
              disabled={disabled || !row.permissions.write || planningPending}
              onClick={() => open("update")}
            >
              Chỉnh mục tiêu
            </button>
          )}
          {pendingDraft && !current.is_latest ? (
            <button
              type="button"
              className="dw-button"
              disabled={disabled || !onSelectCycle}
              onClick={() => onSelectCycle?.(latest!.id)}
            >
              Mở bản nháp tiếp theo <ArrowRight size={13} />
            </button>
          ) : (
            <button
              type="button"
              className="dw-button"
              disabled={disabled || !canPrepare}
              onClick={() => open("prepare")}
            >
              <Plus size={14} /> Chuẩn bị chu kỳ tiếp theo
            </button>
          )}
        </div>
      </div>
      <div className="dw-cycle-goal">
        <Target size={16} aria-hidden="true" />
        <div>
          <span className="dw-eyebrow">MỤC TIÊU CHU KỲ {current.number}</span>
          <p>
            {goalPreview}
            {shortenedGoal ? "…" : ""}
          </p>
          {shortenedGoal && (
            <details className="dw-cycle-goal-full">
              <summary>Mở toàn bộ mục tiêu & yêu cầu</summary>
              <p>{current.goal}</p>
            </details>
          )}
        </div>
      </div>
      <div className="dw-cycle-facts">
        <span>
          Workflow{" "}
          {current.spec.workflow_version
            ? `v${current.spec.workflow_version}`
            : "chưa có phiên bản"}
        </span>
        <span>Đặc tả v{current.spec_revision}</span>
        <span>
          {draft
            ? "Bản nháp · chưa cấp quyền thực thi"
            : "Phê duyệt và kết quả gắn riêng từng chu kỳ"}
        </span>
      </div>
      <details className="dw-cycle-history">
        <summary>
          Lịch sử chu kỳ & kế hoạch <span>{row.cycles.length} chu kỳ</span>
        </summary>
        <ol>
          {row.cycles.map((cycle) => (
            <li key={cycle.id}>
              <button
                type="button"
                className="dw-link"
                disabled={disabled || !onSelectCycle}
                aria-current={cycle.id === current.id ? "true" : undefined}
                onClick={() => onSelectCycle?.(cycle.id)}
              >
                Chu kỳ {cycle.number}
                <ArrowRight size={12} />
              </button>
              <span>{cycle.goal}</span>
              <small>
                {cycleLabel(cycle)} · {time(cycle.created_at)}
              </small>
            </li>
          ))}
        </ol>
        {current.plan_revisions.length > 0 && (
          <div className="dw-cycle-plan-history">
            <h3>Kế hoạch của chu kỳ đang xem</h3>
            {current.plan_revisions.map((revision) => (
              <button
                key={revision.plan_id}
                type="button"
                className="dw-link"
                onClick={() => onAdvanced(`/plans/${revision.plan_id}`)}
              >
                Kế hoạch v{revision.plan_version || revision.ordinal} ·{" "}
                {revision.plan_id === current.plan_id
                  ? "Đang gắn với chu kỳ"
                  : "Bản lưu"}
                <ArrowRight size={12} />
              </button>
            ))}
          </div>
        )}
      </details>
      <Dialog
        open={!!edit}
        onOpenChange={(open) => {
          if (!open) setEdit(null);
        }}
      >
        <DialogContent className="delivery dw-modal">
          <DialogTitle>
            {edit?.mode === "update"
              ? "Chỉnh mục tiêu bản nháp"
              : "Chuẩn bị chu kỳ tiếp theo"}
          </DialogTitle>
          <DialogDescription>
            Chỉ lưu bản nháp. Không gọi AI, thay kế hoạch đang chạy, sao chép
            phê duyệt hoặc bắt đầu thực thi.
          </DialogDescription>
          <form
            onSubmit={async (event) => {
              event.preventDefault();
              if (!edit || stale || disabled || !goal.trim()) return;
              command.current ||= crypto.randomUUID();
              try {
                const save =
                  edit.mode === "update" ? onUpdateCycle : onPrepareCycle;
                if (save) {
                  await save(edit.row, goal.trim(), command.current);
                  setEdit(null);
                }
              } catch {
                /* Keep the exact payload/key after an uncertain acknowledgement. */
              }
            }}
          >
            <label htmlFor="dw-cycle-goal">Mục tiêu cho chu kỳ này</label>
            <textarea
              id="dw-cycle-goal"
              rows={4}
              maxLength={20000}
              value={goal}
              required
              disabled={disabled}
              onChange={(event) => {
                setGoal(event.target.value);
                command.current = null;
              }}
            />
            <p className="dw-muted">
              Workflow được giữ theo phiên bản đang xem. Mã nguồn nền, tiêu chí
              và kế hoạch mới phải được chốt riêng trước khi chạy.
            </p>
            {stale && (
              <p role="alert" className="dw-error">
                Dữ liệu vừa thay đổi. Đóng hộp thoại, tải lại và xem phiên bản
                mới trước khi lưu.
              </p>
            )}
            <div className="dw-modal-actions">
              <button
                type="button"
                className="dw-button"
                onClick={() => setEdit(null)}
              >
                Hủy
              </button>
              <button
                type="submit"
                className="dw-button dw-primary"
                disabled={disabled || stale || !goal.trim()}
              >
                Lưu bản nháp
              </button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </section>
  );
}

export function DraftCycle({ row }: { row: Delivery }) {
  return (
    <section className="dw-panel dw-cycle-draft">
      <span className="dw-eyebrow">CHU KỲ MỚI · CHƯA THỰC THI</span>
      <h2>Mục tiêu đã được lưu, chưa có kế hoạch mới</h2>
      <p>
        Chu kỳ trước vẫn giữ nguyên kế hoạch, lượt chạy và bằng chứng. Bản nháp
        này chưa được phép dùng lại phạm vi hoặc phê duyệt cũ.
      </p>
      <ul>
        <li>
          <strong>Workflow đã tham chiếu</strong>
          <span>Phiên bản được giữ trong đặc tả của chu kỳ.</span>
        </li>
        <li>
          <strong>Cần chốt mã nguồn & tiêu chí</strong>
          <span>Chưa tự dùng candidate chưa duyệt làm mã nguồn nền.</span>
        </li>
        <li>
          <strong>Chưa mở lập kế hoạch thực thi</strong>
          <span>
            Kế hoạch mới cần được tạo, kiểm tra và duyệt riêng trước khi chạy.
          </span>
        </li>
      </ul>
      <details>
        <summary>Đặc tả bản nháp · chỉ xem</summary>
        <pre className="dw-json">
          {JSON.stringify(
            { spec_digest: row.cycle?.spec_digest, ...row.cycle?.spec },
            null,
            2,
          )}
        </pre>
      </details>
    </section>
  );
}
