import { api } from "@/controllers/API/api";
import { getBaseUrl } from "@/customization/utils/urls";

export type IntakeContent = {
  title: string;
  description: string;
  scope_in: string[];
  scope_out: string[];
  constraints: string[];
  acceptance_criteria: string[];
  assumptions: string[];
};
export type IntakeRequest = {
  id: string;
  project_id: string | null;
  revision: number;
  status: "NEW" | "CANCELLED";
  content: IntakeContent;
  content_digest: string;
  created_at: string;
  updated_at: string;
};
export type IntakeHistory = {
  revision: number;
  created_at: string;
  snapshot: IntakeRequest;
};
const base = `${getBaseUrl()}adlc/intake`;
export const intakeApi = {
  list: async (
    offset = 0,
    signal?: AbortSignal,
  ): Promise<{ items: IntakeRequest[]; total: number }> =>
    (
      await api.get(`${base}/requests`, {
        params: { offset, limit: 50 },
        signal,
      })
    ).data,
  projects: async (
    signal?: AbortSignal,
  ): Promise<{ id: string; name: string }[]> =>
    (await api.get(`${base}/projects`, { signal })).data,
  get: async (id: string, signal?: AbortSignal): Promise<IntakeRequest> =>
    (await api.get(`${base}/requests/${encodeURIComponent(id)}`, { signal }))
      .data,
  history: async (
    id: string,
    signal?: AbortSignal,
  ): Promise<{ items: IntakeHistory[] }> =>
    (
      await api.get(`${base}/requests/${encodeURIComponent(id)}/history`, {
        signal,
      })
    ).data,
  create: async (body: {
    command_id: string;
    project_id: string | null;
    content: IntakeContent;
  }): Promise<{ request: IntakeRequest; replayed: boolean }> =>
    (await api.post(`${base}/requests`, body)).data,
  update: async (
    id: string,
    body: {
      command_id: string;
      expected_revision: number;
      content: IntakeContent;
    },
  ): Promise<{ request: IntakeRequest; replayed: boolean }> =>
    (await api.put(`${base}/requests/${encodeURIComponent(id)}`, body)).data,
  cancel: async (
    id: string,
    revision: number,
    command: string,
  ): Promise<{ request: IntakeRequest; replayed: boolean }> =>
    (
      await api.post(`${base}/requests/${encodeURIComponent(id)}/cancel`, {
        expected_revision: revision,
        command_id: command,
      })
    ).data,
};
