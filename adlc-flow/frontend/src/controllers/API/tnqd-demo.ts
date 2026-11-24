import { z } from "zod";
import { getBaseUrl } from "@/customization/utils/urls";
import { api } from "./api";

const task = z.object({
  id: z.string(),
  title: z.string(),
  operation: z.string(),
  role: z.string(),
  depends_on: z.array(z.string()),
  steps: z.array(z.string()),
  inputs: z.array(z.string()),
  outputs: z.array(z.string()),
  acceptance: z.array(z.string()),
  requirements: z.array(z.string()),
  write_paths: z.array(z.string()),
  executor: z.string(),
});
const node = z.object({
  id: z.string(),
  title: z.string().optional(),
  state: z.string(),
  role: z.string().optional(),
  depends_on: z.array(z.string()).optional(),
  session_id: z.string().optional(),
  started_at: z.number().optional(),
  completed_at: z.number().optional(),
  native_start_at: z.number().optional(),
  native_end_at: z.number().optional(),
  summary: z
    .union([z.string(), z.record(z.unknown())])
    .transform((value) =>
      typeof value === "string"
        ? value
        : "Đã nhận báo cáo thực thi; xem Test & Verify để đối chiếu kết quả.",
    )
    .optional(),
  error_code: z.string().optional(),
  context_receipt: z.record(z.string(), z.string()).optional(),
});
const run = z.object({
  run_id: z.string(),
  state: z.string(),
  phase: z.string(),
  created_at: z.string(),
  nodes: z.array(node),
  followup_tasks: z.array(task).optional(),
  error_code: z.string().nullable().optional(),
  plan: z
    .object({
      title: z.string(),
      summary: z.string(),
      digest: z.string(),
      tasks: z.array(task),
      layers: z.array(z.array(z.string())),
      parallel_pair: z.array(z.string()),
      max_parallel: z.number(),
    })
    .optional(),
  documents: z.array(
    z.object({
      id: z.string(),
      title: z.string(),
      revision: z.string(),
      body: z.string(),
      sha256: z.string(),
      previous_body: z.string().optional(),
    }),
  ),
  memory: z
    .array(
      z.object({
        document_id: z.string(),
        revision: z.string(),
        mode: z.string(),
        content_verified: z.boolean(),
        retrieved_at: z.string(),
        source_ref: z.string().optional(),
        sha256: z.string().optional(),
        caller_context_id: z.string().optional(),
        retrieval_id: z.string().optional(),
        harness_state: z.string().optional(),
      }),
    )
    .optional(),
  checks: z
    .array(
      z.object({
        id: z.string(),
        title: z.string(),
        kind: z.string(),
        total: z.number(),
        passed: z.number(),
        tests: z
          .array(
            z.object({
              id: z.string(),
              label: z.string(),
              status: z.string(),
              error: z.string().optional(),
            }),
          )
          .optional(),
      }),
    )
    .optional(),
  preview: z
    .object({
      state: z.string(),
      url: z.string().nullable().optional(),
      expires_at: z.string(),
      sandbox_id: z.string(),
      artifact_sha256: z.string(),
      data_mode: z.string(),
      phase: z.string().optional(),
      uploaded_chunks: z.number().optional(),
    })
    .optional(),
  parallel: z
    .object({
      verified: z.boolean(),
      overlap_seconds: z.number(),
      tasks: z.array(z.string()),
      simultaneous_samples: z.number(),
    })
    .optional(),
  handover: z
    .object({
      summary: z.string(),
      changed_files: z.array(z.string()),
      limitations: z.array(z.string()),
      source_digest: z.string(),
      test_suite_digest: z.string(),
    })
    .optional(),
});
export type TnqdTask = z.infer<typeof task>;
export type TnqdRun = z.infer<typeof run>;
export const tnqdRunSchema = run;
const listing = z.object({ runs: z.array(run) });
const base = (identity: string) =>
  `${getBaseUrl().replace(/\/?$/, "/")}adlc/deliveries/${encodeURIComponent(identity)}/tnqd-demo`;
export const tnqdDemo = {
  resume: async (id: string, body: { cycle_id: string; run_id: string }) =>
    run.parse((await api.post(base(id) + "/resume", body)).data),
  list: async (id: string, cycle: string) =>
    listing.parse(
      (await api.get(base(id), { params: { cycle_id: cycle } })).data,
    ),
  plan: async (id: string, body: { cycle_id: string; run_id: string }) =>
    run.parse((await api.post(base(id) + "/plan", body)).data),
  execute: async (
    id: string,
    body: { cycle_id: string; run_id: string; plan_digest: string },
  ) => run.parse((await api.post(base(id) + "/execute", body)).data),
};
