import { getBaseUrl } from "@/customization/utils/urls";
import { api } from "./api";

const root = `${getBaseUrl().replace(/\/?$/, "/")}adlc/harness-demo`;

export type DemoEvent = {
  seq: number;
  stage: string;
  at: string;
  output: unknown;
};

export type HarnessDemoRun = {
  id: string;
  status: string;
  requirement: string;
  requirement_digest: string;
  events: DemoEvent[];
  plan?: unknown;
  plan_digest?: string;
  candidate?: unknown;
  verification?: unknown;
  task_report?: unknown;
  commit?: string;
  handoff?: unknown;
  handoff_digest?: string;
  issue?: unknown;
  publish_receipt?: unknown;
  error_code?: string;
  interrupted?: boolean;
  github?: boolean;
  restart_of?: string;
  restart_run_id?: string;
  native_diagnostics?: unknown;
  workflow_run_id?: string;
  source_flow_id?: string;
};

export type HarnessDemoCapabilities = {
  ready: boolean;
  blockers: string[];
  requirement: string;
  workflow: {
    workflow_ref: string;
    stages: { id: string; actor: string; input: string; output: string }[];
  };
  sandbox: { image_id: string; backend: string } | null;
  memory_mode: string;
  github_repository: string;
  github_writes_enabled: boolean;
};

export const harnessDemoApi = {
  capabilities: async () =>
    (await api.get<HarnessDemoCapabilities>(`${root}/capabilities`)).data,
  list: async () => (await api.get<HarnessDemoRun[]>(`${root}/runs`)).data,
  get: async (id: string) =>
    (await api.get<HarnessDemoRun>(`${root}/runs/${encodeURIComponent(id)}`))
      .data,
  create: async (requirement: string) =>
    (await api.post<HarnessDemoRun>(`${root}/runs`, { requirement })).data,
  plan: async (id: string) =>
    (
      await api.post<HarnessDemoRun>(
        `${root}/runs/${encodeURIComponent(id)}/plan`,
        {},
      )
    ).data,
  restart: async (id: string) =>
    (
      await api.post<HarnessDemoRun>(
        `${root}/runs/${encodeURIComponent(id)}/restart`,
        {},
      )
    ).data,
  approve: async (id: string, gate: "plan" | "merge", digest: string) =>
    (
      await api.post<HarnessDemoRun>(
        `${root}/runs/${encodeURIComponent(id)}/approve-${gate}`,
        { digest },
      )
    ).data,
  issue: async (requirement: string) =>
    (
      await api.post<{ issue_url: string; awaiting_webhook: boolean }>(
        `${root}/github/issues`,
        { requirement },
      )
    ).data,
};
