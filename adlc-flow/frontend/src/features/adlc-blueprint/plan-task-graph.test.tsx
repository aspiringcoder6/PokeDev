import { fireEvent, render, screen } from "@testing-library/react";
import { makeSpec, makeTask } from "./plan-task-graph-fixtures";
import PlanTaskGraph, { buildPlanTaskGraphLayout } from "./plan-task-graph";

describe("buildPlanTaskGraphLayout", () => {
  it("layers a diamond DAG with each task placed exactly once", () => {
    const layout = buildPlanTaskGraphLayout([
      makeTask("analyze", "Analyze"),
      makeTask("backend", "Backend", ["analyze"]),
      makeTask("frontend", "Frontend", ["analyze"]),
      makeTask("testing", "Testing", ["backend", "frontend"]),
    ]);

    const levels = new Map(
      layout.nodes.map((node) => [node.task.plan_task_id, node.level]),
    );
    expect(levels.get("analyze")).toBe(0);
    expect(levels.get("backend")).toBe(1);
    expect(levels.get("frontend")).toBe(1);
    expect(levels.get("testing")).toBe(2);
    expect(layout.nodes).toHaveLength(4);
    expect(layout.edges).toHaveLength(4);
    expect(
      layout.edges.map((edge) => `${edge.sourceId}->${edge.targetId}`),
    ).toEqual([
      "analyze->backend",
      "analyze->frontend",
      "backend->testing",
      "frontend->testing",
    ]);
  });

  it("places independent tasks on the same root level", () => {
    const layout = buildPlanTaskGraphLayout([
      makeTask("one", "Task One"),
      makeTask("two", "Task Two"),
    ]);

    expect(layout.nodes.every((node) => node.level === 0)).toBe(true);
    expect(layout.edges).toHaveLength(0);
    expect(layout.nodes[0].y).toBe(layout.nodes[1].y);
    expect(layout.nodes[0].x).not.toBe(layout.nodes[1].x);
  });

  it("ignores unknown dependencies and still places the task", () => {
    const layout = buildPlanTaskGraphLayout([
      makeTask("orphan", "Orphan", ["missing-task"]),
    ]);

    expect(layout.nodes).toHaveLength(1);
    expect(layout.nodes[0].level).toBe(0);
    expect(layout.edges).toHaveLength(0);
  });

  it("stays total when the dependency data contains a cycle", () => {
    const layout = buildPlanTaskGraphLayout([
      makeTask("a", "Task A", ["b"]),
      makeTask("b", "Task B", ["a"]),
    ]);

    expect(layout.nodes).toHaveLength(2);
    expect(layout.nodes.every((node) => Number.isFinite(node.y))).toBe(true);
  });

  it("returns an empty layout for an empty plan", () => {
    expect(buildPlanTaskGraphLayout([])).toEqual({
      width: 0,
      height: 0,
      nodes: [],
      edges: [],
    });
  });
});

describe("PlanTaskGraph rendering", () => {
  it("renders one node per task, dependency captions, and edges", () => {
    const tasks = [
      makeTask("analyze", "Analyze"),
      makeTask("backend", "Backend", ["analyze"]),
      makeTask("frontend", "Frontend", ["analyze"]),
      makeTask("testing", "Testing", ["backend", "frontend"]),
    ];
    const specs = new Map(
      tasks.map((task) => [
        task.resolved_node_spec_id,
        makeSpec(task.plan_task_id),
      ]),
    );

    render(<PlanTaskGraph tasks={tasks} specs={specs} />);

    expect(screen.getByTestId("plan-task-graph")).toBeVisible();
    expect(screen.getAllByTestId("plan-task-node")).toHaveLength(4);
    expect(screen.getAllByTestId("plan-task-edge")).toHaveLength(4);
    expect(screen.getByText("Analyze")).toBeVisible();
    expect(
      screen.getAllByText("coding-agent@0.1.0 · agent-provider:mock"),
    ).toHaveLength(4);
    expect(screen.getByText(/after Backend, Frontend/)).toBeVisible();
    expect(screen.getByText(/· root task/)).toBeVisible();
    expect(screen.getAllByText(/max 2 attempt/)).toHaveLength(4);
  });

  it("shows the empty message for a plan without tasks", () => {
    render(<PlanTaskGraph tasks={[]} specs={new Map()} />);

    expect(
      screen.getByText("This plan has no tasks to display."),
    ).toBeVisible();
  });

  it("supports read-only node selection and independent arrow markers for multiple viewers", () => {
    const tasks = [makeTask("a", "Task A"), makeTask("b", "Task B", ["a"])];
    const onSelect = jest.fn();
    const { container } = render(
      <>
        <PlanTaskGraph
          tasks={tasks}
          specs={new Map()}
          onSelectTask={onSelect}
          selectedTaskId="a"
        />
        <PlanTaskGraph tasks={tasks} specs={new Map()} />
      </>,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Task B", exact: true }),
    );
    expect(onSelect).toHaveBeenCalledWith("b");
    expect(
      screen.getByRole("button", { name: "Task A", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    const markers = Array.from(container.querySelectorAll("marker")).map(
      (marker) => marker.id,
    );
    expect(new Set(markers).size).toBe(2);
    expect(
      Array.from(
        container.querySelectorAll('[data-testid="plan-task-edge"]'),
      ).map((edge) => edge.getAttribute("marker-end")),
    ).toEqual(markers.map((id) => `url(#${id})`));
  });
});
