import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  listTestProposals,
  testExtensionCapabilities,
  testProposalAction,
  testProposalTool,
} from "@/controllers/API/test-extensions";
import { replayFixture } from "../ReplayPanel/test-fixtures";
import TestProposalPanel from ".";
import { extensionCaps, proposalFixture } from "./test-fixtures";

jest.mock("@/controllers/API/test-extensions", () => ({
  listTestProposals: jest.fn(),
  testExtensionCapabilities: jest.fn(),
  testProposalAction: jest.fn(),
  testProposalTool: jest.fn(),
}));
let auth = {
  isAuthenticated: true,
  autoLogin: false,
  userData: { id: "owner-one" },
};
jest.mock("@/stores/authStore", () => ({
  __esModule: true,
  default: (selector) => selector(auth),
}));
const onMaterialized = jest.fn();
beforeEach(() => {
  jest.clearAllMocks();
  auth = {
    isAuthenticated: true,
    autoLogin: false,
    userData: { id: "owner-one" },
  };
  (testExtensionCapabilities as jest.Mock).mockResolvedValue(extensionCaps);
  (listTestProposals as jest.Mock).mockResolvedValue([proposalFixture()]);
  (testProposalTool as jest.Mock).mockResolvedValue(proposalFixture());
  (testProposalAction as jest.Mock).mockResolvedValue(
    proposalFixture("APPROVED"),
  );
});
const mount = (readOnly = false, session = false) =>
  render(
    <TestProposalPanel
      scope={session ? { sessionId: "source-session" } : { runId: "run-one" }}
      replays={[replayFixture()]}
      readOnly={readOnly}
      onMaterialized={onMaterialized}
    />,
  );

test("draft case tools cannot approve or silently heal the source suite", async () => {
  mount();
  await screen.findByText("Review a new test standard");
  fireEvent.change(screen.getByLabelText("Proposed expected JSON scalar"), {
    target: { value: "43" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: /^Save proposed case$/i }),
  );
  await waitFor(() =>
    expect(testProposalTool).toHaveBeenCalledWith(
      "run-one",
      expect.objectContaining({
        operation: "upsert_case",
        reference: proposalFixture().reference,
        case: expect.objectContaining({ expected: 43 }),
        idempotency_key: expect.any(String),
      }),
    ),
  );
  expect(testProposalAction).not.toHaveBeenCalled();
  expect(onMaterialized).not.toHaveBeenCalled();
  expect(screen.queryByText(/^PASS$/)).not.toBeInTheDocument();
});
test("explicit permission checkbox is required before target/data limits are recorded", async () => {
  mount();
  const button = await screen.findByRole("button", {
    name: /^Record target \/ data permissions$/i,
  });
  expect(button).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(button);
  await waitFor(() =>
    expect(testProposalTool).toHaveBeenCalledWith(
      "run-one",
      expect.objectContaining({
        operation: "set_permissions",
        permissions: expect.objectContaining({
          environment: "non-production",
          data_scope: "synthetic-run-owned-only",
          allowed_methods: ["GET"],
        }),
      }),
    ),
  );
});
test("review approval is exact and separate from materialization, execution and Submit", async () => {
  const row = proposalFixture("READY_FOR_REVIEW");
  (listTestProposals as jest.Mock).mockResolvedValue([row]);
  mount();
  const button = await screen.findByRole("button", {
    name: /^Approve exact proposal$/i,
  });
  expect(button).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(button);
  await waitFor(() =>
    expect(testProposalAction).toHaveBeenCalledWith("run-one", row, "approve"),
  );
  expect(onMaterialized).not.toHaveBeenCalled();
  expect(
    screen.queryByRole("button", { name: /Submit|Run approved/ }),
  ).not.toBeInTheDocument();
});
test("approved revision creates only a new frozen replay draft and refreshes its panel", async () => {
  const row = proposalFixture("APPROVED");
  (listTestProposals as jest.Mock).mockResolvedValue([row]);
  mount();
  fireEvent.click(
    await screen.findByRole("button", {
      name: /^Create successor replay draft$/i,
    }),
  );
  await waitFor(() =>
    expect(testProposalAction).toHaveBeenCalledWith(
      "run-one",
      row,
      "materialize",
    ),
  );
  await waitFor(() => expect(onMaterialized).toHaveBeenCalledTimes(1));
});
test("fork uses the exact frozen parent and does not invoke approval", async () => {
  const row = proposalFixture("READY_FOR_REVIEW");
  (listTestProposals as jest.Mock).mockResolvedValue([row]);
  mount();
  fireEvent.click(
    await screen.findByRole("button", {
      name: /^Fork new proposal revision$/i,
    }),
  );
  await waitFor(() =>
    expect(testProposalTool).toHaveBeenCalledWith(
      "run-one",
      expect.objectContaining({
        operation: "init",
        parent_reference: row.reference,
      }),
    ),
  );
  expect(testProposalAction).not.toHaveBeenCalled();
});
test.each(["exploration", "performance"] as const)(
  "%s approval never enables risky execution",
  async (kind) => {
    (listTestProposals as jest.Mock).mockResolvedValue([
      proposalFixture("APPROVED", kind),
    ]);
    mount();
    await screen.findByText("Review a new test standard");
    expect(
      screen.getByText("Live exploration & performance · blocked"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: /Create successor replay|Execute|Run|Submit/i,
      }),
    ).not.toBeInTheDocument();
  },
);
test("native projection reads the exact session and has no mutation controls", async () => {
  (listTestProposals as jest.Mock).mockResolvedValue([
    proposalFixture("READY_FOR_REVIEW"),
  ]);
  mount(true, true);
  await screen.findByText("Review a new test standard");
  expect(listTestProposals).toHaveBeenCalledWith({
    sessionId: "source-session",
  });
  expect(
    screen.queryByRole("button", {
      name: /Approve|Create|Save|Freeze|Fork|Record/i,
    }),
  ).not.toBeInTheDocument();
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
});
test.each([
  "executable",
  "verification_evidence",
  "models_used",
  "heal",
] as const)("forged %s cannot render supported actions", async (field) => {
  const row = proposalFixture("READY_FOR_REVIEW");
  row.document[field] = true as false;
  (listTestProposals as jest.Mock).mockResolvedValue([row]);
  mount();
  await screen.findByText(/Unsupported proposal revision/);
  expect(
    screen.queryByRole("button", { name: /^Approve exact proposal$/i }),
  ).not.toBeInTheDocument();
});
test("unknown target, missing case coverage and changed source cannot enable actions", async () => {
  const a = proposalFixture("READY_FOR_REVIEW"),
    b = proposalFixture("READY_FOR_REVIEW"),
    c = proposalFixture("READY_FOR_REVIEW");
  a.document.permissions!.environment = "production" as "non-production";
  b.document.cases = [];
  c.document.source.candidate_digest = "sha256:" + "9".repeat(64);
  c.document.proposal_id = c.reference.proposal_id = "changed-source";
  (listTestProposals as jest.Mock).mockResolvedValue([a, b, c]);
  mount();
  expect(
    await screen.findAllByText(/Unsupported proposal revision/),
  ).toHaveLength(2);
  expect(
    screen.getByRole("button", { name: /^Approve exact proposal$/i }),
  ).toBeDisabled();
});
test("disabled or auto-login views retain history with no authoring controls", async () => {
  auth.autoLogin = true;
  (testExtensionCapabilities as jest.Mock).mockResolvedValue({
    ...extensionCaps,
    enabled: false,
  });
  mount();
  await screen.findByText("Review a new test standard");
  expect(
    screen.queryByRole("button", { name: /^Create test proposal$/i }),
  ).not.toBeInTheDocument();
});
test("late responses from the prior owner cannot reappear after account switch", async () => {
  let resolve!: (v: unknown) => void;
  (listTestProposals as jest.Mock)
    .mockImplementationOnce(
      () =>
        new Promise((r) => {
          resolve = r;
        }),
    )
    .mockResolvedValue([]);
  const { rerender } = mount();
  await waitFor(() => expect(listTestProposals).toHaveBeenCalled());
  auth = { ...auth, userData: { id: "owner-two" } };
  rerender(
    <TestProposalPanel
      scope={{ runId: "run-one" }}
      replays={[]}
      onMaterialized={onMaterialized}
    />,
  );
  resolve([proposalFixture()]);
  await waitFor(() => expect(listTestProposals).toHaveBeenCalledTimes(2));
  expect(
    screen.queryByText("Review a new test standard"),
  ).not.toBeInTheDocument();
});
test("a proposed expected value change is visibly a new standard, not healing a FAIL", async () => {
  const row = proposalFixture("READY_FOR_REVIEW");
  row.document.cases = row.document.cases.map((c) => ({ ...c, expected: 43 }));
  (listTestProposals as jest.Mock).mockResolvedValue([row]);
  mount();
  await screen.findByText("Proposed changes to the frozen standard");
  expect(
    screen.getByText(
      /answer: \/answer = 42, HTTP 200 → \/answer = 43, HTTP 200/,
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/not a repair of the old verdict/),
  ).toBeInTheDocument();
});
test("malformed identity/approval fields are safe fallbacks without actions", async () => {
  const row = proposalFixture("APPROVED");
  row.document.cases[0].criterion_node_id = {} as string;
  (listTestProposals as jest.Mock).mockResolvedValue([row]);
  mount();
  await screen.findByText(/Unsupported proposal revision/);
  expect(
    screen.queryByRole("button", { name: /^Create successor replay draft$/i }),
  ).not.toBeInTheDocument();
});
