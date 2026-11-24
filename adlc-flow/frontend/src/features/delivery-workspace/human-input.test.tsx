import { documentIntake } from "@/controllers/API/document-intake";
import { projectWorkloop } from "@/controllers/API/project-workloop";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AuthContext } from "@/contexts/authContext";
import {
  type HumanAttention,
  type HumanInput,
  liveWorkflows,
} from "@/controllers/API/live-workflows";
import HumanInputNotifications, {
  HumanInputCard,
  RunHumanInputs,
} from "./human-input";

const request: HumanInput = {
  request_id: "question-a",
  run_id: "run-a",
  project_id: "project-a",
  run_title: "Add search",
  node_id: "T01",
  node_title: "Build search",
  kind: "question",
  title: "Agent cần câu trả lời",
  status: "PENDING",
  can_respond: true,
  created_at: "2026-10-26T01:00:00Z",
  questions: [
    {
      id: "color",
      question: "Which label?",
      header: "Label",
      multi_select: false,
      options: [
        { label: "Blue", description: "The blue label" },
        { label: "Green", description: "The green label" },
      ],
    },
    {
      id: "features",
      question: "Which features?",
      header: "Features",
      multi_select: true,
      options: [
        { label: "Search", description: "Find items" },
        { label: "Export", description: "Save items" },
      ],
    },
    {
      id: "note",
      question: "Any other details?",
      header: "Details",
      multi_select: false,
      options: [],
    },
  ],
};
const permission: HumanInput = {
  ...request,
  request_id: "permission-a",
  kind: "permission",
  title: "Agent cần bạn cho phép",
  tool_name: "shell",
  prompt: "Run the project tests?",
  questions: undefined,
};

beforeEach(() => {
  jest.spyOn(documentIntake, "list").mockResolvedValue({
    items: [],
    rules: [],
    can_manage: true,
    stale: false,
  });
  jest
    .spyOn(projectWorkloop, "attention")
    .mockResolvedValue({ items: [], partial: false });
  jest.spyOn(projectWorkloop, "jobs").mockResolvedValue({ items: [] });
  jest
    .spyOn(crypto, "randomUUID")
    .mockReturnValue("11111111-1111-4111-8111-111111111111");
});
afterEach(() => jest.restoreAllMocks());

test("questions support choices, multiple selections and written replies in one native batch", async () => {
  const answer = jest.fn().mockResolvedValue({});
  render(<HumanInputCard request={request} onAnswer={answer} />);
  const submit = screen.getByRole("button", { name: "Gửi câu trả lời" });
  expect(submit).toBeDisabled();
  fireEvent.click(screen.getByRole("radio", { name: /Blue/ }));
  fireEvent.click(screen.getByRole("checkbox", { name: /Search/ }));
  fireEvent.click(screen.getByRole("checkbox", { name: /Export/ }));
  fireEvent.change(
    within(screen.getByRole("group", { name: "Any other details?" })).getByRole(
      "textbox",
    ),
    { target: { value: "Keep it offline" } },
  );
  fireEvent.click(submit);
  await waitFor(() =>
    expect(answer).toHaveBeenCalledWith(
      {
        answers: [
          { id: "color", selected: ["Blue"] },
          { id: "features", selected: ["Search", "Export"] },
          { id: "note", selected: [], custom: "Keep it offline" },
        ],
      },
      "11111111-1111-4111-8111-111111111111",
    ),
  );
});

test("permission has explicit once or reject actions and never approves on render", async () => {
  const answer = jest.fn().mockResolvedValue({});
  render(<HumanInputCard request={permission} onAnswer={answer} />);
  expect(answer).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Từ chối" }));
  await waitFor(() =>
    expect(answer).toHaveBeenCalledWith(
      { decision: "rejected" },
      expect.any(String),
    ),
  );
});

test("double clicks cannot send twice and a disconnected request cannot be approved", async () => {
  let finish!: () => void;
  const answer = jest.fn().mockImplementation(
    () =>
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
  );
  const view = render(
    <HumanInputCard request={permission} onAnswer={answer} />,
  );
  const button = screen.getByRole("button", { name: "Cho phép lần này" });
  fireEvent.click(button);
  fireEvent.click(button);
  expect(answer).toHaveBeenCalledTimes(1);
  expect(button).toBeDisabled();
  await act(async () => finish());
  view.rerender(
    <HumanInputCard
      request={{ ...permission, can_respond: false }}
      onAnswer={answer}
    />,
  );
  expect(button).toBeDisabled();
  fireEvent.click(button);
  expect(answer).toHaveBeenCalledTimes(1);
});

test("a failed send retains a written reply and displays a useful error", async () => {
  const answer = jest.fn().mockRejectedValue({
    response: {
      data: { detail: { code: "LIVE_HUMAN_RESPONSE_UNCONFIRMED" } },
    },
  });
  render(
    <HumanInputCard
      request={{ ...request, questions: [request.questions![2]] }}
      onAnswer={answer}
    />,
  );
  const input = screen.getByRole("textbox");
  fireEvent.change(input, { target: { value: "Do not lose this answer" } });
  fireEvent.click(screen.getByRole("button", { name: "Gửi câu trả lời" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Chưa xác nhận được",
  );
  expect(input).toHaveValue("Do not lose this answer");
});

function mount(element: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const view = render(
    <QueryClientProvider client={client}>
      <AuthContext.Provider
        value={
          { userData: { id: "owner" } } as React.ContextType<typeof AuthContext>
        }
      >
        <MemoryRouter>{element}</MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
  return {
    client,
    stop: () => {
      view.unmount();
      client.clear();
    },
  };
}

test("notifications remain visible outside the run and lead to the correct question or plan", async () => {
  const attention: HumanAttention = {
    connected: true,
    active_runs: 1,
    requests: [request],
    reviews: [
      {
        request_id: "plan:b",
        run_id: "run-b",
        project_id: "project-b",
        run_title: "Another project",
        kind: "plan",
        title: "Kế hoạch đang chờ bạn duyệt",
      },
    ],
  };
  jest.spyOn(liveWorkflows, "attention").mockResolvedValue(attention);
  const view = mount(<HumanInputNotifications />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Cần bạn phản hồi: 2" }),
  );
  expect(
    screen.getByRole("link", { name: /Add search.*Trả lời/ }),
  ).toHaveAttribute("href", "/work?project=project-a&run=run-a");
  expect(
    screen.getByRole("link", { name: /Another project.*Xem kế hoạch/ }),
  ).toHaveAttribute("href", "/work?project=project-b&run=run-b");
  view.stop();
});

test("run details show only that run's questions and send through the authenticated API", async () => {
  jest.spyOn(liveWorkflows, "attention").mockResolvedValue({
    connected: true,
    active_runs: 1,
    requests: [
      permission,
      {
        ...permission,
        request_id: "other",
        run_id: "run-b",
        prompt: "Another run's private question",
      },
    ],
    reviews: [],
  });
  const answer = jest
    .spyOn(liveWorkflows, "answer")
    .mockResolvedValue({ ...permission, status: "ANSWERED" });
  const view = mount(<RunHumanInputs runId="run-a" />);
  await screen.findByText("Run the project tests?");
  expect(
    screen.queryByText("Another run's private question"),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Cho phép lần này" }));
  await waitFor(() =>
    expect(answer).toHaveBeenCalledWith(permission, expect.any(String), {
      decision: "allowed-once",
    }),
  );
  view.stop();
});

test("new Slack documents appear in the shared notification inbox with a direct review link", async () => {
  jest
    .spyOn(liveWorkflows, "attention")
    .mockResolvedValue({
      connected: true,
      active_runs: 0,
      requests: [],
      reviews: [],
    });
  jest
    .spyOn(documentIntake, "list")
    .mockResolvedValue({
      items: [
        {
          document_id: "3",
          title: "A document from Slack",
          doc_type: "ptyc",
          lifecycle_id: "lc-a",
          page_id: "123",
          slack_channel: "C01234567",
          slack_thread: "123.456",
          source_status: "pending",
          state: "NEEDS_PROJECT",
          created_at: "2026-10-28T00:00:00Z",
        },
      ],
      rules: [],
      can_manage: true,
      stale: false,
    });
  const view = mount(<HumanInputNotifications />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Cần bạn phản hồi: 1" }),
  );
  expect(
    screen.getByRole("link", { name: /A document from Slack.*Xem tài liệu/ }),
  ).toHaveAttribute("href", "/work?view=requests&document=3");
  view.stop();
});

test("a reconnect replay does not erase an unsent answer", async () => {
  const question = { ...request, questions: [request.questions![2]] };
  const attention: HumanAttention = {
    connected: true,
    active_runs: 1,
    requests: [question],
    reviews: [],
  };
  jest.spyOn(liveWorkflows, "attention").mockResolvedValue(attention);
  const view = mount(<RunHumanInputs runId="run-a" />);
  const input = await screen.findByRole("textbox");
  fireEvent.change(input, {
    target: { value: "Keep this answer through reconnect" },
  });
  act(() =>
    view.client.setQueryData(["human-attention", "owner"], {
      ...attention,
      requests: [],
    }),
  );
  await waitFor(() =>
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument(),
  );
  act(() => view.client.setQueryData(["human-attention", "owner"], attention));
  expect(await screen.findByRole("textbox")).toHaveValue(
    "Keep this answer through reconnect",
  );
  view.stop();
});

test("desktop notifications do not repeat when the same request is refreshed", async () => {
  const original = globalThis.Notification;
  const notice = Object.assign(
    jest.fn().mockImplementation(() => ({ close: jest.fn() })),
    { permission: "granted" },
  );
  Object.defineProperty(globalThis, "Notification", {
    configurable: true,
    writable: true,
    value: notice,
  });
  const attention: HumanAttention = {
    connected: true,
    active_runs: 1,
    requests: [request],
    reviews: [],
  };
  jest.spyOn(liveWorkflows, "attention").mockResolvedValue(attention);
  const view = mount(<HumanInputNotifications />);
  try {
    await screen.findByRole("button", { name: "Cần bạn phản hồi: 1" });
    await waitFor(() => expect(notice).toHaveBeenCalledTimes(1));
    fireEvent.click(
      screen.getByRole("button", { name: "Cần bạn phản hồi: 1" }),
    );
    act(() =>
      view.client.setQueryData(["human-attention", "owner"], {
        ...attention,
        requests: [{ ...request, run_title: "Updated progress" }],
      }),
    );
    await screen.findByText("Updated progress");
    expect(notice).toHaveBeenCalledTimes(1);
  } finally {
    view.stop();
    Object.defineProperty(globalThis, "Notification", {
      configurable: true,
      writable: true,
      value: original,
    });
  }
});

test("the notification channel loss is visible during execution", async () => {
  jest.spyOn(liveWorkflows, "attention").mockResolvedValue({
    connected: false,
    active_runs: 1,
    requests: [],
    reviews: [],
  });
  const view = mount(<HumanInputNotifications />);
  await screen.findByText("Đang kết nối kênh phản hồi");
  fireEvent.click(screen.getByRole("button", { name: "Thông báo công việc" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Kiểm tra VPN");
  view.stop();
});
