import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import CreateGithubWorkflow from "./create-github-workflow";

const mockCreate = jest.fn(),
  mockNavigate = jest.fn(),
  mockGet = jest.fn();
jest.mock("@/controllers/API/api", () => ({
  api: { get: (...args: unknown[]) => mockGet(...args) },
}));
jest.mock("@/controllers/API/queries/flows/use-post-add-flow", () => ({
  usePostAddFlow: () => ({ mutateAsync: mockCreate }),
}));
jest.mock("@/customization/hooks/use-custom-navigate", () => ({
  useCustomNavigate: () => mockNavigate,
}));
jest.mock("react-router-dom", () => ({
  useParams: () => ({ folderId: "project-a" }),
}));
jest.mock("@/stores/flowsManagerStore", () => ({
  __esModule: true,
  default: {
    getState: () => ({
      flows: [],
      setFlows: jest.fn(),
      setCurrentFlow: jest.fn(),
    }),
  },
}));
jest.mock("@/components/ui/button", () => ({
  Button: ({
    children,
    ...p
  }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button {...p}>{children}</button>
  ),
}));
test("starter creates only a saved workflow in the selected project; it never starts a run", async () => {
  mockGet.mockResolvedValue({
    data: {
      name: "Triển khai thay đổi lên GitHub",
      data: { nodes: [], edges: [] },
    },
  });
  mockCreate.mockResolvedValue({ id: "new-flow" });
  render(<CreateGithubWorkflow />);
  fireEvent.click(screen.getByRole("button", { name: "Tạo workflow GitHub" }));
  await waitFor(() =>
    expect(mockNavigate).toHaveBeenCalledWith("/flow/new-flow"),
  );
  expect(mockGet).toHaveBeenCalledTimes(1);
  expect(mockCreate).toHaveBeenCalledWith(
    expect.objectContaining({ folder_id: "project-a", mcp_enabled: false }),
  );
});
