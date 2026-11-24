import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { liveWorkflows } from "@/controllers/API/live-workflows";
import {
  projectLifecycle,
  type ProjectEnvironment as EnvironmentValue,
} from "@/controllers/API/project-lifecycle";
import ProjectEnvironment, { parseCommandLine } from "./project-environment";

const project = {
  project_id: "project",
  name: "Military Youth",
  repository: "admin/tnqd-sut",
  repository_id: 40,
  repository_url: "http://gitea/admin/tnqd-sut",
  branch: "main",
  base_commit: "a".repeat(40),
};
const environment: EnvironmentValue = {
  project_id: "project",
  revision: 1,
  digest: "a".repeat(64),
  profile: {
    name: "Python",
    working_directory: ".",
    base: null,
    overlays: [],
    setup: [],
    tests: [
      { label: "Tests", argv: ["python", "-m", "unittest"], timeout: 60 },
    ],
    build: [],
    preview: null,
  },
};
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ProjectEnvironment identity="owner" project={project} />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  jest
    .spyOn(projectLifecycle, "environment")
    .mockResolvedValue(structuredClone(environment));
  jest
    .spyOn(liveWorkflows, "repositories")
    .mockResolvedValue({
      items: [
        {
          id: 37,
          name: "base",
          full_name: "admin/tcct-fe-base",
          description: "",
          html_url: "http://gitea/base",
          private: true,
          default_branch: "main",
        },
      ],
    });
});
afterEach(() => jest.restoreAllMocks());
beforeAll(() => {
  global.structuredClone = (value) => JSON.parse(JSON.stringify(value));
});

test("command editor keeps quoted arguments and rejects shell chaining", () => {
  expect(parseCommandLine("python -c \"print('ok')\"")).toEqual([
    "python",
    "-c",
    "print('ok')",
  ]);
  expect(parseCommandLine('node "a file.js"')).toEqual(["node", "a file.js"]);
  expect(() => parseCommandLine("npm ci && npm test")).toThrow("Mỗi dòng");
  expect(() => parseCommandLine('node "missing')).toThrow("dấu nháy");
});

test("environment editor saves a revision and pinned module mapping without exposing local paths", async () => {
  const save = jest
    .spyOn(projectLifecycle, "saveEnvironment")
    .mockImplementation(async (_, revision, profile) => ({
      ...environment,
      revision: revision + 1,
      profile,
    }));
  mount();
  await screen.findByRole("option", { name: "admin/tcct-fe-base" });
  fireEvent.change(await screen.findByLabelText("Repo khung"), {
    target: { value: "37" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Thêm module" }));
  fireEvent.change(screen.getByLabelText("Nguồn module 1"), {
    target: { value: "FE/military-youth-develop" },
  });
  fireEvent.change(screen.getByLabelText("Đích module 1"), {
    target: { value: "src/app/modules/military-youth" },
  });
  fireEvent.change(screen.getByLabelText("Kiểm thử bắt buộc"), {
    target: { value: "npm test -- --watch=false" },
  });
  expect(
    screen.getByRole("button", { name: "Kiểm tra môi trường" }),
  ).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Lưu môi trường" }));
  await waitFor(() => expect(save).toHaveBeenCalled());
  expect(save.mock.calls[0][0]).toBe("project");
  expect(save.mock.calls[0][1]).toBe(1);
  expect(save.mock.calls[0][2].base).toEqual({ repository_id: 37 });
  expect(save.mock.calls[0][2].overlays).toEqual([
    {
      source: "FE/military-youth-develop",
      target: "src/app/modules/military-youth",
    },
  ]);
  expect(save.mock.calls[0][2].tests[0].argv).toEqual([
    "npm",
    "test",
    "--",
    "--watch=false",
  ]);
});

test("baseline check explicitly starts a Sandbox job and displays real failed check logs", async () => {
  const begin = jest
    .spyOn(projectLifecycle, "checkEnvironment")
    .mockResolvedValue({
      check_id: "check",
      state: "RUNNING",
      environment_digest: environment.digest!,
    });
  jest
    .spyOn(projectLifecycle, "readCheck")
    .mockResolvedValue({
      check_id: "check",
      state: "FAILED",
      environment_digest: environment.digest!,
      receipt: {
        checks: [
          {
            id: "test",
            label: "Test baseline",
            passed: false,
            stderr: "Pagination assertion failed",
          },
        ],
      },
    });
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Kiểm tra môi trường" }),
  );
  expect(
    await screen.findByText(/Pagination assertion failed/),
  ).toBeInTheDocument();
  expect(begin.mock.calls[0][0]).toBe("project");
  expect(begin.mock.calls[0][2]).toBe(environment.digest);
  expect(screen.getByText("Cần xử lý")).toBeInTheDocument();
});
