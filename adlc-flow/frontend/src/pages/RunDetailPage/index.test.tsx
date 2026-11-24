import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useParams } from "react-router-dom";
import {
  approveAdlcRun,
  cancelAdlcRun,
  getAdlcHarnessResults,
  getAdlcHarnessSessions,
  getAdlcRun,
  getAdlcRunControls,
  getAdlcRunEvents,
  getAdlcRunTasks,
  getAdlcSourcePatch,
  getAdlcTaskSubtasks,
  getAdlcSubtaskActivity,
  getAdlcTaskLoop,
  pauseAdlcRun,
  reconcileAdlcHarnessRun,
  rejectAdlcRun,
  respondToAdlcHarnessInteraction,
  resumeAdlcRun,
  retryAdlcTask,
  submitAdlcHarnessSession,
} from "@/controllers/API/adlc";
import type {
  AdlcArtifact,
  AdlcHarnessRunSession,
  AdlcRunEvent,
  AdlcSourcePatch,
  AdlcTaskRun,
  AdlcWorkflowRun,
} from "@/types/adlc";
import RunDetailPage from ".";

jest.mock("react-router-dom", () => ({
  ...jest.requireActual("react-router-dom"),
  useParams: jest.fn(),
}));

// Expand a task row. Task rows are the only buttons with aria-expanded;
// other buttons (session cards, etc.) may share the task's name.
async function expandTaskRow(name: RegExp | string) {
  const candidates = await screen.findAllByRole("button", { name });
  const row = candidates.find(
    (candidate) => candidate.getAttribute("aria-expanded") !== null,
  );
  if (row) fireEvent.click(row);
  return row;
}

// Results live in the task's subtask panel under the "Results" tab.
// Radix tabs activate on mousedown, not click.
async function openResultsTab() {
  const trigger = await screen.findByTestId("subtask-view-results");
  fireEvent.mouseDown(trigger, { button: 0, ctrlKey: false });
  fireEvent.click(trigger);
}
jest.mock("@/customization/hooks/use-custom-navigate", () => ({
  useCustomNavigate: () => jest.fn(),
}));
jest.mock("@/components/common/genericIconComponent", () => () => null);
jest.mock("@/components/adlc/ContractPanel", () => () => null);
jest.mock("@/components/adlc/VerificationPanel", () => () => null);
jest.mock("@/components/adlc/ReplayPanel", () => () => null);
jest.mock("@/components/adlc/MemoryPanel", () => () => null);
jest.mock("@/components/adlc/ContractExecutionPanel", () => () => null);
jest.mock("@/components/core/codeTabsComponent", () => () => null);
jest.mock("react-markdown", () => ({
  __esModule: true,
  default: ({ children }: { children: string }) => <div>{children}</div>,
}));
jest.mock("@/controllers/API/adlc", () => ({
  getAdlcRun: jest.fn(),
  getAdlcRunControls: jest.fn(),
  pauseAdlcRun: jest.fn(),
  resumeAdlcRun: jest.fn(),
  cancelAdlcRun: jest.fn(),
  getAdlcTaskLoop: jest.fn(),
  getAdlcTaskLoopRuntime: jest.fn(),
  getAdlcRunTasks: jest.fn(),
  getAdlcRunEvents: jest.fn(),
  getAdlcHarnessSessions: jest.fn(),
  getAdlcHarnessResults: jest.fn(),
  getAdlcTaskSubtasks: jest.fn(),
  getAdlcSubtaskActivity: jest.fn(),
  getAdlcSourcePatch: jest.fn(),
  approveAdlcRun: jest.fn(),
  rejectAdlcRun: jest.fn(),
  retryAdlcTask: jest.fn(),
  reconcileAdlcHarnessRun: jest.fn(),
  reconcileAdlcContractVerification: jest.fn(),
  respondToAdlcHarnessInteraction: jest.fn(),
  submitAdlcHarnessSession: jest.fn(),
}));

const artifact: AdlcArtifact = {
  artifact_id: "artifact-1",
  workflow_run_id: "run-1",
  task_run_id: "task-1",
  kind: "SOURCE_PATCH",
  name: "source-patch.json",
  media_type: "application/vnd.opencode.vcs-diff+json",
  uri: "adlc://runs/run-1/artifacts/artifact-1",
  size_bytes: 100,
  checksum: { algorithm: "SHA256", value: "abc123" },
  metadata: { capture: "workspace-vcs-diff" },
};

const task: AdlcTaskRun = {
  id: "task-1",
  workflow_run_id: "run-1",
  key: "implement",
  name: "Implement",
  task_type: "coding",
  status: "SUCCEEDED",
  dependency_task_run_ids: [],
  retry_count: 0,
  artifacts: [artifact],
};

const run: AdlcWorkflowRun = {
  id: "run-1",
  execution_mode: "EXECUTION_PLAN",
  name: "Review run",
  status: "WAITING_APPROVAL",
  tasks: [task],
  approval_requests: [
    {
      approval_request_id: "approval-1",
      workflow_run_id: "run-1",
      task_run_id: "approval-task",
      status: "PENDING",
      title: "Approve changes",
      context: { summary: "Review the patch." },
    },
  ],
  events: [],
  created_at: "2026-09-17T00:00:00Z",
};

describe("RunDetailPage source-patch approval", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (useParams as jest.Mock).mockReturnValue({ runId: "run-1" });
    (getAdlcRun as jest.Mock).mockResolvedValue(run);
    (getAdlcRunControls as jest.Mock).mockResolvedValue({
      workflow_run_id: "run-1",
      can_pause: false,
      can_resume: false,
      can_cancel: true,
      pause_requested: false,
      pause_reason: null,
    });
    (getAdlcRunTasks as jest.Mock).mockResolvedValue([task]);
    (getAdlcRunEvents as jest.Mock).mockResolvedValue({
      workflow_run_id: "run-1",
      events: [],
    });
    (getAdlcHarnessSessions as jest.Mock).mockResolvedValue([]);
    (getAdlcHarnessResults as jest.Mock).mockResolvedValue([]);
    // Never resolve by default: an undefined patch value would crash
    // SourcePatchReview's expiry effect (patch.artifact of undefined).
    (getAdlcSourcePatch as jest.Mock).mockReturnValue(new Promise(() => {}));
    (getAdlcTaskSubtasks as jest.Mock).mockResolvedValue({
      task_run_id: "task-1",
      subtasks: [],
      summary: {
        total: 0,
        succeeded: 0,
        failed: 0,
        running: 0,
        pending: 0,
        skipped: 0,
      },
      is_mock: true,
    });
    (getAdlcSubtaskActivity as jest.Mock).mockResolvedValue({
      source: "agent-provider:deepseek-harness",
      entries: [],
      entries_total: 0,
      running: false,
    });
    (reconcileAdlcHarnessRun as jest.Mock).mockResolvedValue({
      inspected: 0,
      recovered_results: 0,
      submitted_sessions: 0,
      unavailable_sessions: 0,
    });
  });

  it("enables Approve only after the captured patch can be read", async () => {
    let resolvePatch: (patch: AdlcSourcePatch) => void = () => undefined;
    (getAdlcSourcePatch as jest.Mock).mockReturnValue(
      new Promise<AdlcSourcePatch>((resolve) => {
        resolvePatch = resolve;
      }),
    );

    render(<RunDetailPage />);

    const approve = await screen.findByRole("button", { name: "Approve" });
    expect(approve).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();

    await act(async () => {
      resolvePatch({
        artifact,
        format: "opencode-vcs-diff-v1",
        files: [
          {
            file: "README.md",
            patch: "+reviewed\n",
            additions: 1,
            deletions: 0,
          },
        ],
        reported_files: ["README.md"],
      });
    });

    await waitFor(() => expect(approve).toBeEnabled());
    expect(screen.getByText("+reviewed")).toBeVisible();
  });

  it("shows compact tabs and labelled quality samples without approving or enabling an unread patch", async () => {
    (getAdlcSourcePatch as jest.Mock).mockReturnValue(new Promise(() => {}));
    render(<RunDetailPage />);
    const changes = await screen.findByRole("tab", { name: "Thay đổi" });
    expect(changes).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByText("Event timeline")).toBeNull();
    expect(
      screen.queryByRole("region", {
        name: "Giao diện mẫu Verify và TestForge",
      }),
    ).toBeNull();
    fireEvent.keyDown(changes, { key: "ArrowRight" });
    expect(
      screen.getByRole("tab", { name: "Kiểm thử & Verify" }),
    ).toHaveFocus();
    expect(
      screen.getByText("Giao diện mẫu · không phải kết quả thật"),
    ).toBeVisible();
    expect(screen.getByText("Kết luận: —")).toBeVisible();
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    expect(approveAdlcRun).not.toHaveBeenCalled();
    expect(submitAdlcHarnessSession).not.toHaveBeenCalled();
    fireEvent.click(changes);
    expect(screen.queryByText("Verify độc lập")).toBeNull();
    expect(getAdlcSourcePatch).toHaveBeenCalledTimes(1);
  });

  it("shows the task failure and does not offer an exhausted retry", async () => {
    const failedTask: AdlcTaskRun = {
      ...task,
      status: "FAILED",
      artifacts: [],
      request: { constraints: { max_attempts: 1 } },
      result: {
        error: {
          code: "LOCAL_WORKTREE_CREATE_FAILED",
          message:
            "The sandbox:local-git-worktree adapter failed while executing the task.",
        },
      },
    };
    (getAdlcRun as jest.Mock).mockResolvedValue({
      ...run,
      status: "PAUSED",
      tasks: [failedTask],
      approval_requests: [],
    });
    (getAdlcRunTasks as jest.Mock).mockResolvedValue([failedTask]);

    render(<RunDetailPage />);

    expect(
      await screen.findByText(/LOCAL_WORKTREE_CREATE_FAILED: The sandbox/),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("tab", { name: "Hoạt động & nâng cao" }));
    expect(screen.getByText("1/1 attempts used")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Retry" }),
    ).not.toBeInTheDocument();
  });

  it("shows the attempt history derived from events and retries the latest attempt", async () => {
    const failedTask: AdlcTaskRun = {
      ...task,
      status: "FAILED",
      artifacts: [],
      request: { constraints: { max_attempts: 2 } },
      result: {
        error: {
          code: "MOCK_EXECUTION_FAILED",
          message: "Injected failure for attempt 1.",
        },
      },
    };
    let sequence = 0;
    const event = (overrides: Partial<AdlcRunEvent>): AdlcRunEvent => {
      sequence += 1;
      return {
        event_id: `event-${sequence}`,
        event_type: "task_run.started",
        sequence,
        status: "RUNNING",
        occurred_at: `2026-09-17T10:30:0${sequence}Z`,
        ...overrides,
      };
    };
    const events: AdlcRunEvent[] = [
      event({
        event_type: "task_run.started",
        task_run_id: "task-1",
        attempt_id: "attempt-1",
      }),
      event({
        event_type: "task_run.failed",
        status: "FAILED",
        task_run_id: "task-1",
        attempt_id: "attempt-1",
        payload: { error_code: "MOCK_EXECUTION_FAILED" },
      }),
      event({
        event_type: "task_run.started",
        task_run_id: "task-1",
        attempt_id: "attempt-2",
      }),
    ];
    (getAdlcRun as jest.Mock).mockResolvedValue({
      ...run,
      status: "PAUSED",
      tasks: [failedTask],
      approval_requests: [],
    });
    (getAdlcRunTasks as jest.Mock).mockResolvedValue([failedTask]);
    (getAdlcRunEvents as jest.Mock).mockResolvedValue({
      workflow_run_id: "run-1",
      events,
    });
    (retryAdlcTask as jest.Mock).mockResolvedValue({
      ...run,
      status: "RUNNING",
    });

    render(<RunDetailPage />);

    fireEvent.click(
      await screen.findByRole("tab", { name: "Hoạt động & nâng cao" }),
    );
    expect(await screen.findByText("Attempt #1")).toBeVisible();
    expect(screen.getByText("Attempt #2")).toBeVisible();
    const retry = screen.getByRole("button", { name: "Retry" });
    expect(retry.closest("li")?.textContent?.includes("Attempt #2")).toBe(true);

    fireEvent.click(retry);

    await waitFor(() => expect(retryAdlcTask).toHaveBeenCalledWith("task-1"));
  });

  it("lists the artifacts produced by the run tasks", async () => {
    const artifactTask: AdlcTaskRun = {
      ...task,
      status: "SUCCEEDED",
      artifacts: [
        {
          artifact_id: "artifact-mock-1",
          workflow_run_id: "run-1",
          task_run_id: "task-1",
          kind: "source_patch",
          name: "source_patch.txt",
          media_type: "text/plain",
          uri: "mock://artifacts/artifact-mock-1",
          size_bytes: 2048,
          checksum: { algorithm: "SHA256", value: "deadbeef" },
          metadata: { mock: true },
        },
      ],
    };
    (getAdlcRunTasks as jest.Mock).mockResolvedValue([artifactTask]);

    render(<RunDetailPage />);

    fireEvent.click(
      await screen.findByRole("tab", { name: "Hoạt động & nâng cao" }),
    );
    expect(await screen.findByText("Artifacts")).toBeVisible();
    expect(screen.getByText("source_patch.txt")).toBeVisible();
    expect(screen.getByText(/Implement · text\/plain/)).toBeVisible();
    expect(screen.getByText(/2\.0 KB/)).toBeVisible();
  });

  it("labels timeline events with the owning task and attempt number", async () => {
    const events: AdlcRunEvent[] = [
      {
        event_id: "event-1",
        event_type: "task_run.created",
        sequence: 1,
        status: "PENDING",
        occurred_at: "2026-09-25T11:24:56Z",
        task_run_id: "task-1",
      },
      {
        event_id: "event-2",
        event_type: "task_run.started",
        sequence: 2,
        status: "RUNNING",
        occurred_at: "2026-09-25T11:24:57Z",
        task_run_id: "task-1",
        attempt_id: "attempt-1",
      },
      {
        event_id: "event-3",
        event_type: "workflow_run.started",
        sequence: 3,
        status: "RUNNING",
        occurred_at: "2026-09-25T11:24:56Z",
      },
    ];
    (getAdlcRunEvents as jest.Mock).mockResolvedValue({
      workflow_run_id: "run-1",
      events,
    });

    render(<RunDetailPage />);

    fireEvent.click(
      await screen.findByRole("tab", { name: "Hoạt động & nâng cao" }),
    );
    expect(await screen.findByText("task_run.started")).toBeVisible();
    expect(screen.getByText("Implement · attempt #1")).toBeVisible();
    expect(screen.getByText("task_run.created")).toBeVisible();
    expect(screen.getByText("workflow_run.started")).toBeVisible();
  });

  describe("polling", () => {
    const POLL_INTERVAL_MS = 1500;

    const flushLoad = async () => {
      await act(async () => {
        await Promise.resolve();
      });
    };

    it.each([
      ["CREATED", true],
      ["QUEUED", true],
      ["RUNNING", true],
      ["PAUSED", true],
      ["WAITING_APPROVAL", true],
      ["SUCCEEDED", false],
      ["FAILED", false],
      ["CANCELLED", false],
    ])(
      "%s reloads while polling is expected: %s",
      async (status, shouldPoll) => {
        jest.useFakeTimers();
        try {
          (getAdlcRun as jest.Mock).mockResolvedValue({
            ...run,
            status,
            approval_requests:
              status === "WAITING_APPROVAL" ? run.approval_requests : [],
          });

          render(<RunDetailPage />);
          await flushLoad();

          const callsAfterLoad = (getAdlcRun as jest.Mock).mock.calls.length;
          await act(async () => {
            jest.advanceTimersByTime(POLL_INTERVAL_MS);
          });
          await flushLoad();
          const callsAfterPoll = (getAdlcRun as jest.Mock).mock.calls.length;

          if (shouldPoll) {
            expect(callsAfterPoll).toBeGreaterThan(callsAfterLoad);
          } else {
            expect(callsAfterPoll).toBe(callsAfterLoad);
          }
        } finally {
          jest.useRealTimers();
        }
      },
    );
  });

  it("resolves an agent approval against its exact Harness session", async () => {
    const harnessSession: AdlcHarnessRunSession = {
      attempt_id: "attempt-1",
      task_run_id: "task-1",
      attempt_status: "WAITING_INTERACTION",
      session: {
        schema_version: "0.1",
        session_id: "session-1",
        status: "WAITING_INTERACTION",
        submission_mode: "MANUAL",
        interactions: [
          {
            interaction_id: "interaction-1",
            kind: "APPROVAL",
            status: "PENDING",
            title: "Allow deployment preparation",
            prompt: "The agent needs your decision before it continues.",
            input_schema: {
              type: "object",
              properties: {
                action: { type: "string", enum: ["approve", "reject"] },
              },
              required: ["action"],
              additionalProperties: false,
            },
            ui_schema: {},
            requested_at: "2026-09-17T00:00:00Z",
            metadata: {},
          },
        ],
        created_at: "2026-09-17T00:00:00Z",
        updated_at: "2026-09-17T00:00:00Z",
      },
    };
    (getAdlcHarnessSessions as jest.Mock).mockResolvedValue([harnessSession]);
    (respondToAdlcHarnessInteraction as jest.Mock).mockResolvedValue({});

    render(<RunDetailPage />);
    fireEvent.click(
      await screen.findByRole("button", { name: /Approve agent request/i }),
    );

    await waitFor(() =>
      expect(respondToAdlcHarnessInteraction).toHaveBeenCalledWith(
        "run-1",
        "session-1",
        "interaction-1",
        { action: "approve" },
      ),
    );
  });

  it("submits a native DSH question form including multi-select answers", async () => {
    const harnessSession: AdlcHarnessRunSession = {
      attempt_id: "attempt-1",
      task_run_id: "task-1",
      attempt_status: "WAITING_INTERACTION",
      session: {
        schema_version: "0.1",
        session_id: "session-form",
        status: "WAITING_INTERACTION",
        submission_mode: "MANUAL",
        interactions: [
          {
            interaction_id: "interaction-form",
            kind: "FORM",
            status: "PENDING",
            title: "Agent questions",
            prompt: "Choose how the agent should continue.",
            input_schema: {
              type: "object",
              properties: {
                branch: {
                  type: "string",
                  title: "Branch",
                  enum: ["main", "develop"],
                },
                checks: {
                  type: "array",
                  title: "Checks",
                  items: { type: "string", enum: ["unit", "e2e"] },
                },
                note: { type: "string", title: "Note" },
              },
              required: ["branch", "checks", "note"],
              additionalProperties: false,
            },
            ui_schema: {},
            requested_at: "2026-09-17T00:00:00Z",
            metadata: { bridge_source: "dsh.user-questions/request" },
          },
        ],
        created_at: "2026-09-17T00:00:00Z",
        updated_at: "2026-09-17T00:00:00Z",
      },
    };
    (getAdlcHarnessSessions as jest.Mock).mockResolvedValue([harnessSession]);
    (respondToAdlcHarnessInteraction as jest.Mock).mockResolvedValue({});

    render(<RunDetailPage />);
    fireEvent.change(await screen.findByLabelText("Branch"), {
      target: { value: "main" },
    });
    fireEvent.click(screen.getByLabelText("unit"));
    fireEvent.click(screen.getByLabelText("e2e"));
    fireEvent.change(screen.getByLabelText("Note"), {
      target: { value: "Run the full suite" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Submit response/i }));

    await waitFor(() =>
      expect(respondToAdlcHarnessInteraction).toHaveBeenCalledWith(
        "run-1",
        "session-form",
        "interaction-form",
        {
          branch: "main",
          checks: ["unit", "e2e"],
          note: "Run the full suite",
        },
      ),
    );
  });

  it("submits a verified manual Harness result", async () => {
    (getAdlcHarnessSessions as jest.Mock).mockResolvedValue([
      {
        attempt_id: "attempt-1",
        task_run_id: "task-1",
        attempt_status: "READY_TO_SUBMIT",
        session: {
          schema_version: "0.1",
          session_id: "session-1",
          status: "READY_FOR_SUBMISSION",
          submission_mode: "MANUAL",
          interactions: [],
          result: {
            status: "SUCCEEDED",
            metadata: {
              driver: {
                profile_ref: "harness-profile:adlc-coding/0.1.0",
                provider: "my-codex",
                model: "cx/gpt-5.6-luna",
              },
            },
          },
          created_at: "2026-09-17T00:00:00Z",
          updated_at: "2026-09-17T00:00:00Z",
        },
      },
    ] satisfies AdlcHarnessRunSession[]);
    (submitAdlcHarnessSession as jest.Mock).mockResolvedValue({});

    render(<RunDetailPage />);
    fireEvent.click(
      await screen.findByRole("tab", { name: "Hoạt động & nâng cao" }),
    );
    expect(
      await screen.findByText("Executed with my-codex / cx/gpt-5.6-luna"),
    ).toBeVisible();
    fireEvent.click(
      screen.getByRole("button", { name: /Submit verified result/i }),
    );

    await waitFor(() =>
      expect(submitAdlcHarnessSession).toHaveBeenCalledWith(
        "run-1",
        "session-1",
      ),
    );
  });

  it("reconciles one run and reports the bounded recovery result", async () => {
    (getAdlcHarnessSessions as jest.Mock).mockResolvedValue([
      {
        attempt_id: "attempt-1",
        task_run_id: "task-1",
        attempt_status: "RUNNING",
        session: {
          schema_version: "0.1",
          session_id: "session-1",
          status: "RUNNING",
          submission_mode: "MANUAL",
          interactions: [],
          created_at: "2026-09-17T00:00:00Z",
          updated_at: "2026-09-17T00:00:00Z",
        },
      },
    ] satisfies AdlcHarnessRunSession[]);
    (reconcileAdlcHarnessRun as jest.Mock).mockResolvedValue({
      inspected: 1,
      recovered_results: 1,
      submitted_sessions: 0,
      unavailable_sessions: 0,
    });

    render(<RunDetailPage />);
    fireEvent.click(
      await screen.findByRole("button", { name: /Recover Harness state/i }),
    );

    await waitFor(() =>
      expect(reconcileAdlcHarnessRun).toHaveBeenCalledWith("run-1"),
    );
    expect(await screen.findByText(/1 result\(s\) recovered/)).toBeVisible();
  });

  it("keeps completed results visible when the Harness session is gone or offline", async () => {
    (getAdlcRun as jest.Mock).mockResolvedValue({
      ...run,
      status: "SUCCEEDED",
      approval_requests: [],
    });
    (getAdlcRunTasks as jest.Mock).mockResolvedValue([
      { ...task, artifacts: [] },
    ]);
    (getAdlcHarnessSessions as jest.Mock).mockRejectedValue(
      new Error("Harness is offline"),
    );
    (getAdlcHarnessResults as jest.Mock).mockResolvedValue([
      {
        attempt_id: "attempt-1",
        task_run_id: "task-1",
        attempt_status: "SUCCEEDED",
        stored_at: "2026-10-02T00:00:00Z",
        result: {
          status: "SUCCEEDED",
          output: { summary: "The final answer is retained." },
        },
      },
    ]);

    render(<RunDetailPage />);
    fireEvent.click(
      await screen.findByRole("tab", { name: "Hoạt động & nâng cao" }),
    );
    expect(
      await screen.findByText("The final answer is retained."),
    ).toBeVisible();
    expect(screen.getByText(/Saved in ADLC/)).toBeVisible();
    expect(
      await screen.findByText(/Live Harness control is unavailable/),
    ).toBeVisible();
    // An older in-flight archive snapshot must not erase an accepted result.
    (getAdlcHarnessResults as jest.Mock).mockResolvedValueOnce([]);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    });
    expect(getAdlcHarnessResults).toHaveBeenCalledTimes(2);
    expect(screen.getByText("The final answer is retained.")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: /Submit verified result/i }),
    ).not.toBeInTheDocument();
  });

  it("loads saved results without waiting for a slow live Harness response", async () => {
    (getAdlcRun as jest.Mock).mockResolvedValue({
      ...run,
      status: "SUCCEEDED",
      approval_requests: [],
    });
    (getAdlcRunTasks as jest.Mock).mockResolvedValue([
      { ...task, artifacts: [] },
    ]);
    (getAdlcHarnessSessions as jest.Mock).mockReturnValue(
      new Promise(() => {}),
    );
    (getAdlcHarnessResults as jest.Mock).mockResolvedValue([
      {
        attempt_id: "attempt-1",
        task_run_id: "task-1",
        attempt_status: "SUCCEEDED",
        stored_at: "2026-10-02T00:00:00Z",
        result: { status: "SUCCEEDED", output: "Read from ADLC only." },
      },
    ]);

    render(<RunDetailPage />);
    fireEvent.click(
      await screen.findByRole("tab", { name: "Hoạt động & nâng cao" }),
    );
    expect(await screen.findByText("Read from ADLC only.")).toBeVisible();
  });

  it("still shows the run if its archive cannot be refreshed", async () => {
    (getAdlcRunTasks as jest.Mock).mockResolvedValue([
      { ...task, artifacts: [] },
    ]);
    (getAdlcHarnessResults as jest.Mock).mockRejectedValue(
      new Error("Archive error"),
    );

    render(<RunDetailPage />);
    expect(
      await screen.findByRole("heading", { name: "Review run" }),
    ).toBeVisible();
    expect(
      screen.getByText(/Unable to refresh saved agent results: Archive error/),
    ).toBeVisible();
  });
});

describe("RunDetailPage operator controls and loop approval", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (useParams as jest.Mock).mockReturnValue({ runId: "run-1" });
    (getAdlcRun as jest.Mock).mockResolvedValue(run);
    (getAdlcRunTasks as jest.Mock).mockResolvedValue([]);
    (getAdlcRunEvents as jest.Mock).mockResolvedValue({
      workflow_run_id: "run-1",
      events: [],
    });
    (getAdlcHarnessSessions as jest.Mock).mockResolvedValue([]);
    (getAdlcHarnessResults as jest.Mock).mockResolvedValue([]);
    (getAdlcRunControls as jest.Mock).mockResolvedValue({
      workflow_run_id: "run-1",
      can_pause: false,
      can_resume: false,
      can_cancel: true,
      pause_requested: false,
      pause_reason: null,
    });
  });

  it("requests a pause and explains the iteration boundary", async () => {
    (getAdlcRun as jest.Mock).mockResolvedValue({
      ...run,
      status: "RUNNING",
      approval_requests: [],
    });
    (getAdlcRunControls as jest.Mock)
      .mockResolvedValueOnce({
        workflow_run_id: "run-1",
        can_pause: true,
        can_resume: false,
        can_cancel: true,
        pause_requested: false,
        pause_reason: null,
      })
      .mockResolvedValue({
        workflow_run_id: "run-1",
        can_pause: false,
        can_resume: false,
        can_cancel: true,
        pause_requested: true,
        pause_reason: null,
      });
    (pauseAdlcRun as jest.Mock).mockResolvedValue({
      ...run,
      status: "RUNNING",
    });
    render(<RunDetailPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Pause" }));
    await waitFor(() => expect(pauseAdlcRun).toHaveBeenCalledWith("run-1"));
    expect(
      await screen.findByText(/Waiting for the current iteration to finish/),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Pause" }),
    ).not.toBeInTheDocument();
  });

  it("shows retained review feedback after rejection", async () => {
    (getAdlcRun as jest.Mock).mockResolvedValue({
      ...run,
      status: "FAILED",
      approval_requests: [
        {
          ...run.approval_requests[0],
          status: "REJECTED",
          decision: {
            comment: "Fix the repeated verifier failure in the next run.",
          },
        },
      ],
    });
    render(<RunDetailPage />);
    expect(
      await screen.findByText(
        "Fix the repeated verifier failure in the next run.",
      ),
    ).toBeVisible();
    expect(
      screen.getByRole("region", { name: "Saved review feedback" }),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Approve" }),
    ).not.toBeInTheDocument();
  });

  it("resumes a user pause and supports cancellation through existing actions", async () => {
    (getAdlcRun as jest.Mock).mockResolvedValue({
      ...run,
      status: "PAUSED",
      approval_requests: [],
    });
    (getAdlcRunControls as jest.Mock).mockResolvedValue({
      workflow_run_id: "run-1",
      can_pause: false,
      can_resume: true,
      can_cancel: true,
      pause_requested: true,
      pause_reason: "user_requested",
    });
    (resumeAdlcRun as jest.Mock).mockResolvedValue(run);
    (cancelAdlcRun as jest.Mock).mockResolvedValue({
      ...run,
      status: "CANCELLED",
    });
    render(<RunDetailPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Resume" }));
    await waitFor(() => expect(resumeAdlcRun).toHaveBeenCalledWith("run-1"));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Cancel run/i })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: /Cancel run/i }));
    await waitFor(() => expect(cancelAdlcRun).toHaveBeenCalledWith("run-1"));
  });

  it("keeps controls unavailable when their owner-scoped read fails", async () => {
    (getAdlcRun as jest.Mock).mockResolvedValue({
      ...run,
      status: "PAUSED",
      approval_requests: [],
    });
    (getAdlcRunControls as jest.Mock).mockRejectedValue(
      new Error("Unavailable"),
    );
    render(<RunDetailPage />);
    expect(
      await screen.findByText(/Run controls are unavailable/),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Resume" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Cancel run/i }),
    ).not.toBeInTheDocument();
  });

  it("requires the task-loop candidate patch to load before approval and retains feedback", async () => {
    const loopArtifact = {
      ...artifact,
      metadata: {
        capture: "task-loop-candidate",
        candidate_id: "verified-candidate",
        candidate_digest: "sha256:verified",
        iteration: 2,
      },
    };
    (getAdlcRunTasks as jest.Mock).mockResolvedValue([
      {
        ...task,
        executor: {
          service: "agent-provider:coding-agent-contract-loop",
          operation: "coding-task-loop",
        },
        artifacts: [loopArtifact],
      },
    ]);
    (getAdlcTaskLoop as jest.Mock).mockReturnValue(new Promise(() => {}));
    let resolvePatch: (patch: unknown) => void = () => undefined;
    (getAdlcSourcePatch as jest.Mock).mockReturnValue(
      new Promise((resolve) => {
        resolvePatch = resolve;
      }),
    );
    (rejectAdlcRun as jest.Mock).mockResolvedValue({
      ...run,
      status: "FAILED",
    });
    render(<RunDetailPage />);
    const approve = await screen.findByRole("button", { name: "Approve" });
    expect(approve).toBeDisabled();
    await act(async () =>
      resolvePatch({
        artifact: loopArtifact,
        format: "opencode-vcs-diff-v1",
        files: [],
        reported_files: [],
      }),
    );
    await waitFor(() => expect(approve).toBeEnabled());
    expect(screen.getByText("Candidate verified-candidate")).not.toBeVisible();
    fireEvent.click(screen.getByText("Thông tin kỹ thuật & thời hạn lưu"));
    expect(screen.getByText("Candidate verified-candidate")).toBeVisible();
    fireEvent.click(screen.getByText("Thêm nhận xét (không bắt buộc)"));
    fireEvent.change(screen.getByRole("textbox", { name: "Review feedback" }), {
      target: { value: "Improve the verifier in the successor run." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    fireEvent.change(
      screen.getByRole("textbox", { name: "Rejection reason" }),
      {
        target: { value: "Improve the verifier in the successor run." },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: /Reject &/ }));
    await waitFor(() =>
      expect(rejectAdlcRun).toHaveBeenCalledWith(
        "approval-1",
        "Improve the verifier in the successor run.",
      ),
    );
  });
});
