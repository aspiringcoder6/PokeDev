import { fireEvent, render, screen } from "@testing-library/react";
import TaskSubtaskPanel from "./TaskSubtaskPanel";
import { makeTaskSubtasks, parallelSubtasks } from "./__fixtures__/subtasks";

// The Results tab embeds HarnessResults, which pulls in
// SanitizedMarkdown → react-syntax-highlighter (ESM-only).
jest.mock("@/components/core/sanitizedMarkdown", () => ({
  SanitizedMarkdown: () => null,
}));

const baseProps = { runId: "run-1", taskRunId: "task-1", results: [], sessions: [], tasks: [] };

describe("TaskSubtaskPanel", () => {
  it("renders progress bar with summary", () => {
    render(
      <TaskSubtaskPanel
        {...baseProps}
        data={makeTaskSubtasks(parallelSubtasks)}
      />,
    );
    expect(screen.getByTestId("subtask-progress")).toBeInTheDocument();
    expect(screen.getByText("2/3")).toBeInTheDocument();
  });

  it("renders list view by default", () => {
    render(
      <TaskSubtaskPanel
        {...baseProps}
        data={makeTaskSubtasks(parallelSubtasks)}
      />,
    );
    expect(screen.getByTestId("subtask-list")).toBeInTheDocument();
  });

  it("renders both tab triggers", () => {
    render(
      <TaskSubtaskPanel
        {...baseProps}
        data={makeTaskSubtasks(parallelSubtasks)}
      />,
    );
    expect(screen.getByTestId("subtask-view-list")).toBeInTheDocument();
    expect(screen.getByTestId("subtask-view-graph")).toBeInTheDocument();
  });

  it("shows detail panel when a subtask is selected", () => {
    render(
      <TaskSubtaskPanel
        {...baseProps}
        data={makeTaskSubtasks(parallelSubtasks)}
      />,
    );
    fireEvent.click(screen.getByTestId("subtask-item-task-1.sub-1"));
    expect(screen.getByTestId("subtask-detail")).toBeInTheDocument();
  });

  it("hides detail panel when no subtask is selected", () => {
    render(
      <TaskSubtaskPanel
        {...baseProps}
        data={makeTaskSubtasks(parallelSubtasks)}
      />,
    );
    expect(screen.queryByTestId("subtask-detail")).not.toBeInTheDocument();
  });

  it("shows demo data badge when isMockData is true", () => {
    render(
      <TaskSubtaskPanel
        {...baseProps}
        data={makeTaskSubtasks(parallelSubtasks)}
        isMockData
      />,
    );
    expect(screen.getByTestId("subtask-mock-badge")).toBeInTheDocument();
  });

  it("hides demo data badge by default", () => {
    render(
      <TaskSubtaskPanel
        {...baseProps}
        data={makeTaskSubtasks(parallelSubtasks)}
      />,
    );
    expect(screen.queryByTestId("subtask-mock-badge")).not.toBeInTheDocument();
  });
});
