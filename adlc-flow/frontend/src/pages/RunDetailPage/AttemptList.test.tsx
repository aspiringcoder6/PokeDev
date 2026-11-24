import { render, screen } from "@testing-library/react";
import type { AdlcRunEvent, AdlcTaskRun } from "@/types/adlc";
import AttemptList, {
  buildTaskAttempts,
} from "@/pages/RunDetailPage/AttemptList";

let sequence = 0;

function makeEvent(overrides: Partial<AdlcRunEvent>): AdlcRunEvent {
  sequence += 1;
  return {
    event_id: `event-${sequence}`,
    event_type: "task_run.started",
    sequence,
    status: "RUNNING",
    occurred_at: new Date(Date.parse("2026-09-17T10:30:00Z") + sequence * 1000)
      .toISOString(),
    ...overrides,
  };
}

const task: AdlcTaskRun = {
  id: "task-1",
  workflow_run_id: "run-1",
  key: "implement",
  name: "Implement",
  task_type: "coding",
  status: "SUCCEEDED",
  dependency_task_run_ids: [],
  retry_count: 1,
};

describe("buildTaskAttempts", () => {
  it("derives one attempt per attempt_id and carries the failure code", () => {
    const attempts = buildTaskAttempts(task, [
      makeEvent({
        event_type: "task_run.started",
        task_run_id: "task-1",
        attempt_id: "attempt-1",
      }),
      makeEvent({
        event_type: "task_run.failed",
        status: "FAILED",
        task_run_id: "task-1",
        attempt_id: "attempt-1",
        payload: { error_code: "MOCK_EXECUTION_FAILED" },
      }),
      makeEvent({
        event_type: "task_run.started",
        task_run_id: "task-1",
        attempt_id: "attempt-2",
      }),
    ]);

    expect(attempts).toHaveLength(2);
    expect(attempts[0]).toMatchObject({
      attemptId: "attempt-1",
      number: 1,
      status: "FAILED",
      errorCode: "MOCK_EXECUTION_FAILED",
    });
    expect(attempts[0].startedAt).toBeDefined();
    expect(attempts[0].finishedAt).toBeDefined();
    expect(attempts[1]).toMatchObject({
      attemptId: "attempt-2",
      number: 2,
      status: "RUNNING",
    });
    expect(attempts[1].errorCode).toBeUndefined();
  });

  it("tracks waiting approval and resume within the same attempt", () => {
    const [attempt] = buildTaskAttempts(task, [
      makeEvent({
        event_type: "task_run.started",
        task_run_id: "task-1",
        attempt_id: "attempt-1",
      }),
      makeEvent({
        event_type: "task_run.waiting_approval",
        status: "WAITING_APPROVAL",
        task_run_id: "task-1",
        attempt_id: "attempt-1",
      }),
      makeEvent({
        event_type: "task_run.resumed",
        task_run_id: "task-1",
        attempt_id: "attempt-1",
      }),
      makeEvent({
        event_type: "task_run.succeeded",
        status: "SUCCEEDED",
        task_run_id: "task-1",
        attempt_id: "attempt-1",
      }),
    ]);

    expect(attempt.status).toBe("SUCCEEDED");
  });

  it("ignores events from other tasks and events without an attempt", () => {
    const attempts = buildTaskAttempts(task, [
      makeEvent({
        event_type: "task_run.created",
        status: "PENDING",
        task_run_id: "task-1",
      }),
      makeEvent({
        event_type: "task_run.started",
        task_run_id: "task-other",
        attempt_id: "attempt-9",
      }),
    ]);

    expect(attempts).toHaveLength(1);
    expect(attempts[0].attemptId).toBe("");
    expect(attempts[0].status).toBe(task.status);
  });

  it("returns nothing for a pending task without attempt events", () => {
    const pendingTask: AdlcTaskRun = { ...task, status: "PENDING" };
    expect(buildTaskAttempts(pendingTask, [])).toHaveLength(0);
  });
});

describe("AttemptList", () => {
  it("renders the attempt history and puts the retry slot on the latest attempt", () => {
    render(
      <AttemptList
        task={{ ...task, status: "RUNNING" }}
        events={[
          makeEvent({
            event_type: "task_run.started",
            task_run_id: "task-1",
            attempt_id: "attempt-1",
          }),
          makeEvent({
            event_type: "task_run.failed",
            status: "FAILED",
            task_run_id: "task-1",
            attempt_id: "attempt-1",
            payload: { error_code: "MOCK_EXECUTION_FAILED" },
          }),
          makeEvent({
            event_type: "task_run.started",
            task_run_id: "task-1",
            attempt_id: "attempt-2",
          }),
        ]}
        retrySlot={<button type="button">Retry</button>}
      />,
    );

    expect(screen.getByText("Attempt #1")).toBeInTheDocument();
    expect(screen.getByText("Attempt #2")).toBeInTheDocument();
    expect(screen.getByText("MOCK_EXECUTION_FAILED")).toBeVisible();
    const retryButtons = screen.getAllByRole("button", { name: "Retry" });
    expect(retryButtons).toHaveLength(1);
    expect(
      retryButtons[0].closest("li")?.textContent?.includes("Attempt #2"),
    ).toBe(true);
  });

  it("renders nothing for a pending task", () => {
    const { container } = render(
      <AttemptList
        task={{ ...task, status: "PENDING" }}
        events={[]}
        retrySlot={<button type="button">Retry</button>}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
