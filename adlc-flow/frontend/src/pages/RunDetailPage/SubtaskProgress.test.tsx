import { render, screen } from "@testing-library/react";
import SubtaskProgress from "./SubtaskProgress";
import { makeSummary } from "./__fixtures__/subtasks";

describe("SubtaskProgress", () => {
  it("renders nothing useful when total is zero", () => {
    render(<SubtaskProgress summary={makeSummary()} />);
    expect(screen.getByText("No subtasks")).toBeInTheDocument();
  });

  it("shows succeeded/total count", () => {
    render(
      <SubtaskProgress
        summary={makeSummary({ total: 8, succeeded: 5, failed: 1, running: 2 })}
      />,
    );
    expect(screen.getByText("5/8")).toBeInTheDocument();
  });

  it("shows failed badge when there are failures", () => {
    render(
      <SubtaskProgress
        summary={makeSummary({ total: 3, succeeded: 1, failed: 1, running: 1 })}
      />,
    );
    expect(screen.getByText("1 failed")).toBeInTheDocument();
  });

  it("shows running badge when there are running subtasks", () => {
    render(
      <SubtaskProgress
        summary={makeSummary({ total: 3, succeeded: 1, running: 2 })}
      />,
    );
    expect(screen.getByText("2 running")).toBeInTheDocument();
  });

  it("hides badges in compact mode", () => {
    render(
      <SubtaskProgress
        summary={makeSummary({ total: 3, succeeded: 1, failed: 1, running: 1 })}
        compact
      />,
    );
    expect(screen.queryByText("1 failed")).not.toBeInTheDocument();
    expect(screen.queryByText("1 running")).not.toBeInTheDocument();
  });

  it("renders progress bar segments", () => {
    const { container } = render(
      <SubtaskProgress
        summary={makeSummary({ total: 4, succeeded: 2, running: 1, pending: 1 })}
      />,
    );
    const segments = container.querySelectorAll("[title]");
    expect(segments.length).toBeGreaterThan(0);
  });
});
