import {
  executionLayout,
  nativeExecution,
  nativeJourney,
  taskTone,
  executionTime,
  nativeRunRefreshInterval,
} from "./execution-model";
import type { LiveRun } from "@/controllers/API/live-workflows";

const tasks = ["develop", "test", "review"].map((id) => ({
  id,
  title: id,
  state: "PENDING",
}));

test.each(["PLANNING", "PLAN_READY", "RUNNING", "UNCONFIRMED"])(
  "the reader keeps observing %s so another operator's action appears live", (state) => {
    expect(nativeRunRefreshInterval(state)).toBe(3000);
  },
);
test.each([undefined, "SUCCEEDED", "FAILED"])("terminal %s does not keep active polling", (state) => {
  expect(nativeRunRefreshInterval(state)).toBe(false);
});
test("parallel tasks share a column and dependencies advance with bounded feedback", () => {
  const layout = executionLayout(tasks, [
    { source: "develop", target: "review" },
    { source: "test", target: "review" },
    { source: "review", target: "develop", feedback: true },
  ]);
  expect(layout[0].x).toBe(layout[1].x);
  expect(layout[0].y).not.toBe(layout[1].y);
  expect(layout[2].x).toBeGreaterThan(layout[0].x);
});
test("unknown dependencies and malformed cycles cannot produce infinite positions", () => {
  const layout = executionLayout(tasks, [
    { source: "missing", target: "review" },
    { source: "develop", target: "test" },
    { source: "test", target: "develop" },
  ]);
  expect(layout).toHaveLength(3);
  expect(
    layout.every((p) => Number.isFinite(p.x) && Number.isFinite(p.y)),
  ).toBe(true);
});
test.each([
  ["IN_PROGRESS", "running"],
  ["DONE_WITH_CONCERNS", "waiting"],
  ["WAITING_INPUT", "waiting"],
  ["BLOCKED", "failed"],
  ["SKIPPED", "skipped"],
  ["DONE", "done"],
  ["COMPLETED", "idle"],
])("task state %s has the correct tone", (state, tone) =>
  expect(taskTone(state)).toBe(tone),
);
const run = (value: Partial<LiveRun>) =>
  ({
    run_id: "r",
    project_id: "p",
    phase: "execution",
    state: "RUNNING",
    nodes: [],
    documents: [],
    ...value,
  }) as LiveRun;
test("native graph keeps control-flow labels and includes execution-only verification nodes", () => {
  const definitions = tasks.slice(0, 2).map((t) => ({ ...t, depends_on: [] }));
  const current = run({
    plan: {
      title: "Search",
      summary: "Build search",
      digest: "a".repeat(64),
      commands: [],
      tasks: definitions,
      control_flow: {
        version: 1,
        loops: [],
        max_repairs: 0,
        edges: [
          {
            source: "develop",
            target: "test",
            port: "approved",
            feedback: false,
          },
        ],
      },
    },
    nodes: [{ ...definitions[0], state: "WAITING_INPUT" }],
  });
  const graph = nativeExecution(definitions, current);
  expect(graph.tasks[0].state).toBe("WAITING_INPUT");
  expect(graph.edges[0]).toEqual(
    expect.objectContaining({ label: "approved" }),
  );
});
test("a successful run does not imply the PR is merged", () => {
  const journey = nativeJourney(
    run({
      state: "SUCCEEDED",
      published: { branch: "feature", url: "http://gitea/branch", commit: "a" },
    }),
  );
  expect(journey.find((s) => s.id === "verify")?.state).toBe("done");
  expect(journey.find((s) => s.id === "handover")?.state).toBe("current");
});
test("the journey directs plan approval before execution and flags execution failure", () => {
  expect(
    nativeJourney(run({ state: "PLAN_READY", phase: "planning" })).find(
      (s) => s.id === "approval",
    )?.state,
  ).toBe("current");
  expect(
    nativeJourney(run({ state: "FAILED" })).find((s) => s.id === "execution")
      ?.state,
  ).toBe("attention");
});
test("timestamps always use Vietnam time", () =>
  expect(executionTime("2026-10-28T01:00:00Z")).toContain("08:00:00"));

test("finished planning agents cannot be counted as completed implementation tasks", () => {
  const journey = nativeJourney(run({
    phase: "planning", state: "PLAN_READY", plan: { tasks } as any,
    nodes: [
      { id: "P01", state: "DONE", title: "Analyze", depends_on: [] },
      { id: "P02", state: "DONE", title: "Plan", depends_on: [] },
    ],
  }));
  expect(journey.find((step) => step.id === "execution")).toEqual(
    expect.objectContaining({ state: "waiting", detail: `0/${tasks.length} task · chưa bắt đầu` }),
  );
});

test("runtime verification dependencies are preserved alongside planned branch labels", () => {
  const definitions = tasks.map((t) => ({ ...t, depends_on: [] }));
  const current = run({
    nodes: [
      { ...definitions[2], depends_on: ["SYS_VERIFY"], state: "RUNNING" },
    ],
  });
  expect(nativeExecution(definitions, current).edges).toContainEqual({
    source: "SYS_VERIFY",
    target: "review",
  });
});
