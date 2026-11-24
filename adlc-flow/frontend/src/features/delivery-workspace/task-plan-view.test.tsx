import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "@/utils/a11y-test";
import {
  fixture,
  taskGraphFixture,
} from "../../../tests/delivery-workspace-preview/fixture";
import { boardTasks } from "./model";
import TaskPlanView from "./task-plan-view";

test("compiler-validated diamond is rendered once per task with both join edges", () => {
  const row = taskGraphFixture();
  const onSelect = jest.fn();
  const before = JSON.stringify(row);
  render(
    <TaskPlanView row={row} tasks={boardTasks(row)} onSelect={onSelect} />,
  );
  expect(screen.getAllByTestId("plan-task-node")).toHaveLength(4);
  expect(screen.getAllByTestId("plan-task-edge")).toHaveLength(4);
  const join = row.plan!.tasks.find(
    (task) => task.dependency_task_ids.length === 2,
  )!;
  const incoming = screen
    .getAllByTestId("plan-task-edge")
    .filter(
      (edge) => edge.getAttribute("data-target-task-id") === join.plan_task_id,
    );
  expect(
    incoming.map((edge) => edge.getAttribute("data-source-task-id")).sort(),
  ).toEqual([...join.dependency_task_ids].sort());
  fireEvent.click(screen.getByRole("button", { name: join.name }));
  expect(onSelect).toHaveBeenCalledWith(
    expect.objectContaining({ id: join.plan_task_id }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Danh sách" }));
  const listIds = Array.from(
    document.querySelectorAll("[data-plan-task-id]"),
  ).map((node) => node.getAttribute("data-plan-task-id"));
  expect(listIds).toEqual(row.plan!.tasks.map((task) => task.plan_task_id));
  expect(JSON.stringify(row)).toBe(before);
});

test("zoom is bounded, resets, and never changes tasks or dependency data", () => {
  const row = fixture(2);
  const onSelect = jest.fn();
  render(
    <TaskPlanView row={row} tasks={boardTasks(row)} onSelect={onSelect} />,
  );
  const zoomOut = screen.getByRole("button", { name: "Thu nhỏ sơ đồ" });
  const zoomIn = screen.getByRole("button", { name: "Phóng to sơ đồ" });
  for (let i = 0; i < 15; i++) fireEvent.click(zoomOut);
  expect(zoomOut).toBeDisabled();
  expect(screen.getByTestId("plan-task-graph")).toHaveStyle({
    transform: "scale(0.5)",
  });
  for (let i = 0; i < 15; i++) fireEvent.click(zoomIn);
  expect(zoomIn).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Đặt lại sơ đồ 100%" }));
  expect(screen.getByTestId("plan-task-graph")).toHaveStyle({
    transform: "scale(1)",
  });
  expect(screen.getAllByTestId("plan-task-node")).toHaveLength(5);
  expect(onSelect).not.toHaveBeenCalled();
});

test("runtime node status follows task IDs, not array position", () => {
  const row = fixture(3);
  row.run!.tasks.reverse();
  render(
    <TaskPlanView row={row} tasks={boardTasks(row)} onSelect={jest.fn()} />,
  );
  const node = screen.getByRole("button", {
    name: row.plan!.tasks[2].name,
  });
  expect(node).toHaveTextContent("Đang thực hiện");
  expect(node).not.toHaveTextContent("Hoàn tất");
});

test("an empty plan stays empty rather than creating tasks from workflow stages", () => {
  const row = fixture(2);
  row.plan!.tasks = [];
  render(
    <TaskPlanView row={row} tasks={boardTasks(row)} onSelect={jest.fn()} />,
  );
  expect(screen.queryAllByTestId("plan-task-node")).toHaveLength(0);
  expect(screen.getByText("This plan has no tasks to display.")).toBeVisible();
});

test("graph controls are keyboard operable and have no detected axe violations", async () => {
  const row = taskGraphFixture();
  const onSelect = jest.fn();
  const { container } = render(
    <TaskPlanView row={row} tasks={boardTasks(row)} onSelect={onSelect} />,
  );
  expect(await axe(container)).toHaveNoViolations();
  const user = userEvent.setup();
  screen.getByRole("button", { name: row.plan!.tasks[0].name }).focus();
  await user.keyboard("{Enter}");
  expect(onSelect).toHaveBeenCalledWith(
    expect.objectContaining({ id: row.plan!.tasks[0].plan_task_id }),
  );
});
