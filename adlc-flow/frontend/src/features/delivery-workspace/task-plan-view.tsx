import { GitBranch, List, Minus, Plus } from "lucide-react";
import { useState } from "react";
import type { Delivery } from "@/controllers/API/delivery";
import PlanTaskGraph from "@/features/adlc-blueprint/plan-task-graph";
import { type BoardTask, column, label } from "./model";
import { isStageLevelPlan, taskPlanGroups, taskStage } from "./task-plan-model";

export default function TaskPlanView({
  row,
  tasks,
  selectedTaskId,
  onSelect,
}: {
  row: Delivery;
  tasks: BoardTask[];
  selectedTaskId?: string;
  onSelect: (task: BoardTask) => void;
}) {
  const [view, setView] = useState<"graph" | "list">("graph");
  const [zoom, setZoom] = useState(1);
  const plan = row.plan;
  if (!plan) return null;
  const groups = taskPlanGroups(row);
  const byId = new Map(tasks.map((task) => [task.id, task]));
  const specs = new Map(
    (plan.resolved_node_specs ?? []).map((spec) => [
      spec.resolved_node_spec_id,
      spec,
    ]),
  );
  const dependencyCount = plan.tasks.reduce(
    (sum, task) => sum + task.dependency_task_ids.length,
    0,
  );
  return (
    <section
      className="dw-task-plan"
      aria-label="Sơ đồ và danh sách công việc"
      data-plan-id={plan.execution_plan_id}
    >
      <div className="dw-task-plan-toolbar">
        <div
          className="dw-view-switch"
          role="group"
          aria-label="Cách xem kế hoạch"
        >
          <button
            type="button"
            aria-pressed={view === "graph"}
            onClick={() => setView("graph")}
          >
            <GitBranch size={14} />
            Sơ đồ
          </button>
          <button
            type="button"
            aria-pressed={view === "list"}
            onClick={() => setView("list")}
          >
            <List size={14} />
            Danh sách
          </button>
        </div>
        <span className="dw-task-plan-version">
          {typeof plan.plan_version === "number"
            ? `Kế hoạch v${plan.plan_version}`
            : "Kế hoạch hiện tại"}{" "}
          · {tasks.length} công việc · {dependencyCount} liên kết
        </span>
        {view === "graph" && (
          <div
            className="dw-graph-zoom"
            role="group"
            aria-label="Thu phóng sơ đồ"
          >
            <button
              type="button"
              aria-label="Thu nhỏ sơ đồ"
              disabled={zoom <= 0.5}
              onClick={() =>
                setZoom((value) =>
                  Math.max(0.5, Number((value - 0.1).toFixed(1))),
                )
              }
            >
              <Minus size={14} />
            </button>
            <button
              type="button"
              aria-label="Đặt lại sơ đồ 100%"
              onClick={() => setZoom(1)}
            >
              {Math.round(zoom * 100)}%
            </button>
            <button
              type="button"
              aria-label="Phóng to sơ đồ"
              disabled={zoom >= 1.5}
              onClick={() =>
                setZoom((value) =>
                  Math.min(1.5, Number((value + 0.1).toFixed(1))),
                )
              }
            >
              <Plus size={14} />
            </button>
          </div>
        )}
      </div>
      <div className="dw-task-stage-legend" aria-label="Nhóm theo giai đoạn">
        {groups.map((group) => (
          <span
            key={group.id}
            className={`dw-stage-label dw-stage-${group.color}`}
          >
            <i aria-hidden="true" />
            {group.name}
            <small>{group.count}</small>
          </span>
        ))}
      </div>
      {view === "graph" ? (
        <>
          <p className="dw-task-graph-help">
            Mũi tên là quan hệ phụ thuộc. Công việc cùng hàng có thể chạy song
            song nếu đủ điều kiện. Chọn một ô để xem chi tiết.
          </p>
          <div className="dw-task-graph">
            <PlanTaskGraph
              tasks={plan.tasks}
              specs={specs}
              scale={zoom}
              selectedTaskId={selectedTaskId}
              onSelectTask={(id) => {
                const task = byId.get(id);
                if (task) onSelect(task);
              }}
              renderTask={(task) => {
                const board = byId.get(task.plan_task_id)!;
                const group = taskStage(row, task);
                return (
                  <>
                    <span
                      className={`dw-graph-node-stage dw-stage-label dw-stage-${group.color}`}
                      title={group.name}
                    >
                      <i aria-hidden="true" />
                      {group.name}
                    </span>
                    <strong className="dw-graph-node-name" title={task.name}>
                      {task.name}
                    </strong>
                    <span className="dw-graph-node-footer">
                      <span
                        className={`dw-node-status dw-node-${row.run ? column(board.status) : "unstarted"}`}
                      >
                        {row.run ? label(board.status) : "Chưa khởi chạy"}
                      </span>
                      <small>
                        {task.dependency_task_ids.length
                          ? `Sau ${task.dependency_task_ids.length} việc`
                          : "Bắt đầu"}
                      </small>
                    </span>
                  </>
                );
              }}
            />
          </div>
        </>
      ) : (
        <div className="dw-task-table">
          <div className="dw-task-head">
            <span>CÔNG VIỆC</span>
            <span>ĐẦU RA CẦN CÓ</span>
            <span>PHỤ THUỘC</span>
          </div>
          {tasks.map((task, index) => (
            <button
              type="button"
              className="dw-task-row"
              key={task.id}
              data-plan-task-id={task.id}
              onClick={() => onSelect(task)}
            >
              <span>
                <small>{String(index + 1).padStart(2, "0")}</small>
                <span>
                  <strong>{task.name}</strong>
                  <p>{task.objective}</p>
                  <span
                    className={`dw-node-status dw-node-${row.run ? column(task.status) : "unstarted"}`}
                  >
                    {row.run ? label(task.status) : "Chưa khởi chạy"}
                  </span>
                </span>
              </span>
              <span>{task.outputs.join(", ") || "Chưa khai báo đầu ra"}</span>
              <span>
                {task.dependencies.length
                  ? `${task.dependencies.length} công việc trước`
                  : "Không phụ thuộc"}
              </span>
            </button>
          ))}
        </div>
      )}
      {!tasks.length && view === "list" && (
        <p className="dw-task-graph-help">Kế hoạch này chưa có công việc.</p>
      )}
      <p className="dw-task-graph-note">
        {isStageLevelPlan(row)
          ? "Kế hoạch hiện có một công việc cho mỗi giai đoạn; chưa có task nhỏ hơn trong dữ liệu. "
          : ""}
        Chỉ hiển thị kế hoạch đã lưu. Trạng thái hoàn tất không thay thế bằng
        chứng kiểm thử.
      </p>
    </section>
  );
}
