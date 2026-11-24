import { translateUi, useUiLocale } from "@/i18n/ui";
export type WorkflowHarnessReview = {
  kind: "PLAN" | "COMMIT";
  repository: string;
  digest: string;
  evidence: {
    steps?: string[];
    objective?: string;
    commit?: string;
    target?: string;
  };
  result: {
    candidate?: { changes?: Record<string, { content?: string }> };
    verification?: {
      checks?: { passed: boolean; executed_tests: number; exit_code: number }[];
    };
    memory?: { source: string; chunks?: { text: string }[] }[];
    briefs?: { brief?: { approach?: string; steps?: string[] } }[];
    publish_receipt?: {
      github_pushed: boolean;
      repository: string;
      branch: string;
      commit: string;
    };
  };
};

export function workflowHarnessReview(
  value: unknown,
): WorkflowHarnessReview | undefined {
  if (!value || typeof value !== "object") return undefined;
  const r = value as WorkflowHarnessReview;
  return ["PLAN", "COMMIT"].includes(r.kind) &&
    typeof r.digest === "string" &&
    r.evidence &&
    r.result
    ? r
    : undefined;
}

export default function HarnessWorkflowReview({
  review,
}: {
  review: WorkflowHarnessReview;
}) {
  useUiLocale();
  return (
    <section
      aria-label="Bằng chứng Harness"
      className="w-full space-y-3 rounded-lg border p-3 text-sm"
    >
      <p className="font-medium">
        {review.kind === "PLAN"
          ? "Kế hoạch của Harness"
          : "Thay đổi đã được xác minh"}
      </p>
      <p>
        {translateUi("Repository:")} {review.repository} · không ghi trực tiếp
        lên main
      </p>
      {review.evidence.objective && <p>{review.evidence.objective}</p>}
      {review.evidence.steps && (
        <ol className="list-decimal pl-5">
          {review.evidence.steps.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ol>
      )}
      {review.result.briefs?.map((b, i) => (
        <p key={i}>
          {translateUi("Task brief:")} {b.brief?.approach}
        </p>
      ))}
      {review.result.memory?.map((m, i) => (
        <div key={i}>
          <p>
            {translateUi("Memory:")}{" "}
            {m.source === "REVIEWED_GATEWAY"
              ? translateUi("Backend theo project")
              : "Ngữ cảnh cục bộ"}{" "}
            · advisory, không phải bằng chứng Verify
          </p>
          {m.chunks?.map((c, j) => (
            <p key={j} className="text-muted-foreground">
              {c.text}
            </p>
          ))}
        </div>
      ))}
      {Object.entries(review.result.candidate?.changes ?? {}).map(
        ([path, file]) => (
          <div key={path}>
            <p>
              {translateUi("Source:")} {path.split("/").pop()}
            </p>
            <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded border p-2 text-xs">
              {file.content}
            </pre>
          </div>
        ),
      )}
      {review.result.verification?.checks?.map((c, i) => (
        <p key={i}>
          Verify độc lập: {c.passed ? "Đạt" : "Không đạt"} · {c.executed_tests}{" "}
          test thực thi · exit {c.exit_code}
        </p>
      ))}
      {review.evidence.commit && (
        <p className="break-all font-mono text-xs">
          {translateUi("Commit:")} {review.evidence.commit}
        </p>
      )}
      {review.evidence.target && (
        <p className="break-all text-xs">Nhánh: {review.evidence.target}</p>
      )}
      <p className="break-all font-mono text-xs">
        Digest cần duyệt: {review.digest}
      </p>
    </section>
  );
}
