import { render, screen } from "@testing-library/react";
import HarnessWorkflowResults from "./HarnessWorkflowResults";
import HarnessWorkflowReview, {
  workflowHarnessReview,
} from "./HarnessWorkflowReview";

test("review presents actual protected tests, scoped source and target without implementation labels", () => {
  const review = workflowHarnessReview({
    kind: "COMMIT",
    digest: "sha256:exact",
    repository: "aspiringcoder6/vanguard",
    evidence: { commit: "sha", target: "codex/work" },
    result: {
      candidate: {
        changes: {
          "docs/harness-demo/pagination/app.py": {
            content: "def paginate(): pass",
          },
        },
      },
      verification: {
        checks: [{ passed: true, executed_tests: 4, exit_code: 0 }],
      },
    },
  })!;
  render(<HarnessWorkflowReview review={review} />);
  expect(screen.getByText("Source: app.py")).toBeInTheDocument();
  expect(screen.getByText(/4 test thực thi/)).toBeInTheDocument();
  expect(screen.queryByText(/demo/i)).not.toBeInTheDocument();
});
test("retained publication contains the real repository branch and commit, not a new action", () => {
  render(
    <HarnessWorkflowResults
      tasks={[
        {
          id: "t",
          workflow_run_id: "r",
          key: "publish",
          name: "Push GitHub",
          task_type: "IMPLEMENTATION",
          status: "SUCCEEDED",
          dependency_task_run_ids: [],
          retry_count: 0,
          executor: {
            service: "agent-provider:harness-workflow",
            operation: "PUBLISH",
          },
          result: {
            output: {
              outputs: {
                result: {
                  publish_receipt: {
                    github_pushed: true,
                    repository: "aspiringcoder6/vanguard",
                    branch: "codex/work",
                    commit: "exact-sha",
                  },
                },
              },
            },
          },
        },
      ]}
    />,
  );
  expect(
    screen.getByRole("link", { name: "Xem thay đổi trên GitHub" }),
  ).toHaveAttribute(
    "href",
    "https://github.com/aspiringcoder6/vanguard/tree/codex/work",
  );
  expect(screen.getByText("Commit: exact-sha")).toBeInTheDocument();
});
