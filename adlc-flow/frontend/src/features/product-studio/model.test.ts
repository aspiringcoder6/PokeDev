import {
  createPatch,
  createStudioPlan,
  initialStudioState,
  pageAvailable,
  REQUEST_EXAMPLES,
  restoreStudioState,
  runEvents,
  studioReducer,
  taskStatus,
} from "./model";
import type { StudioState } from "./model";
import {
  createVanguardReport,
  VANGUARD_OPTIONS,
  VANGUARD_REQUEST,
} from "./vanguard";

function proposed(): StudioState {
  return studioReducer(
    studioReducer(initialStudioState(), {
      type: "REQUEST",
      text: REQUEST_EXAMPLES[0].text,
    }),
    { type: "GENERATE" },
  );
}
function approved(): StudioState {
  return studioReducer(studioReducer(proposed(), { type: "GENERATED" }), {
    type: "APPROVE_PLAN",
  });
}
function advance(state: StudioState, ticks: number): StudioState {
  for (let i = 0; i < ticks; i++)
    state = studioReducer(state, { type: "TICK" });
  return state;
}

test("the same request creates the same plan and each supported request has its own outcome", () => {
  const plans = REQUEST_EXAMPLES.map((example) =>
    createStudioPlan(example.text),
  );
  expect(plans[0]).toEqual(createStudioPlan(REQUEST_EXAMPLES[0].text));
  expect(plans.map((plan) => plan.scenario)).toEqual([
    "export",
    "reset",
    "insights",
    "vanguard",
  ]);
  expect(new Set(plans.map((plan) => plan.id)).size).toBe(4);
  expect(plans[1].checks).toContain("30-minute link expiry");
  expect(plans[2].files[0].path).toContain("sales");
  const custom = createStudioPlan("Let members bookmark favourite articles.");
  expect(custom.scenario).toBe("feature");
  expect(custom.title).toBe("Let members bookmark favourite articles");
  expect(custom.requirement).toBe("Let members bookmark favourite articles.");
  const dashboard = createStudioPlan(
    "Add dark mode to the activity dashboard.",
  );
  expect(dashboard.scenario).toBe("feature");
  expect(dashboard.title).toBe("Add dark mode to the activity dashboard");
});

test("Vanguard preserves the pilot scope, independent corpus branch and decision through a refresh", () => {
  let state = studioReducer(initialStudioState(), {
    type: "REQUEST",
    text: VANGUARD_REQUEST,
  });
  state = studioReducer(state, { type: "GENERATE" });
  expect(state.plan!.scenario).toBe("vanguard");
  expect(state.plan!.scope[0]).toContain("frozen Java/Spring IR");
  expect(state.plan!.tasks[2].role).toBe("tester");
  expect(state.plan!.tasks[3].dependencies).toEqual(["service", "interface"]);
  state = studioReducer(state, { type: "GENERATED" });
  state = studioReducer(state, { type: "APPROVE_PLAN" });
  state = advance(studioReducer(state, { type: "START" }), 100);
  expect(state.run.status).toBe("waiting");
  state = studioReducer(state, { type: "ANSWER", answer: VANGUARD_OPTIONS[1] });
  const restored = restoreStudioState(JSON.stringify(state));
  expect(restored.run.answer).toBe(VANGUARD_OPTIONS[1]);
  expect(restored.plan!.scenario).toBe("vanguard");
  expect(
    runEvents(advance(state, 3)).find((e) => e.id === "interface")!.role,
  ).toBe("tester");
  expect(createPatch(restored.plan!)).toContain(
    "internal/rules/pagination/list_paginated.go",
  );
  expect(createPatch(restored.plan!)).not.toContain("server/orders");
});

test("Vanguard report reflects the selected pagination policy and retains its recording origin", () => {
  const standard = createVanguardReport(VANGUARD_OPTIONS[0]);
  const strict = createVanguardReport(VANGUARD_OPTIONS[1]);
  expect(
    standard.cases.find((c) => c.id === "explicit-page-size")!.finding,
  ).toBe("No finding");
  expect(strict.cases.find((c) => c.id === "explicit-page-size")!.finding).toBe(
    "WARN",
  );
  expect(standard.findings).toHaveLength(2);
  expect(strict.findings).toHaveLength(3);
  expect(standard.origin).toBe("studio-recording-fixtures");
  expect(standard.cases.find((c) => c.id === "source-location")!.source).toBe(
    "ShipmentController.java:22",
  );
  expect(standard.cases.find((c) => c.id === "post-command")!.finding).toBe(
    "Out of scope",
  );
});

test("execution and results are gated by a completed proposal and explicit approval", () => {
  let state = proposed();
  expect(studioReducer(state, { type: "APPROVE_PLAN" }).approved).toBe(false);
  expect(studioReducer(state, { type: "START" }).run.status).toBe("idle");
  expect(pageAvailable(state, "results")).toBe(false);
  state = studioReducer(state, { type: "GENERATED" });
  state = studioReducer(state, { type: "ROLE", role: "tester" });
  expect(studioReducer(state, { type: "APPROVE_PLAN" }).approved).toBe(false);
  state = studioReducer(state, { type: "ROLE", role: "analyst" });
  state = studioReducer(state, { type: "APPROVE_PLAN" });
  expect(studioReducer(state, { type: "START" }).run.status).toBe("running");
});

test("changing acceptance criteria invalidates approval and a plan cannot have zero criteria", () => {
  let state = approved();
  state = studioReducer(state, {
    type: "ADD_CRITERION",
    text: "Include a release note.",
  });
  expect(state.approved).toBe(false);
  expect(state.plan!.criteria.at(-1)!.label).toBe("Include a release note.");
  for (const criterion of state.plan!.criteria)
    state = studioReducer(state, { type: "CRITERION", id: criterion.id });
  expect(studioReducer(state, { type: "APPROVE_PLAN" }).approved).toBe(false);
});

test("parallel work starts after the decision and final completion waits for owner approval", () => {
  let state = advance(studioReducer(approved(), { type: "START" }), 100);
  expect(state.run.status).toBe("waiting");
  expect(state.run.elapsed).toBe(7);
  expect(taskStatus(state.plan!.tasks[1], state.run)).toBe("queued");
  state = studioReducer(state, {
    type: "ANSWER",
    answer: state.plan!.question.options[0],
  });
  expect(taskStatus(state.plan!.tasks[1], state.run)).toBe("running");
  expect(taskStatus(state.plan!.tasks[2], state.run)).toBe("running");
  state = advance(state, 100);
  expect(state.run.status).toBe("review");
  expect(state.run.elapsed).toBe(53);
  expect(taskStatus(state.plan!.tasks[5], state.run)).toBe("queued");
  const developer = studioReducer(state, { type: "ROLE", role: "developer" });
  expect(studioReducer(developer, { type: "APPROVE_HANDOFF" }).run.status).toBe(
    "review",
  );
  state = advance(studioReducer(state, { type: "APPROVE_HANDOFF" }), 100);
  expect(state.run.status).toBe("completed");
  expect(state.run.elapsed).toBe(58);
  expect(pageAvailable(state, "results")).toBe(true);
  expect(
    state.plan!.tasks.every(
      (task) => taskStatus(task, state.run) === "completed",
    ),
  ).toBe(true);
});

test("pause freezes progress and role switching preserves the run and its guidance", () => {
  let state = studioReducer(approved(), { type: "START" });
  state = advance(state, 3);
  state = studioReducer(state, {
    type: "NOTE",
    text: "Keep the release note concise.",
  });
  state = studioReducer(state, { type: "PAUSE" });
  state = advance(state, 20);
  expect(state.run.elapsed).toBe(3);
  const run = state.run;
  state = studioReducer(state, { type: "ROLE", role: "developer" });
  expect(state.run).toEqual(run);
  expect(runEvents(state).find((event) => event.id === "note-1")!.detail).toBe(
    "Keep the release note concise.",
  );
  state = advance(studioReducer(state, { type: "RESUME" }), 1);
  expect(state.run.elapsed).toBe(4);
  expect(state.run.notes).toHaveLength(1);
});

test("refresh restores a running session as paused and retains pending decisions", () => {
  const running = advance(studioReducer(approved(), { type: "START" }), 3);
  const restored = restoreStudioState(JSON.stringify(running));
  expect(restored.run.status).toBe("paused");
  expect(restored.run.elapsed).toBe(3);
  expect(restored.plan).toEqual(running.plan);
  const waiting = advance(running, 4);
  expect(restoreStudioState(JSON.stringify(waiting)).run.status).toBe(
    "waiting",
  );
});

test("invalid saved state is discarded instead of breaking the workspace", () => {
  expect(restoreStudioState("{broken")).toEqual(initialStudioState());
  expect(
    restoreStudioState(JSON.stringify({ ...approved(), page: "unknown" })),
  ).toEqual(initialStudioState());
  const invalid = studioReducer(approved(), { type: "START" });
  invalid.run.notes = [
    { id: 1, at: 2, text: "Note", role: "invalid" as never },
  ];
  expect(restoreStudioState(JSON.stringify(invalid))).toEqual(
    initialStudioState(),
  );
});

test("reset clears the work but retains the chosen role, and downloads use the current plan", () => {
  const state = studioReducer(approved(), { type: "ROLE", role: "developer" });
  const reset = studioReducer(state, { type: "RESET" });
  expect(reset).toEqual(initialStudioState("developer"));
  expect(createPatch(state.plan!)).toContain("+++ b/server/orders/export.py");
  const resetPlan = createStudioPlan(REQUEST_EXAMPLES[1].text);
  expect(createPatch(resetPlan)).toContain(
    "+++ b/server/auth/password_reset.py",
  );
  expect(createPatch(resetPlan)).not.toContain("server/orders");
});
