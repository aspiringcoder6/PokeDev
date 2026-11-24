import type { DashboardHistory } from "@/controllers/API/workspace-dashboard";

export const dashboardStates: Record<
  string,
  { label: string; status: string; color: string }
> = {
  succeeded: { label: "Hoàn tất", status: "SUCCEEDED", color: "#49b894" },
  running: { label: "Đang thực hiện", status: "running", color: "#759de4" },
  waiting: {
    label: "Chờ phản hồi / duyệt",
    status: "waiting",
    color: "#d6a34e",
  },
  unconfirmed: {
    label: "Cần đối soát",
    status: "UNCONFIRMED",
    color: "#bd92e6",
  },
  failed: { label: "Gặp lỗi", status: "FAILED", color: "#eb7379" },
  other: { label: "Trạng thái khác", status: "other", color: "#898b95" },
};
export const actionKinds: Record<string, string> = {
  question: "Câu hỏi",
  permission: "Xin quyền",
  gate: "Cổng duyệt",
  plan: "Kế hoạch",
  issue: "Issue Gitea",
  recovery: "Đối soát",
  failed: "Lỗi",
  handover: "Bàn giao",
  advanced: "Workflow gói",
};

export function dashboardHistoryUrl(
  project?: string,
  range?: { from: string; to: string; days: number },
  status?: string,
  day?: string,
) {
  const query = new URLSearchParams({ view: "history", filtered: "1" });
  if (project) query.set("project", project);
  if (range) {
    query.set("from", day || range.from);
    query.set("to", day || range.to);
    query.set("range", String(range.days));
  }
  if (status) query.set("status", status);
  return "/work?" + query;
}

export function localDashboardDay(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? ""
    : new Intl.DateTimeFormat("en-CA", {
        timeZone: "Asia/Ho_Chi_Minh",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }).format(date);
}

export function matchesDashboardHistory(
  row: Pick<DashboardHistory, "state" | "created_at"> & { category?: string },
  params: URLSearchParams,
): boolean {
  const day = localDashboardDay(row.created_at),
    from = params.get("from"),
    to = params.get("to"),
    status = params.get("status");
  if ((from || to) && (!day || (from && day < from) || (to && day > to)))
    return false;
  if (!status) return true;
  if (status === "active") return ["RUNNING", "PLANNING"].includes(row.state);
  if (["running", "waiting", "other"].includes(status))
    return row.category === status;
  return row.state === status;
}

export function waitingAge(since: string | null, now = Date.now()): string {
  if (!since) return "Chưa có mốc chờ";
  const time = new Date(since).getTime();
  if (!Number.isFinite(time)) return "Chưa có mốc chờ";
  const minutes = Math.max(0, Math.floor((now - time) / 60000));
  if (minutes < 1) return "Vừa cập nhật";
  if (minutes < 60) return `${minutes} phút`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)} giờ`;
  return `${Math.floor(minutes / 1440)} ngày`;
}
