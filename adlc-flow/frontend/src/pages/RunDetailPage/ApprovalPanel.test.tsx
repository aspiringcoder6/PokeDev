import { fireEvent, render, screen } from "@testing-library/react";
import ApprovalPanel from "./ApprovalPanel";
import type { AdlcApprovalRequest, AdlcTaskRun } from "@/types/adlc";

const approval: AdlcApprovalRequest = {
  approval_request_id: "apr-1",
  workflow_run_id: "run-1",
  task_run_id: "task-1",
  status: "PENDING",
  title: "Approve changes",
  context: {
    summary: "Review the changes before continuing.",
  },
};

const tasks: AdlcTaskRun[] = [
  {
    id: "task-1",
    workflow_run_id: "run-1",
    key: "task-1",
    name: "Implement feature",
    task_type: "backend",
    status: "SUCCEEDED",
    dependency_task_run_ids: [],
    retry_count: 0,
  },
  {
    id: "task-2",
    workflow_run_id: "run-1",
    key: "task-2",
    name: "Write tests",
    task_type: "testing",
    status: "SUCCEEDED",
    dependency_task_run_ids: ["task-1"],
    retry_count: 0,
  },
];

describe("ApprovalPanel", () => {
  it("renders approval title and summary", () => {
    render(
      <ApprovalPanel
        approval={approval}
        tasks={tasks}
        acting={false}
        onApprove={jest.fn()}
        onReject={jest.fn()}
      />,
    );
    expect(screen.getByText("Approve changes")).toBeInTheDocument();
    expect(
      screen.getByText("Review the changes before continuing."),
    ).toBeInTheDocument();
  });

  it("shows Accept and Reject buttons by default", () => {
    render(
      <ApprovalPanel
        approval={approval}
        tasks={tasks}
        acting={false}
        onApprove={jest.fn()}
        onReject={jest.fn()}
      />,
    );
    expect(screen.getByTestId("approval-approve")).toBeInTheDocument();
    expect(screen.getByTestId("approval-reject-toggle")).toBeInTheDocument();
  });

  it("calls onApprove when Accept is clicked", () => {
    const onApprove = jest.fn();
    render(
      <ApprovalPanel
        approval={approval}
        tasks={tasks}
        acting={false}
        onApprove={onApprove}
        onReject={jest.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("approval-approve"));
    expect(onApprove).toHaveBeenCalledWith(undefined);
  });

  it("shows reject form when Reject is clicked", () => {
    render(
      <ApprovalPanel
        approval={approval}
        tasks={tasks}
        acting={false}
        onApprove={jest.fn()}
        onReject={jest.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("approval-reject-toggle"));
    expect(screen.getByTestId("approval-reject-form")).toBeInTheDocument();
    expect(screen.getByTestId("approval-reject-reason")).toBeInTheDocument();
  });

  it("requires reason before allowing reject submission", () => {
    render(
      <ApprovalPanel
        approval={approval}
        tasks={tasks}
        acting={false}
        onApprove={jest.fn()}
        onReject={jest.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("approval-reject-toggle"));
    const submitBtn = screen.getByTestId("approval-reject-submit");
    expect(submitBtn).toBeDisabled();
  });

  it("calls onReject with reason and target task when submitted", () => {
    const onReject = jest.fn();
    render(
      <ApprovalPanel
        approval={approval}
        tasks={tasks}
        acting={false}
        onApprove={jest.fn()}
        onReject={onReject}
      />,
    );
    fireEvent.click(screen.getByTestId("approval-reject-toggle"));
    fireEvent.change(screen.getByTestId("approval-reject-reason"), {
      target: { value: "Need to add error handling" },
    });
    fireEvent.change(screen.getByTestId("approval-reject-target"), {
      target: { value: "task-1" },
    });
    fireEvent.click(screen.getByTestId("approval-reject-submit"));
    expect(onReject).toHaveBeenCalledWith(
      "Need to add error handling",
      "task-1",
    );
  });

  it("calls onReject without target task when none selected", () => {
    const onReject = jest.fn();
    render(
      <ApprovalPanel
        approval={approval}
        tasks={tasks}
        acting={false}
        onApprove={jest.fn()}
        onReject={onReject}
      />,
    );
    fireEvent.click(screen.getByTestId("approval-reject-toggle"));
    fireEvent.change(screen.getByTestId("approval-reject-reason"), {
      target: { value: "General feedback" },
    });
    fireEvent.click(screen.getByTestId("approval-reject-submit"));
    expect(onReject).toHaveBeenCalledWith("General feedback", undefined);
  });

  it("cancels reject form when Cancel is clicked", () => {
    render(
      <ApprovalPanel
        approval={approval}
        tasks={tasks}
        acting={false}
        onApprove={jest.fn()}
        onReject={jest.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("approval-reject-toggle"));
    fireEvent.click(screen.getByTestId("approval-reject-cancel"));
    expect(screen.queryByTestId("approval-reject-form")).not.toBeInTheDocument();
  });

  it("disables buttons when disabled prop is true", () => {
    render(
      <ApprovalPanel
        approval={approval}
        tasks={tasks}
        acting={false}
        disabled
        disabledReason="Patches not loaded"
        onApprove={jest.fn()}
        onReject={jest.fn()}
      />,
    );
    expect(screen.getByTestId("approval-approve")).toBeDisabled();
    expect(screen.getByTestId("approval-reject-toggle")).toBeDisabled();
    expect(screen.getByTestId("approval-disabled-reason")).toHaveTextContent(
      "Patches not loaded",
    );
  });

  it("lists redoable tasks in the target dropdown", () => {
    render(
      <ApprovalPanel
        approval={approval}
        tasks={tasks}
        acting={false}
        onApprove={jest.fn()}
        onReject={jest.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("approval-reject-toggle"));
    const select = screen.getByTestId("approval-reject-target");
    expect(select).toBeInTheDocument();
    // Both tasks should be in the dropdown.
    expect(screen.getByRole("option", { name: /Implement feature/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Write tests/ })).toBeInTheDocument();
  });
});
