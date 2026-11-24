import { parseApprovedReference } from "./approved-reference";

const reference = {
  schema_ref: "adlc://schemas/skilltree-contract/0.1",
  contract_id: "11111111-1111-4111-8111-111111111111",
  revision: 3,
  content_digest: `sha256:${"a".repeat(64)}`,
};
test("preserves all four exact fields as an object, never a plain string or latest reference", () => {
  expect(parseApprovedReference(JSON.stringify(reference))).toEqual(reference);
});
test.each([
  "",
  "null",
  "[]",
  "{}",
  '"latest"',
  JSON.stringify({ ...reference, revision: true }),
  JSON.stringify({ ...reference, revision: 0 }),
  JSON.stringify({ ...reference, revision: 513 }),
  JSON.stringify({ ...reference, content_digest: "sha256:short" }),
  JSON.stringify({ ...reference, owner: "caller" }),
  JSON.stringify({ ...reference, contract_id: "not-a-uuid" }),
  JSON.stringify({ ...reference, schema_ref: "unknown" }),
])("rejects incomplete or caller-selected authority: %s", (text) => {
  expect(() => parseApprovedReference(text)).toThrow(
    /exact approved contract reference/,
  );
});
