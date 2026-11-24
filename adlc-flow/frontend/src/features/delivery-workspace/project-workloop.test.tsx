import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { AuthContext } from "@/contexts/authContext";
import {
  projectWorkloop,
  type WorkloopJob,
} from "@/controllers/API/project-workloop";
import ProjectWorkloop, {
  WorkloopRunDetail,
  workloopHref,
} from "./project-workloop";
import { humanRunUrl } from "./human-input";

jest.mock("./execution-graph", () => ({
  __esModule: true,
  default: ({
    tasks,
    select,
  }: {
    tasks: { id: string; state: string }[];
    select: (id: string) => void;
  }) => (
    <div>
      {tasks.map((t) => (
        <button key={t.id} onClick={() => select(t.id)}>
          {t.id} · {t.state}
        </button>
      ))}
    </div>
  ),
  WorkJourney: ({
    steps,
    select,
  }: {
    steps: { id: string; title: string; tab: string }[];
    select: (tab: string) => void;
  }) => (
    <nav>
      {steps.map((s) => (
        <button key={s.id} onClick={() => select(s.tab)}>
          {s.title}
        </button>
      ))}
    </nav>
  ),
}));
jest.mock("@/components/core/sanitizedMarkdown", () => ({
  SanitizedMarkdown: ({ chatMessage }: { chatMessage: string }) => (
    <p>{chatMessage}</p>
  ),
}));
const project = {
  project_id: "project-a",
  repository: "admin/app",
  repository_id: 1,
  name: "App",
  repository_url: "http://gitea/admin/app",
  branch: "main",
  base_commit: "a",
};
const fixture = (changes: Partial<WorkloopJob> = {}): WorkloopJob => ({
  job_id: "job-a",
  workflow: "Build",
  title: "Add search",
  project_id: "project-a",
  repository: "admin/app",
  state: "RUNNING",
  version: 1,
  created_at: "2026-10-28T01:00:00Z",
  updated_at: "2026-10-28T01:00:00Z",
  checked_at: "2026-10-28T01:00:00Z",
  requests: [],
  commands: [],
  topology: {
    state: "pinned",
    commit: "a".repeat(40),
    edges: [{ source: "build", target: "test" }],
  },
  tasks: [
    {
      id: "build",
      title: "Build search",
      state: "IN_PROGRESS",
      started_at: "2026-10-28T01:00:00Z",
    },
    { id: "test", title: "Test search", state: "PENDING" },
  ],
  ...changes,
});
function Location() {
  const location = useLocation();
  return <output data-testid="location">{location.search}</output>;
}
function mount(detail = true, admin = true) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <AuthContext.Provider
        value={
          {
            userData: { id: "owner", is_superuser: admin },
          } as React.ContextType<typeof AuthContext>
        }
      >
        <MemoryRouter
          initialEntries={["/work?project=project-a&workloop_job=job-a"]}
        >
          {detail ? (
            <WorkloopRunDetail project={project} jobId="job-a" />
          ) : (
            <ProjectWorkloop project={project} />
          )}
          <Location />
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
  return {
    client,
    close: () => {
      view.unmount();
      client.clear();
    },
  };
}
beforeEach(() => {
  jest.spyOn(projectWorkloop, "read").mockResolvedValue(fixture());
  jest.spyOn(projectWorkloop, "jobs").mockResolvedValue({ items: [] });
  jest
    .spyOn(projectWorkloop, "reports")
    .mockResolvedValue({ job_id: "job-a", checked_at: "now", nodes: [] });
  jest.spyOn(projectWorkloop, "command").mockResolvedValue({
    command_id: "c",
    action: "PAUSE",
    state: "REQUESTED",
    created_at: "now",
  });
  jest
    .spyOn(projectWorkloop, "candidates")
    .mockResolvedValue({ items: [fixture()], limit: 100 });
  jest.spyOn(projectWorkloop, "link").mockResolvedValue(fixture());
});
afterEach(() => jest.restoreAllMocks());
test("remote completed state is distinct from verification and has no resume", async () => {
  jest
    .mocked(projectWorkloop.read)
    .mockResolvedValue(fixture({ state: "COMPLETED" }));
  const view = mount();
  expect(await screen.findByText("Đã chạy xong")).toBeInTheDocument();
  expect(
    screen.getByText(/Xem báo cáo trước khi xác nhận/),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Tiếp tục" }),
  ).not.toBeInTheDocument();
  view.close();
});
test("pause is queued, not reported as paused before observation", async () => {
  const view = mount();
  fireEvent.click(await screen.findByRole("button", { name: "Tạm dừng" }));
  await waitFor(() => expect(projectWorkloop.command).toHaveBeenCalledTimes(1));
  expect(screen.getAllByText("Đang chạy").length).toBeGreaterThan(0);
  expect(jest.mocked(projectWorkloop.command).mock.calls[0][2]).toEqual(
    expect.objectContaining({
      action: "PAUSE",
      command_id: expect.any(String),
    }),
  );
  view.close();
});
test("poll refresh updates graph task state while task links remain shareable", async () => {
  const view = mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "test · PENDING" }),
  );
  expect(screen.getByTestId("location")).toHaveTextContent("task=test");
  jest
    .mocked(projectWorkloop.read)
    .mockResolvedValue(
      fixture({ tasks: [{ id: "test", title: "Test search", state: "DONE" }] }),
    );
  await view.client.invalidateQueries({ queryKey: ["project-workloop-job"] });
  expect(
    await screen.findByRole("button", { name: "test · DONE" }),
  ).toBeInTheDocument();
  view.close();
});
test("stale cached jobs disable all execution controls", async () => {
  jest.mocked(projectWorkloop.read).mockResolvedValue(fixture({ stale: true }));
  const view = mount();
  expect(
    await screen.findByRole("button", { name: "Tạm dừng" }),
  ).toBeDisabled();
  expect(screen.getByRole("button", { name: "Dừng" })).toBeDisabled();
  view.close();
});
test("interrupted job explains why resume is unavailable", async () => {
  jest
    .mocked(projectWorkloop.read)
    .mockResolvedValue(fixture({ state: "INTERRUPTED" }));
  const view = mount();
  expect(
    await screen.findByText(/API hiện chỉ hỗ trợ tiếp tục/),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Tiếp tục" }),
  ).not.toBeInTheDocument();
  view.close();
});
test("linking a shared job requires explicit repository confirmation", async () => {
  const view = mount(false);
  fireEvent.click(
    await screen.findByRole("button", { name: "Liên kết lượt Workloop" }),
  );
  await screen.findByRole("option", { name: /Build · job-a/ });
  fireEvent.change(screen.getByLabelText("Lượt Workloop"), {
    target: { value: "job-a" },
  });
  const submit = screen.getByRole("button", { name: /Liên kết vào project/ });
  expect(submit).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(submit);
  await waitFor(() =>
    expect(projectWorkloop.link).toHaveBeenCalledWith(
      "project-a",
      "job-a",
      "Build",
      "admin/app",
    ),
  );
  view.close();
});
test("non-admin cannot browse shared unbound jobs", async () => {
  const view = mount(false, false);
  await screen.findByText(/Chưa liên kết lượt Workloop/);
  expect(
    screen.queryByRole("button", { name: "Liên kết lượt Workloop" }),
  ).not.toBeInTheDocument();
  expect(projectWorkloop.candidates).not.toHaveBeenCalled();
  view.close();
});
test("attention links open the exact remote project and job", () => {
  expect(workloopHref("p", "job-123")).toBe(
    "/work?project=p&workloop_job=job-123",
  );
  expect(
    humanRunUrl({ kind: "workloop", project_id: "p", run_id: "job-123" }),
  ).toContain("workloop_job=job-123&tab=attention");
});
