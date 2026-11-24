import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import {
  approveContract,
  forkContract,
  getContractViewerCapabilities,
  listContracts,
  readContract,
} from "@/controllers/API/contracts";
import { copyContract } from "../ContractViewer/test-fixtures";
import ContractPanel from ".";

jest.mock("@/controllers/API/contracts", () => ({
  approveContract: jest.fn(),
  downloadContract: jest.fn(),
  forkContract: jest.fn(),
  getContractViewerCapabilities: jest.fn(),
  listContracts: jest.fn(),
  readContract: jest.fn(),
}));
let auth = { isAuthenticated: true, autoLogin: false };
jest.mock("@/stores/authStore", () => ({
  __esModule: true,
  default: (selector) => selector(auth),
}));

const capabilities = {
  enabled: true,
  human_actions_configured: true,
  renderer_refs: ["adlc-renderer:skilltree/0.1"],
  execution_policy_enforced: false,
};
const mount = (readOnly = false, sessionId?: string) =>
  render(
    <MemoryRouter>
      <ContractPanel
        scope={sessionId ? { sessionId } : { runId: "run-one" }}
        readOnly={readOnly}
      />
    </MemoryRouter>,
  );
beforeEach(() => {
  jest.useFakeTimers();
  jest.clearAllMocks();
  auth = { isAuthenticated: true, autoLogin: false };
  (getContractViewerCapabilities as jest.Mock).mockResolvedValue(capabilities);
  (listContracts as jest.Mock).mockResolvedValue([copyContract()]);
});
afterEach(() => {
  jest.useRealTimers();
});

test("approval requires explicit confirmation and sends exactly the displayed reference", async () => {
  const approved = copyContract();
  approved.status = "APPROVED";
  approved.approval = {
    approval_id: "receipt",
    reference: approved.reference,
    approved_by: "owner",
    approved_at: "2026-10-07T11:00:00Z",
    comment: null,
  };
  (approveContract as jest.Mock).mockImplementation(async () => {
    (listContracts as jest.Mock).mockResolvedValue([approved]);
    return { contract: approved };
  });
  mount();
  const button = await screen.findByRole("button", {
    name: "Approve exact contract",
  });
  expect(button).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  expect(button).not.toBeDisabled();
  fireEvent.click(button);
  await waitFor(() =>
    expect(approveContract).toHaveBeenCalledWith(
      "run-one",
      copyContract().reference,
      expect.any(String),
    ),
  );
  expect(
    await screen.findByText(/The run was not submitted or resumed/),
  ).toBeInTheDocument();
  expect(
    await screen.findByRole("button", { name: "Fork new draft" }),
  ).not.toBeDisabled();
});
test("new head invalidates review confirmation; stale responses cannot approve", async () => {
  mount();
  await screen.findByRole("button", { name: "Approve exact contract" });
  fireEvent.click(screen.getByRole("checkbox"));
  const changed = copyContract();
  changed.document.revision = changed.reference.revision = 4;
  changed.reference.content_digest = `sha256:${"b".repeat(64)}`;
  changed.validation!.content_digest = changed.reference.content_digest;
  (listContracts as jest.Mock).mockResolvedValue([changed]);
  await act(async () => {
    jest.advanceTimersByTime(4000);
  });
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  expect(
    screen.getByRole("button", { name: "Approve exact contract" }),
  ).toBeDisabled();
});
test("refresh failures disable actions even while the last document remains visible", async () => {
  mount();
  await screen.findByRole("checkbox");
  fireEvent.click(screen.getByRole("checkbox"));
  (listContracts as jest.Mock).mockRejectedValue(
    new Error("transport unavailable"),
  );
  await act(async () => {
    jest.advanceTimersByTime(4000);
  });
  expect(
    screen.getByRole("button", { name: "Approve exact contract" }),
  ).toBeDisabled();
  expect(screen.getByRole("alert")).toBeInTheDocument();
  expect(screen.getByText("ADLC plugin roadmap")).toBeInTheDocument();
});
test("auto-login can read but cannot approve or fork", async () => {
  auth.autoLogin = true;
  mount();
  expect(
    await screen.findByRole("button", { name: "Approve exact contract" }),
  ).toBeDisabled();
  expect(screen.getByRole("checkbox")).toBeDisabled();
});
test("Harness uses the same renderer but exposes no approval controls or service secrets", async () => {
  mount(true, "session-one");
  expect(
    await screen.findByLabelText("Skilltree contract"),
  ).toBeInTheDocument();
  expect(listContracts).toHaveBeenCalledWith({ sessionId: "session-one" });
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Approve exact contract" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Review and approve in ADLC" }),
  ).toHaveAttribute("href", "/runs/run-one/");
});
test("historical revisions are review-only", async () => {
  const checked = copyContract(),
    historical = copyContract();
  historical.document.revision = historical.reference.revision = 2;
  historical.status = "DRAFT";
  historical.validation = null;
  (readContract as jest.Mock).mockResolvedValue(historical);
  mount();
  await screen.findByRole("checkbox");
  fireEvent.change(screen.getByLabelText("Contract revision"), {
    target: { value: "2" },
  });
  expect(await screen.findByText(/Historical revision/)).toBeInTheDocument();
  expect(approveContract).not.toHaveBeenCalled();
  expect(forkContract).not.toHaveBeenCalled();
  expect(checked.status).toBe("VALIDATED");
});
test("fork sends the approved exact reference and preserves the original receipt", async () => {
  const original = copyContract();
  original.status = "APPROVED";
  original.approval = {
    approval_id: "receipt",
    reference: original.reference,
    approved_by: "owner",
    approved_at: "2026-10-07T11:00:00Z",
    comment: null,
  };
  (listContracts as jest.Mock).mockResolvedValue([original]);
  const draft = copyContract();
  draft.status = "DRAFT";
  draft.validation = null;
  draft.document.contract_id = draft.reference.contract_id =
    "10000000-0000-4000-8000-000000000010";
  draft.document.revision = draft.reference.revision = 1;
  draft.document.supersedes = original.reference;
  (forkContract as jest.Mock).mockImplementation(async () => {
    (listContracts as jest.Mock).mockResolvedValue([original, draft]);
    return { contract: draft };
  });
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Fork new draft" }),
  );
  await waitFor(() =>
    expect(forkContract).toHaveBeenCalledWith(
      "run-one",
      original.reference,
      expect.any(String),
    ),
  );
  expect(
    await screen.findByText(/The original approved contract is unchanged/),
  ).toBeInTheDocument();
  expect(original.approval.approval_id).toBe("receipt");
  expect(original.status).toBe("APPROVED");
  expect(approveContract).not.toHaveBeenCalled();
});
test("a default-off host quietly hides the panel", async () => {
  (getContractViewerCapabilities as jest.Mock).mockRejectedValue({
    isAxiosError: true,
    response: { status: 404 },
  });
  mount();
  await act(async () => {});
  expect(screen.queryByLabelText("Contract documents")).not.toBeInTheDocument();
  expect(listContracts).not.toHaveBeenCalled();
});
