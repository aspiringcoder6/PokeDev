import { fireEvent, render, screen } from "@testing-library/react";
import type { AdlcHarnessRunSession } from "@/types/adlc";
import HarnessSessions from "./HarnessSessions";

function session(
  status: "VERIFYING" | "RUNNING" | "READY_FOR_SUBMISSION",
  waiting = true,
): AdlcHarnessRunSession {
  return {
    attempt_id: "attempt-1",
    task_run_id: "task-1",
    attempt_status: "VERIFYING",
    session: {
      schema_version: "0.1",
      session_id: "session-1",
      status,
      submission_mode: "MANUAL",
      interactions: [],
      created_at: "2026-10-08T00:00:00Z",
      updated_at: "2026-10-08T00:00:00Z",
      events: [
        {
          event_type: waiting
            ? "execution.reconciliation_waiting"
            : "verification.started",
        },
      ],
    },
  };
}

test("recovery retries only the saved verification, without responding or submitting", () => {
  const onRespond = jest.fn(),
    onSubmit = jest.fn(),
    onReconcileVerification = jest.fn();
  render(
    <HarnessSessions
      sessions={[session("VERIFYING")]}
      tasks={[]}
      onRespond={onRespond}
      onSubmit={onSubmit}
      onReconcileVerification={onReconcileVerification}
    />,
  );
  expect(
    screen.getByText(/does not call the model again or Submit/),
  ).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: /retry verification recovery/i }),
  );
  expect(onReconcileVerification).toHaveBeenCalledWith("session-1");
  expect(onRespond).not.toHaveBeenCalled();
  expect(onSubmit).not.toHaveBeenCalled();
});

test.each([
  ["RUNNING", true],
  ["VERIFYING", false],
] as const)(
  "normal %s activity is not presented as a recovery command",
  (status, waiting) => {
    render(
      <HarnessSessions
        sessions={[session(status, waiting)]}
        tasks={[]}
        onRespond={jest.fn()}
        onSubmit={jest.fn()}
        onReconcileVerification={jest.fn()}
      />,
    );
    expect(
      screen.queryByRole("button", { name: /retry verification recovery/i }),
    ).not.toBeInTheDocument();
  },
);

test("a recovered MANUAL candidate still needs a separate Submit", () => {
  const onSubmit = jest.fn(),
    onReconcileVerification = jest.fn();
  render(
    <HarnessSessions
      sessions={[session("READY_FOR_SUBMISSION")]}
      tasks={[]}
      onRespond={jest.fn()}
      onSubmit={onSubmit}
      onReconcileVerification={onReconcileVerification}
    />,
  );
  expect(onSubmit).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: /submit verified result/i }),
  );
  expect(onSubmit).toHaveBeenCalledWith("session-1");
  expect(onReconcileVerification).not.toHaveBeenCalled();
});
