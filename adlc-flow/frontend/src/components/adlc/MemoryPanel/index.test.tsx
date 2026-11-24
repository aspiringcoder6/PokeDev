import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  checkMemory,
  memoryView,
  queryMemory,
} from "@/controllers/API/project-memory";
import MemoryPanel from ".";
import { memoryFixture, memoryViewFixture } from "./test-fixtures";

jest.mock("@/controllers/API/project-memory", () => ({
  checkMemory: jest.fn(),
  memoryView: jest.fn(),
  queryMemory: jest.fn(),
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
beforeEach(() => {
  jest.clearAllMocks();
  auth = {
    isAuthenticated: true,
    autoLogin: false,
    userData: { id: "owner-one" },
  };
  (memoryView as jest.Mock).mockResolvedValue(memoryViewFixture());
  (queryMemory as jest.Mock).mockResolvedValue(memoryFixture());
  (checkMemory as jest.Mock).mockResolvedValue({ ready: true });
  if (!crypto.randomUUID)
    Object.defineProperty(crypto, "randomUUID", {
      configurable: true,
      value: () => "offline-query-key",
    });
});
const mount = (readOnly = false) =>
  render(<MemoryPanel scope={{ runId: "run-one" }} readOnly={readOnly} />);

test("provenance, advisory boundary and passive reads are visible", async () => {
  mount();
  expect(
    await screen.findByText("verification-design-notes · r2"),
  ).toBeInTheDocument();
  expect(screen.getByText("Context is not authority")).toBeInTheDocument();
  expect(screen.getByText(/Matches pinned commit/)).toBeInTheDocument();
  expect(
    screen.getByText(/Document digest \(not independently verified\)/),
  ).toBeInTheDocument();
  expect(queryMemory).not.toHaveBeenCalled();
  expect(checkMemory).not.toHaveBeenCalled();
});
test("explicit query sends no caller scope and retains raw text", async () => {
  mount();
  fireEvent.change(await screen.findByLabelText("Find raw source context"), {
    target: { value: " Earlier decision? " },
  });
  fireEvent.click(screen.getByRole("button", { name: /^Find context$/i }));
  await waitFor(() =>
    expect(queryMemory).toHaveBeenCalledWith(
      "run-one",
      expect.objectContaining({
        query: "Earlier decision?",
        top_k: 5,
        idempotency_key: expect.any(String),
      }),
    ),
  );
  expect(
    Object.keys((queryMemory as jest.Mock).mock.calls[0][1]).sort(),
  ).toEqual(["idempotency_key", "query", "top_k"]);
  expect(
    await screen.findByText(/Context retained in ADLC/),
  ).toBeInTheDocument();
});
test("no human mutation/query controls in Harness projection", async () => {
  render(<MemoryPanel scope={{ sessionId: "source-session" }} readOnly />);
  expect(
    await screen.findByText(/Harness projection · read-only/),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /^Find context$/i }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /^Check connection$/i }),
  ).not.toBeInTheDocument();
});
test("expired and different commit chunks are explicitly stale", async () => {
  const view = memoryViewFixture();
  view.records[0].record.chunks[0].source_commit = "f".repeat(40);
  (memoryView as jest.Mock).mockResolvedValue(view);
  mount();
  expect(
    await screen.findByText(/Different commit · stale/),
  ).toBeInTheDocument();
});
test("expired context is never shown as current or verified", async () => {
  const view = memoryViewFixture();
  view.records[0].record.chunks[0].recorded_at = "2020-01-01T00:00:00Z";
  view.records[0].record.chunks[0].expires_at = "2020-02-01T00:00:00Z";
  (memoryView as jest.Mock).mockResolvedValue(view);
  mount();
  expect(await screen.findByText("Expired context")).toBeInTheDocument();
});
test("memory outages keep retained context and never fabricate evidence", async () => {
  (queryMemory as jest.Mock).mockRejectedValue({
    response: {
      data: {
        detail: { code: "MEMORY_GATEWAY_UNAVAILABLE", message: "secret" },
      },
    },
  });
  mount();
  fireEvent.change(await screen.findByLabelText("Find raw source context"), {
    target: { value: "new" },
  });
  fireEvent.click(screen.getByRole("button", { name: /^Find context$/i }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    /Official contracts and verification results are unchanged/,
  );
  expect(
    screen.getByText("verification-design-notes · r2"),
  ).toBeInTheDocument();
  expect(screen.queryByText("secret")).not.toBeInTheDocument();
});
test("disabled module still renders retained context with no query", async () => {
  const view = memoryViewFixture();
  view.capabilities.enabled = false;
  (memoryView as jest.Mock).mockResolvedValue(view);
  mount();
  expect(
    await screen.findByText(/Live memory is not enabled or configured/),
  ).toBeInTheDocument();
  expect(
    screen.getByText("verification-design-notes · r2"),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /^Find context$/i }),
  ).not.toBeInTheDocument();
});
test("unknown profile and attempted authority escalation fail closed", async () => {
  const view = memoryViewFixture();
  view.capabilities.profile_ref = "future-profile";
  (
    view.records[0].record as unknown as { verification_evidence: boolean }
  ).verification_evidence = true;
  (memoryView as jest.Mock).mockResolvedValue(view);
  mount();
  expect(
    await screen.findByText(/Unsupported memory profile/),
  ).toBeInTheDocument();
  expect(screen.getByText(/Unsupported retained context/)).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /^Find context$/i }),
  ).not.toBeInTheDocument();
});
test("switching owner drops old context immediately and ignores a late response", async () => {
  let resolve: (value: ReturnType<typeof memoryViewFixture>) => void;
  (memoryView as jest.Mock).mockImplementationOnce(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  const page = mount();
  auth = { ...auth, userData: { id: "owner-two" } };
  const empty = memoryViewFixture();
  empty.records = [];
  (memoryView as jest.Mock).mockResolvedValue(empty);
  page.rerender(<MemoryPanel scope={{ runId: "run-one" }} />);
  await waitFor(() =>
    expect(screen.getByText(/No retained context reads/)).toBeInTheDocument(),
  );
  resolve!(memoryViewFixture());
  await waitFor(() =>
    expect(
      screen.queryByText("verification-design-notes · r2"),
    ).not.toBeInTheDocument(),
  );
});
test("text is escaped, auto-login cannot query, and no deletion tool exists", async () => {
  auth.autoLogin = true;
  const view = memoryViewFixture();
  view.records[0].record.chunks[0].text = '<img src="x" onerror="alert(1)">';
  (memoryView as jest.Mock).mockResolvedValue(view);
  mount();
  expect(
    await screen.findByText('<img src="x" onerror="alert(1)">'),
  ).toBeInTheDocument();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", {
      name: /find context|forget|remember|delete/i,
    }),
  ).not.toBeInTheDocument();
});
