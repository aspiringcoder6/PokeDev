import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { api } from "@/controllers/API/api";
import LarkConversationPanel, {
  type ConversationPage,
} from "./lark-conversation-panel";

jest.mock("@/controllers/API/api", () => ({ api: { get: jest.fn() } }));
const client = jest.mocked(api);
const first = "00000000-0000-4000-8000-000000000001";
const second = "00000000-0000-4000-8000-000000000002";
const page = (text = "Supplement Alpha"): ConversationPage => ({
  enabled: true,
  total: 1,
  items: [
    {
      id: "entry-1",
      received_at: "2026-11-26T01:22:11+00:00",
      chat_type: "group",
      message_id: "om_alpha",
      parent_id: "om_root",
      root_id: "om_root",
      thread_id: "omt_alpha",
      text,
      action: "APPENDED",
    },
  ],
});
beforeEach(() => {
  jest.clearAllMocks();
});

test("renders supplementary evidence as plain text with explicit target guidance", async () => {
  client.get.mockResolvedValue({ data: page("<script>private text</script>") });
  const { container } = render(
    <LarkConversationPanel requestId={first} closed={false} />,
  );
  expect(
    await screen.findByText("<script>private text</script>"),
  ).toBeInTheDocument();
  expect(container.querySelector("script")).toBeNull();
  expect(screen.getByText(/Brief chỉ đổi/)).toBeInTheDocument();
  expect(
    screen.getByText(`/intake ${first} nội dung bổ sung`),
  ).toBeInTheDocument();
  expect(screen.getByText("omt_alpha")).toBeInTheDocument();
});

test("late responses from another request cannot appear under the new request", async () => {
  let resolveFirst!: (value: any) => void;
  client.get.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        resolveFirst = resolve;
      }),
  );
  client.get.mockResolvedValue({ data: page("Supplement Beta") });
  const view = render(
    <LarkConversationPanel requestId={first} closed={false} />,
  );
  view.rerender(<LarkConversationPanel requestId={second} closed={false} />);
  expect(await screen.findByText("Supplement Beta")).toBeInTheDocument();
  resolveFirst({ data: page("PRIVATE_ALPHA") });
  await waitFor(() =>
    expect(screen.queryByText("PRIVATE_ALPHA")).not.toBeInTheDocument(),
  );
  expect(
    screen.queryByText(`/intake ${first} nội dung bổ sung`),
  ).not.toBeInTheDocument();
});

test("revoked access clears old evidence and exposes a recoverable read error", async () => {
  client.get
    .mockResolvedValueOnce({ data: page("PRIVATE_ALPHA") })
    .mockRejectedValue({ response: { status: 404 } });
  render(<LarkConversationPanel requestId={first} closed={false} />);
  expect(await screen.findByText("PRIVATE_ALPHA")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Cập nhật tin" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "kiểm tra quyền truy cập",
  );
  expect(screen.queryByText("PRIVATE_ALPHA")).not.toBeInTheDocument();
});

test("pagination uses the selected request and closed records show no target command", async () => {
  client.get.mockResolvedValue({ data: { ...page(), total: 51 } });
  render(<LarkConversationPanel requestId={first} closed />);
  fireEvent.click(await screen.findByRole("button", { name: "Tin trước" }));
  await waitFor(() =>
    expect(client.get).toHaveBeenLastCalledWith(
      expect.stringContaining(first),
      expect.objectContaining({ params: { limit: 50, offset: 50 } }),
    ),
  );
  expect(screen.queryByText(/Chọn đúng hồ sơ/)).not.toBeInTheDocument();
});

test("disabled empty history hides the conversation panel", async () => {
  client.get.mockResolvedValue({
    data: { enabled: false, items: [], total: 0 },
  });
  render(<LarkConversationPanel requestId={first} closed={false} />);
  await waitFor(() => expect(client.get).toHaveBeenCalled());
  expect(
    screen.queryByRole("region", { name: "Nguồn hội thoại Lark" }),
  ).not.toBeInTheDocument();
});
