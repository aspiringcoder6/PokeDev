import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  createVerification,
  downloadVerification,
  listVerifications,
  verificationAction,
  verificationCandidates,
  verificationCapabilities,
} from "@/controllers/API/verification";
import { copyContract } from "../ContractViewer/test-fixtures";
import VerificationPanel from ".";
import { fixtureCapabilities, verificationFixture } from "./test-fixtures";

jest.mock("@/controllers/API/verification", () => ({
  createVerification: jest.fn(),
  downloadVerification: jest.fn(),
  listVerifications: jest.fn(),
  verificationAction: jest.fn(),
  verificationCandidates: jest.fn(),
  verificationCapabilities: jest.fn(),
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
  (verificationCapabilities as jest.Mock).mockResolvedValue(
    fixtureCapabilities,
  );
  (listVerifications as jest.Mock).mockResolvedValue([verificationFixture()]);
  (verificationAction as jest.Mock).mockResolvedValue(
    verificationFixture("APPROVED"),
  );
});
afterEach(() => jest.useRealTimers());
const mount = (readOnly = false, sessionId?: string) =>
  render(
    <VerificationPanel
      scope={sessionId ? { sessionId } : { runId: "run-one" }}
      readOnly={readOnly}
    />,
  );

test("exact approval requires review and never executes or submits implicitly", async () => {
  mount();
  const button = await screen.findByRole("button", {
    name: /^Approve exact verification plan$/i,
  });
  expect(button).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  expect(button).not.toBeDisabled();
  fireEvent.click(button);
  await waitFor(() =>
    expect(verificationAction).toHaveBeenCalledWith(
      "run-one",
      verificationFixture(),
      "approve",
    ),
  );
  expect(verificationAction).toHaveBeenCalledTimes(1);
  expect(
    await screen.findByText(/Exact verification plan approved/),
  ).toBeInTheDocument();
});

test("running an approved plan is separate from manual result submit", async () => {
  const row = verificationFixture("APPROVED");
  (listVerifications as jest.Mock).mockResolvedValue([row]);
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: /^Run approved verification$/i }),
  );
  await waitFor(() =>
    expect(verificationAction).toHaveBeenCalledWith("run-one", row, "execute"),
  );
  expect(verificationAction).toHaveBeenCalledTimes(1);
  expect(
    screen.queryByRole("button", { name: /^Submit verification report$/i }),
  ).not.toBeInTheDocument();
});

test("PASS preview shows fixed expected/observed evidence and an explicit Submit", async () => {
  const row = verificationFixture("READY_FOR_SUBMISSION");
  (listVerifications as jest.Mock).mockResolvedValue([row]);
  mount();
  expect(
    await screen.findByText(/Prepared evidence preview/),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/Reproduced 1\/1 required cases/),
  ).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: /^Submit verification report$/i }),
  );
  await waitFor(() =>
    expect(verificationAction).toHaveBeenCalledWith("run-one", row, "submit"),
  );
});

test("a genuine FAIL is not rendered as NOT VERIFIED or a passing run", async () => {
  (listVerifications as jest.Mock).mockResolvedValue([
    verificationFixture("SUBMITTED", "FAIL"),
  ]);
  mount();
  await screen.findByText("h6a-fixture.json");
  expect(screen.getAllByText("FAIL")).toHaveLength(2);
  expect(screen.queryByText("PASS")).not.toBeInTheDocument();
});

test("missing evidence and uncertain dispatch show no success claim", async () => {
  const row = verificationFixture("DISPATCH_UNCERTAIN");
  row.error_code = "VERIFICATION_EXECUTION_UNCONFIRMED";
  (listVerifications as jest.Mock).mockResolvedValue([row]);
  mount();
  await screen.findByText(/no passing verdict was accepted/);
  expect(screen.queryByText("PASS")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Reconcile evidence/i }));
  await waitFor(() =>
    expect(verificationAction).toHaveBeenCalledWith(
      "run-one",
      row,
      "reconcile",
    ),
  );
});

test("empty or inconsistent receipt cannot receive a PASS badge", async () => {
  const row = verificationFixture("READY_FOR_SUBMISSION");
  row.receipt!.tests_run = 0;
  (listVerifications as jest.Mock).mockResolvedValue([row]);
  mount();
  expect(
    await screen.findByText(/Unsupported or inconsistent evidence/),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /^Submit verification report$/i }),
  ).not.toBeInTheDocument();
});

test("read-only Harness session view has no approval, execution or submit actions", async () => {
  (listVerifications as jest.Mock).mockResolvedValue([
    verificationFixture("READY_FOR_SUBMISSION"),
  ]);
  mount(true, "source-session");
  await screen.findByText("h6a-fixture.json");
  expect(listVerifications).toHaveBeenCalledWith({
    sessionId: "source-session",
  });
  expect(
    screen.queryByRole("button", { name: /^Submit verification report$/i }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /^Create verification plan$/i }),
  ).not.toBeInTheDocument();
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
});

test("another session scope is rejected without a completion badge", async () => {
  mount(true, "different-session");
  expect(
    await screen.findByText(/Unsupported or inconsistent evidence/),
  ).toBeInTheDocument();
  expect(screen.queryByText("PASS")).not.toBeInTheDocument();
});

test("auto-login cannot approve even when data is readable", async () => {
  auth.autoLogin = true;
  mount();
  expect(
    await screen.findByText(/Explicit ADLC owner login/),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: /^Approve exact verification plan$/i }),
  ).toBeDisabled();
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
});

test("worker unavailability blocks Run while plan approval remains separate", async () => {
  (verificationCapabilities as jest.Mock).mockResolvedValue({
    ...fixtureCapabilities,
    worker_ready: false,
  });
  (listVerifications as jest.Mock).mockResolvedValue([
    verificationFixture("APPROVED"),
  ]);
  mount();
  expect(
    await screen.findByRole("button", { name: /^Run approved verification$/i }),
  ).toBeDisabled();
  expect(screen.getByText(/reproducer is not ready/)).toBeInTheDocument();
});

test("draft uses a captured candidate, exact approved contract and typed scalar, not commands", async () => {
  const contract = copyContract();
  contract.status = "APPROVED";
  (verificationCandidates as jest.Mock).mockResolvedValue({
    contracts: [contract],
    patches: [
      {
        source_task_id: "task-one",
        artifact_id: "artifact-one",
        task_name: "Coding",
        files: ["h6a-fixture.json"],
      },
    ],
  });
  (createVerification as jest.Mock).mockResolvedValue(verificationFixture());
  mount();
  const createButton = await screen.findByRole("button", {
    name: /^Create verification plan$/i,
  });
  await waitFor(() => expect(createButton).not.toBeDisabled());
  fireEvent.click(createButton);
  fireEvent.click(
    await screen.findByRole("button", {
      name: /^Save draft · do not execute$/i,
    }),
  );
  await waitFor(() =>
    expect(createVerification).toHaveBeenCalledWith(
      "run-one",
      expect.objectContaining({
        file: "h6a-fixture.json",
        contract_reference: contract.reference,
        cases: [
          {
            case_id: "case-1",
            pointer: "/answer",
            expected: 42,
            criterion_node_id: contract.document.nodes.find(
              (node) => node.acceptance_criteria.length,
            )!.node_id,
            criterion_index: 0,
          },
        ],
      }),
    ),
  );
  expect(verificationAction).not.toHaveBeenCalled();
});

test("checkpoint recovery explains that the original process exit was not observed", async () => {
  const row = verificationFixture("READY_FOR_SUBMISSION");
  row.receipt!.completion_mode = "durable-checkpoint";
  row.receipt!.exit_code = null;
  (listVerifications as jest.Mock).mockResolvedValue([row]);
  mount();
  expect(
    await screen.findByText(/original process exit was not observed/),
  ).toBeInTheDocument();
});

test.each(["1e999", "9007199254740992", "[]"])(
  "invalid expected %s is rejected instead of coercing to null",
  async (expected) => {
    const contract = copyContract();
    contract.status = "APPROVED";
    (verificationCandidates as jest.Mock).mockResolvedValue({
      contracts: [contract],
      patches: [
        {
          source_task_id: "task-one",
          artifact_id: "artifact-one",
          task_name: "Coding",
          files: ["h6a-fixture.json"],
        },
      ],
    });
    mount();
    const button = await screen.findByRole("button", {
      name: /^Create verification plan$/i,
    });
    await waitFor(() => expect(button).not.toBeDisabled());
    fireEvent.click(button);
    fireEvent.change(await screen.findByLabelText("Expected JSON value"), {
      target: { value: expected },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /^Save draft · do not execute$/i }),
    );
    expect(
      await screen.findByText(/Expected value must be a bounded JSON scalar/),
    ).toBeInTheDocument();
    expect(createVerification).not.toHaveBeenCalled();
  },
);

test("untrusted expected text is escaped and download is an independent read", async () => {
  const row = verificationFixture("SUBMITTED");
  const text = '<img src="x" onerror="alert(1)">';
  row.plan.cases[0].expected = text;
  row.report!.checks[0].expected = text;
  row.report!.checks[0].observed = text;
  row.receipt!.observations[0].observed = text;
  (listVerifications as jest.Mock).mockResolvedValue([row]);
  mount();
  await screen.findByText("h6a-fixture.json");
  expect(document.querySelector("img")).toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: /^Download checksummed evidence$/i }),
  );
  await waitFor(() =>
    expect(downloadVerification).toHaveBeenCalledWith("run-one", row),
  );
});
