import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  projectIssues,
  type IssueProposal,
} from "@/controllers/API/project-issues";
import IssueAssessment, { IssueAuditTrail } from "./issue-assessment";

const item: IssueProposal = {
  proposal_id: "proposal-a",
  project_id: "project-a",
  repository: "admin/notes",
  source_digest: "a".repeat(64),
  revision: 1,
  state: "NEEDS_CONTEXT",
  issue: {
    number: 7,
    title: "Counter",
    body: "TBD",
    state: "open",
    author: "maintainer",
    url: "http://gitea/issue/7",
    labels: [],
    updated_at: null,
  },
  run_id: null,
  previous_runs: [],
  error_code: null,
  review_reason: null,
  triage: {
    version: "v1",
    action: "needs_human",
    confidence: 0.45,
    reasons: ["Cần chốt kết quả kiểm chứng."],
    questions: [],
    input_digest: "b".repeat(64),
    planning_style: "implement",
  },
  risk: {
    tier: "R1",
    level: 1,
    preliminary: true,
    paths: [],
    factors: [
      {
        factor: "reversibility",
        level: 1,
        reason: "Chỉ thay đổi code trong bản làm việc.",
      },
    ],
  },
};
const answers = {
  goal: "Show a click counter",
  scope: "Only app.js and tests",
  acceptance: "Three clicks must show three",
};
const fields: Record<string, RegExp> = {
  goal: /Kết quả cụ thể/,
  scope: /Phần nào hoặc file nào/,
  acceptance: /Kiểm tra thế nào/,
};
function mount(value = item) {
  const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    }),
    onChange = jest.fn().mockResolvedValue(undefined);
  return {
    ...render(
      <QueryClientProvider client={client}>
        <IssueAssessment item={value} onChange={onChange} />
      </QueryClientProvider>,
    ),
    onChange,
    client,
  };
}
beforeEach(() => {
  jest
    .spyOn(projectIssues, "clarify")
    .mockResolvedValue({
      ...item,
      state: "DETECTED",
      triage: { ...item.triage!, action: "ready" },
    });
  jest
    .spyOn(projectIssues, "audit")
    .mockResolvedValue({
      items: [
        {
          id: 1,
          event: "auto_approved",
          at: "2026-10-27T00:00:00Z",
          details: {
            policy_revision: 3,
            risk: {
              tier: "R1",
              level: 1,
              preliminary: false,
              paths: ["app.js"],
              factors: [],
            },
          },
        },
      ],
    });
});
afterEach(() => jest.restoreAllMocks());

it("requires all clarifications before saving and binds the response to the source", async () => {
  const { onChange } = mount();
  const save = screen.getByRole("button", { name: "Lưu thông tin" });
  expect(save).toBeDisabled();
  for (const [key, value] of Object.entries(answers))
    fireEvent.change(screen.getByRole("textbox", { name: fields[key] }), {
      target: { value },
    });
  fireEvent.change(screen.getByRole("combobox"), {
    target: { value: "spec_first" },
  });
  fireEvent.click(save);
  await waitFor(() =>
    expect(projectIssues.clarify).toHaveBeenCalledWith(
      item.project_id,
      item,
      answers,
      "spec_first",
    ),
  );
  expect(onChange).toHaveBeenCalled();
  expect(await screen.findByRole("status")).toHaveTextContent(
    "Đã lưu thông tin",
  );
});
it("keeps the human's draft when the same issue is refreshed", () => {
  const { rerender, onChange, client } = mount();
  const input = screen.getByRole("textbox", { name: fields.goal });
  fireEvent.change(input, { target: { value: "My unsent outcome" } });
  rerender(
    <QueryClientProvider client={client}>
      <IssueAssessment item={{ ...item }} onChange={onChange} />
    </QueryClientProvider>,
  );
  expect(screen.getByRole("textbox", { name: fields.goal })).toHaveValue(
    "My unsent outcome",
  );
});
it("shows a save error without losing the answer", async () => {
  jest
    .mocked(projectIssues.clarify)
    .mockRejectedValue({
      response: { data: { detail: { code: "ISSUE_CHANGED" } } },
    });
  mount();
  for (const [key, value] of Object.entries(answers))
    fireEvent.change(screen.getByRole("textbox", { name: fields[key] }), {
      target: { value },
    });
  fireEvent.click(screen.getByRole("button", { name: "Lưu thông tin" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Issue đã thay đổi",
  );
  expect(screen.getByRole("textbox", { name: fields.goal })).toHaveValue(
    answers.goal,
  );
});
it("explains high risk even when the issue is clear enough to plan", () => {
  mount({
    ...item,
    triage: { ...item.triage!, action: "ready" },
    risk: { ...item.risk!, tier: "R3", level: 3 },
    auto_decision: {
      allowed: false,
      code: "ISSUE_RISK_REVIEW_REQUIRED",
      policy_revision: 1,
      risk_tier: "R3",
    },
  });
  expect(screen.getByText("Dự kiến R3")).toBeInTheDocument();
  expect(screen.getByText(/rủi ro từ R2 trở lên/)).toBeInTheDocument();
});
it("preserves the answers used by a running job instead of editing its requirement", () => {
  mount({
    ...item,
    run_id: "run-a",
    triage: { ...item.triage!, action: "ready" },
    clarification: {
      source_digest: item.source_digest,
      answers,
      approach: "implement",
      by: "alice",
      at: "2026-10-27T00:00:00Z",
    },
  });
  fireEvent.click(screen.getByText("Thông tin đã dùng để lập kế hoạch"));
  expect(screen.getByText(answers.goal)).toBeInTheDocument();
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
});
it("loads the decision history only when opened and scopes it to the project", async () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <IssueAuditTrail item={item} identity="alice" />
    </QueryClientProvider>,
  );
  expect(projectIssues.audit).not.toHaveBeenCalled();
  const details = screen.getByText("Lịch sử quyết định").closest("details")!;
  details.open = true;
  fireEvent(details, new Event("toggle"));
  expect(
    await screen.findByText("Duyệt thực hiện theo chính sách project"),
  ).toBeInTheDocument();
  expect(projectIssues.audit).toHaveBeenCalledWith(
    item.project_id,
    item.proposal_id,
  );
  expect(screen.getByText(/Chính sách v3/)).toBeInTheDocument();
});
