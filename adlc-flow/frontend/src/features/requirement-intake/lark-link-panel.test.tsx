import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { api } from "@/controllers/API/api";
import LarkLinkPanel from "./lark-link-panel";

jest.mock("@/controllers/API/api", () => ({
  api: { get: jest.fn(), post: jest.fn() },
}));
const client = jest.mocked(api);
beforeEach(() => {
  jest.clearAllMocks();
  client.get.mockResolvedValue({
    data: { enabled: true, username: "alice", linked: false },
  });
});

test("requires explicit password and displays a one-time linking command without assigning an owner", async () => {
  client.post.mockResolvedValue({
    data: {
      command: "/link one-time-code",
      expires_at: "2099-01-01T00:00:00Z",
    },
  });
  render(<LarkLinkPanel projects={[{ id: "project-1", name: "Payments" }]} />);
  fireEvent.click(await screen.findByRole("button", { name: "Liên kết Lark" }));
  fireEvent.change(screen.getByLabelText("Dự án cho yêu cầu từ Lark"), {
    target: { value: "project-1" },
  });
  fireEvent.change(screen.getByLabelText("Mật khẩu PokeDev"), {
    target: { value: "confirmed-password" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Tạo mã liên kết" }));
  expect(await screen.findByText("/link one-time-code")).toBeInTheDocument();
  expect(client.post).toHaveBeenCalledWith(
    expect.stringContaining("/lark/link"),
    { password: "confirmed-password", project_id: "project-1" },
  );
});

test("a rejected password does not link and the password field is cleared", async () => {
  client.post.mockRejectedValue({
    response: { data: { detail: { code: "LARK_REAUTH_REQUIRED" } } },
  });
  render(<LarkLinkPanel projects={[]} />);
  fireEvent.click(await screen.findByRole("button", { name: "Liên kết Lark" }));
  fireEvent.change(screen.getByLabelText("Mật khẩu PokeDev"), {
    target: { value: "wrong" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Tạo mã liên kết" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Mật khẩu PokeDev chưa đúng",
  );
  expect(screen.getByLabelText("Mật khẩu PokeDev")).toHaveValue("");
});

test("an existing link can only be removed after explicit password confirmation", async () => {
  client.get
    .mockResolvedValueOnce({
      data: { enabled: true, username: "alice", linked: true },
    })
    .mockResolvedValue({
      data: { enabled: true, username: "alice", linked: false },
    });
  client.post.mockResolvedValue({ data: { linked: false } });
  render(<LarkLinkPanel projects={[]} />);
  fireEvent.click(await screen.findByRole("button", { name: "Gỡ liên kết" }));
  expect(client.post).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("Mật khẩu PokeDev"), {
    target: { value: "confirmed-password" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Xác nhận gỡ liên kết" }));
  await waitFor(() =>
    expect(client.post).toHaveBeenCalledWith(
      expect.stringContaining("/lark/unlink"),
      { password: "confirmed-password" },
    ),
  );
  expect(
    await screen.findByRole("button", { name: "Liên kết Lark" }),
  ).toBeInTheDocument();
});
