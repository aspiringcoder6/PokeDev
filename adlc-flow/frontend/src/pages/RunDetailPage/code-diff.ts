export type DiffLine = {
  kind: "context" | "add" | "remove" | "hunk" | "note";
  text: string;
  oldLine?: number;
  newLine?: number;
};

// A diff is not a complete file. Only number lines supplied by a valid hunk;
// never invent omitted context or silently discard an unsupported patch.
export function parseUnifiedDiff(patch: string): DiffLine[] | null {
  const lines = patch.replace(/\r\n/g, "\n").split("\n");
  if (lines.at(-1) === "") lines.pop();
  const result: DiffLine[] = [];
  let oldLine = 0;
  let newLine = 0;
  let oldRemaining = 0;
  let newRemaining = 0;
  let foundHunk = false;
  for (const text of lines) {
    const hunk = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)$/.exec(
      text,
    );
    if (hunk) {
      if (oldRemaining || newRemaining) return null;
      const nextOld = Number(hunk[1]);
      const nextNew = Number(hunk[3]);
      if (foundHunk && (nextOld < oldLine || nextNew < newLine)) return null;
      oldLine = nextOld;
      newLine = nextNew;
      oldRemaining = Number(hunk[2] ?? 1);
      newRemaining = Number(hunk[4] ?? 1);
      foundHunk = true;
      result.push({ kind: "hunk", text });
      continue;
    }
    if (!foundHunk) {
      if (
        /^(diff --git |index |--- |\+\+\+ |new file mode |deleted file mode |old mode |new mode |similarity index |rename from |rename to )/.test(
          text,
        )
      )
        continue;
      return null;
    }
    if (text === "\\ No newline at end of file") {
      result.push({ kind: "note", text });
    } else if (text.startsWith(" ") && oldRemaining > 0 && newRemaining > 0) {
      result.push({
        kind: "context",
        text: text.slice(1),
        oldLine: oldLine++,
        newLine: newLine++,
      });
      oldRemaining--;
      newRemaining--;
    } else if (text.startsWith("-") && oldRemaining > 0) {
      result.push({ kind: "remove", text: text.slice(1), oldLine: oldLine++ });
      oldRemaining--;
    } else if (text.startsWith("+") && newRemaining > 0) {
      result.push({ kind: "add", text: text.slice(1), newLine: newLine++ });
      newRemaining--;
    } else {
      return null;
    }
  }
  return foundHunk && !oldRemaining && !newRemaining ? result : null;
}

export function splitDiffRows(lines: DiffLine[]) {
  const rows: { left?: DiffLine; right?: DiffLine; divider?: DiffLine }[] = [];
  for (let i = 0; i < lines.length; ) {
    const line = lines[i];
    if (line.kind === "context") {
      rows.push({ left: line, right: line });
      i++;
    } else if (line.kind === "hunk" || line.kind === "note") {
      rows.push({ divider: line });
      i++;
    } else {
      const removed: DiffLine[] = [];
      const added: DiffLine[] = [];
      while (i < lines.length && ["add", "remove"].includes(lines[i].kind)) {
        (lines[i].kind === "remove" ? removed : added).push(lines[i++]);
      }
      for (let j = 0; j < Math.max(removed.length, added.length); j++) {
        rows.push({ left: removed[j], right: added[j] });
      }
    }
  }
  return rows;
}
