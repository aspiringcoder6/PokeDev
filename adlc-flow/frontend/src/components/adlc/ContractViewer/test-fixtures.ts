import type { ContractRead } from "@/types/contracts";

export const contractFixture: ContractRead = {
  schema_version: "0.1",
  document: {
    schema_version: "0.1",
    document_type: "skilltree",
    schema_ref: "adlc://schemas/skilltree-contract/0.1",
    producer_plugin: "plugin:vai-adlc-skilltree/0.1.0",
    renderer_ref: "adlc-renderer:skilltree/0.1",
    contract_id: "10000000-0000-4000-8000-000000000001",
    revision: 3,
    title: "ADLC plugin roadmap",
    scope: {
      objective: "Deliver a small, reviewable slice",
      in_scope: ["Shared viewer and exact review"],
      out_of_scope: ["Automatic execution"],
    },
    constraints: {
      read_only: true,
      allowed_paths: ["*"],
      forbidden_actions: ["commit", "push"],
    },
    supersedes: null,
    nodes: [
      {
        node_id: "10000000-0000-4000-8000-000000000002",
        kind: "MILESTONE",
        title: "Shared contract view",
        description: "One durable source for both hosts",
        acceptance_criteria: [],
      },
      {
        node_id: "10000000-0000-4000-8000-000000000003",
        kind: "TASK",
        title: "Render the complete acceptance criteria",
        description:
          "Keep full text available even when the graph title is short.",
        acceptance_criteria: [
          {
            description:
              "Human can inspect the full roadmap and exact reference",
            verification: "HUMAN",
            verifier_ref: null,
          },
        ],
      },
      {
        node_id: "10000000-0000-4000-8000-000000000004",
        kind: "DECISION",
        title: "Approve an exact revision",
        description: "Separate contract approval from submitting the run.",
        acceptance_criteria: [],
      },
    ],
    dependencies: [
      {
        source_id: "10000000-0000-4000-8000-000000000002",
        target_id: "10000000-0000-4000-8000-000000000003",
        relation: "CONTAINS",
      },
      {
        source_id: "10000000-0000-4000-8000-000000000003",
        target_id: "10000000-0000-4000-8000-000000000004",
        relation: "REQUIRES",
      },
    ],
  },
  reference: {
    schema_ref: "adlc://schemas/skilltree-contract/0.1",
    contract_id: "10000000-0000-4000-8000-000000000001",
    revision: 3,
    content_digest: `sha256:${"a".repeat(64)}`,
  },
  binding: {
    workflow_run_id: "run-one",
    task_run_id: "task-one",
    session_id: "session-one",
    request_id: "request-one",
    attempt_id: "attempt-one",
  },
  status: "VALIDATED",
  validation: {
    content_digest: `sha256:${"a".repeat(64)}`,
    passed: true,
    criteria_executed: false,
    checked_at: "2026-10-07T10:00:00Z",
    validator_ref: "adlc-validator:skilltree/0.1",
    checks: [
      {
        check_id: "tasks",
        passed: true,
        summary: "Tasks declare acceptance criteria",
      },
    ],
  },
  approval: null,
  created_at: "2026-10-07T09:00:00Z",
  authored_by: "harness-session:session-one",
  authored_via: "HARNESS_TOOL",
};
export const copyContract = () =>
  JSON.parse(JSON.stringify(contractFixture)) as ContractRead;
