import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthContext } from "@/contexts/authContext";
import { workloop } from "@/controllers/API/workloop";
import useAuthStore from "@/stores/authStore";
import type { WorkloopListing } from "@/controllers/API/workloop";
import WorkloopPanel, { WorkloopView } from "./workloop";
const data: WorkloopListing = {
  context: {
    context_digest: "digest",
    candidate: { loop_id: "candidate", source_sha256: "a".repeat(64) },
    factories: [],
  },
  capabilities: {
    ready: true,
    preview_ready: true,
    engine_revision: "a".repeat(40),
    model: { provider: "netmind", model: "GLM" },
    max_duration_seconds: 900,
    token_cost_cap: false,
  },
  inventory: {
    observed_at: "2026-10-22T00:00:00Z",
    error_code: null,
    plugins: [],
  },
  runs: [],
};
const props = {
  data,
  busy: false,
  error: "",
  canWrite: true,
  onStart: jest.fn(),
  onRefresh: jest.fn(),
};
test("loads automatically from the workspace auth context when the separate store has no user", async () => {
  useAuthStore.setState({ userData: null });
  const list = jest.spyOn(workloop, "list").mockResolvedValue(data);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <AuthContext.Provider
        value={
          { userData: { id: "owner" } } as React.ContextType<typeof AuthContext>
        }
      >
        <WorkloopPanel deliveryId="delivery" cycleId="cycle" canWrite />
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
  await waitFor(() => expect(list).toHaveBeenCalledWith("delivery", "cycle"));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Tạo bản chạy thử" }),
    ).toBeEnabled(),
  );
  client.clear();
  list.mockRestore();
});
test("viewing Workloop never creates a run; launch remains explicit", () => {
  render(<WorkloopView {...props} />);
  expect(props.onStart).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Tạo bản chạy thử" }));
  expect(props.onStart).toHaveBeenCalledWith("pokedev", "candidate-preview");
});
test("an uncertain run cannot create a duplicate and reports no success", () => {
  render(
    <WorkloopView
      {...props}
      data={{
        ...data,
        runs: [
          {
            run_id: "id",
            factory: "pokedev",
            workflow: "candidate-preview",
            state: "UNCONFIRMED",
            created_at: "2026-10-22T00:00:00Z",
            model: data.capabilities.model,
            nodes: [],
            events: [],
            canonical_cycle_execution: false,
          },
        ],
      }}
    />,
  );
  expect(screen.getByRole("button", { name: "Đang theo dõi" })).toBeDisabled();
  expect(screen.getByText("Cần đối soát")).toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: "Mở ứng dụng" }),
  ).not.toBeInTheDocument();
});
test("expired previews hide application links while retaining actual test logs", () => {
  render(
    <WorkloopView
      {...props}
      data={{
        ...data,
        runs: [
          {
            run_id: "id",
            factory: "pokedev",
            workflow: "candidate-preview",
            state: "SUCCEEDED",
            created_at: "2026-10-22T00:00:00Z",
            model: data.capabilities.model,
            nodes: [{ id: "test", state: "DONE" }],
            events: [],
            canonical_cycle_execution: false,
            preview: {
              preview_id: "id",
              sandbox_id: "sandbox",
              state: "EXPIRED",
              expires_at: "2000-01-01T00:00:00Z",
              source_sha256: "a".repeat(64),
              url: null,
              tests: {
                passed: true,
                protected_intact: true,
                checks: [
                  {
                    check_id: "acceptance",
                    exit_code: 0,
                    stdout: "",
                    stderr: "Ran 9 tests\nOK",
                  },
                ],
              },
            },
          },
        ],
      }}
    />,
  );
  expect(screen.getByText("Bản chạy thử đã hết hạn")).toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: "Mở ứng dụng" }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "Test & Verify" }));
  expect(screen.getByText(/Ran 9 tests/)).toBeInTheDocument();
});
