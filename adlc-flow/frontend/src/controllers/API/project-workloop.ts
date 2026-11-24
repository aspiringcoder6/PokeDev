import { getBaseUrl } from "@/customization/utils/urls";
import { api } from "./api";
import type { HumanInput } from "./live-workflows";
import type {
  ExecutionTask,
  ExecutionEdge,
} from "@/features/delivery-workspace/execution-model";

export type WorkloopCommand = {
  command_id: string;
  action: string;
  state: "SENDING" | "REQUESTED" | "CONFIRMED" | "REJECTED" | "UNCERTAIN";
  request_id?: string;
  created_at: string;
};
export type WorkloopJob = {
  job_id: string;
  workflow: string;
  version?: number;
  state: string;
  title: string;
  project_id: string;
  repository: string;
  created_at: string;
  updated_at: string;
  checked_at: string;
  stale?: boolean;
  error_code?: string;
  error?: string;
  topology?: {
    state: "pinned" | "unavailable";
    commit?: string;
    edges: ExecutionEdge[];
  };
  tasks?: (Omit<ExecutionTask, "started_at" | "completed_at"> & {
    started_at?: string;
    completed_at?: string;
    brief?: string;
    session_id?: string;
    attempts?: string[];
    source_state?: string;
  })[];
  events?: {
    id: string;
    kind: string;
    node_id: string;
    at: string;
    state: string;
  }[];
  requests: (HumanInput & { supported: boolean })[];
  commands?: WorkloopCommand[];
};
export type WorkloopReport = {
  job_id: string;
  checked_at: string;
  nodes: { id: string; state: string; message: string }[];
};
const base = (project: string) =>
  `${getBaseUrl().replace(/\/?$/, "/")}adlc/live/projects/${encodeURIComponent(project)}/workloop`;
export const projectWorkloop = {
  attention: async (): Promise<{ items: WorkloopJob[]; partial: boolean }> =>
    (
      await api.get(
        `${getBaseUrl().replace(/\/?$/, "/")}adlc/live/workloop/attention`,
      )
    ).data,
  jobs: async (project: string): Promise<{ items: WorkloopJob[] }> =>
    (await api.get(`${base(project)}/jobs`)).data,
  read: async (project: string, job: string): Promise<WorkloopJob> =>
    (await api.get(`${base(project)}/jobs/${encodeURIComponent(job)}`)).data,
  candidates: async (
    project: string,
  ): Promise<{ items: WorkloopJob[]; limit: number }> =>
    (await api.get(`${base(project)}/candidates`)).data,
  link: async (
    project: string,
    job: string,
    title: string,
    repository: string,
  ): Promise<WorkloopJob> =>
    (
      await api.post(`${base(project)}/links`, {
        job_id: job,
        title,
        confirm_repository: repository,
      })
    ).data,
  reports: async (project: string, job: string): Promise<WorkloopReport> =>
    (await api.get(`${base(project)}/jobs/${encodeURIComponent(job)}/reports`))
      .data,
  command: async (
    project: string,
    job: string,
    command: {
      command_id: string;
      action: string;
      request_id?: string;
      source_digest?: string;
      response?: Record<string, unknown>;
    },
  ): Promise<WorkloopCommand> =>
    (
      await api.post(
        `${base(project)}/jobs/${encodeURIComponent(job)}/commands`,
        command,
      )
    ).data,
};
