import { useState } from "react";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type {
  AdlcHarnessRunResult,
  AdlcHarnessRunSession,
  AdlcTaskRun,
  AdlcTaskSubtasks,
} from "@/types/adlc";
import HarnessResults from "./HarnessResults";
import SubtaskDetail from "./SubtaskDetail";
import SubtaskGraph from "./SubtaskGraph";
import SubtaskList from "./SubtaskList";
import SubtaskProgress from "./SubtaskProgress";
import { useTranslation } from "react-i18next";
import "@/i18n";

interface TaskSubtaskPanelProps {
  runId: string;
  taskRunId: string;
  data: AdlcTaskSubtasks;
  isMockData?: boolean;
  results: AdlcHarnessRunResult[];
  sessions: AdlcHarnessRunSession[];
  tasks: AdlcTaskRun[];
}

/**
 * Panel showing the subtasks of a task. Includes:
 * - Progress bar with aggregated stats (5/8 style)
 * - Tabbed view: list / graph / results (documents produced by the sub-agents)
 * - Detail panel for the selected subtask
 */
export default function TaskSubtaskPanel({
  runId,
  taskRunId,
  data,
  isMockData = false,
  results,
  sessions,
  tasks,
}: TaskSubtaskPanelProps) {
  const { t } = useTranslation();
  const [selectedId, setSelectedId] = useState<string | undefined>();
  const [view, setView] = useState<"list" | "graph" | "results">("list");

  const selectedSubtask = data.subtasks.find((s) => s.id === selectedId);
  const resultCount =
    results.length + sessions.filter((entry) => entry.session.result).length;
  const hasResults = resultCount > 0;

  return (
    <div
      className="space-y-3"
      data-testid="task-subtask-panel"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold">{t("adlc.run.subtasks")}</h3>
          {isMockData && (
            <span
              className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-700 dark:bg-amber-950 dark:text-amber-300"
              data-testid="subtask-mock-badge"
              title={t("adlc.run.demoDataTitle")}
            >
              {t("adlc.run.demoData")}
            </span>
          )}
        </div>
        <SubtaskProgress summary={data.summary} />
      </div>

      <Tabs
        value={view}
        onValueChange={(v) => setView(v as "list" | "graph" | "results")}
      >
        <TabsList>
          <TabsTrigger value="list" data-testid="subtask-view-list">
            <ForwardedIconComponent name="List" className="mr-1 h-3.5 w-3.5" />
            List
          </TabsTrigger>
          <TabsTrigger value="graph" data-testid="subtask-view-graph">
            <ForwardedIconComponent name="GitBranch" className="mr-1 h-3.5 w-3.5" />
            Graph
          </TabsTrigger>
          <TabsTrigger value="results" data-testid="subtask-view-results">
            <ForwardedIconComponent name="FileText" className="mr-1 h-3.5 w-3.5" />
            Results
            {hasResults ? (
              <span className="ml-1 text-[10px] text-muted-foreground">
                ({resultCount})
              </span>
            ) : null}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="list" className="mt-2">
          <SubtaskList
            subtasks={data.subtasks}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
        </TabsContent>
        <TabsContent value="graph" className="mt-2">
          <SubtaskGraph
            subtasks={data.subtasks}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
        </TabsContent>
        <TabsContent value="results" className="mt-2">
          {hasResults ? (
            <HarnessResults embedded results={results} sessions={sessions} tasks={tasks} />
          ) : (
            <p
              className="p-4 text-xs text-muted-foreground"
              data-testid="subtask-results-empty"
            >
              {t("adlc.run.noDocumentsYet")}
            </p>
          )}
        </TabsContent>
      </Tabs>

      {selectedSubtask && (
        <SubtaskDetail
          runId={runId}
          taskRunId={taskRunId}
          subtask={selectedSubtask}
        />
      )}
    </div>
  );
}
