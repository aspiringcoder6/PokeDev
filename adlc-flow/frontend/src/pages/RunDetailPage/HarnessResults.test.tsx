jest.unmock("react-markdown");
jest.mock("@/components/core/codeTabsComponent", () => () => null);

import { fireEvent, render, screen, within } from "@testing-library/react";
import type {
  AdlcHarnessRunResult,
  AdlcHarnessRunSession,
  AdlcTaskRun,
} from "@/types/adlc";
import HarnessResults from "./HarnessResults";

const saved: AdlcHarnessRunResult = {
  attempt_id: "attempt-1",
  task_run_id: "task-1",
  attempt_status: "SUCCEEDED",
  stored_at: "2026-10-02T00:00:02Z",
  result: {
    session_id: "closed-session-1",
    status: "SUCCEEDED",
    output: {
      summary: "Completed the **read-only** review.",
      outputs: { answer: "Ready for the next stage." },
    },
    artifacts: [],
    verification_reports: [
      {
        verifier_ref: "plugin:vai-adlc-verify-structured/0.1.0",
        status: "PASSED",
        checks: [
          {
            check_id: "structured",
            status: "PASSED",
            summary: "The result matches the schema.",
          },
        ],
        started_at: "2026-10-02T00:00:00Z",
        completed_at: "2026-10-02T00:00:01Z",
      },
    ],
    interaction_records: [
      {
        interaction_id: "approval-1",
        kind: "APPROVAL",
        status: "SUBMITTED",
        title: "Confirm report",
        prompt: "Return the report?",
        input_schema: {},
        ui_schema: {},
        requested_at: "2026-10-02T00:00:00Z",
        response: { action: "approve" },
        metadata: {},
      },
    ],
    trace_ref: "harness://closed-session-1/events",
    metadata: { driver: { provider: "my-codex", model: "cx/gpt-5.6-luna" } },
    completed_at: "2026-10-02T00:00:01Z",
  },
};

const task: AdlcTaskRun = {
  id: "task-1",
  workflow_run_id: "run-1",
  key: "review",
  name: "Review project",
  task_type: "coding",
  status: "SUCCEEDED",
  dependency_task_run_ids: [],
  retry_count: 0,
};

const preview: AdlcHarnessRunSession = {
  attempt_id: "attempt-1",
  task_run_id: "task-1",
  attempt_status: "READY_TO_SUBMIT",
  session: {
    schema_version: "0.1",
    session_id: "closed-session-1",
    status: "READY_FOR_SUBMISSION",
    submission_mode: "MANUAL",
    interactions: [],
    result: saved.result,
    created_at: "2026-10-02T00:00:00Z",
    updated_at: "2026-10-02T00:00:01Z",
  },
};

describe("HarnessResults", () => {
  it("renders retained output, verification, model route, and human interaction history", () => {
    render(<HarnessResults results={[saved]} sessions={[]} tasks={[task]} />);
    const section = screen.getByRole("region", { name: "Agent results" });
    expect(
      within(section).getByRole("heading", { name: "Review project" }),
    ).toBeVisible();
    expect(within(section).getByText("read-only").tagName).toBe("STRONG");
    expect(section).toHaveTextContent("Ready for the next stage.");
    expect(
      screen.getByText("PASSED: The result matches the schema."),
    ).toBeVisible();
    expect(
      screen.getByText("Executed with my-codex / cx/gpt-5.6-luna"),
    ).toBeVisible();
    fireEvent.click(screen.getByText("Human interaction history"));
    expect(screen.getByText("Confirm report · SUBMITTED")).toBeVisible();
    fireEvent.click(screen.getByText("Result JSON & diagnostics"));
    expect(screen.getByText("Harness session: closed-session-1")).toBeVisible();
  });

  it("labels a manual preview honestly and prefers the saved copy without duplication", () => {
    const view = render(
      <HarnessResults results={[]} sessions={[preview]} tasks={[task]} />,
    );
    expect(
      screen.getByText(/Harness preview.*manual runs still require Submit/),
    ).toBeVisible();
    expect(screen.queryByText(/Saved in ADLC/)).not.toBeInTheDocument();

    view.rerender(
      <HarnessResults results={[saved]} sessions={[preview]} tasks={[task]} />,
    );
    expect(screen.queryByText(/Harness preview/)).not.toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: /Download result JSON/i }),
    ).toHaveLength(1);
  });

  it("retains each retry attempt, including failure details and verification failures", () => {
    const failed: AdlcHarnessRunResult = {
      ...saved,
      attempt_id: "attempt-failed",
      attempt_status: "FAILED",
      result: {
        ...saved.result,
        status: "FAILED",
        output: null,
        error: {
          code: "HARNESS_VERIFY_FAILED",
          message: "The output did not pass verification.",
        },
        verification_reports: [
          {
            ...saved.result.verification_reports![0],
            status: "FAILED",
            checks: [],
          },
        ],
      },
    };
    render(
      <HarnessResults results={[failed, saved]} sessions={[]} tasks={[task]} />,
    );
    expect(
      screen.getAllByRole("button", { name: /Download result JSON/i }),
    ).toHaveLength(2);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "HARNESS_VERIFY_FAILED",
    );
    expect(
      screen.getByText("FAILED · plugin:vai-adlc-verify-structured/0.1.0"),
    ).toBeVisible();
    expect(screen.getByText("No output was returned.")).toBeVisible();
  });

  it("does not ask for Submit again while the callback is delivering", () => {
    render(
      <HarnessResults
        results={[]}
        sessions={[
          { ...preview, session: { ...preview.session, status: "DELIVERING" } },
        ]}
        tasks={[task]}
      />,
    );
    expect(screen.getByText(/Awaiting result receipt by ADLC/)).toBeVisible();
    expect(
      screen.queryByText(/manual runs still require Submit/),
    ).not.toBeInTheDocument();
  });

  it("exports the full accepted result unchanged as JSON", () => {
    URL.createObjectURL = jest.fn(() => "blob:result");
    URL.revokeObjectURL = jest.fn();
    const click = jest
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function (this: HTMLAnchorElement) {
        expect(this.download).toBe("harness-result-attempt-1.json");
        expect(this.href).toBe("blob:result");
      });
    const OriginalBlob = Blob;
    const blob = jest
      .spyOn(global, "Blob")
      .mockImplementation((parts, options) => new OriginalBlob(parts, options));
    render(<HarnessResults results={[saved]} sessions={[]} tasks={[task]} />);
    fireEvent.click(
      screen.getByRole("button", { name: /Download result JSON/i }),
    );
    expect(blob).toHaveBeenCalledWith([JSON.stringify(saved.result, null, 2)], {
      type: "application/json",
    });
    expect(click).toHaveBeenCalledTimes(1);
    blob.mockRestore();
    click.mockRestore();
  });

  it("sanitizes model-provided HTML and does not activate structured-output URLs", () => {
    const unsafe = {
      ...saved,
      result: {
        ...saved.result,
        output: {
          summary:
            '<img src="x" onerror="alert(1)"><a href="javascript:alert(1)">Unsafe link</a>',
          outputs: { uri: "javascript:alert(1)" },
        },
      },
    };
    render(<HarnessResults results={[unsafe]} sessions={[]} tasks={[task]} />);
    expect(screen.getByText("Unsafe link")).not.toHaveAttribute("href");
    expect(document.querySelector("[onerror]")).toBeNull();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
