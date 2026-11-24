import { render, screen } from "@testing-library/react";
import ReplayInsights, { replayTrend, sameReplayStandard } from "./insights";
import { replayFixture } from "./test-fixtures";

test("comparison requires identical approved oracle, config and contract, not green alone", () => {
  const first = replayFixture("SUBMITTED"),
    next = replayFixture("SUBMITTED", "FAIL");
  expect(replayTrend(next, first)).toMatch(/Standard changed/);
  next.plan.cases = first.plan.cases.map((c) => ({ ...c }));
  next.plan.candidate.content_digest = "sha256:" + "9".repeat(64);
  expect(sameReplayStandard(next, first)).toBe(true);
  expect(replayTrend(next, first)).toMatch(/Fixture regression/);
  expect(replayTrend(first, next)).toMatch(/Recovered fixture/);
  next.plan.contract_reference.revision++;
  expect(sameReplayStandard(next, first)).toBe(false);
  expect(replayTrend(next, first)).toMatch(/Standard changed/);
});
test("pending/uncertain/cancelled runs never become completed comparisons", () => {
  render(
    <ReplayInsights
      rows={[
        replayFixture("RUNNING"),
        {
          ...replayFixture("CANCELLED"),
          plan: { ...replayFixture().plan, plan_id: "cancelled-two" },
        },
      ]}
    />,
  );
  expect(screen.getByText("0 completed comparisons")).toBeInTheDocument();
  expect(screen.queryByText(/^PASS$/)).not.toBeInTheDocument();
  expect(
    screen.getAllByText(/0\/1 confirmed complete · no verdict/),
  ).toHaveLength(2);
});
