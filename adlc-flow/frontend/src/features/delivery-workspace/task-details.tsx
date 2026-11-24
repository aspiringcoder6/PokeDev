import { ArrowRight } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import type { Delivery } from "@/controllers/API/delivery";
import { type BoardTask, label, objects, strings, text } from "./model";
import { taskAcceptance, taskStage } from "./task-plan-model";

export default function TaskDetails({
  row,
  task,
  tasks,
  onClose,
  onSelect,
  onAdvanced,
}: {
  row: Delivery;
  task?: BoardTask;
  tasks: BoardTask[];
  onClose: () => void;
  onSelect: (task: BoardTask) => void;
  onAdvanced: (path: string) => void;
}) {
  const spec = row.plan?.resolved_node_specs?.find(
    (entry) =>
      entry.resolved_node_spec_id === task?.plan?.resolved_node_spec_id,
  );
  const group = task?.plan ? taskStage(row, task.plan) : null;
  const acceptance = taskAcceptance(task?.plan);
  const criterionIds = strings(task?.plan?.metadata.criterion_ids);
  if (!acceptance.criteria.length && criterionIds.length) {
    acceptance.criteria = objects(row.cycle?.spec.acceptance_criteria)
      .filter((item) => criterionIds.includes(text(item.criterion_id)))
      .map((item) => ({
        id: text(item.criterion_id),
        description: text(item.description),
        checks: strings(item.check_refs),
      }));
  }
  const dependents = task
    ? tasks.filter((entry) => entry.dependencies.includes(task.id))
    : [];
  const inputs = Object.entries(task?.plan?.inputs ?? {});
  return (
    <Dialog open={!!task} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="delivery dw-modal dw-task-drawer">
        <span className="dw-eyebrow">CHI TIẾT CÔNG VIỆC · CHỈ XEM</span>
        <DialogTitle>{task?.name || "Chi tiết công việc"}</DialogTitle>
        <DialogDescription className="dw-prewrap">
          {task?.objective || "Chưa khai báo mục tiêu."}
        </DialogDescription>
        <div className="dw-task-drawer-tags">
          <span className="dw-pill">
            {row.run ? label(task?.status ?? "UNKNOWN") : "Chưa khởi chạy"}
          </span>
          {group && (
            <span className={`dw-stage-label dw-stage-${group.color}`}>
              <i aria-hidden="true" />
              {group.name}
            </span>
          )}
        </div>
        {row.run && !task?.runtime && (
          <p className="dw-muted">
            Chưa đối soát được task với đúng lượt chạy/kế hoạch. Không suy ra đã
            hoàn tất.
          </p>
        )}
        <dl className="dw-task-facts">
          <div>
            <dt>Thực hiện bởi</dt>
            <dd>
              {spec?.kind === "APPROVAL"
                ? "Người duyệt · chưa gán người cụ thể"
                : spec?.kind === "AGENT"
                  ? "AI agent"
                  : spec
                    ? "Bộ thực thi theo gói"
                    : "Chưa có thông tin phân công"}
            </dd>
          </div>
          <div>
            <dt>Executor</dt>
            <dd>
              {spec?.implementation?.adapter_ref || "Chưa khai báo executor"}
            </dd>
          </div>
          <div>
            <dt>Gói thực thi</dt>
            <dd>
              {spec
                ? `${spec.package_ref.package_id}@${spec.package_ref.version}`
                : "Chưa có thông tin gói"}
            </dd>
          </div>
        </dl>
        <section>
          <h3>Đầu ra mong đợi</h3>
          {task?.outputs.length ? (
            <ul className="dw-task-output-list">
              {task.outputs.map((output, index) => (
                <li key={`${index}:${output}`}>{output}</li>
              ))}
            </ul>
          ) : (
            <p className="dw-muted">Chưa khai báo đầu ra.</p>
          )}
        </section>
        <section>
          <h3>Điều kiện bắt đầu</h3>
          {task?.dependencies.length ? (
            <ul className="dw-task-dependencies">
              {task.dependencies.map((id) => {
                const dependency = tasks.find((entry) => entry.id === id);
                return (
                  <li key={id}>
                    {dependency ? (
                      <button
                        type="button"
                        className="dw-link"
                        onClick={() => onSelect(dependency)}
                      >
                        {dependency.name}
                        <ArrowRight size={13} />
                      </button>
                    ) : (
                      <span className="dw-muted">
                        Không tìm thấy công việc phụ thuộc trong kế hoạch này.
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="dw-muted">Không có công việc phụ thuộc.</p>
          )}
        </section>
        {dependents.length > 0 && (
          <section>
            <h3>Công việc phía sau</h3>
            <ul className="dw-task-dependencies">
              {dependents.map((dependent) => (
                <li key={dependent.id}>
                  <button
                    type="button"
                    className="dw-link"
                    onClick={() => onSelect(dependent)}
                  >
                    {dependent.name}
                    <ArrowRight size={13} />
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
        <section>
          <h3>Tiêu chí chấp nhận</h3>
          {acceptance.criteria.length ? (
            <>
              <p className="dw-muted">
                Tiêu chí đã khai báo, không phải kết luận kiểm thử.
              </p>
              <ul className="dw-task-criteria">
                {acceptance.criteria.map((criterion, index) => (
                  <li key={`${criterion.id}:${index}`}>
                    <p>{criterion.description}</p>
                    {criterion.checks.length > 0 && (
                      <small>
                        Đối chiếu qua: {criterion.checks.join(", ")}
                      </small>
                    )}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="dw-muted">
              Chưa có tiêu chí chấp nhận có cấu trúc trong task này.
            </p>
          )}
        </section>
        {(acceptance.writablePaths.length > 0 ||
          acceptance.maxIterations !== null) && (
          <section>
            <h3>Phạm vi đã khóa</h3>
            {acceptance.writablePaths.length > 0 && (
              <p>
                Được sửa:{" "}
                <span className="dw-prewrap">
                  {acceptance.writablePaths.join(", ")}
                </span>
              </p>
            )}
            {acceptance.maxIterations !== null && (
              <p className="dw-muted">
                Tối đa {acceptance.maxIterations} vòng Task Loop.
              </p>
            )}
            {acceptance.checks.map((check) => (
              <p key={check.id} className="dw-muted">
                {check.id}
                {check.path ? ` · ${check.path}` : ""}
              </p>
            ))}
          </section>
        )}
        <section>
          <h3>Đầu vào</h3>
          {inputs.length ? (
            <div className="dw-task-inputs">
              {inputs.map(([key, value]) => (
                <details key={key}>
                  <summary>
                    {key}
                    <small>
                      {key === "task_loop_spec"
                        ? "Đặc tả Task Loop"
                        : typeof value === "string"
                          ? "Văn bản"
                          : "Dữ liệu có cấu trúc"}
                    </small>
                  </summary>
                  <pre className="dw-json">
                    {typeof value === "string"
                      ? value
                      : JSON.stringify(value, null, 2)}
                  </pre>
                </details>
              ))}
            </div>
          ) : (
            <p className="dw-muted">Chưa khai báo đầu vào.</p>
          )}
        </section>
        {task?.runtime?.result?.error && (
          <div role="alert" className="dw-error">
            {task.runtime.result.error.message}
          </div>
        )}
        <section className="dw-task-evidence">
          <h3>Kết quả & bằng chứng</h3>
          <p className="dw-muted">
            Mở trang lượt chạy để xem patch, kiểm thử và cổng duyệt thật. Việc
            mở trang không thực thi hay phê duyệt.
          </p>
          {task?.runtime && row.run ? (
            <button
              type="button"
              className="dw-button"
              onClick={() => onAdvanced(`/runs/${row.run!.id}`)}
            >
              Xem thay đổi & bằng chứng
              <ArrowRight size={14} />
            </button>
          ) : (
            <p className="dw-muted">Chưa có lượt chạy gắn với công việc này.</p>
          )}
        </section>
        <details className="dw-task-technical">
          <summary>Dữ liệu kỹ thuật & phiên bản kế hoạch</summary>
          <pre className="dw-json">
            {JSON.stringify(
              {
                plan_id: row.plan?.execution_plan_id,
                plan_version: row.plan?.plan_version,
                plan_digest: row.plan_digest,
                task: task?.plan,
                runtime: task?.runtime,
                resolved_spec: spec,
              },
              null,
              2,
            )}
          </pre>
          {row.plan && (
            <button
              type="button"
              className="dw-link"
              onClick={() =>
                onAdvanced(`/plans/${row.plan!.execution_plan_id}`)
              }
            >
              Mở kế hoạch nâng cao
              <ArrowRight size={13} />
            </button>
          )}
        </details>
      </DialogContent>
    </Dialog>
  );
}
