import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { listAdlcRuns } from "@/controllers/API/adlc";
import type { AdlcRunListResponse, AdlcWorkflowRunSummary } from "@/types/adlc";
import RunHistoryPage from ".";

const mockNavigate = jest.fn();
jest.mock("@/customization/hooks/use-custom-navigate", () => ({
  useCustomNavigate: () => mockNavigate,
}));
jest.mock("@/components/common/genericIconComponent", () => () => null);
jest.mock("@/controllers/API/adlc", () => ({ listAdlcRuns: jest.fn() }));

const run: AdlcWorkflowRunSummary = {
  id: "persisted-run-1",
  name: "Read-only report",
  execution_mode: "EXECUTION_PLAN",
  status: "WAITING_APPROVAL",
  task_count: 2,
  completed_task_count: 1,
  created_at: "2026-10-04T00:00:00Z",
  updated_at: "2026-10-04T00:01:00Z",
};
const page: AdlcRunListResponse = {
  runs: [run],
  total: 26,
  limit: 25,
  offset: 0,
};
const mockList = listAdlcRuns as jest.MockedFunction<typeof listAdlcRuns>;

function renderHistory(url = "/runs") {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <RunHistoryPage />
    </MemoryRouter>,
  );
}

describe("RunHistoryPage", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockList.mockResolvedValue(page);
  });

  it("loads durable runs and opens the original run id", async () => {
    renderHistory();
    expect(await screen.findByText("Read-only report")).toBeInTheDocument();
    expect(screen.getByText(/1\/2 tasks completed/)).toBeInTheDocument();
    expect(mockList).toHaveBeenCalledWith({
      status: undefined,
      flowId: undefined,
      limit: 25,
      offset: 0,
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Open run Read-only report" }),
    );
    expect(mockNavigate).toHaveBeenCalledWith("/runs/persisted-run-1");
  });

  it("applies status/workflow filters and resets pagination on filter changes", async () => {
    renderHistory("/runs?flowId=flow-1&offset=25");
    await screen.findByText("Read-only report");
    fireEvent.change(screen.getByLabelText("Status"), {
      target: { value: "SUCCEEDED" },
    });
    await waitFor(() =>
      expect(mockList).toHaveBeenLastCalledWith({
        status: "SUCCEEDED",
        flowId: "flow-1",
        limit: 25,
        offset: 0,
      }),
    );
    await screen.findByText("Read-only report");
    fireEvent.click(
      screen.getByRole("button", { name: /clear workflow filter/i }),
    );
    await waitFor(() =>
      expect(mockList).toHaveBeenLastCalledWith({
        status: "SUCCEEDED",
        flowId: undefined,
        limit: 25,
        offset: 0,
      }),
    );
  });

  it("paginates and refreshes without starting a run", async () => {
    renderHistory();
    await screen.findByText("Read-only report");
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    await waitFor(() =>
      expect(mockList).toHaveBeenLastCalledWith({
        status: undefined,
        flowId: undefined,
        limit: 25,
        offset: 25,
      }),
    );
    await screen.findByText("Read-only report");
    expect(screen.getByRole("button", { name: /next/i })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /refresh/i }));
    await waitFor(() => expect(mockList).toHaveBeenCalledTimes(3));
  });

  it("shows a helpful empty state", async () => {
    mockList.mockResolvedValue({ runs: [], total: 0, limit: 25, offset: 0 });
    renderHistory();
    expect(await screen.findByText("No saved runs found")).toBeInTheDocument();
    expect(screen.getByText("0 runs")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /next/i })).toBeDisabled();
  });

  it("shows an error and lets the user retry the history read", async () => {
    mockList.mockRejectedValueOnce(new Error("offline"));
    renderHistory();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Unable to load run history",
    );
    fireEvent.click(screen.getByRole("button", { name: /refresh/i }));
    expect(await screen.findByText("Read-only report")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("ignores an outdated response after the user changes the filter", async () => {
    let finishOld: (value: AdlcRunListResponse) => void = () => undefined;
    mockList.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishOld = resolve;
        }),
    );
    mockList.mockResolvedValue({
      ...page,
      runs: [{ ...run, name: "New result", status: "SUCCEEDED" }],
    });
    renderHistory();
    fireEvent.change(screen.getByLabelText("Status"), {
      target: { value: "SUCCEEDED" },
    });
    await screen.findByText("New result");
    await act(async () => finishOld(page));
    expect(screen.getByText("New result")).toBeInTheDocument();
    expect(screen.queryByText("Read-only report")).not.toBeInTheDocument();
  });
});
