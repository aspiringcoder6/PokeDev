import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { cyclePlanningFixture } from "../../../tests/delivery-workspace-preview/fixture";
import { deliveryApi } from "@/controllers/API/delivery";
import { axe } from "@/utils/a11y-test";
import CyclePlanning from "./cycle-planning";

jest.mock("@/controllers/API/delivery", () => ({
  ...jest.requireActual("@/controllers/API/delivery"),
  deliveryApi: {
    planningContext: jest.fn(),
    freezePlanning: jest.fn(),
    generateDetailed: jest.fn(),
    reconcilePlanning: jest.fn(),
    acceptGraph: jest.fn(),
  },
}));
beforeEach(() => jest.clearAllMocks());
function props(row = cyclePlanningFixture()) {
  return { row, disabled: false, onRefresh: jest.fn(), onAdvanced: jest.fn() };
}
test("reading a preview never generates, accepts or starts work", () => {
  render(<CyclePlanning {...props()} />);
  expect(screen.getByText(/Graph đã kiểm tra/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Duyệt graph này" })).toBeEnabled();
  expect(deliveryApi.generateDetailed).not.toHaveBeenCalled();
  expect(deliveryApi.acceptGraph).not.toHaveBeenCalled();
  expect(
    screen.queryByRole("button", { name: /Bắt đầu thực hiện/ }),
  ).not.toBeInTheDocument();
});
test("exact graph approval requires review and submits the selected cycle snapshot", async () => {
  (deliveryApi.acceptGraph as jest.Mock).mockResolvedValue({ approved: true });
  const input = props();
  render(<CyclePlanning {...input} />);
  fireEvent.click(screen.getByRole("button", { name: "Duyệt graph này" }));
  expect(screen.getByRole("button", { name: "Xác nhận" })).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Xác nhận" }));
  await waitFor(() => expect(deliveryApi.acceptGraph).toHaveBeenCalledTimes(1));
  expect(deliveryApi.acceptGraph).toHaveBeenCalledWith(
    input.row,
    input.row.cycle!.planning_operations![0],
    expect.any(String),
  );
  expect(deliveryApi.generateDetailed).not.toHaveBeenCalled();
});
test("stale approval cannot accept a refreshed cycle/graph", () => {
  const input = props();
  const { rerender } = render(<CyclePlanning {...input} />);
  fireEvent.click(screen.getByRole("button", { name: "Duyệt graph này" }));
  fireEvent.click(screen.getByRole("checkbox"));
  rerender(
    <CyclePlanning
      {...input}
      row={{ ...input.row, revision: input.row.revision + 1 }}
    />,
  );
  expect(screen.getByRole("button", { name: "Xác nhận" })).toBeDisabled();
  expect(screen.getByRole("alert")).toHaveTextContent("Dữ liệu vừa thay đổi");
  expect(deliveryApi.acceptGraph).not.toHaveBeenCalled();
});
test("unknown acknowledgement exposes observation only, not another paid call", () => {
  const input = props(cyclePlanningFixture("RUNNING"));
  input.row.cycle!.planning_operations![0].status = "UNCONFIRMED";
  input.row.cycle!.planning_operations![0].phase = "UNCONFIRMED";
  render(<CyclePlanning {...input} />);
  expect(
    screen.getByRole("button", { name: "Đối soát trạng thái" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /Tạo task chi tiết|Tạo đề xuất mới/ }),
  ).not.toBeInTheDocument();
  expect(deliveryApi.generateDetailed).not.toHaveBeenCalled();
  expect(deliveryApi.reconcilePlanning).not.toHaveBeenCalled();
});
test("accepted graph remains separate from execution authority", () => {
  render(<CyclePlanning {...props(cyclePlanningFixture("ACCEPTED"))} />);
  expect(screen.getByText(/Đã duyệt graph cho chu kỳ/)).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Duyệt graph này" }),
  ).not.toBeInTheDocument();
  expect(screen.getByText(/chưa tự mở quyền chạy/)).toBeInTheDocument();
});
test("read-only preview is accessible and does not call external APIs", async () => {
  const input = props();
  input.row.permissions.write = false;
  const { container } = render(<CyclePlanning {...input} />);
  expect(
    screen.getByRole("button", { name: "Duyệt graph này" }),
  ).toBeDisabled();
  expect(await axe(container)).toHaveNoViolations();
});
