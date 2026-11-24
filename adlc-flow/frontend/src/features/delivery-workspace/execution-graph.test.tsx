import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import ExecutionGraph, { reconcileExecutionNodes } from "./execution-graph";

jest.mock("@xyflow/react", () => {
  const React = require("react");
  const Empty = () => null;
  return {
    Background: Empty, Controls: Empty, Handle: Empty, MiniMap: Empty,
    BackgroundVariant: { Dots: "dots" }, MarkerType: { ArrowClosed: "arrow" },
    Position: { Left: "left", Right: "right" },
    ReactFlowProvider: ({ children }: { children: React.ReactNode }) => children,
    useNodesState: (initial: unknown) => {
      const [nodes, setNodes] = React.useState(initial);
      return [nodes, setNodes, (changes: any[]) => setNodes((old: any[]) => old.map((node) => {
        const change = changes.find((item) => item.type === "select" && item.id === node.id);
        return change ? { ...node, selected: change.selected } : node;
      }))];
    },
    useReactFlow: () => ({ fitView: jest.fn() }),
    ReactFlow: ({ nodes, onSelectionChange, onNodesChange, onNodeClick }: any) => {
      React.useEffect(() => {
        onSelectionChange?.({ nodes: nodes.filter((node: any) => node.selected) });
      }, [nodes, onSelectionChange]);
      return <div>{nodes.map((node: any) => <button key={node.id} aria-label={node.id} onClick={() => {
        onNodesChange(nodes.map((item: any) => ({ type: "select", id: item.id, selected: item.id === node.id })));
        onNodeClick(null, node);
      }}>{node.data.task.title} · {node.data.task.state}</button>)}</div>;
    },
  };
});

const tasks = [{ id: "P01", title: "Read approved specification", state: "RUNNING" }];

test("choosing a different task survives controlled selection notifications and parent polling copies", () => {
  const select = jest.fn();
  function Parent() {
    const [updates, setUpdates] = useState(0);
    const [selected, setSelected] = useState("P01");
    return <>
      <output aria-label="Selection updates">{updates}</output>
      <ExecutionGraph tasks={[...tasks, { id: "P02", title: "Plan tasks", state: "PENDING" }].map((task) => ({ ...task }))} edges={[]} selected={selected} select={(id) => {
        select(id);
        setSelected(id);
        setUpdates((count) => count + 1);
      }} />
    </>;
  }
  render(<Parent />);
  fireEvent.click(screen.getByRole("button", { name: "P02", exact: true }));
  expect(screen.getByLabelText("Selection updates")).toHaveTextContent("1");
  expect(select).toHaveBeenCalledTimes(1);
  expect(select).toHaveBeenLastCalledWith("P02");
  fireEvent.click(screen.getByRole("button", { name: "P01", exact: true }));
  expect(screen.getByLabelText("Selection updates")).toHaveTextContent("2");
  expect(select).toHaveBeenLastCalledWith("P01");
  expect(screen.getByText(/Read approved specification · RUNNING/)).toBeInTheDocument();
});

test("equivalent polls preserve measured dimensions and dragged positions; status still updates", () => {
  const layout = [{ id: "P01", x: 0, y: 0 }];
  const nodes = reconcileExecutionNodes([], tasks, layout, "P01", "all", true);
  const dragged = [{ ...nodes[0], position: { x: 420, y: 90 }, measured: { width: 220, height: 120 } }];
  const unchanged = reconcileExecutionNodes(dragged, tasks.map((t) => ({ ...t })), layout, "P01", "all", false);
  expect(unchanged).toBe(dragged);
  const changed = reconcileExecutionNodes(dragged, [{ ...tasks[0], state: "DONE" }], layout, "P01", "all", false);
  expect(changed[0].data.task.state).toBe("DONE");
  expect(changed[0].position).toEqual({ x: 420, y: 90 });
  expect(changed[0].measured).toEqual({ width: 220, height: 120 });
});
