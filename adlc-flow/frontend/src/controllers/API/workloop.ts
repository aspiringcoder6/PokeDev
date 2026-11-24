import { z } from "zod";
import { getBaseUrl } from "@/customization/utils/urls";
import { api } from "./api";

const testCheck = z.object({
  check_id: z.string(),
  exit_code: z.number(),
  stdout: z.string(),
  stderr: z.string(),
});
const preview = z.object({
  preview_id: z.string(),
  state: z.string(),
  source_sha256: z.string(),
  sandbox_id: z.string(),
  expires_at: z.string(),
  url: z.string().nullable().optional(),
  error_code: z.string().optional(),
  tests: z
    .object({
      passed: z.boolean(),
      protected_intact: z.boolean(),
      checks: z.array(testCheck),
    })
    .optional(),
  http: z
    .object({
      passed: z.boolean(),
      checks: z.array(
        z.object({ id: z.string(), label: z.string(), passed: z.boolean() }),
      ),
    })
    .optional(),
});
const run = z.object({
  run_id: z.string(),
  factory: z.string(),
  workflow: z.string(),
  state: z.string(),
  created_at: z.string(),
  model: z.object({ provider: z.string(), model: z.string() }),
  nodes: z.array(
    z.object({
      id: z.string(),
      state: z.string(),
      summary: z.string().optional(),
      session_id: z.string().nullable().optional(),
    }),
  ),
  events: z.array(
    z.object({ node: z.string(), state: z.string(), at: z.number() }),
  ),
  preview: preview.optional(),
  error_code: z.string().optional(),
  job_id: z.string().optional(),
  canonical_cycle_execution: z.literal(false),
});
const listing = z.object({
  context: z.object({
    context_digest: z.string(),
    candidate: z
      .object({ loop_id: z.string(), source_sha256: z.string() })
      .nullable(),
    factories: z.array(
      z.object({
        id: z.string(),
        revision: z.string(),
        workflows: z.array(
          z.object({
            id: z.string(),
            description: z.string(),
            enabled: z.boolean(),
            reason: z.string().nullable(),
            nodes: z.array(z.object({ id: z.string(), role: z.string() })),
          }),
        ),
      }),
    ),
  }),
  capabilities: z.object({
    ready: z.boolean(),
    preview_ready: z.boolean(),
    engine_revision: z.string(),
    model: z.object({ provider: z.string(), model: z.string() }),
    max_duration_seconds: z.number(),
    token_cost_cap: z.boolean(),
  }),
  inventory: z.object({
    observed_at: z.string(),
    error_code: z.string().nullable(),
    plugins: z.array(
      z.object({
        name: z.string(),
        version: z.string().nullable(),
        loaded: z.boolean(),
        runtime_tools: z.boolean(),
      }),
    ),
  }),
  runs: z.array(run),
});
export type WorkloopRun = z.infer<typeof run>;
export type WorkloopListing = z.infer<typeof listing>;
const path = (id: string) =>
  `${getBaseUrl().replace(/\/?$/, "/")}adlc/deliveries/${encodeURIComponent(id)}/workloop`;
export const workloop = {
  list: async (id: string, cycle: string) =>
    listing.parse(
      (await api.get(path(id), { params: { cycle_id: cycle } })).data,
    ),
  start: async (
    id: string,
    body: {
      cycle_id: string;
      run_id: string;
      factory: string;
      workflow: string;
      context_digest: string;
    },
  ) => run.parse((await api.post(path(id), body)).data),
};
