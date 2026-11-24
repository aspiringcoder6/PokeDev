import { z } from "zod";
import { getBaseUrl } from "@/customization/utils/urls";
import { api } from "./api";

const checks = z.object({
  passed: z.boolean().optional(),
  protected_intact: z.boolean().optional(),
  checks: z
    .array(
      z.object({
        check_id: z.string(),
        exit_code: z.number(),
        stdout: z.string(),
        stderr: z.string(),
      }),
    )
    .optional(),
});
const loop = z.object({
  loop_id: z.string(),
  state: z.enum(["RESERVED", "RUNNING", "UNCONFIRMED", "SUCCEEDED", "FAILED"]),
  created_at: z.string(),
  baseline: checks.optional(),
  iterations: z
    .array(checks.extend({ number: z.number(), state: z.string() }))
    .optional(),
  changed_paths: z.array(z.string()).optional(),
  files: z.record(z.string()).optional(),
  diff: z.string(),
  model: z.object({ provider: z.string(), model: z.string() }).optional(),
  contract: z.object({ status: z.string() }).passthrough().optional(),
  goal_state: z
    .object({ phase: z.string() })
    .passthrough()
    .nullable()
    .optional(),
  memory: z
    .object({ mode: z.string(), recalled: z.boolean() })
    .passthrough()
    .optional(),
  error_code: z.string().nullable().optional(),
  summary: z.string().optional(),
  canonical_cycle_execution: z.literal(false),
  release_status: z.literal("REVIEW_REQUIRED"),
});
const listing = z.object({
  context: z
    .object({
      context_digest: z.string(),
      base_commit: z.string(),
      goal: z.string(),
      writable_paths: z.array(z.string()),
      max_iterations: z.number(),
      file_sizes: z.record(z.number()),
      checks: z.array(
        z.object({ check_id: z.string(), test_path: z.string() }),
      ),
    })
    .nullable(),
  capabilities: z
    .object({
      ready: z.boolean(),
      model: z.object({ provider: z.string(), model: z.string() }),
      max_iterations: z.number(),
    })
    .passthrough()
    .nullable(),
  error_code: z.string().nullable(),
  loops: z.array(loop),
});
export type NativeLoop = z.infer<typeof loop>;
export type NativeLoops = z.infer<typeof listing>;
const path = (id: string) =>
  `${getBaseUrl().replace(/\/?$/, "/")}adlc/deliveries/${encodeURIComponent(id)}/native-loop`;
export const nativeLoops = {
  list: async (id: string, cycle: string) =>
    listing.parse(
      (await api.get(path(id), { params: { cycle_id: cycle } })).data,
    ),
  start: async (id: string, cycle: string, context: string, identity: string) =>
    loop.parse(
      (
        await api.post(path(id), {
          cycle_id: cycle,
          loop_id: identity,
          context_digest: context,
        })
      ).data,
    ),
};
