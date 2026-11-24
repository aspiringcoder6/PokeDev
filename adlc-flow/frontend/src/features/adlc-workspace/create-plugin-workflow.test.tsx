import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import CreatePluginWorkflow from "./create-plugin-workflow";

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
  Button: ({ children, variant, ...props }: any) => (
    <button {...props}>{children}</button>
  ),
}));

test("creating a plugin workflow saves its graph without starting TestForge or memory calls", async () => {
  mockGet.mockResolvedValue({
    data: { name: "AgentMemory và TestForge", data: { nodes: [], edges: [] } },
  });
  mockCreate.mockResolvedValue({ id: "plugin-flow" });
  render(<CreatePluginWorkflow />);
  fireEvent.click(
    screen.getByRole("button", { name: "Workflow AgentMemory & TestForge" }),
  );
  await waitFor(() =>
    expect(mockNavigate).toHaveBeenCalledWith("/flow/plugin-flow"),
  );
  expect(mockGet).toHaveBeenCalledTimes(1);
  expect(mockGet).toHaveBeenCalledWith(
    expect.stringContaining("adlc/workflow-plugins/starter"),
  );
  expect(mockCreate).toHaveBeenCalledWith(
    expect.objectContaining({ folder_id: "project-a", mcp_enabled: false }),
  );
});
