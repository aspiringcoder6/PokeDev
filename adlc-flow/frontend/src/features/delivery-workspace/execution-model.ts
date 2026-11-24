import type { LiveRun, LiveTask } from "@/controllers/API/live-workflows";

export type ExecutionTask = {
  id: string;
  title: string;
  role?: string;
  state: string;
  started_at?: number;
  completed_at?: number;
  summary?: string;
};
export type ExecutionEdge = {
  source: string;
  target: string;
  label?: string;
  feedback?: boolean;
};
export type ExecutionTone =
  | "running"
  | "done"
  | "waiting"
  | "failed"
  | "idle"
  | "skipped";

export function nativeRunRefreshInterval(state?: string): number | false {
  return state && ["PLANNING", "PLAN_READY", "RUNNING", "UNCONFIRMED"].includes(state)
    ? 3000
    : false;
}

export function taskTone(state: string): ExecutionTone {
  if (["RUNNING", "IN_PROGRESS"].includes(state)) return "running";
  if (["DONE", "SUCCEEDED"].includes(state)) return "done";
  if (
    [
      "WAITING_INPUT",
      "NEEDS_CONTEXT",
      "DONE_WITH_CONCERNS",
      "SUSPENDED",
    ].includes(state)
  )
    return "waiting";
  if (["FAILED", "BLOCKED", "UNCONFIRMED", "INTERRUPTED"].includes(state))
    return "failed";
  return state === "SKIPPED" ? "skipped" : "idle";
}
export const executionState: Record<string, string> = {
  RUNNING: "Đang chạy",
  IN_PROGRESS: "Đang chạy",
  DONE: "Hoàn tất",
  SUCCEEDED: "Hoàn tất",
  WAITING_INPUT: "Cần phản hồi",
  NEEDS_CONTEXT: "Cần ngữ cảnh",
  DONE_WITH_CONCERNS: "Có lưu ý",
  FAILED: "Lỗi",
  BLOCKED: "Bị chặn",
  UNCONFIRMED: "Cần đối soát",
  INTERRUPTED: "Đã ngắt",
  SUSPENDED: "Đã tạm dừng",
  PENDING: "Chờ phụ thuộc",
  WAITING_SLOT: "Chờ agent",
  SKIPPED: "Bỏ qua nhánh",
};

// Ignore feedback edges for ranking. A cycle never creates an unbounded layout.
export function executionLayout(
  tasks: ExecutionTask[],
  edges: ExecutionEdge[],
) {
  const ids = new Set(tasks.map((t) => t.id));
  const ranks: Record<string, number> = {};
  const pending = new Set(ids);
  for (let pass = 0; pending.size && pass <= tasks.length; pass++) {
    let changed = false;
    for (const id of pending) {
      const parents = edges
        .filter((e) => e.target === id && !e.feedback && ids.has(e.source))
        .map((e) => e.source);
      if (parents.every((p) => ranks[p] !== undefined)) {
        ranks[id] = parents.length
          ? Math.max(...parents.map((p) => ranks[p])) + 1
          : 0;
        pending.delete(id);
        changed = true;
      }
    }
    if (!changed) break;
  }
  const counts: Record<number, number> = {};
  return tasks.map((t) => {
    const rank = ranks[t.id] ?? 0;
    const row = counts[rank] || 0;
    counts[rank] = row + 1;
    return { id: t.id, x: rank * 280, y: row * 150 };
  });
}

export function nativeExecution(tasks: LiveTask[], run: LiveRun) {
  const resolved = tasks.map((t) => ({
    ...t,
    ...run.nodes.find((n) => n.id === t.id),
    state: run.nodes.find((n) => n.id === t.id)?.state || "PENDING",
  }));
  return {
    tasks: resolved,
    edges: resolved.flatMap((t) => {
      const planned =
        run.plan?.control_flow && run.plan.tasks.some((p) => p.id === t.id)
          ? run.plan.control_flow.edges
              .filter((e) => e.target === t.id)
              .map((e) => ({
                ...e,
                label: e.feedback
                  ? "Sửa có giới hạn"
                  : e.port !== "done"
                    ? e.port
                    : undefined,
              }))
          : [];
      return [
        ...planned,
        ...t.depends_on
          .filter((source) => !planned.some((e) => e.source === source))
          .map((source) => ({ source, target: t.id })),
      ];
    }),
  };
}

export type JourneyStep = {
  id: string;
  title: string;
  detail: string;
  state: "done" | "current" | "waiting" | "attention";
  tab: string;
};
export function nativeJourney(run: LiveRun): JourneyStep[] {
  const executing = run.phase === "execution";
  const verified = run.state === "SUCCEEDED";
  const failed = ["FAILED", "UNCONFIRMED"].includes(run.state);
  const checks = run.checks || [];
  return [
    {
      id: "request",
      title: "Yêu cầu",
      detail: run.origin_document
        ? `Slack · Confluence v${run.origin_document.page_version}`
        : run.issue
          ? `Gitea #${run.issue.number}`
          : "Yêu cầu đã lưu",
      state: "done",
      tab: "spec",
    },
    {
      id: "plan",
      title: "Tài liệu & kế hoạch",
      detail: run.plan
        ? `${run.plan.tasks.length} task · có phiên bản`
        : "Agent đang chuẩn bị",
      state: run.plan ? "done" : failed ? "attention" : "current",
      tab: "spec",
    },
    {
      id: "approval",
      title: "Duyệt",
      detail: executing
        ? "Kế hoạch đã duyệt"
        : run.state === "PLAN_READY"
          ? "Đang chờ bạn"
          : "Sau khi có kế hoạch",
      state: executing
        ? "done"
        : run.state === "PLAN_READY"
          ? "current"
          : "waiting",
      tab: "tasks",
    },
    {
      id: "execution",
      title: "Thực hiện",
      detail: executing
        ? `${run.nodes.filter((n) => n.state === "DONE").length}/${run.nodes.length} task hoàn tất`
        : run.plan
          ? `0/${run.plan.tasks.length} task · chưa bắt đầu`
          : "Sau khi duyệt kế hoạch",
      state: verified
        ? "done"
        : executing && failed
          ? "attention"
          : executing
            ? "current"
            : "waiting",
      tab: "tasks",
    },
    {
      id: "verify",
      title: "Kiểm chứng",
      detail: checks.length
        ? `${checks.length} kết quả kiểm tra`
        : "Chưa có kết quả kiểm tra",
      state: verified
        ? "done"
        : executing && checks.length
          ? "current"
          : "waiting",
      tab: "tests",
    },
    {
      id: "handover",
      title: "Bàn giao",
      detail: run.handover?.pull?.merged
        ? "PR đã hợp nhất"
        : run.handover?.pull
          ? `PR #${run.handover.pull.number}`
          : run.published
            ? "Nhánh đã sẵn sàng"
            : "Sau khi kiểm chứng",
      state: run.handover?.pull?.merged
        ? "done"
        : verified
          ? "current"
          : "waiting",
      tab: "handover",
    },
  ];
}

export function executionTime(value?: number | string) {
  return value
    ? new Date(typeof value === "number" ? value * 1000 : value).toLocaleString(
        "vi-VN",
        {
          timeZone: "Asia/Ho_Chi_Minh",
          day: "2-digit",
          month: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        },
      )
    : "—";
}
