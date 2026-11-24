import { fireEvent, render, screen } from "@testing-library/react";
import SubtaskGraph from "./SubtaskGraph";
import { diamondSubtasks, makeSubtask } from "./__fixtures__/subtasks";

describe("SubtaskGraph", () => {
  it("renders empty state when no subtasks", () => {
    render(<SubtaskGraph subtasks={[]} />);
    expect(screen.getByTestId("subtask-graph-empty")).toBeInTheDocument();
  });

  it("renders one node per subtask", () => {
    render(<SubtaskGraph subtasks={diamondSubtasks} />);
    for (const subtask of diamondSubtasks) {
      expect(
        screen.getByTestId(`subtask-graph-node-${subtask.id}`),
      ).toBeInTheDocument();
    }
  });

  it("renders edges for dependencies", () => {
    const { container } = render(<SubtaskGraph subtasks={diamondSubtasks} />);
    const edges = container.querySelectorAll("path");
    // diamondSubtasks has 4 edges: sub-1->sub-2, sub-1->sub-3, sub-2->sub-4, sub-3->sub-4
    expect(edges.length).toBe(4);
  });

  it("calls onSelect when a node is clicked", () => {
    const onSelect = jest.fn();
    render(
      <SubtaskGraph subtasks={diamondSubtasks} onSelect={onSelect} />,
    );
    fireEvent.click(screen.getByTestId("subtask-graph-node-task-1.sub-1"));
    expect(onSelect).toHaveBeenCalledWith("task-1.sub-1");
  });

  it("handles linear chain layout", () => {
    const linear = [
      makeSubtask("a", { status: "succeeded" }),
      makeSubtask("b", { status: "succeeded", dependencies: ["a"] }),
      makeSubtask("c", { status: "running", dependencies: ["b"] }),
    ];
    render(<SubtaskGraph subtasks={linear} />);
    expect(screen.getByTestId("subtask-graph-node-a")).toBeInTheDocument();
    expect(screen.getByTestId("subtask-graph-node-b")).toBeInTheDocument();
    expect(screen.getByTestId("subtask-graph-node-c")).toBeInTheDocument();
  });

  it("handles parallel subtasks at the same level", () => {
    const parallel = [
      makeSubtask("a", { status: "succeeded" }),
      makeSubtask("b", { status: "succeeded" }),
      makeSubtask("c", { status: "succeeded" }),
    ];
    render(<SubtaskGraph subtasks={parallel} />);
    for (const id of ["a", "b", "c"]) {
      expect(screen.getByTestId(`subtask-graph-node-${id}`)).toBeInTheDocument();
    }
  });
});
