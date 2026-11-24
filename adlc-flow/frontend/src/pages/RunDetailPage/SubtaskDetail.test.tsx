import { render, screen, waitFor } from "@testing-library/react";
import SubtaskDetail from "./SubtaskDetail";
import { makeSubtask } from "./__fixtures__/subtasks";

const baseProps = { runId: "run-1", taskRunId: "task-1" };

jest.mock("@/controllers/API/adlc", () => ({
  getAdlcSubtaskActivity: jest.fn().mockResolvedValue({
    source: "agent-provider:deepseek-harness",
    session_id: null,
    directory: null,
    running: false,
    entries: [],
    entries_total: 0,
    note: "HARNESS_SESSION_PENDING",
    updated_at: new Date().toISOString(),
  }),
}));

describe("SubtaskDetail", () => {
  it("renders subtask name and status", () => {
    render(
      <SubtaskDetail
        {...baseProps}
        subtask={makeSubtask("task-1.sub-1", {
          name: "Read models",
          status: "succeeded",
        })}
      />,
    );
    expect(screen.getByText("Read models")).toBeInTheDocument();
    expect(screen.getByText("succeeded")).toBeInTheDocument();
  });

  it("renders description when provided", () => {
    render(
      <SubtaskDetail
        {...baseProps}
        subtask={makeSubtask("task-1.sub-1", {
          description: "Read all model files",
        })}
      />,
    );
    expect(screen.getByText("Read all model files")).toBeInTheDocument();
  });

  it("renders error when present", () => {
    render(
      <SubtaskDetail
        {...baseProps}
        subtask={makeSubtask("task-1.sub-1", {
          status: "failed",
          error: { code: "TEST_ERROR", message: "Something went wrong" },
        })}
      />,
    );
    expect(screen.getByTestId("subtask-error")).toBeInTheDocument();
    expect(screen.getByText("TEST_ERROR")).toBeInTheDocument();
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
  });

  it("renders result when present", () => {
    render(
      <SubtaskDetail
        {...baseProps}
        subtask={makeSubtask("task-1.sub-1", {
          status: "succeeded",
          result: { summary: "Done", count: 5 },
        })}
      />,
    );
    expect(screen.getByTestId("subtask-result")).toBeInTheDocument();
    expect(screen.getByText(/summary/)).toBeInTheDocument();
  });

  it("renders dependencies as badges", () => {
    render(
      <SubtaskDetail
        {...baseProps}
        subtask={makeSubtask("task-1.sub-2", {
          dependencies: ["task-1.sub-1", "task-1.sub-0"],
        })}
      />,
    );
    expect(screen.getByText("task-1.sub-1")).toBeInTheDocument();
    expect(screen.getByText("task-1.sub-0")).toBeInTheDocument();
  });

  it("formats duration correctly", () => {
    render(
      <SubtaskDetail
        {...baseProps}
        subtask={makeSubtask("task-1.sub-1", { duration_ms: 65000 })}
      />,
    );
    expect(screen.getByText("1m 5s")).toBeInTheDocument();
  });

  it("renders execution detail panel", async () => {
    render(
      <SubtaskDetail
        {...baseProps}
        subtask={makeSubtask("task-1.sub-1", { status: "running" })}
      />,
    );
    await waitFor(() => {
      expect(
        screen.getByTestId("subtask-execution-detail"),
      ).toBeInTheDocument();
    });
  });
});
