import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { liveWorkflows } from "@/controllers/API/live-workflows";
import {
  projectIssues,
  type IssueProposal,
  type ProjectIssueSettings,
} from "@/controllers/API/project-issues";
import ProjectIssues from "./project-issues";
import { humanRunUrl } from "./human-input";

jest.mock("@/components/core/sanitizedMarkdown", () => ({
  SanitizedMarkdown: ({ chatMessage }: { chatMessage: string }) => (
    <p>{chatMessage}</p>
  ),
}));
const project = {
  project_id: "project-a",
  name: "Notes",
  repository: "admin/notes",
  repository_id: 41,
  repository_url: "http://gitea/admin/notes",
  branch: "main",
  base_commit: "a".repeat(40),
};
const settings: ProjectIssueSettings = {
  project_id: project.project_id,
  watch_issues: true,
  mode: "review",
  labels: [],
  workflow_id: null,
  revision: 1,
  updated_at: "2026-10-26T00:00:00Z",
  last_scan_at: null,
  scan_error: null,
  scan_truncated: false,
  poll_seconds: 60,
};
const issue: IssueProposal = {
  proposal_id: "proposal-a",
  project_id: project.project_id,
  repository: project.repository,
  source_digest: "a".repeat(64),
  revision: 1,
  state: "DETECTED",
  issue: {
    number: 7,
    title: "Add search to notes",
    body: "Keep the saved notes unchanged.",
    state: "open",
    author: "maintainer",
    url: "http://gitea/admin/notes/issues/7",
    labels: ["ready"],
    updated_at: null,
  },
  run_id: null,
  previous_runs: [],
  error_code: null,
  review_reason: null,
};

function mount(section: "issues" | "settings" = "issues", noProject = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const onOpenRun = jest.fn(),
    onSettings = jest.fn();
  const result = render(
    <QueryClientProvider client={client}>
      <ProjectIssues
        project={noProject ? undefined : project}
        identity="alice"
        section={section}
        onOpenRun={onOpenRun}
        onSettings={onSettings}
      />
    </QueryClientProvider>,
  );
  return { ...result, client, onOpenRun, onSettings };
}
beforeEach(() => {
  jest
    .spyOn(projectIssues, "list")
    .mockResolvedValue({ settings, items: [issue] });
  jest
    .spyOn(projectIssues, "scan")
    .mockResolvedValue({ settings, items: [issue] });
  jest
    .spyOn(projectIssues, "act")
    .mockResolvedValue({ ...issue, run_id: "run-a", state: "PLANNING" });
  jest
    .spyOn(projectIssues, "save")
    .mockImplementation(async (_id, command) => ({
      ...settings,
      ...command,
      revision: 2,
    }));
  jest.spyOn(liveWorkflows, "workflows").mockResolvedValue({
    items: [
      {
        workflow_id: "workflow-a",
        project_id: project.project_id,
        name: "My canvas",
        ready: true,
        revision: 3,
        digest: "b".repeat(64),
        graph: {
          version: 1,
          title: "My canvas",
          summary: "",
          nodes: [],
          edges: [],
          commands: [],
          preview: null,
          browser_checks: [],
        },
      },
    ],
  });
});
afterEach(() => jest.restoreAllMocks());

it("detects proposals without silently starting work or changing settings", async () => {
  mount();
  expect(await screen.findByText("Add search to notes")).toHaveAttribute(
    "href",
    issue.issue.url,
  );
  expect(screen.getByText("Chờ bạn duyệt")).toBeInTheDocument();
  expect(projectIssues.act).not.toHaveBeenCalled();
  expect(projectIssues.save).not.toHaveBeenCalled();
});
it("starts a bound plan on the user's action and opens its run", async () => {
  const { onOpenRun } = mount();
  fireEvent.click(await screen.findByRole("button", { name: /Lập kế hoạch/ }));
  await waitFor(() => expect(onOpenRun).toHaveBeenCalledWith("run-a"));
  expect(projectIssues.act).toHaveBeenCalledWith(
    project.project_id,
    issue,
    "plan",
  );
});
it("ignores proposals without mutating the source issue", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Bỏ qua" }));
  await waitFor(() =>
    expect(projectIssues.act).toHaveBeenCalledWith(
      project.project_id,
      issue,
      "ignore",
    ),
  );
});
it("requires an explicit acknowledgement for automatic execution and saves the chosen canvas workflow", async () => {
  mount("settings");
  fireEvent.click(
    await screen.findByRole("radio", { name: /Tự duyệt và thực hiện/ }),
  );
  const save = screen.getByRole("button", { name: "Lưu cài đặt" });
  expect(save).toBeDisabled();
  await screen.findByRole("option", { name: "My canvas · v3" });
  fireEvent.change(screen.getByRole("combobox"), {
    target: { value: "workflow-a" },
  });
  fireEvent.change(screen.getByPlaceholderText("Ví dụ: ready, pokedev"), {
    target: { value: "ready, pokedev" },
  });
  fireEvent.click(screen.getByRole("checkbox", { name: /Tôi cho phép/ }));
  fireEvent.click(save);
  await waitFor(() =>
    expect(projectIssues.save).toHaveBeenCalledWith(project.project_id, {
      expected_revision: 1,
      watch_issues: true,
      mode: "auto",
      labels: ["ready", "pokedev"],
      workflow_id: "workflow-a",
      auto_confirmed: true,
      auto_allowed_paths: ["docs/**", "tests/**"],
      auto_max_runs_per_day: 3,
      auto_max_active_minutes: 20,
    }),
  );
  expect(await screen.findByText("Đã lưu cài đặt")).toBeInTheDocument();
});
it("lets the user turn monitoring off without reaffirming automatic execution", async () => {
  jest
    .mocked(projectIssues.list)
    .mockResolvedValue({ settings: { ...settings, mode: "auto" }, items: [] });
  mount("settings");
  fireEvent.click(
    await screen.findByRole("checkbox", { name: /Theo dõi issue/ }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Lưu cài đặt" }));
  await waitFor(() =>
    expect(projectIssues.save).toHaveBeenCalledWith(
      project.project_id,
      expect.objectContaining({
        mode: "auto",
        watch_issues: false,
        auto_confirmed: false,
      }),
    ),
  );
});

it("saves risk-limited scopes and budgets only after acknowledgement", async () => {
  mount("settings");
  fireEvent.click(
    await screen.findByRole("radio", { name: /Tự làm việc ít rủi ro/ }),
  );
  expect(screen.getByRole("button", { name: "Lưu cài đặt" })).toBeDisabled();
  fireEvent.change(
    screen.getByRole("textbox", { name: /File hoặc thư mục được tự sửa/ }),
    { target: { value: "app.js\ntests/**" } },
  );
  fireEvent.change(
    screen.getByRole("spinbutton", { name: /Số lượt tự động/ }),
    { target: { value: "2" } },
  );
  fireEvent.change(
    screen.getByRole("spinbutton", { name: /Thời gian làm việc/ }),
    { target: { value: "10" } },
  );
  fireEvent.click(screen.getByRole("checkbox", { name: /Tôi cho phép/ }));
  fireEvent.click(screen.getByRole("button", { name: "Lưu cài đặt" }));
  await waitFor(() =>
    expect(projectIssues.save).toHaveBeenCalledWith(
      project.project_id,
      expect.objectContaining({
        mode: "risk",
        auto_confirmed: true,
        auto_allowed_paths: ["app.js", "tests/**"],
        auto_max_runs_per_day: 2,
        auto_max_active_minutes: 10,
      }),
    ),
  );
});
it("retains an unsaved choice when settings are refreshed in the background", async () => {
  const { client } = mount("settings");
  const input = await screen.findByPlaceholderText("Ví dụ: ready, pokedev");
  fireEvent.change(input, { target: { value: "ready" } });
  client.setQueryData(["project-issues", "alice", project.project_id], {
    settings: { ...settings, revision: 2 },
    items: [issue],
  });
  expect(input).toHaveValue("ready");
});
it("shows existing proposals and a scan failure together", async () => {
  jest.mocked(projectIssues.list).mockResolvedValue({
    settings: { ...settings, scan_error: "GITEA_UNAVAILABLE" },
    items: [issue],
  });
  mount();
  expect(await screen.findByText("Add search to notes")).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Chưa cập nhật được từ Gitea",
  );
});
it("opens issue notifications in the matching project's inbox", () => {
  const url = new URL(
    humanRunUrl({
      project_id: "p",
      run_id: "",
      kind: "issue",
      proposal_id: "i",
    }),
    "http://localhost",
  );
  expect(Object.fromEntries(url.searchParams)).toEqual({
    project: "p",
    view: "issues",
    issue: "i",
  });
});
it("requires a project selection before loading private issue data", () => {
  mount("settings", true);
  expect(screen.getByText("Chọn project để tiếp tục")).toBeInTheDocument();
  expect(projectIssues.list).not.toHaveBeenCalled();
});
