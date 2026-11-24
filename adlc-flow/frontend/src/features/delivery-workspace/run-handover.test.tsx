import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthContext } from "@/contexts/authContext";
import type { LiveRun } from "@/controllers/API/live-workflows";
import {
  projectLifecycle,
  type Handover,
} from "@/controllers/API/project-lifecycle";
import RunHandover, { RunRecovery } from "./run-handover";

const run: LiveRun = {
  run_id: "run",
  project_id: "project",
  delivery_id: "delivery",
  title: "Fix search",
  requirement: "Fix pagination",
  repository: "admin/sut",
  base_commit: "a".repeat(40),
  created_at: "2026-10-27T01:00:00Z",
  state: "SUCCEEDED",
  phase: "execution",
  nodes: [],
  documents: [],
  published: {
    branch: "codex/result",
    commit: "b".repeat(40),
    url: "http://gitea/branch",
  },
};
const open: Handover = {
  state: "OPEN",
  pull: {
    number: 7,
    title: "Fix search",
    url: "http://gitea/admin/sut/pulls/7",
    head: "b".repeat(40),
    base: "main",
    base_commit: "a".repeat(40),
    merged: false,
    state: "open",
  },
  readiness: {
    can_merge: true,
    no_ci: true,
    ci: [],
    reasons: [],
    approvals: 0,
    required_approvals: 0,
  },
};
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <AuthContext.Provider
        value={
          { userData: { id: "owner" } } as React.ContextType<typeof AuthContext>
        }
      >
        <RunHandover run={run} />
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
}
afterEach(() => jest.restoreAllMocks());

test("PR content is reviewable before creation and one intent is kept", async () => {
  jest
    .spyOn(projectLifecycle, "handover")
    .mockResolvedValue({ state: "NOT_CREATED" });
  jest
    .spyOn(projectLifecycle, "handoverPreview")
    .mockResolvedValue({
      title: "Fix search",
      body: "Verified evidence and changed files",
    });
  const create = jest
    .spyOn(projectLifecycle, "createPull")
    .mockResolvedValue(open);
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Xem nội dung PR" }),
  );
  expect(
    await screen.findByText(/Verified evidence and changed files/),
  ).toBeInTheDocument();
  const button = screen.getByRole("button", { name: "Tạo Pull Request" });
  expect(button).toBeDisabled();
  fireEvent.click(
    screen.getByLabelText("Tạo PR với nội dung này từ nhánh đã xuất."),
  );
  fireEvent.click(button);
  await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
  expect(create.mock.calls[0].slice(0, 2)).toEqual(["run", "b".repeat(40)]);
});

test("merge requires a human decision and explicit acceptance when CI is missing", async () => {
  jest.spyOn(projectLifecycle, "handover").mockResolvedValue(open);
  const merge = jest
    .spyOn(projectLifecycle, "merge")
    .mockResolvedValue({ ...open, state: "MERGED" });
  mount();
  const button = await screen.findByRole("button", { name: "Duyệt và merge" });
  expect(button).toBeDisabled();
  fireEvent.click(screen.getByLabelText(/Tôi đã xem thay đổi/));
  expect(button).toBeDisabled();
  fireEvent.click(screen.getByLabelText(/Repo chưa có CI/));
  fireEvent.click(button);
  await waitFor(() => expect(merge).toHaveBeenCalledTimes(1));
  expect(merge.mock.calls[0].slice(0, 3)).toEqual([
    "run",
    "b".repeat(40),
    "a".repeat(40),
  ]);
  expect(merge.mock.calls[0].slice(4)).toEqual([true, false]);
});

test("failed CI and an uncertain merge block the merge button", async () => {
  jest
    .spyOn(projectLifecycle, "handover")
    .mockResolvedValue({
      ...open,
      merge_intent: { command_id: "already-sent" },
      readiness: {
        ...open.readiness!,
        no_ci: false,
        can_merge: false,
        reasons: ["LIVE_PR_CHECKS_NOT_PASSED"],
      },
    });
  mount();
  fireEvent.click(await screen.findByLabelText(/Tôi đã xem thay đổi/));
  expect(screen.getByRole("button", { name: "Duyệt và merge" })).toBeDisabled();
  expect(screen.getByText(/CI của commit hiện tại/)).toBeInTheDocument();
});

test("recovery continues the same run using the saved generation and plan", async () => {
  const recover = jest.spyOn(projectLifecycle, "recover").mockResolvedValue({});
  const interrupted = {
    ...run,
    state: "UNCONFIRMED",
    approved_plan_digest: "c".repeat(64),
    recovery_status: { available: true, generation: 2, completed_tasks: 3 },
  };
  render(
    <RunRecovery
      run={interrupted}
      busy=""
      action={(_, operation) => void operation()}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Tiếp tục lượt này" }));
  await waitFor(() => expect(recover).toHaveBeenCalledTimes(1));
  expect(recover.mock.calls[0][0]).toBe("run");
  expect(recover.mock.calls[0].slice(2)).toEqual([2, "c".repeat(64)]);
});
