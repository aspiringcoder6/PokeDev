import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { intakeApi, type IntakeRequest } from "./api";
import IntakePage from "./intake-page";

const mockNavigate = jest.fn();
jest.mock("./lark-conversation-panel", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("./lark-link-panel", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/customization/hooks/use-custom-navigate", () => ({
  __esModule: true,
  useCustomNavigate: () => mockNavigate,
}));
jest.mock("./api", () => ({
  intakeApi: {
    list: jest.fn(),
    projects: jest.fn(),
    get: jest.fn(),
    history: jest.fn(),
    create: jest.fn(),
    update: jest.fn(),
  },
}));
const api = jest.mocked(intakeApi);
const id = "00000000-0000-4000-8000-000000000101";
const row: IntakeRequest = {
  id,
  project_id: null,
  revision: 1,
  status: "NEW",
  content_digest: "sha256:" + "a".repeat(64),
  created_at: "2026-11-25T01:00:00Z",
  updated_at: "2026-11-25T01:00:00Z",
  content: {
    title: "Monthly revenue",
    description: "Export revenue by month",
    scope_in: [],
    scope_out: [],
    constraints: [],
    acceptance_criteria: [],
    assumptions: [],
  },
};
function show(path = "/intake") {
  render(
    <MemoryRouter
      initialEntries={[path]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <Routes>
        <Route path="/intake/:requestId?" element={<IntakePage />} />
      </Routes>
    </MemoryRouter>,
  );
}
beforeEach(() => {
  jest.clearAllMocks();
  api.list.mockResolvedValue({ items: [], total: 0 });
  api.projects.mockResolvedValue([]);
  api.get.mockResolvedValue(row);
  api.history.mockResolvedValue({
    items: [{ revision: 1, created_at: row.created_at, snapshot: row }],
  });
  api.create.mockReset();
  api.update.mockReset();
  Object.defineProperty(crypto, "randomUUID", {
    configurable: true,
    value: jest.fn(() => "00000000-0000-4000-8000-000000000201"),
  });
});

test("new request submits only user content and navigates to its durable ID", async () => {
  api.create.mockResolvedValue({ request: row, replayed: false });
  show();
  fireEvent.change(screen.getByLabelText("Tiêu đề"), {
    target: { value: "Monthly revenue" },
  });
  fireEvent.change(screen.getByLabelText("Mô tả yêu cầu"), {
    target: { value: "Export revenue by month" },
  });
  fireEvent.change(screen.getByLabelText("Tiêu chí nghiệm thu"), {
    target: { value: "  CSV has month column\n\nAmounts match the source  " },
  });
  fireEvent.click(screen.getByRole("button", { name: "Lưu yêu cầu" }));
  await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1));
  expect(api.create.mock.calls[0][0]).toEqual({
    command_id: expect.any(String),
    project_id: null,
    content: {
      ...row.content,
      acceptance_criteria: ["CSV has month column", "Amounts match the source"],
    },
  });
  await waitFor(() =>
    expect(mockNavigate).toHaveBeenCalledWith(`/intake/${id}`),
  );
});

test("an uncertain save freezes edits and retries the exact same command", async () => {
  api.create
    .mockRejectedValueOnce(new Error("Connection lost"))
    .mockResolvedValueOnce({ request: row, replayed: true });
  show();
  fireEvent.change(screen.getByLabelText("Tiêu đề"), {
    target: { value: row.content.title },
  });
  fireEvent.change(screen.getByLabelText("Mô tả yêu cầu"), {
    target: { value: row.content.description },
  });
  fireEvent.click(screen.getByRole("button", { name: "Lưu yêu cầu" }));
  await screen.findByText(/Chưa xác nhận được kết quả/);
  expect(screen.getByLabelText("Tiêu đề")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Thử lại để đối soát" }));
  await waitFor(() => expect(api.create).toHaveBeenCalledTimes(2));
  expect(api.create.mock.calls[0][0]).toEqual(api.create.mock.calls[1][0]);
});

test("revision conflicts preserve the draft instead of replacing it", async () => {
  api.update.mockRejectedValue({
    response: {
      status: 409,
      data: { detail: { code: "INTAKE_REVISION_CONFLICT" } },
    },
  });
  show(`/intake/${id}`);
  await screen.findByDisplayValue(row.content.title);
  fireEvent.change(screen.getByLabelText("Tiêu đề"), {
    target: { value: "My unsaved CSV scope" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Lưu thay đổi" }));
  await screen.findByText(/Yêu cầu đã có phiên bản mới/);
  expect(screen.getByLabelText("Tiêu đề")).toHaveValue("My unsaved CSV scope");
  expect(api.update.mock.calls[0][1].expected_revision).toBe(1);
});

test("cancelled requests keep their history and cannot be edited", async () => {
  api.get.mockResolvedValue({ ...row, status: "CANCELLED", revision: 2 });
  show(`/intake/${id}`);
  await screen.findByDisplayValue(row.content.title);
  expect(screen.getByLabelText("Tiêu đề")).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: "Lưu thay đổi" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("region", { name: "Lịch sử yêu cầu" }),
  ).toBeInTheDocument();
});
