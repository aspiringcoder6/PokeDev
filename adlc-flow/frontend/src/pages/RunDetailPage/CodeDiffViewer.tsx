import { useMemo, useState } from "react";
import { parseUnifiedDiff, splitDiffRows, type DiffLine } from "./code-diff";

export default function CodeDiffViewer({
  patch,
  file,
}: {
  patch: string;
  file: string;
}) {
  const [mode, setMode] = useState<"split" | "unified">(() =>
    window.matchMedia?.("(max-width: 760px)").matches ? "unified" : "split",
  );
  const [wrap, setWrap] = useState(true);
  const lines = useMemo(() => parseUnifiedDiff(patch), [patch]);
  const split = useMemo(() => (lines ? splitDiffRows(lines) : []), [lines]);
  const cell = (line: DiffLine | undefined, side: "old" | "new") => (
    <div className={`rr-diff-cell rr-diff-${line?.kind ?? "empty"}`}>
      <span className="rr-line-number" aria-hidden="true">
        {side === "old" ? line?.oldLine : line?.newLine}
      </span>
      <code>
        <span className="rr-diff-sign" aria-hidden="true">
          {line?.kind === "add" ? "+" : line?.kind === "remove" ? "−" : " "}
        </span>
        {line?.text ?? ""}
      </code>
    </div>
  );
  return (
    <section
      className={`rr-diff ${wrap ? "rr-diff-wrap" : ""}`}
      aria-label={`So sánh ${file}`}
    >
      <div className="rr-diff-toolbar">
        <div className="rr-segment" aria-label="Cách xem thay đổi">
          <button
            type="button"
            aria-pressed={mode === "split"}
            onClick={() => setMode("split")}
          >
            Hai cột
          </button>
          <button
            type="button"
            aria-pressed={mode === "unified"}
            onClick={() => setMode("unified")}
          >
            Một cột
          </button>
        </div>
        <label className="rr-wrap-option">
          <input
            type="checkbox"
            checked={wrap}
            onChange={(e) => setWrap(e.target.checked)}
          />
          Ngắt dòng
        </label>
        <span className="rr-diff-legend">
          <span>− Xóa</span>
          <span>+ Thêm</span>
        </span>
      </div>
      {lines ? (
        <div
          className={`rr-diff-scroll rr-mode-${mode}`}
          tabIndex={0}
          aria-label={`Nội dung thay đổi ${file}`}
        >
          {mode === "split" ? (
            <>
              <div className="rr-diff-columns">
                <span>Trước thay đổi</span>
                <span>Sau thay đổi</span>
              </div>
              {split.map((row, index) =>
                row.divider ? (
                  <div key={index} className="rr-diff-divider">
                    {row.divider.text}
                  </div>
                ) : (
                  <div className="rr-diff-row" key={index}>
                    {cell(row.left, "old")}
                    {cell(row.right, "new")}
                  </div>
                ),
              )}
            </>
          ) : (
            lines.map((line, index) =>
              line.kind === "hunk" || line.kind === "note" ? (
                <div key={index} className="rr-diff-divider">
                  {line.text}
                </div>
              ) : (
                <div
                  key={index}
                  className={`rr-unified-row rr-diff-${line.kind}`}
                >
                  <span className="rr-line-number" aria-hidden="true">
                    {line.oldLine}
                  </span>
                  <span className="rr-line-number" aria-hidden="true">
                    {line.newLine}
                  </span>
                  <code>
                    <span className="rr-diff-sign" aria-hidden="true">
                      {line.kind === "add"
                        ? "+"
                        : line.kind === "remove"
                          ? "−"
                          : " "}
                    </span>
                    {line.text}
                  </code>
                </div>
              ),
            )
          )}
        </div>
      ) : (
        <div className="rr-raw-fallback">
          <p>Định dạng này được giữ nguyên để tránh hiển thị sai thay đổi.</p>
          <pre>{patch}</pre>
        </div>
      )}
      {lines && (
        <details className="rr-raw-source">
          <summary>Xem patch gốc</summary>
          <pre>{patch}</pre>
        </details>
      )}
    </section>
  );
}
