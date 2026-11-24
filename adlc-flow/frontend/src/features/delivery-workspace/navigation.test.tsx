import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import WorkspaceNavigation from "../adlc-workspace/workspace-navigation";

jest.mock("@/i18n/ui", () => ({
  translateUi: (value: string) => value,
  useUiLocale: () => {},
}));
jest.mock("@/customization/hooks/use-custom-navigate", () => ({
  useCustomNavigate: () => jest.fn(),
}));
test("primary navigation opens workspace overview and hides project-only shortcuts without a project", () => {
  render(
    <MemoryRouter initialEntries={["/work"]}>
      <WorkspaceNavigation />
    </MemoryRouter>,
  );
  expect(
    screen.getByRole("button", { name: "Tổng quan workspace" }),
  ).toHaveAttribute("aria-current", "page");
  expect(
    screen.queryByRole("button", { name: "Studio" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Agent Harness" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Công cụ workflow" }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Workflow của project" }),
  ).not.toBeInTheDocument();
});
test("results is a filtered view of the same workspace", () => {
  render(
    <MemoryRouter initialEntries={["/work?view=results"]}>
      <WorkspaceNavigation />
    </MemoryRouter>,
  );
  expect(
    screen.getByRole("button", { name: "Kiểm thử & kết quả" }),
  ).toHaveAttribute("aria-current", "page");
  expect(
    screen.getByRole("button", { name: "Lịch sử công việc" }),
  ).not.toHaveAttribute("aria-current");
});

test.each([
  "/work?view=requests",
  "/work?project=project-a&view=requests&document=1",
])("document inbox navigation is active at %s", (path) => {
  render(
    <MemoryRouter initialEntries={[path]}>
      <WorkspaceNavigation />
    </MemoryRouter>,
  );
  expect(
    screen.getByRole("button", { name: "Yêu cầu & tài liệu" }),
  ).toHaveAttribute("aria-current", "page");
  expect(
    screen.getByRole("button", { name: "Tổng quan workspace" }),
  ).not.toHaveAttribute("aria-current");
});

test("project navigation keeps its workflow shortcut in the additional menu", async () => {
  render(
    <MemoryRouter initialEntries={["/work?project=project-a"]}>
      <WorkspaceNavigation />
    </MemoryRouter>,
  );
  expect(screen.getByRole("button", { name: "Công việc" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  expect(
    screen.queryByRole("button", { name: "Workflow của project" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Tổng quan workspace" }),
  ).not.toHaveAttribute("aria-current");
  fireEvent.keyDown(
    screen.getByRole("button", { name: "Thêm mục điều hướng" }),
    { key: "Enter", code: "Enter" },
  );
  expect(
    await screen.findByRole("menuitem", { name: "Workflow của project" }),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Công cụ workflow" }),
  ).not.toBeInTheDocument();
});
