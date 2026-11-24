import "@testing-library/jest-dom";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  cycleFixture,
  cycleIds,
} from "../../../tests/delivery-workspace-preview/fixture";
import { axe } from "@/utils/a11y-test";
import CyclePanel from "./cycle-panel";

function props(row = cycleFixture()) {
  return {
    row,
    disabled: false,
    onSelectCycle: jest.fn(),
    onPrepareCycle: jest.fn().mockResolvedValue(undefined),
    onUpdateCycle: jest.fn().mockResolvedValue(undefined),
    onAdvanced: jest.fn(),
  };
}

test("selecting history only navigates, never prepares or executes", () => {
  const input = props(cycleFixture("initial", true));
  render(<CyclePanel {...input} />);
  fireEvent.change(screen.getByLabelText("Chu kỳ đang xem"), {
    target: { value: cycleIds.next },
  });
  expect(input.onSelectCycle).toHaveBeenCalledWith(cycleIds.next);
  expect(input.onPrepareCycle).not.toHaveBeenCalled();
  expect(
    screen.queryByRole("button", { name: /Chuẩn bị chu kỳ tiếp theo/ }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByText(/Lịch sử chu kỳ & kế hoạch/));
  fireEvent.click(screen.getByRole("button", { name: /Kế hoạch v1/ }));
  expect(input.onAdvanced).toHaveBeenCalledWith(`/plans/${input.row.plan_id}`);
});

test("preparing requires an explicit goal and submits the frozen snapshot only once", async () => {
  const input = props();
  render(<CyclePanel {...input} />);
  fireEvent.click(
    screen.getByRole("button", { name: /Chuẩn bị chu kỳ tiếp theo/ }),
  );
  expect(input.onPrepareCycle).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Lưu bản nháp" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Mục tiêu cho chu kỳ này"), {
    target: { value: " Add CSV export " },
  });
  fireEvent.click(screen.getByRole("button", { name: "Lưu bản nháp" }));
  await waitFor(() => expect(input.onPrepareCycle).toHaveBeenCalledTimes(1));
  expect(input.onPrepareCycle).toHaveBeenCalledWith(
    input.row,
    "Add CSV export",
    expect.any(String),
  );
  expect(input.onUpdateCycle).not.toHaveBeenCalled();
});

test("editing a draft saves a new spec, not another cycle", async () => {
  const input = props(cycleFixture("draft"));
  render(<CyclePanel {...input} />);
  fireEvent.click(screen.getByRole("button", { name: "Chỉnh mục tiêu" }));
  fireEvent.change(screen.getByLabelText("Mục tiêu cho chu kỳ này"), {
    target: { value: "CSV only" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Lưu bản nháp" }));
  await waitFor(() =>
    expect(input.onUpdateCycle).toHaveBeenCalledWith(
      input.row,
      "CSV only",
      expect.any(String),
    ),
  );
  expect(input.onPrepareCycle).not.toHaveBeenCalled();
});

test("a long legacy requirement is collapsed rather than flooding the cycle summary", () => {
  const input = props();
  input.row.cycle!.goal = "Build a task board.\n\nLOCKED SPECIFICATION JSON";
  render(<CyclePanel {...input} />);
  expect(screen.getByText("Build a task board.…")).toBeVisible();
  expect(screen.getByText(/LOCKED SPECIFICATION JSON/)).not.toBeVisible();
  fireEvent.click(screen.getByText("Mở toàn bộ mục tiêu & yêu cầu"));
  expect(screen.getByText(/LOCKED SPECIFICATION JSON/)).toBeVisible();
});

test("a stale revision blocks submission but permits dismissal", () => {
  const input = props();
  const { rerender } = render(<CyclePanel {...input} />);
  fireEvent.click(
    screen.getByRole("button", { name: /Chuẩn bị chu kỳ tiếp theo/ }),
  );
  fireEvent.change(screen.getByLabelText("Mục tiêu cho chu kỳ này"), {
    target: { value: "Export" },
  });
  rerender(
    <CyclePanel
      {...input}
      row={{ ...input.row, revision: input.row.revision + 1 }}
    />,
  );
  expect(screen.getByRole("button", { name: "Lưu bản nháp" })).toBeDisabled();
  expect(screen.getByRole("alert")).toHaveTextContent("Dữ liệu vừa thay đổi");
  fireEvent.click(screen.getByRole("button", { name: "Hủy" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(input.onPrepareCycle).not.toHaveBeenCalled();
});

test("read-only access can browse history but cannot create or revise a draft", () => {
  const input = props(cycleFixture("draft"));
  input.row = {
    ...input.row,
    permissions: { write: false, execute: false },
    cycle_capabilities: {
      prepare: false,
      execute: false,
      edit_workflow: false,
    },
  };
  render(<CyclePanel {...input} />);
  expect(screen.getByLabelText("Chu kỳ đang xem")).not.toBeDisabled();
  expect(screen.getByRole("button", { name: "Chỉnh mục tiêu" })).toBeDisabled();
  expect(
    screen.getByRole("button", { name: /Chuẩn bị chu kỳ tiếp theo/ }),
  ).toBeDisabled();
});

test("cycle controls have no detected axe violations and keyboard form dismissal works", async () => {
  const input = props();
  const { container } = render(<CyclePanel {...input} />);
  expect(await axe(container)).toHaveNoViolations();
  const user = userEvent.setup();
  screen.getByRole("button", { name: /Chuẩn bị chu kỳ tiếp theo/ }).focus();
  await user.keyboard("{Enter}");
  const dialog = screen.getByRole("dialog");
  expect(
    within(dialog).getByLabelText("Mục tiêu cho chu kỳ này"),
  ).toBeInTheDocument();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
