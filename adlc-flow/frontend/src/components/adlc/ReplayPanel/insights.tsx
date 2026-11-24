import { translateUi, useUiLocale, formatUiStatus } from "@/i18n/ui";
import type { ReplayRead } from "@/types/replay";

// Compare only a fixed standard. A different oracle/config is not a regression
// or recovery, even when its new report is green. All rows are pre-validated by
// ReplayPanel; this projection confers no acceptance or action authority.
export function sameReplayStandard(a: ReplayRead, b: ReplayRead) {
  const x = a.plan,
    y = b.plan;
  return (
    x.profile_ref === y.profile_ref &&
    x.config_digest === y.config_digest &&
    x.suite_digest === y.suite_digest &&
    x.target_profile_ref === y.target_profile_ref &&
    x.credential_ref === y.credential_ref &&
    x.candidate.project_id === y.candidate.project_id &&
    x.candidate.file === y.candidate.file &&
    x.contract_reference.contract_id === y.contract_reference.contract_id &&
    x.contract_reference.revision === y.contract_reference.revision &&
    x.contract_reference.content_digest ===
      y.contract_reference.content_digest &&
    x.cases.length === y.cases.length &&
    x.cases.every((c, i) => {
      const d = y.cases[i];
      return (
        c.case_id === d.case_id &&
        c.pointer === d.pointer &&
        c.expected === d.expected &&
        c.expected_status === d.expected_status &&
        c.method === d.method &&
        c.path === d.path &&
        c.criterion_node_id === d.criterion_node_id &&
        c.criterion_index === d.criterion_index
      );
    })
  );
}
export function replayTrend(row: ReplayRead, previous?: ReplayRead) {
  if (!row.report || !row.receipt) return "Not verified yet";
  if (!previous?.report) return "First retained comparison";
  if (!sameReplayStandard(row, previous))
    return "Standard changed · no regression verdict";
  if (
    row.plan.candidate.content_digest === previous.plan.candidate.content_digest
  )
    return "Repeated candidate · same standard";
  if (previous.report.verdict === "PASS" && row.report.verdict === "FAIL")
    return "Fixture regression · fixed standard";
  if (previous.report.verdict === "FAIL" && row.report.verdict === "PASS")
    return "Recovered fixture · fixed standard";
  return "Unchanged verdict · fixed standard";
}
export default function ReplayInsights({ rows }: { rows: ReplayRead[] }) {
  useUiLocale();
  const history = [...rows].sort(
    (a, b) =>
      Date.parse(a.created_at) - Date.parse(b.created_at) ||
      a.plan.plan_id.localeCompare(b.plan.plan_id),
  );
  if (!history.length) return null;
  const completed = history.filter((r) => r.report && r.receipt);
  return (
    <section
      aria-label={translateUi("Replay history and coverage")}
      className="space-y-3 rounded-lg border bg-muted/20 p-3"
    >
      <h3 className="text-sm font-semibold">
        {translateUi("Coverage & regression history")}
      </h3>
      <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
        <div>
          {history.length} {translateUi("frozen suites")}
        </div>
        <div>
          {completed.length} {translateUi("completed comparisons")}
        </div>
        <div>
          {completed.filter((r) => r.report!.verdict === "PASS").length}{" "}
          {translateUi("fixture PASS")}
        </div>
        <div>
          {completed.filter((r) => r.report!.verdict === "FAIL").length}{" "}
          {translateUi("fixture FAIL")}
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        {translateUi(
          "This owner/run or exact session only. Changed criteria, suite, contract or target configuration start a different standard. No application-level verification is implied.",
        )}
      </p>
      <ol className="space-y-2">
        {history.map((row, i) => {
          const previous = history
            .slice(0, i)
            .reverse()
            .find(
              (r) =>
                r.report &&
                r.plan.candidate.project_id === row.plan.candidate.project_id &&
                r.plan.candidate.file === row.plan.candidate.file,
            );
          return (
            <li
              key={row.plan.plan_id}
              className="rounded border bg-background p-2 text-xs"
            >
              <a
                className="font-medium underline"
                href={`#replay-${row.plan.plan_id}`}
              >
                {row.plan.candidate.file} · {formatUiStatus(row.state)}
              </a>
              <p>{replayTrend(row, previous)}</p>
              <p>
                {row.report
                  ? translateUi(
                      "{{value0}}/{{value1}} completed · {{value2}} passed · {{value3}} failed · 0 skipped",
                      {
                        value0: row.report.completed_cases,
                        value1: row.report.required_cases,
                        value2: row.report.checks.filter((c) => c.passed)
                          .length,
                        value3: row.report.checks.filter((c) => !c.passed)
                          .length,
                      },
                    )
                  : translateUi(
                      "0/{{value0}} confirmed complete · no verdict",
                      { value0: row.plan.cases.length },
                    )}
              </p>
              <p className="break-all text-muted-foreground">
                {translateUi("Suite")} {row.plan.suite_digest}{" "}
                {translateUi("· candidate")} {row.plan.candidate.content_digest}
              </p>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
