import { fireEvent, render, screen } from "@testing-library/react";
import SubtaskList from "./SubtaskList";
import { makeSubtask } from "./__fixtures__/subtasks";

describe("SubtaskList", () => {
  it("renders empty state when no subtasks", () => {
    render(<SubtaskList subtasks={[]} />);
    expect(screen.getByTestId("subtask-list-empty")).toBeInTheDocument();
  });

  it("renders one item per subtask", () => {
    const subtasks = [
      makeSubtask("task-1.sub-1", { name: "Read models", status: "succeeded" }),
      makeSubtask("task-1.sub-2", { name: "Identify patterns", status: "running" }),
    ];
    render(<SubtaskList subtasks={subtasks} />);
    expect(screen.getByText("Read models")).toBeInTheDocument();
    expect(screen.getByText("Identify patterns")).toBeInTheDocument();
  });

  it("shows status badge for each subtask", () => {
    const subtasks = [
      makeSubtask("task-1.sub-1", { status: "succeeded" }),
      makeSubtask("task-1.sub-2", { status: "failed" }),
    ];
    render(<SubtaskList subtasks={subtasks} />);
    expect(screen.getByText("succeeded")).toBeInTheDocument();
    expect(screen.getByText("failed")).toBeInTheDocument();
  });

  it("calls onSelect when a subtask is clicked", () => {
    const onSelect = jest.fn();
    const subtasks = [makeSubtask("task-1.sub-1", { name: "Sub 1" })];
    render(<SubtaskList subtasks={subtasks} onSelect={onSelect} />);
    fireEvent.click(screen.getByTestId("subtask-item-task-1.sub-1"));
    expect(onSelect).toHaveBeenCalledWith("task-1.sub-1");
  });

  it("highlights the selected subtask", () => {
    const subtasks = [
      makeSubtask("task-1.sub-1", { name: "Sub 1" }),
      makeSubtask("task-1.sub-2", { name: "Sub 2" }),
    ];
    render(<SubtaskList subtasks={subtasks} selectedId="task-1.sub-2" />);
    const selected = screen.getByTestId("subtask-item-task-1.sub-2");
    expect(selected.className).toContain("secondary");
  });
});
