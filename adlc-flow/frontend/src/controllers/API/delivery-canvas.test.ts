import { api } from "./api";
import { deliveryApi } from "./delivery";

beforeAll(() => { global.structuredClone = (value) => JSON.parse(JSON.stringify(value)); });
afterEach(() => jest.restoreAllMocks());

test("using a package canvas copies its graph into the selected project and leaves the template intact", async () => {
  const original = { id: "template", name: "Shared canvas", folder_id: "old-project", data: { adlc: { workflow_definition_id: "template" }, nodes: [{ id: "requirement", data: { adlcDraft: { kind: "REQUIREMENT", requirement: "Old requirement" } } }, { id: "agent", data: { adlc: { inputs: { requirement: "Old requirement" }, metadata: { package: "coding-agent" } } } }], edges: [{ source: "requirement", target: "agent" }] } };
  jest.spyOn(api, "get").mockResolvedValue({ data: original });
  const flowId = "9ce04ca0-4f67-4f07-933c-160eb4d76f6d";
  const post = jest.spyOn(api, "post").mockResolvedValueOnce({ data: { id: flowId } }).mockResolvedValueOnce({ data: { id: "51fcab08-a333-4e44-8fba-b91c1107bb9e", flow_id: flowId, title: "New work", requirement: "Implement the new requirement in the project", revision: 1 } });
  await deliveryApi.createFromCanvas("template", "selected-project", "New work", "Implement the new requirement in the project");
  const copied = post.mock.calls[0][1] as { folder_id: string; data: typeof original.data };
  expect(copied.folder_id).toBe("selected-project");
  expect(copied.data.adlc.workflow_definition_id).toBe("");
  expect(copied.data.nodes[0].data.adlcDraft?.requirement).toBe("Implement the new requirement in the project");
  expect(copied.data.edges).toEqual(original.data.edges);
  expect(original.data.adlc.workflow_definition_id).toBe("template");
  expect(original.data.nodes[0].data.adlcDraft?.requirement).toBe("Old requirement");
  expect(post.mock.calls[1][1]).toEqual({ flow_id: flowId, title: "New work", requirement: "Implement the new requirement in the project" });
});
