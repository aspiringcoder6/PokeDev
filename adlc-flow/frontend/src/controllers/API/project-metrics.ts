import { getBaseUrl } from "@/customization/utils/urls";
import { api } from "./api";

export type ModelRate = {
  provider: string;
  model: string;
  source: string;
  input: number;
  cache_read: number;
  cache_write: number;
  output: number;
};
export type MetricUsage = {
  tokens: number | null;
  sessions: number;
  measured_sessions: number;
  priced_sessions: number;
  cost_usd: number | null;
  cost_kind: string;
  partial: boolean;
  last_measured_at: string | null;
};
export type ProjectMetricSummary = {
  project_id: string;
  days: number;
  models: { provider: string; model: string }[];
  totals: {
    runs: number;
    finished: number;
    succeeded: number;
    success_rate: number | null;
    unconfirmed: number;
    average_active_seconds: number | null;
    human_wait_seconds: number;
    human_interventions: number;
    repair_rounds: number;
  };
  usage: MetricUsage;
  pricing: { revision: number; rates: ModelRate[]; updated_at: string | null };
  refresh: {
    updated_at: string | null;
    error_code: string | null;
    running: boolean;
  };
  runs: {
    run_id: string;
    title: string;
    state: string;
    created_at: string;
    issue?: { number: number; title: string; url: string };
    workflow: { name?: string; revision?: number; workflow_id?: string };
    timing: {
      total_seconds: number | null;
      active_seconds: number | null;
      active_source: string;
      human_wait_seconds: number;
      approval_wait_seconds: number;
      repair_rounds: number;
      human_interventions: number;
      verification_attempts: number;
    };
    usage: MetricUsage;
  }[];
};
const base = (project: string) =>
  `${getBaseUrl().replace(/\/?$/, "/")}adlc/live/projects/${encodeURIComponent(project)}/metrics`;
export const projectMetrics = {
  read: async (project: string, days: number): Promise<ProjectMetricSummary> =>
    (await api.get(base(project), { params: { days } })).data,
  refresh: async (project: string) =>
    (await api.post(base(project) + "/refresh")).data,
  savePricing: async (
    project: string,
    expected_revision: number,
    rates: ModelRate[],
  ) =>
    (await api.put(base(project) + "/pricing", { expected_revision, rates }))
      .data,
};
