import { fireEvent, render, screen } from "@testing-library/react";
import CodeDiffViewer from "./CodeDiffViewer";
import { parseUnifiedDiff, splitDiffRows } from "./code-diff";

const patch =
  "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -10,3 +10,4 @@ example\n keep\n-old\n+new\n+extra\n end\n";

test("numbers only supplied context and aligns unequal replacement blocks", () => {
  const lines = parseUnifiedDiff(patch)!;
  expect(lines).toEqual([
    { kind: "hunk", text: "@@ -10,3 +10,4 @@ example" },
    { kind: "context", text: "keep", oldLine: 10, newLine: 10 },
    { kind: "remove", text: "old", oldLine: 11 },
    { kind: "add", text: "new", newLine: 11 },
    { kind: "add", text: "extra", newLine: 12 },
    { kind: "context", text: "end", oldLine: 12, newLine: 13 },
  ]);
  expect(splitDiffRows(lines)[2]).toMatchObject({
    left: { text: "old" },
    right: { text: "new" },
  });
  expect(splitDiffRows(lines)[3]).toEqual({
    left: undefined,
    right: { kind: "add", text: "extra", newLine: 12 },
  });
});

test.each([
  ["@@ -0,0 +1,1 @@\n+created\n", "add", 1],
  ["@@ -1 +0,0 @@\n-removed\n", "remove", 1],
  [
    "@@ -2 +2 @@\r\n-old\r\n+new\r\n\\ No newline at end of file\r\n",
    "note",
    undefined,
  ],
])(
  "supports added/deleted files and newline notes: %s",
  (value, kind, number) => {
    const lines = parseUnifiedDiff(value)!;
    expect(lines.at(-1)?.kind).toBe(kind);
    if (number)
      expect(lines.at(-1)?.newLine ?? lines.at(-1)?.oldLine).toBe(number);
  },
);

test.each([
  "+only a fragment\n",
  "Binary files differ\n",
  "@@ -1,2 +1 @@\n-old\n+new\n",
  "@@ -1 +1 @@\n-old\n+new\n+extra\n",
  "@@ -4 +4 @@\n-old\n+new\n@@ -2 +2 @@\n-a\n+b\n",
])(
  "falls back instead of dropping unsupported or incomplete content: %s",
  (value) => {
    expect(parseUnifiedDiff(value)).toBeNull();
  },
);

test("keeps separated hunks and never fills omitted file context", () => {
  const lines = parseUnifiedDiff(
    "@@ -1 +1 @@\n-a\n+b\n@@ -20 +20 @@\n-c\n+d\n",
  )!;
  expect(lines.filter((line) => line.kind === "hunk")).toHaveLength(2);
  expect(lines.some((line) => line.oldLine === 2)).toBe(false);
});

test("provides colored changes, a one-column view, wrapping, and escaped source", () => {
  const { container } = render(
    <CodeDiffViewer
      file="app.py"
      patch={patch.replace("+new", "+<script>unsafe()</script>")}
    />,
  );
  expect(container.querySelector(".rr-diff-remove code")).toHaveTextContent(
    "old",
  );
  expect(container.querySelector(".rr-diff-add code")).toHaveTextContent(
    "<script>unsafe()</script>",
  );
  expect(container.querySelector("script")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Một cột" }));
  expect(screen.getByRole("button", { name: "Một cột" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(container.querySelector(".rr-unified-row")).not.toBeNull();
  fireEvent.click(screen.getByRole("checkbox", { name: "Ngắt dòng" }));
  expect(container.querySelector(".rr-diff-wrap")).toBeNull();
  expect(container.querySelector("details")).not.toHaveAttribute("open");
});

test("raw fallback preserves exactly one visible copy of a malformed patch", () => {
  render(<CodeDiffViewer file="readme" patch={"+original\n"} />);
  expect(screen.getByText("+original")).toBeVisible();
  expect(screen.queryByText("Xem patch gốc")).toBeNull();
});
