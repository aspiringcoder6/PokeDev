import { getBaseUrl } from "@/customization/utils/urls";
import { api } from "./api";

const root = `${getBaseUrl().replace(/\/?$/, "/")}adlc`;

export type WorkflowPluginRecord = {
  id: string;
  run_id?: string;
  task_id?: string | null;
  operation: "HEALTH" | "MEMORY_CONTEXT" | "TESTFORGE_REPLAY";
  state: string;
  created_at?: string;
  job_id?: string;
  error_code?: string | null;
  verification_evidence: false;
  data: Record<string, unknown> | null;
};

export type WorkflowPluginView = {
  enabled: boolean;
  configuration_error?: string | null;
  connections: {
    connection: string;
    memory_configured: boolean;
    replay_configured: boolean;
    memory_dataset?: string | null;
    replay_target?: string | null;
    replay_session?: string | null;
  }[];
  records: WorkflowPluginRecord[];
};

export const workflowPluginApi = {
  view: async (runId: string) =>
    (
      await api.get<WorkflowPluginView>(
        `${root}/runs/${encodeURIComponent(runId)}/workflow-plugins`,
      )
    ).data,
  health: async (runId: string, callId: string) =>
    (
      await api.post<WorkflowPluginRecord>(
        `${root}/runs/${encodeURIComponent(runId)}/workflow-plugins/health`,
        { call_id: callId },
      )
    ).data,
};
