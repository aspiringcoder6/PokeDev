import { render, screen, waitFor } from "@testing-library/react";
import { listContractExecutions } from "@/controllers/API/contracts";
import type { ContractExecutionRead } from "@/types/contractExecution";
import { copyContract } from "../ContractViewer/test-fixtures";
import ContractExecutionPanel from ".";
import { supportedExecution } from "./model";

jest.mock("@/controllers/API/contracts", () => ({
  listContractExecutions: jest.fn(),
}));
const list = listContractExecutions as jest.MockedFunction<
  typeof listContractExecutions
>;
function fixture(): ContractExecutionRead {
  const contract = copyContract();
  contract.status = "APPROVED";
  contract.document.constraints.read_only = false;
  contract.document.constraints.allowed_paths = ["demo.json"];
  contract.document.nodes.forEach((node) => {
    node.acceptance_criteria =
      node.kind === "TASK"
        ? [
            {
              description: "Nonempty captured patch",
              verification: "ARTIFACT",
              verifier_ref: "verifier:contract-source-patch/0.1.0",
            },
          ]
        : [];
  });
  contract.approval = {
    approval_id: "approval",
    reference: contract.reference,
    approved_by: "owner",
    approved_at: "2026-10-08T10:00:00Z",
    comment: null,
  };
  const criteria = contract.document.nodes.flatMap((node) =>
    node.acceptance_criteria.map((c, i) => ({
      node_id: node.node_id,
      criterion_index: i,
      verifier_ref: c.verifier_ref!,
    })),
  );
  return {
    contract,
    binding: {
      schema_version: "0.1",
      scope: {
        ...contract.binding,
        workflow_run_id: "run-execution",
        session_id: "session-execution",
      },
      execution_plan_id: "plan-execution",
      resolved_node_digest: `sha256:${"b".repeat(64)}`,
      reference: contract.reference,
      policy_digest: `sha256:${"c".repeat(64)}`,
      bound_at: "2026-10-08T10:00:00Z",
      policy: {
        policy_ref: "policy:adlc-contract-repository/0.1.0",
        contract_reference: contract.reference,
        read_only: false,
        allowed_paths: ["demo.json"],
        denied_actions: [
          "commit",
          "push",
          "deploy",
          "network",
          "shell",
          "subagent",
          "delete",
        ],
        criteria,
        natural_language_enforced: false,
      },
    },
    proof: {
      reference: contract.reference,
      policy_digest: `sha256:${"c".repeat(64)}`,
      artifact_id: "artifact-execution",
      artifact_checksum: `sha256:${"d".repeat(64)}`,
      base_commit: "e".repeat(40),
      changed_paths: ["demo.json"],
      checks: criteria.map((c) => ({ ...c, passed: true })),
      checked_at: "2026-10-08T10:01:00Z",
      criteria_executed: true,
      execution_policy_enforced: true,
      natural_language_enforced: false,
    },
  };
}
beforeEach(() => jest.clearAllMocks());

test("shows exact binding and captured predicates without claiming semantic contract completion", async () => {
  const row = fixture();
  list.mockResolvedValue([row]);
  render(<ContractExecutionPanel scope={{ runId: "run-execution" }} />);
  expect(
    await screen.findByText("Registered machine predicates passed"),
  ).toBeInTheDocument();
  expect(screen.getByText(/Natural-language scope/)).toBeInTheDocument();
  expect(screen.getByText(/Captured artifact/)).toHaveTextContent(
    row.proof!.artifact_checksum,
  );
  expect(screen.getByText(/Policy sha256/)).toHaveTextContent(
    row.binding.policy_digest,
  );
  expect(list).toHaveBeenCalledWith({ runId: "run-execution" });
});
test("pending binding and failed predicates do not display success", async () => {
  const row = fixture();
  row.proof = null;
  list.mockResolvedValue([row]);
  const { unmount } = render(
    <ContractExecutionPanel scope={{ runId: "run-execution" }} />,
  );
  expect(
    await screen.findByText(/Verification evidence has not been recorded/),
  ).toBeInTheDocument();
  expect(
    screen.queryByText("Registered machine predicates passed"),
  ).not.toBeInTheDocument();
  unmount();
  const failed = fixture();
  const task = failed.contract.document.nodes.find((n) => n.kind === "TASK")!;
  task.acceptance_criteria.push({
    description: "Changed JSON parses",
    verification: "TEST",
    verifier_ref: "verifier:contract-json-syntax/0.1.0",
  });
  const criterion = {
    node_id: task.node_id,
    criterion_index: 1,
    verifier_ref: "verifier:contract-json-syntax/0.1.0",
  };
  failed.binding.policy.criteria.push(criterion);
  failed.proof!.checks.push({ ...criterion, passed: false });
  list.mockResolvedValue([failed]);
  render(<ContractExecutionPanel scope={{ sessionId: "session-execution" }} />);
  expect(
    await screen.findByText("Machine predicates rejected this candidate"),
  ).toBeInTheDocument();
  expect(list).toHaveBeenLastCalledWith({ sessionId: "session-execution" });
});
test.each([
  "ref",
  "predicate",
  "permission",
  "missing-check",
  "semantic-claim",
  "path-list",
  "out-of-scope",
  "sensitive-path",
  "inconsistent-check",
])("%s mismatch uses escaped fallback only", async (kind) => {
  const row = fixture();
  if (kind === "ref")
    row.proof!.reference = { ...row.contract.reference, revision: 99 };
  if (kind === "predicate") row.proof!.checks[0].verifier_ref = "unknown";
  if (kind === "permission") row.binding.policy.denied_actions = [];
  if (kind === "missing-check") row.proof!.checks = [];
  if (kind === "semantic-claim")
    Object.assign(row.proof!, { natural_language_enforced: true });
  if (kind === "path-list")
    Object.assign(row.proof!, { changed_paths: [false] });
  if (kind === "out-of-scope") row.proof!.changed_paths = ["elsewhere.txt"];
  if (kind === "sensitive-path") row.proof!.changed_paths = [".env"];
  if (kind === "inconsistent-check") row.proof!.checks[0].passed = false;
  expect(supportedExecution(row)).toBe(false);
  row.contract.document.title = '<script>alert("x")</script>';
  list.mockResolvedValue([row]);
  const { container } = render(
    <ContractExecutionPanel scope={{ runId: "run-execution" }} />,
  );
  expect(await screen.findByText(/Showing escaped JSON/)).toBeInTheDocument();
  expect(
    screen.queryByText("Registered machine predicates passed"),
  ).not.toBeInTheDocument();
  expect(container.querySelector("script,img")).toBeNull();
});
test("evidence from the wrong run cannot display a completion badge", async () => {
  list.mockResolvedValue([fixture()]);
  render(<ContractExecutionPanel scope={{ runId: "another-run" }} />);
  expect(await screen.findByText(/Showing escaped JSON/)).toBeInTheDocument();
  expect(
    screen.queryByText("Registered machine predicates passed"),
  ).not.toBeInTheDocument();
});
test("late previous-scope responses cannot replace the current execution evidence", async () => {
  let finish: (rows: ContractExecutionRead[]) => void = () => {};
  list
    .mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    )
    .mockResolvedValueOnce([]);
  const { rerender } = render(
    <ContractExecutionPanel scope={{ runId: "old" }} />,
  );
  rerender(<ContractExecutionPanel scope={{ runId: "new" }} />);
  await waitFor(() => expect(list).toHaveBeenCalledWith({ runId: "new" }));
  finish([fixture()]);
  await waitFor(() =>
    expect(
      screen.queryByText("Registered machine predicates passed"),
    ).not.toBeInTheDocument(),
  );
});
test("read failure removes unconfirmed evidence and never implies completion", async () => {
  list.mockRejectedValue(new Error("offline"));
  render(<ContractExecutionPanel scope={{ runId: "run-execution" }} />);
  expect(
    await screen.findByText(/No completion claim is available/),
  ).toBeInTheDocument();
});
