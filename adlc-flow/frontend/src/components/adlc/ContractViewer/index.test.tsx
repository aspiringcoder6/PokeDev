import { fireEvent, render, screen } from "@testing-library/react";
import ContractViewer from ".";
import { isSupportedContract, SCHEMA_REF, skilltreeLayout } from "./model";
import { copyContract } from "./test-fixtures";

test("diagram layout is deterministic, preserves content and distinguishes hierarchy/dependencies", () => {
  const contract = copyContract(),
    before = JSON.stringify(contract);
  const first = skilltreeLayout(contract)!;
  expect(first).toEqual(skilltreeLayout(contract));
  expect(first.points.get(contract.document.nodes[0].node_id)!.x).toBeLessThan(
    first.points.get(contract.document.nodes[1].node_id)!.x,
  );
  expect(JSON.stringify(contract)).toBe(before);
  expect(isSupportedContract(contract)).toBe(true);
  render(<ContractViewer contract={contract} />);
  expect(screen.getByText(/Solid: requires/)).toBeInTheDocument();
  expect(
    screen.getByText(contract.reference.content_digest),
  ).toBeInTheDocument();
});
test("full acceptance text and verifier declarations remain accessible without invented progress", () => {
  render(<ContractViewer contract={copyContract()} />);
  fireEvent.click(
    screen.getByRole("button", { name: /TASK Render the complete/ }),
  );
  expect(
    screen.getAllByText(/Human can inspect the full roadmap/).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getAllByText(/HUMAN · human review · not executed/).length,
  ).toBeGreaterThan(0);
  expect(
    screen.getByText(/Declaration checks do not execute acceptance criteria/),
  ).toBeInTheDocument();
});
test("malicious markup is text in both roadmap and JSON, never interpreted as HTML or links", () => {
  const contract = copyContract();
  contract.document.title = '<img src=x onerror="alert(1)">';
  contract.document.scope.objective =
    "[click](javascript:alert(1)) <script>alert(1)</script>";
  const { container } = render(<ContractViewer contract={contract} />);
  expect(screen.getByText(contract.document.title)).toBeInTheDocument();
  expect(container.querySelector("img,script,a")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "JSON & receipts" }));
  expect(container.querySelector("pre")!.textContent).toContain(
    contract.document.title.replaceAll('"', '\\"'),
  );
  expect(container.querySelector("img,script,a")).toBeNull();
});
test.each([
  "renderer",
  "schema",
  "receipt",
  "cycle",
  "malformed",
  "validation-shape",
  "projection-schema",
  "supersedes-shape",
])(
  "unknown/invalid %s uses escaped JSON fallback without approval claims",
  (mode) => {
    const contract = copyContract();
    if (mode === "renderer")
      contract.document.renderer_ref = "plugin:unknown/view";
    if (mode === "schema")
      contract.document.schema_ref = "adlc://schemas/other/1";
    if (mode === "receipt") contract.status = "APPROVED";
    if (mode === "cycle")
      contract.document.dependencies.push({
        source_id: contract.document.nodes[2].node_id,
        target_id: contract.document.nodes[0].node_id,
        relation: "REQUIRES",
      });
    if (mode === "malformed") contract.document.nodes = [null as never];
    if (mode === "validation-shape")
      contract.validation!.checks = [null as never];
    if (mode === "projection-schema") contract.schema_version = "0.2" as never;
    if (mode === "supersedes-shape")
      contract.document.supersedes = {
        schema_ref: SCHEMA_REF,
        contract_id: {},
      } as never;
    expect(isSupportedContract(contract)).toBe(false);
    render(<ContractViewer contract={contract} />);
    expect(screen.getByLabelText("Contract JSON fallback")).toBeInTheDocument();
    expect(screen.queryByLabelText("Roadmap graph")).not.toBeInTheDocument();
  },
);
