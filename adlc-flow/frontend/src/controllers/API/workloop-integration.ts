import { getBaseUrl } from "@/customization/utils/urls";
import { api } from "./api";

export type WorkloopConnection = {
  checked_at: string;
  workloop: { available: boolean; url: string; integration_url: string };
  mcp: {
    available: boolean;
    url: string;
    server: { name: string; version: string } | null;
  };
  slack: {
    registered: boolean | null;
    connector_connected: boolean | null;
    bot_response_status: "unverified";
    app_id: string | null;
    bot_url: string | null;
    workspace_url: string;
    scope: "conversation_and_spec";
  };
  errors: string[];
};

export const workloopIntegration = {
  read: async (): Promise<WorkloopConnection> =>
    (
      await api.get(
        `${getBaseUrl().replace(/\/?$/, "/")}adlc/live/integrations/workloop`,
      )
    ).data,
};

export type SlackNotificationConnection = {
  configured: boolean;
  identity: {
    team: string;
    user: string;
    bot_id: string;
    verified_at: string;
  } | null;
};
const slackBase = () =>
  `${getBaseUrl().replace(/\/?$/, "/")}adlc/live/integrations/slack-notifications`;
export const slackNotificationConnection = {
  read: async (): Promise<SlackNotificationConnection> =>
    (await api.get(slackBase())).data,
  save: async (token: string): Promise<SlackNotificationConnection> =>
    (await api.put(slackBase(), { token })).data,
  remove: async (): Promise<SlackNotificationConnection> =>
    (await api.delete(slackBase())).data,
};
