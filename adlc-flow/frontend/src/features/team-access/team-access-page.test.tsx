import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import * as access from "@/controllers/API/team-access";
import TeamAccessPage, { policyDiff } from "./team-access-page";

jest.mock("@/stores/authStore", () => ({
  __esModule: true,
  default: (selector: (state: unknown) => unknown) =>
    selector({ userData: { id: "00000000-0000-4000-8000-000000000001" } }),
}));
jest.mock("@/controllers/API/team-access", () => ({
  roleIds: ["admin", "developer", "business_analyst", "tester"],
  teamProjects: jest.fn(),
  teamProject: jest.fn(),
  createTeamProject: jest.fn(),
  saveTeamPolicy: jest.fn(),
  setTeamMember: jest.fn(),
  revokeTeamMember: jest.fn(),
  teamEffective: jest.fn(),
  teamAudit: jest.fn(),
  teamError: () => "Quyền không xác định — khóa an toàn",
}));

const uid = "00000000-0000-4000-8000-000000000001";
const pid = "00000000-0000-4000-8000-000000000002";
function fixture(): access.TeamAccessView {
  const roles = ["admin", "developer", "business_analyst", "tester"] as const;
  return {
    project_id: pid,
    name: "Team A",
    mode: "CONFIGURATION_ONLY",
    revision: 5,
    can_manage: true,
    roles: roles.map((id, index) => ({
      id,
      name: ["Admin", "Developer", "Business Analyst", "Tester"][index],
    })),
    policy: {
      roles: {
        admin: { allow: ["project:read", "policy:manage"], deny: [] },
        developer: { allow: ["project:read", "flow:write"], deny: [] },
        business_analyst: { allow: ["project:read"], deny: [] },
        tester: { allow: ["project:read"], deny: [] },
      },
    },
    catalog: [
      {
        key: "project:read",
        label: "Xem project",
        area: "Project",
        phase: "H7A",
      },
      {
        key: "policy:manage",
        label: "Quản lý chính sách",
        area: "Quản trị",
        phase: "H7A",
      },
      {
        key: "flow:write",
        label: "Sửa workflow",
        area: "Workflows",
        phase: "H7B",
      },
    ],
    members: [
      { user_id: uid, username: "operator", roles: ["admin"], is_active: true },
    ],
    effective: {
      user_id: uid,
      roles: ["admin"],
      revision: 5,
      permissions: {
        "project:read": {
          allowed: true,
          granted: true,
          reason: "TEAM_PERMISSION_GRANTED",
          phase: "H7A",
        },
      },
    },
  };
}
let client: QueryClient;
beforeEach(() => {
  jest.clearAllMocks();
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  (access.teamProjects as jest.Mock).mockResolvedValue({
    phase: "H7A",
    can_create: true,
    projects: [
      {
        project_id: pid,
        name: "Team A",
        revision: 5,
        roles: ["admin"],
        mode: "CONFIGURATION_ONLY",
      },
    ],
  });
  (access.teamProject as jest.Mock).mockResolvedValue(fixture());
  (access.teamAudit as jest.Mock).mockResolvedValue([]);
  (access.teamEffective as jest.Mock).mockResolvedValue(fixture().effective);
});
afterEach(() => client.clear());
function mount() {
  return render(
    <QueryClientProvider client={client}>
      <TeamAccessPage />
    </QueryClientProvider>,
  );
}

test("renders four roles and explicitly keeps shared execution closed", async () => {
  mount();
  expect(
    await screen.findByRole("button", { name: /Business Analyst/ }),
  ).toBeInTheDocument();
  expect(
    screen.getByText("H7A · Quản trị thật, chưa mở thực thi chung"),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Xem thay đổi/i })).toBeDisabled();
  expect(
    screen.getByLabelText("Developer: Quản lý chính sách — allow"),
  ).toBeDisabled();
  expect(access.saveTeamPolicy).not.toHaveBeenCalled();
});

test("deny replaces allow and saving requires a separate preview", async () => {
  (access.saveTeamPolicy as jest.Mock).mockResolvedValue({ revision: 6 });
  mount();
  await screen.findByRole("button", { name: /Developer/ });
  fireEvent.click(screen.getByText(/Quyền chuẩn bị cho H7B/));
  fireEvent.click(screen.getByLabelText("Developer: Sửa workflow — deny"));
  expect(
    screen.getByLabelText("Developer: Sửa workflow — allow"),
  ).not.toBeChecked();
  expect(access.saveTeamPolicy).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: /Xem thay đổi/i }));
  expect(
    screen.getByRole("dialog", { name: "Xem trước thay đổi quyền" }),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Lưu chính sách/i }));
  await waitFor(() => expect(access.saveTeamPolicy).toHaveBeenCalledTimes(1));
  const [id, revision, policy] = (access.saveTeamPolicy as jest.Mock).mock
    .calls[0];
  expect(id).toBe(pid);
  expect(revision).toBe(5);
  expect(policy.roles.developer.deny).toContain("flow:write");
  expect(policy.roles.developer.allow).not.toContain("flow:write");
});

test("a new revision locks a stale draft instead of silently rebasing it", async () => {
  mount();
  await screen.findByRole("button", { name: /Developer/ });
  await waitFor(() =>
    expect(
      screen.getByLabelText("Developer: Xem project — allow"),
    ).toBeEnabled(),
  );
  fireEvent.click(screen.getByLabelText("Developer: Xem project — allow"));
  await act(async () =>
    client.setQueryData(["team-access", uid, pid], {
      ...fixture(),
      revision: 6,
    }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Chính sách đã có phiên bản mới",
  );
  expect(screen.getByRole("button", { name: /Xem thay đổi/i })).toBeDisabled();
  expect(access.saveTeamPolicy).not.toHaveBeenCalled();
});

test("non-admin sees their own permissions, not membership management", async () => {
  const data = fixture();
  data.can_manage = false;
  data.members = [];
  data.policy = null;
  data.effective.roles = ["tester"];
  (access.teamProject as jest.Mock).mockResolvedValue(data);
  (access.teamProjects as jest.Mock).mockResolvedValue({
    phase: "H7A",
    can_create: false,
    projects: [{ project_id: pid, name: "Team A" }],
  });
  mount();
  await screen.findByRole("button", { name: /Tester/ });
  expect(
    screen.queryByRole("button", { name: /Xem thay đổi/i }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "Thành viên" }));
  expect(
    screen.queryByLabelText("Username thành viên"),
  ).not.toBeInTheDocument();
  expect(
    screen.getByText(/Chỉ người có quyền quản trị thành viên/),
  ).toBeInTheDocument();
});

test("unknown or failed policy lookups never render actionable controls", async () => {
  (access.teamProject as jest.Mock).mockRejectedValue(new Error("offline"));
  mount();
  expect(await screen.findByRole("alert")).toHaveTextContent("khóa an toàn");
  expect(
    screen.queryByRole("button", { name: /Xem thay đổi/i }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByLabelText("Username thành viên"),
  ).not.toBeInTheDocument();
});

test("membership writes are scoped and include the current revision", async () => {
  (access.setTeamMember as jest.Mock).mockResolvedValue({ revision: 6 });
  mount();
  await screen.findByRole("tab", { name: "Thành viên" });
  fireEvent.click(screen.getByRole("tab", { name: "Thành viên" }));
  fireEvent.change(screen.getByLabelText("Username thành viên"), {
    target: { value: "tester-user" },
  });
  fireEvent.change(screen.getByLabelText("Vai trò thành viên"), {
    target: { value: "tester" },
  });
  fireEvent.click(screen.getByRole("button", { name: /Thêm \/ thay role/i }));
  expect(access.setTeamMember).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: /Xác nhận gán role/i }));
  await waitFor(() =>
    expect(access.setTeamMember).toHaveBeenCalledWith(pid, 5, "tester-user", [
      "tester",
    ]),
  );
});

test("revocation requires an explicit confirmation and preserves project scope", async () => {
  (access.revokeTeamMember as jest.Mock).mockRejectedValue(
    new Error("last admin"),
  );
  mount();
  await screen.findByRole("tab", { name: "Thành viên" });
  fireEvent.click(screen.getByRole("tab", { name: "Thành viên" }));
  fireEvent.click(screen.getByRole("button", { name: /Thu hồi/i }));
  expect(access.revokeTeamMember).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: /Xác nhận thu hồi/i }));
  await waitFor(() =>
    expect(access.revokeTeamMember).toHaveBeenCalledWith(pid, 5, uid),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("khóa an toàn");
});

test("policy comparison has stable per-role per-effect changes", () => {
  const before = fixture().policy!;
  const after = JSON.parse(JSON.stringify(before));
  after.roles.tester.deny = ["flow:write"];
  expect(policyDiff(before, after)).toEqual([
    { role: "tester", effect: "deny", key: "flow:write", enabled: true },
  ]);
});
