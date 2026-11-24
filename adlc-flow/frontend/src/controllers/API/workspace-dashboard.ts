import { getBaseUrl } from "@/customization/utils/urls";
import { api } from "./api";

export type DashboardAction = {
  id: string;
  kind: string;
  title: string;
  run_title: string;
  run_id: string;
  project_id: string | null;
  project_name: string;
  since: string | null;
  reason: string;
  can_act: boolean;
  action_label: string;
  href: string;
  priority: number;
};
export type DashboardHistory = {
  run_id: string;
  project_id: string | null;
  title: string;
  repository: string;
  state: string;
  created_at: string;
  category: string;
};
export type WorkspaceDashboardData = {
  generated_at: string;
  timezone: string;
  range: { days: number; from: string; to: string };
  project_id: string | null;
  projects: { project_id: string; name: string; repository: string }[];
  totals: {
    runs: number;
    finished: number;
    succeeded: number;
    failed: number;
    success_rate: number | null;
    active_now: number;
    waiting_now: number;
    attention_now: number;
    projects: number;
    workflows: number;
  };
  daily: {
    date: string;
    total: number;
    succeeded: number;
    failed: number;
    other: number;
  }[];
  statuses: { state: string; count: number }[];
  roles: {
    role: string;
    total: number;
    active: number;
    waiting: number;
    done: number;
  }[];
  attention: DashboardAction[];
  recent_runs: {
    run_id: string;
    project_id: string | null;
    project_name: string;
    title: string;
    state: string;
    created_at: string;
    href: string;
  }[];
  history: DashboardHistory[];
  sources: { native_connected: boolean; errors: string[] };
  quality: { invalid_timestamps: number };
};
export const workspaceDashboard = {
  read: async (
    days: 7 | 28 = 28,
    project?: string,
  ): Promise<WorkspaceDashboardData> =>
    (
      await api.get(`${getBaseUrl().replace(/\/?$/, "/")}adlc/live/dashboard`, {
        params: { days, ...(project ? { project_id: project } : {}) },
      })
    ).data,
};
