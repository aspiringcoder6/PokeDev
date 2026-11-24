import { api } from "./api";
import {
  collaborationError,
  decideShared,
  sharedResourceSchema,
  workspaceSchema,
} from "./collaboration";

jest.mock("./api", () => ({
  api: { get: jest.fn(), put: jest.fn(), post: jest.fn() },
}));
const id = "00000000-0000-4000-8000-000000000001";
const hash = `sha256:${"a".repeat(64)}`;
function item() {
  return sharedResourceSchema.parse({
    id,
    project_id: id,
    kind: "CONTRACT",
    title: "Scope",
    created_by: id,
    origin_owner_id: id,
    responsible_ids: [id],
    revision: 3,
    content_digest: hash,
    status: "SUBMITTED",
    dependencies: {},
    parent_id: null,
    created_at: "2026-10-17T01:00:00Z",
    updated_at: "2026-10-17T01:00:00Z",
    payload: {},
    selected_revision: 3,
    policy_revision: 9,
    stale_dependencies: false,
    reviewers: [],
    can_decide: false,
    required_action: "contract:approve",
    decisions: [],
  });
}
beforeEach(() => jest.clearAllMocks());
test("unknown or malformed permission payloads never enable a workspace", () => {
  expect(() => workspaceSchema.parse({ execution_enabled: true })).toThrow();
  expect(() =>
    sharedResourceSchema.parse({ ...item(), can_decide: "true" }),
  ).toThrow();
});
test("a decision carries exact resource and policy proof, not an owner or role from the browser", async () => {
  (api.post as jest.Mock).mockResolvedValue({
    data: {
      id,
      decided_by: id,
      decision: "APPROVE",
      comment: "Reviewed",
      resource_revision: 3,
      policy_revision: 9,
      content_digest: hash,
      created_at: "2026-10-17T01:00:00Z",
      expires_at: "2026-10-18T01:00:00Z",
    },
  });
  await decideShared(item(), "APPROVE", "Reviewed");
  expect(api.post).toHaveBeenCalledWith(
    expect.stringContaining(`/projects/${id}/resources/${id}/decisions`),
    {
      policy_revision: 9,
      expected_revision: 3,
      content_digest: hash,
      decision: "APPROVE",
      comment: "Reviewed",
    },
  );
});
test("a malformed mutation receipt cannot be treated as approved", async () => {
  (api.post as jest.Mock).mockResolvedValue({ data: { approved: true } });
  await expect(decideShared(item(), "APPROVE", "Reviewed")).rejects.toThrow();
});
test("only fixed safe error vocabulary reaches the UI", () => {
  expect(collaborationError(new Error("private-runtime-token"))).not.toContain(
    "private-runtime-token",
  );
  expect(
    collaborationError({
      response: {
        data: { detail: { code: "TEAM_INDEPENDENT_REVIEWER_REQUIRED" } },
      },
    }),
  ).toContain("người khác");
});
