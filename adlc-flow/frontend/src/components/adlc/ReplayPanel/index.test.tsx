import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  createReplay,
  downloadReplay,
  listReplays,
  replayAction,
  replayCapabilities,
} from "@/controllers/API/replay";
import { verificationCandidates } from "@/controllers/API/verification";
import { copyContract } from "../ContractViewer/test-fixtures";
import ReplayPanel from ".";
import { replayFixture, replayFixtureCapabilities } from "./test-fixtures";

jest.mock("../TestProposalPanel", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("./screenshots", () => ({ __esModule: true, default: () => null }));

jest.mock("@/controllers/API/replay", () => ({
  createReplay: jest.fn(),
  downloadReplay: jest.fn(),
  listReplays: jest.fn(),
  replayAction: jest.fn(),
  replayCapabilities: jest.fn(),
}));
jest.mock("@/controllers/API/verification", () => ({
  verificationCandidates: jest.fn(),
}));
let auth = { isAuthenticated: true, autoLogin: false };
jest.mock("@/stores/authStore", () => ({
  __esModule: true,
  default: (selector) => selector(auth),
}));
beforeEach(() => {
  jest.useFakeTimers();
  jest.clearAllMocks();
  auth = { isAuthenticated: true, autoLogin: false };
  (replayCapabilities as jest.Mock).mockResolvedValue(
    replayFixtureCapabilities,
  );
  (listReplays as jest.Mock).mockResolvedValue([replayFixture()]);
  (replayAction as jest.Mock).mockResolvedValue(replayFixture("APPROVED"));
});
afterEach(() => jest.useRealTimers());
const mount = (readOnly = false, sessionId?: string) =>
  render(
    <ReplayPanel
      scope={sessionId ? { sessionId } : { runId: "run-one" }}
      readOnly={readOnly}
    />,
  );

test("exact approval is separate from running and publication, with remote blocked", async () => {
  mount();
  const button = await screen.findByRole("button", {
    name: /^Approve exact replay suite$/i,
  });
  expect(button).toBeDisabled();
  expect(screen.getByText("TestForge remote · blocked")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(button);
  await waitFor(() =>
    expect(replayAction).toHaveBeenCalledWith(
      "run-one",
      replayFixture(),
      "approve",
    ),
  );
  expect(replayAction).toHaveBeenCalledTimes(1);
});
test("approved suite runs once and cancellation is an explicit independent action", async () => {
  const row = replayFixture("APPROVED");
  (listReplays as jest.Mock).mockResolvedValue([row]);
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: /^Run approved replay$/i }),
  );
  await waitFor(() =>
    expect(replayAction).toHaveBeenCalledWith("run-one", row, "execute"),
  );
  expect(
    screen.queryByRole("button", { name: /^Submit replay report$/i }),
  ).not.toBeInTheDocument();
});
test("preview shows real coverage, exact comparisons, XML and manual Submit", async () => {
  const row = replayFixture("READY_FOR_SUBMISSION");
  (listReplays as jest.Mock).mockResolvedValue([row]);
  mount();
  expect(
    await screen.findByText(/1\/1 required cases completed/),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/fixture coverage, not application verification/),
  ).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: /^Submit replay report$/i }),
  );
  await waitFor(() =>
    expect(replayAction).toHaveBeenCalledWith("run-one", row, "submit"),
  );
  expect(
    screen.getByRole("button", { name: /^Download JUnit XML$/i }),
  ).toBeInTheDocument();
});
test("failure is retained as a report, not converted to coding success", async () => {
  (listReplays as jest.Mock).mockResolvedValue([
    replayFixture("SUBMITTED", "FAIL"),
  ]);
  mount();
  expect(await screen.findByText(/Archived replay report/)).toBeInTheDocument();
  expect(screen.getAllByText("FAIL")).toHaveLength(2);
  expect(
    screen.queryByRole("button", { name: /^Submit replay report$/i }),
  ).not.toBeInTheDocument();
});
test.each(["CANCEL_REQUESTED", "CANCELLED"] as const)(
  "%s never claims a verification verdict",
  async (state) => {
    (listReplays as jest.Mock).mockResolvedValue([replayFixture(state)]);
    mount();
    expect(await screen.findByText(state)).toBeInTheDocument();
    expect(screen.queryByText(/^PASS$/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Submit replay report$/i }),
    ).not.toBeInTheDocument();
    if (state === "CANCEL_REQUESTED")
      expect(
        screen.getByText(/Cancellation requested, not confirmed/),
      ).toBeInTheDocument();
  },
);
test("running cancellation records intent, never a substitute verdict or automatic retry", async () => {
  const row = replayFixture("RUNNING");
  (listReplays as jest.Mock).mockResolvedValue([row]);
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: /^Cancel replay$/i }),
  );
  await waitFor(() =>
    expect(replayAction).toHaveBeenCalledWith("run-one", row, "cancel"),
  );
  expect(replayAction).toHaveBeenCalledTimes(1);
});
test("native Harness view uses source session and has no mutation actions", async () => {
  (listReplays as jest.Mock).mockResolvedValue([
    replayFixture("READY_FOR_SUBMISSION"),
  ]);
  mount(true, "source-session");
  expect(
    await screen.findByText(/Prepared replay evidence preview/),
  ).toBeInTheDocument();
  expect(listReplays).toHaveBeenCalledWith({ sessionId: "source-session" });
  expect(
    screen.queryByRole("button", {
      name: /Submit|Approve|Run approved|Cancel replay|Create frozen/,
    }),
  ).not.toBeInTheDocument();
});
test("unknown profile, changed target, incomplete cases or invalid JUnit cannot display a PASS badge", async () => {
  const variants = Array.from({ length: 4 }, () =>
    replayFixture("READY_FOR_SUBMISSION"),
  );
  variants[0].plan.heal = true as unknown as false;
  variants[1].receipt!.target_instance_id = "other";
  variants[2].report!.completed_cases = 0;
  variants[3].receipt!.junit_xml = '<testsuite tests="0" />';
  variants.forEach((row, i) => {
    row.plan.plan_id = `invalid-${i}`;
  });
  (listReplays as jest.Mock).mockResolvedValue(variants);
  mount();
  expect(
    await screen.findAllByText(/Unsupported or incomplete replay evidence/),
  ).toHaveLength(4);
  expect(screen.queryByText(/^PASS$/)).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /^Submit replay report$/i }),
  ).not.toBeInTheDocument();
});
test("auto-login cannot approve or run", async () => {
  auth.autoLogin = true;
  mount();
  const button = await screen.findByRole("button", {
    name: /^Approve exact replay suite$/i,
  });
  expect(button).toBeDisabled();
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
});
test("XML/strings are escaped; unsupported evidence is text, not script", async () => {
  const row = replayFixture("READY_FOR_SUBMISSION");
  row.receipt!.junit_xml = "<script>window.hacked = true</script>";
  (listReplays as jest.Mock).mockResolvedValue([row]);
  const { container } = mount();
  expect(
    await screen.findByText(/Unsupported or incomplete/),
  ).toBeInTheDocument();
  expect(container.querySelector("script")).toBeNull();
});
test("author can add small required cases and save an immutable draft without execution", async () => {
  const contract = copyContract();
  contract.status = "APPROVED";
  const criterion = contract.document.nodes[0].acceptance_criteria[0];
  contract.document.nodes[0].acceptance_criteria = [
    { ...criterion, description: "First" },
    { ...criterion, description: "Second" },
  ];
  const row = replayFixture();
  (verificationCandidates as jest.Mock).mockResolvedValue({
    contracts: [contract],
    patches: [
      {
        source_task_id: "task-one",
        artifact_id: "artifact-one",
        task_name: "Candidate",
        files: ["h6b-fixture.json"],
      },
    ],
  });
  (createReplay as jest.Mock).mockResolvedValue(row);
  mount();
  const createButton = await screen.findByRole("button", {
    name: /^Create frozen replay suite$/i,
  });
  await waitFor(() => expect(createButton).not.toBeDisabled());
  fireEvent.click(createButton);
  fireEvent.click(
    await screen.findByRole("button", { name: /^Add required case$/i }),
  );
  fireEvent.change(screen.getAllByLabelText("Contract criterion")[1], {
    target: { value: `${contract.document.nodes[0].node_id}:1` },
  });
  fireEvent.click(screen.getByRole("button", { name: /^Save frozen suite$/i }));
  await waitFor(() => expect(createReplay).toHaveBeenCalledTimes(1));
  expect((createReplay as jest.Mock).mock.calls[0][1].cases).toHaveLength(2);
  expect((createReplay as jest.Mock).mock.calls[0][1].cases[1].method).toBe(
    "GET",
  );
  expect(replayAction).not.toHaveBeenCalled();
});
test("JUnit downloads use protected ADLC artifact archive, not a runner URL", async () => {
  const row = replayFixture("SUBMITTED");
  (listReplays as jest.Mock).mockResolvedValue([row]);
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: /^Download JUnit XML$/i }),
  );
  await waitFor(() =>
    expect(downloadReplay).toHaveBeenCalledWith("run-one", row, "junit"),
  );
});
