import { api } from "./api";
import {
  revokeTeamMember,
  saveTeamPolicy,
  setTeamMember,
  teamError,
  teamProjects,
} from "./team-access";

jest.mock("./api", () => ({
  api: { get: jest.fn(), put: jest.fn(), post: jest.fn() },
}));
beforeEach(() => jest.clearAllMocks());

test("rejects incomplete permission responses instead of enabling fallback actions", async () => {
  (api.get as jest.Mock).mockResolvedValue({ data: { projects: [] } });
  await expect(teamProjects()).rejects.toThrow();
});
test("membership payload contains only explicit scoped role and revision", async () => {
  (api.put as jest.Mock).mockResolvedValue({ data: { revision: 8 } });
  await setTeamMember("project-a", 7, "tester", ["tester"]);
  expect(api.put).toHaveBeenCalledWith(
    expect.stringContaining("/projects/project-a/members"),
    { expected_revision: 7, username: "tester", roles: ["tester"] },
  );
});
test("policy never sends a caller-supplied owner or global domain", async () => {
  (api.put as jest.Mock).mockResolvedValue({ data: { revision: 8 } });
  const role = { allow: [], deny: [] };
  const policy = {
    roles: {
      admin: role,
      developer: role,
      business_analyst: role,
      tester: role,
    },
  };
  await saveTeamPolicy("project-a", 7, policy);
  expect(api.put).toHaveBeenCalledWith(
    expect.stringContaining("/projects/project-a/policy"),
    { expected_revision: 7, policy },
  );
});
test("only safe error vocabulary reaches the UI", () => {
  expect(
    teamError({
      response: {
        data: {
          detail: {
            code: "TEAM_LAST_ADMIN_PROTECTED",
            token: "do-not-display",
          },
        },
      },
    }),
  ).toContain("Admin");
  expect(teamError(new Error("do-not-display"))).not.toContain(
    "do-not-display",
  );
});

test("rejects malformed mutation receipts instead of reporting success", async () => {
  (api.put as jest.Mock).mockResolvedValue({ data: { revision: 0 } });
  await expect(
    setTeamMember("project-a", 7, "tester", ["tester"]),
  ).rejects.toThrow();
  (api.post as jest.Mock).mockResolvedValue({
    data: { revision: 8, revoked: false },
  });
  await expect(revokeTeamMember("project-a", 7, "subject-a")).rejects.toThrow();
});
