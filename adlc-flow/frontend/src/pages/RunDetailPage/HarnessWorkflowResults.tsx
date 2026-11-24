import { translateUi, useUiLocale } from "@/i18n/ui";
import type { AdlcTaskRun } from "@/types/adlc";
import HarnessWorkflowReview, {
  workflowHarnessReview,
} from "./HarnessWorkflowReview";

export default function HarnessWorkflowResults({
  tasks,
}: {
  tasks: AdlcTaskRun[];
}) {
  useUiLocale();
  const native = tasks.filter(
    (t) => t.executor?.service === "agent-provider:harness-workflow",
  );
  if (!native.length) return null;
  return (
    <section aria-label="Kết quả Harness của workflow" className="space-y-3">
      <h2 className="font-semibold">Harness · Input/output được giữ lại</h2>
      {native.map((task) => {
        const output = task.result?.output as
          | {
              outputs?: {
                review?: unknown;
                session?: { id: string };
                result?: {
                  publish_receipt?: {
                    github_pushed: boolean;
                    repository: string;
                    branch: string;
                    commit: string;
                  };
                };
              };
            }
          | undefined;
        const review = workflowHarnessReview(output?.outputs?.review);
        const publish = output?.outputs?.result?.publish_receipt;
        return (
          <div
            key={task.id}
            className="space-y-2 rounded-lg border p-3 text-sm"
          >
            <p className="font-medium">{task.name}</p>
            {review && <HarnessWorkflowReview review={review} />}
            {output?.outputs?.session && (
              <a
                className="text-primary underline"
                href={`/harness/?run=${output.outputs.session.id}`}
              >
                Xem phiên Harness
              </a>
            )}
            {publish?.github_pushed && (
              <div>
                <p>Đã push GitHub · {publish.branch}</p>
                <p className="break-all font-mono text-xs">
                  {translateUi("Commit:")} {publish.commit}
                </p>
                <a
                  className="text-primary underline"
                  href={`https://github.com/${publish.repository}/tree/${publish.branch}`}
                >
                  Xem thay đổi trên GitHub
                </a>
              </div>
            )}
          </div>
        );
      })}
    </section>
  );
}
