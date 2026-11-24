import { getBaseUrl } from "@/customization/utils/urls";
import { api } from "./api";

export type EnvironmentCommand = {
  label: string;
  argv: string[];
  timeout?: number;
};
export type EnvironmentProfile = {
  name: string;
  working_directory: string;
  base: { repository_id: number; commit?: string; repository?: string } | null;
  overlays: { source: string; target: string }[];
  setup: EnvironmentCommand[];
  tests: EnvironmentCommand[];
  build: EnvironmentCommand[];
  preview: { path?: string; argv?: string[] } | null;
};
export type ProjectEnvironment = {
  project_id: string;
  revision: number;
  digest: string | null;
  profile: EnvironmentProfile;
  last_check?: EnvironmentCheck | null;
};
export type EnvironmentCheck = {
  check_id: string;
  environment_digest: string;
  base_commit?: string;
  state: string;
  error_code?: string;
  receipt?: {
    checks: {
      id: string;
      label: string;
      passed: boolean;
      stdout?: string;
      stderr?: string;
    }[];
  };
};
export type Handover = {
  state: string;
  base_branch?: string;
  pull?: {
    number: number;
    url: string;
    title: string;
    state: string;
    merged: boolean;
    merge_commit?: string;
    head: string;
    base: string;
    base_commit: string;
  };
  readiness?: {
    can_merge: boolean;
    no_ci: boolean;
    reasons: string[];
    approvals?: number;
    required_approvals?: number;
    checked_at?: string;
    ci: {
      context: string;
      state: string;
      url?: string;
      description?: string;
    }[];
  };
  merge_intent?: { command_id: string };
  issue_update?: { state: string; number: number };
};

const base = () => `${getBaseUrl().replace(/\/?$/, "/")}adlc/live`;
export const projectLifecycle = {
  stopRecovery: async (
    run: string,
    command: string,
    generation: number,
  ): Promise<unknown> =>
    (
      await api.post(`${base()}/runs/${run}/recovery/stop`, {
        command_id: command,
        expected_generation: generation,
      })
    ).data,
  environment: async (project: string): Promise<ProjectEnvironment> =>
    (await api.get(`${base()}/projects/${project}/environment`)).data,
  saveEnvironment: async (
    project: string,
    revision: number,
    profile: EnvironmentProfile,
  ): Promise<ProjectEnvironment> =>
    (
      await api.put(`${base()}/projects/${project}/environment`, {
        expected_revision: revision,
        profile,
      })
    ).data,
  checkEnvironment: async (
    project: string,
    check: string,
    digest: string,
  ): Promise<EnvironmentCheck> =>
    (
      await api.post(`${base()}/projects/${project}/environment/checks`, {
        check_id: check,
        environment_digest: digest,
      })
    ).data,
  readCheck: async (
    project: string,
    check: string,
  ): Promise<EnvironmentCheck> =>
    (await api.get(`${base()}/projects/${project}/environment/checks/${check}`))
      .data,
  recover: async (
    run: string,
    command: string,
    generation: number,
    plan?: string,
  ): Promise<unknown> =>
    (
      await api.post(`${base()}/runs/${run}/recover`, {
        command_id: command,
        expected_generation: generation,
        plan_digest: plan || null,
      })
    ).data,
  handover: async (run: string): Promise<Handover> =>
    (await api.get(`${base()}/runs/${run}/handover`)).data,
  handoverPreview: async (
    run: string,
  ): Promise<{ title: string; body: string }> =>
    (await api.get(`${base()}/runs/${run}/handover/preview`)).data,
  createPull: async (
    run: string,
    head: string,
    command: string,
  ): Promise<Handover> =>
    (
      await api.post(`${base()}/runs/${run}/handover/pull-request`, {
        head_commit: head,
        command_id: command,
      })
    ).data,
  merge: async (
    run: string,
    head: string,
    baseCommit: string,
    command: string,
    acceptNoCI: boolean,
    closeIssue: boolean,
  ): Promise<Handover> =>
    (
      await api.post(`${base()}/runs/${run}/handover/merge`, {
        head_commit: head,
        base_commit: baseCommit,
        command_id: command,
        accept_no_ci: acceptNoCI,
        close_issue: closeIssue,
      })
    ).data,
};
