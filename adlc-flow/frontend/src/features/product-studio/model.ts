import { translateUi } from "@/i18n/ui";
import { VANGUARD_REQUEST, VANGUARD_SCENARIO, vanguardTasks } from "./vanguard";

export type StudioRole = "analyst" | "developer" | "tester" | "lead";
export type StudioPage = "request" | "workflow" | "plan" | "run" | "results";
export type RunStatus =
  | "idle"
  | "running"
  | "paused"
  | "waiting"
  | "review"
  | "completed";
export type TaskStatus = "queued" | "running" | "completed";
export type Scenario = "export" | "reset" | "insights" | "feature" | "vanguard";

export interface StudioTask {
  id: string;
  title: string;
  role: StudioRole | "memory";
  description: string;
  output: string;
  dependencies: string[];
  start: number;
  end: number;
}
export interface Criterion {
  id: string;
  label: string;
  included: boolean;
}
export interface ChangedFile {
  path: string;
  purpose: string;
  additions: string[];
}
export interface StudioPlan {
  id: string;
  title: string;
  requirement: string;
  scenario: Scenario;
  tasks: StudioTask[];
  criteria: Criterion[];
  scope: string[];
  files: ChangedFile[];
  checks: string[];
  question: { title: string; detail: string; options: string[] };
}
export interface TeamNote {
  id: number;
  at: number;
  text: string;
  role: StudioRole;
}
export interface StudioState {
  version: 1;
  role: StudioRole;
  page: StudioPage;
  request: string;
  plan: StudioPlan | null;
  generating: boolean;
  approved: boolean;
  approvedBy: StudioRole | null;
  run: {
    status: RunStatus;
    elapsed: number;
    answer: string | null;
    notes: TeamNote[];
    handoffApproved: boolean;
    handoffBy: StudioRole | null;
  };
}
export type StudioAction =
  | { type: "ROLE"; role: StudioRole }
  | { type: "REQUEST"; text: string }
  | { type: "GENERATE" }
  | { type: "GENERATED" }
  | { type: "PAGE"; page: StudioPage }
  | { type: "CRITERION"; id: string }
  | { type: "ADD_CRITERION"; text: string }
  | { type: "APPROVE_PLAN" }
  | { type: "START" }
  | { type: "TICK" }
  | { type: "PAUSE" }
  | { type: "RESUME" }
  | { type: "ANSWER"; answer: string }
  | { type: "NOTE"; text: string }
  | { type: "APPROVE_HANDOFF" }
  | { type: "RESET" };

export const ROLE_INFO: Record<
  StudioRole,
  { label: string; short: string; title: string; description: string }
> = {
  get analyst() {
    return {
      get label() {
        return translateUi("Business Analyst");
      },
      short: "BA",
      get title() {
        return translateUi("Keep the outcome in focus");
      },
      get description() {
        return translateUi(
          "Requirements, acceptance criteria, and decisions that need you.",
        );
      },
    };
  },
  get developer() {
    return {
      get label() {
        return translateUi("Developer");
      },
      short: "DEV",
      get title() {
        return translateUi("See how the change comes together");
      },
      get description() {
        return translateUi(
          "Implementation tasks, dependencies, and changes to review.",
        );
      },
    };
  },
  get tester() {
    return {
      get label() {
        return translateUi("Tester");
      },
      short: "QA",
      get title() {
        return translateUi("Follow the evidence");
      },
      get description() {
        return translateUi(
          "Test coverage, check results, and acceptance criteria.",
        );
      },
    };
  },
  get lead() {
    return {
      get label() {
        return translateUi("Project Lead");
      },
      short: "LEAD",
      get title() {
        return translateUi("Keep the team moving");
      },
      get description() {
        return translateUi("Team progress, decisions, and the final handoff.");
      },
    };
  },
};

export const REQUEST_EXAMPLES = [
  {
    get label() {
      return translateUi("Export orders to CSV");
    },
    get text() {
      return translateUi(
        "Add a CSV export to the orders dashboard. Administrators should be able to export orders for a selected date range. Keep the current filters, include order ID, customer, date and total, and show a clear message if no orders match.",
      );
    },
  },
  {
    get label() {
      return translateUi("Reset a password");
    },
    get text() {
      return translateUi(
        "Add a password reset flow. Users can request a reset link by email, set a new password, and see a clear confirmation. Links must expire after 30 minutes and the response must not reveal whether an email address exists.",
      );
    },
  },
  {
    get label() {
      return translateUi("Understand sales");
    },
    get text() {
      return translateUi(
        "Add a sales insights dashboard. Show revenue, order volume and average order value for a selected date range. Support comparison with the previous period and a clear empty state when there is no data.",
      );
    },
  },
  {
    get label() {
      return translateUi("Vanguard: pagination rule");
    },
    text: VANGUARD_REQUEST,
  },
] as const;

export const RUN_LENGTH = 58;
export const QUESTION_AT = 7;
export const REVIEW_AT = 53;
export const STORAGE_KEY = "pokedev.studio.v1";
const ROLES: StudioRole[] = ["analyst", "developer", "tester", "lead"];
export const canApprove = (role: StudioRole) =>
  role === "analyst" || role === "lead";

const emptyRun = (): StudioState["run"] => ({
  status: "idle",
  elapsed: 0,
  answer: null,
  notes: [],
  handoffApproved: false,
  handoffBy: null,
});
export function initialStudioState(role: StudioRole = "analyst"): StudioState {
  return {
    version: 1,
    role,
    page: "request",
    request: "",
    plan: null,
    generating: false,
    approved: false,
    approvedBy: null,
    run: emptyRun(),
  };
}

const SCENARIOS = {
  vanguard: VANGUARD_SCENARIO,
  get export() {
    return {
      get title() {
        return translateUi("Export orders to CSV");
      },
      work: ["Build the export service", "Add the dashboard export action"],
      criteria: [
        "Only administrators can export orders.",
        "The export respects the selected date range and filters.",
        "The CSV includes order ID, customer, date, and total.",
        "An empty result shows a clear message.",
      ],
      scope: [
        translateUi("Orders dashboard"),
        translateUi("Export service"),
        translateUi("CSV and access checks"),
      ],
      checks: [
        translateUi("Administrator access"),
        translateUi("Selected date range"),
        translateUi("Current dashboard filters"),
        translateUi("CSV headers and encoding"),
        translateUi("Quoted customer names"),
        translateUi("Empty result message"),
      ],
      files: [
        {
          path: "server/orders/export.py",
          purpose: translateUi("Filter orders and build the CSV response."),
          additions: [
            "def export_orders(orders, start, end, timezone):",
            "    rows = filter_orders(orders, start, end, timezone)",
            "    return to_csv(rows, fields=['id', 'customer', 'date', 'total'])",
          ],
        },
        {
          path: "web/orders/ExportOrdersButton.tsx",
          purpose: translateUi("Add an export action for administrators."),
          additions: [
            "export function ExportOrdersButton({ filters, isAdmin }) {",
            "  if (!isAdmin) return null;",
            "  return <button onClick={() => exportOrders(filters)}>Export CSV</button>;",
            "}",
          ],
        },
        {
          path: "tests/orders/export.test.ts",
          purpose: translateUi(
            "Cover access, filters, CSV format, and empty results.",
          ),
          additions: [
            'describe("Order export", () => {',
            '  it("keeps the selected filters");',
            '  it("requires administrator access");',
            '  it("handles an empty result");',
            "});",
          ],
        },
        {
          path: "docs/changes/orders-export.md",
          purpose: translateUi(
            "Document the export behaviour and review decisions.",
          ),
          additions: [
            "# Order export",
            "Administrators can download orders using the current date range and filters.",
            "Columns: order ID, customer, date, total.",
          ],
        },
      ],
      question: {
        get title() {
          return translateUi("Which timezone should the date filter use?");
        },
        get detail() {
          return translateUi(
            "The team needs one rule for orders near the start and end of a day.",
          );
        },
        options: [
          translateUi("Use the project's timezone"),
          translateUi("Use UTC"),
        ],
      },
    };
  },
  get reset() {
    return {
      get title() {
        return translateUi("Reset a password");
      },
      work: [
        "Build the reset-link service",
        "Create the password reset screens",
      ],
      criteria: [
        "A user can request a reset link by email.",
        "A reset link expires after 30 minutes.",
        "The response does not reveal whether an email exists.",
        "A successful reset shows a clear confirmation.",
      ],
      scope: [
        translateUi("Sign-in experience"),
        translateUi("Reset-link service"),
        translateUi("Security and expiry checks"),
      ],
      checks: [
        translateUi("Reset request response"),
        translateUi("30-minute link expiry"),
        translateUi("Single-use reset links"),
        translateUi("Unknown email privacy"),
        translateUi("Password validation"),
        translateUi("Successful reset confirmation"),
      ],
      files: [
        {
          path: "server/auth/password_reset.py",
          purpose: translateUi("Issue an expiring, single-use reset link."),
          additions: [
            "def request_reset(email):",
            "    token = create_single_use_token(email, expires_in=1800)",
            "    send_reset_link_if_account_exists(email, token)",
            '    return {"message": "Check your email for the next step."}',
          ],
        },
        {
          path: "web/auth/ResetPassword.tsx",
          purpose: translateUi(
            "Let users request a link and set a new password.",
          ),
          additions: [
            "export function ResetPassword() {",
            "  return <ResetForm onSubmit={submitNewPassword} />;",
            "}",
          ],
        },
        {
          path: "tests/auth/reset.test.ts",
          purpose: translateUi("Cover expiry, privacy, and the success path."),
          additions: [
            'describe("Password reset", () => {',
            '  it("expires the link after 30 minutes");',
            '  it("returns the same response for unknown email");',
            '  it("uses each link once");',
            "});",
          ],
        },
        {
          path: "docs/changes/password-reset.md",
          purpose: translateUi(
            "Record the reset-link behaviour and decisions.",
          ),
          additions: [
            "# Password reset",
            "Links expire after 30 minutes and can be used once.",
          ],
        },
      ],
      question: {
        get title() {
          return translateUi(
            "Where should users return after resetting their password?",
          );
        },
        get detail() {
          return translateUi(
            "The team needs to finish the success screen with a clear next step.",
          );
        },
        options: [
          translateUi("Return to sign in"),
          translateUi("Show confirmation first"),
        ],
      },
    };
  },
  get insights() {
    return {
      get title() {
        return translateUi("Understand sales at a glance");
      },
      work: [
        "Build the sales summary service",
        "Create the insights dashboard",
      ],
      criteria: [
        "Revenue, order volume, and average order value are visible.",
        "Every metric uses the selected date range.",
        "The previous period comparison uses the same duration.",
        "An empty range shows a clear empty state.",
      ],
      scope: [
        translateUi("Sales dashboard"),
        translateUi("Summary service"),
        translateUi("Period comparison checks"),
      ],
      checks: [
        translateUi("Revenue calculation"),
        translateUi("Order volume"),
        translateUi("Average order value"),
        translateUi("Selected date range"),
        translateUi("Previous period comparison"),
        translateUi("Empty range state"),
      ],
      files: [
        {
          path: "server/sales/summary.py",
          purpose: translateUi("Aggregate metrics and compare periods."),
          additions: [
            "def sales_summary(orders, period):",
            "    current = aggregate_orders(orders, period)",
            "    previous = aggregate_orders(orders, period.previous())",
            '    return {"current": current, "previous": previous}',
          ],
        },
        {
          path: "web/sales/SalesDashboard.tsx",
          purpose: translateUi("Present metrics and a date-range selector."),
          additions: [
            "export function SalesDashboard({ summary }) {",
            "  return <MetricCards data={summary} showComparison />;",
            "}",
          ],
        },
        {
          path: "tests/sales/summary.test.ts",
          purpose: translateUi(
            "Cover metric calculations and period boundaries.",
          ),
          additions: [
            'describe("Sales summary", () => {',
            '  it("calculates revenue for the selected range");',
            '  it("compares equal-length periods");',
            '  it("handles an empty range");',
            "});",
          ],
        },
        {
          path: "docs/changes/sales-insights.md",
          purpose: translateUi("Document the metrics and comparison rule."),
          additions: [
            "# Sales insights",
            "Compare revenue and orders with the previous period.",
          ],
        },
      ],
      question: {
        get title() {
          return translateUi(
            "How should the dashboard present monetary values?",
          );
        },
        get detail() {
          return translateUi(
            "The team needs a consistent display rule across the three metrics.",
          );
        },
        options: [
          translateUi("Use the project's currency"),
          translateUi("Show currency next to each value"),
        ],
      },
    };
  },
};

// This local deterministic proposal/runtime is the recording adapter.
// Keep its boundary separate from the UI so an API/event adapter can replace it.
export function createStudioPlan(requirement: string): StudioPlan {
  const trimmed = requirement.trim();
  const scenario: Scenario = /vanguard|list-paginated|r3xx/i.test(trimmed)
    ? "vanguard"
    : /csv|export|xuất/i.test(trimmed)
      ? "export"
      : /password|reset|mật khẩu/i.test(trimmed)
        ? "reset"
        : /sales|insights|revenue|doanh thu/i.test(trimmed)
          ? "insights"
          : "feature";
  const selected =
    scenario === "feature"
      ? {
          ...SCENARIOS.insights,
          title: trimmed.split(/[.!?\n]/)[0].slice(0, 72),
          work: ["Implement the feature logic", "Build the user experience"],
          criteria: [
            "The requested outcome is covered by the implementation.",
            "The main user path has clear feedback.",
            "Invalid inputs and empty results have clear states.",
            "Changes include checks and handoff notes.",
          ],
          scope: [
            translateUi("Requested feature"),
            translateUi("User experience"),
            translateUi("Checks and documentation"),
          ],
          checks: [
            translateUi("Main user path"),
            translateUi("Input validation"),
            translateUi("Access rules"),
            translateUi("Error feedback"),
            translateUi("Empty state"),
            translateUi("Acceptance review"),
          ],
          files: [
            {
              path: "server/features/feature.py",
              purpose: translateUi("Implement the requested feature."),
              additions: [
                "def run_feature(request):",
                "    return process_feature(request)",
              ],
            },
            {
              path: "web/features/FeaturePanel.tsx",
              purpose: translateUi("Present the feature and its feedback."),
              additions: [
                "export function FeaturePanel() {",
                "  return <FeatureForm onSubmit={runFeature} />;",
                "}",
              ],
            },
            {
              path: "tests/features/feature.test.ts",
              purpose: translateUi("Cover the main path and edge cases."),
              additions: [
                'describe("Requested feature", () => {',
                '  it("handles the main user path");',
                '  it("shows clear error feedback");',
                "});",
              ],
            },
            {
              path: "docs/changes/feature.md",
              purpose: translateUi("Record the requested outcome."),
              additions: ["# Feature handoff", trimmed],
            },
          ],
          question: {
            title: translateUi("Which environment should the team target?"),
            detail: translateUi(
              "The team will keep its changes within this environment.",
            ),
            options: [
              translateUi("Development environment"),
              translateUi("Staging environment"),
            ],
          },
        }
      : SCENARIOS[scenario];
  let hash = 0;
  for (const character of trimmed)
    hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  const definitions = [
    [
      "scope",
      "Confirm scope and criteria",
      "analyst",
      "Turn the request into a clear outcome and agreed acceptance criteria.",
      "Requirements brief",
      [],
      0,
      7,
    ],
    [
      "service",
      selected.work[0],
      "developer",
      "Implement the feature logic in a separate workspace.",
      "Service changes",
      ["scope"],
      7,
      23,
    ],
    [
      "interface",
      selected.work[1],
      "developer",
      "Build the user-facing path and its feedback states.",
      "Interface changes",
      ["scope"],
      7,
      27,
    ],
    [
      "tests",
      "Verify behaviour and edge cases",
      "tester",
      "Check the agreed behaviour and attach the results.",
      "Check report",
      ["service", "interface"],
      27,
      45,
    ],
    [
      "review",
      "Review the complete change",
      "developer",
      "Review scope, changes, and check evidence before handoff.",
      "Review summary",
      ["tests"],
      45,
      53,
    ],
    [
      "memory",
      "Save the project knowledge",
      "memory",
      "Keep the decisions and handoff notes for the next request.",
      "Project memory",
      ["review"],
      53,
      RUN_LENGTH,
    ],
  ] as const;
  return {
    id: "plan-" + hash.toString(16).padStart(8, "0"),
    title: selected.title || translateUi("Build the requested feature"),
    requirement: trimmed,
    scenario,
    tasks:
      scenario === "vanguard"
        ? vanguardTasks()
        : definitions.map(
            ([
              id,
              title,
              role,
              description,
              output,
              dependencies,
              start,
              end,
            ]) => ({
              id,
              title: translateUi(title),
              role,
              description: translateUi(description),
              output: translateUi(output),
              dependencies: [...dependencies],
              start,
              end,
            }),
          ),
    criteria: selected.criteria.map((label, index) => ({
      id: "criterion-" + index,
      label: translateUi(label),
      included: true,
    })),
    scope: [...selected.scope],
    files: selected.files.map((file) => ({
      ...file,
      additions: [...file.additions],
    })),
    checks: [...selected.checks],
    question: { ...selected.question, options: [...selected.question.options] },
  };
}

export function taskStatus(
  task: StudioTask,
  run: StudioState["run"],
): TaskStatus {
  if (run.status === "idle" || run.elapsed < task.start) return "queued";
  if (task.id === "memory" && !run.handoffApproved) return "queued";
  if (!run.answer && task.start >= QUESTION_AT) return "queued";
  return run.elapsed >= task.end ? "completed" : "running";
}
export function checkStatus(index: number, elapsed: number): TaskStatus {
  const at = 29 + index * 3;
  return elapsed >= at + 1 ? "completed" : elapsed >= at ? "running" : "queued";
}
export function pageAvailable(state: StudioState, page: StudioPage) {
  if (page === "request") return true;
  if (page === "workflow" || page === "plan")
    return !!state.plan && !state.generating;
  if (page === "run") return state.run.status !== "idle";
  return state.run.status === "completed";
}
export function studioReducer(
  state: StudioState,
  action: StudioAction,
): StudioState {
  switch (action.type) {
    case "ROLE":
      return ROLES.includes(action.role)
        ? { ...state, role: action.role }
        : state;
    case "REQUEST":
      return state.run.status === "idle"
        ? { ...state, request: action.text.slice(0, 1200) }
        : state;
    case "GENERATE":
      return state.request.trim().length < 12 || state.run.status !== "idle"
        ? state
        : {
            ...state,
            page: "workflow",
            plan: createStudioPlan(state.request),
            generating: true,
            approved: false,
            approvedBy: null,
            run: emptyRun(),
          };
    case "GENERATED":
      return { ...state, generating: false };
    case "PAGE":
      return pageAvailable(state, action.page)
        ? { ...state, page: action.page }
        : state;
    case "CRITERION":
      if (!state.plan || state.run.status !== "idle" || !canApprove(state.role))
        return state;
      return {
        ...state,
        approved: false,
        approvedBy: null,
        plan: {
          ...state.plan,
          criteria: state.plan.criteria.map((c) =>
            c.id === action.id ? { ...c, included: !c.included } : c,
          ),
        },
      };
    case "ADD_CRITERION": {
      const text = action.text.trim().slice(0, 180);
      if (
        !state.plan ||
        !text ||
        state.plan.criteria.length >= 8 ||
        state.run.status !== "idle" ||
        !canApprove(state.role)
      )
        return state;
      return {
        ...state,
        approved: false,
        approvedBy: null,
        plan: {
          ...state.plan,
          criteria: [
            ...state.plan.criteria,
            {
              id: "criterion-" + state.plan.criteria.length,
              label: text,
              included: true,
            },
          ],
        },
      };
    }
    case "APPROVE_PLAN":
      return state.plan &&
        state.plan.criteria.some((c) => c.included) &&
        canApprove(state.role) &&
        !state.generating &&
        state.run.status === "idle"
        ? { ...state, approved: true, approvedBy: state.role }
        : state;
    case "START":
      return state.plan && state.approved && state.run.status === "idle"
        ? { ...state, page: "run", run: { ...emptyRun(), status: "running" } }
        : state;
    case "TICK": {
      if (state.run.status !== "running") return state;
      const elapsed = Math.min(RUN_LENGTH, state.run.elapsed + 1);
      const status: RunStatus =
        elapsed >= QUESTION_AT && !state.run.answer
          ? "waiting"
          : elapsed >= REVIEW_AT && !state.run.handoffApproved
            ? "review"
            : elapsed >= RUN_LENGTH
              ? "completed"
              : "running";
      return { ...state, run: { ...state.run, elapsed, status } };
    }
    case "PAUSE":
      return state.run.status === "running"
        ? { ...state, run: { ...state.run, status: "paused" } }
        : state;
    case "RESUME":
      return state.run.status === "paused"
        ? { ...state, run: { ...state.run, status: "running" } }
        : state;
    case "ANSWER":
      return state.run.status === "waiting" &&
        state.plan?.question.options.includes(action.answer)
        ? {
            ...state,
            run: { ...state.run, answer: action.answer, status: "running" },
          }
        : state;
    case "NOTE": {
      const text = action.text.trim().slice(0, 500);
      if (
        !text ||
        state.run.status === "idle" ||
        state.run.status === "completed"
      )
        return state;
      return {
        ...state,
        run: {
          ...state.run,
          notes: [
            ...state.run.notes,
            {
              id: state.run.notes.length + 1,
              at: state.run.elapsed,
              text,
              role: state.role,
            },
          ],
        },
      };
    }
    case "APPROVE_HANDOFF":
      return state.run.status === "review" && canApprove(state.role)
        ? {
            ...state,
            run: {
              ...state.run,
              status: "running",
              handoffApproved: true,
              handoffBy: state.role,
            },
          }
        : state;
    case "RESET":
      return initialStudioState(state.role);
    default:
      return state;
  }
}

export function restoreStudioState(raw: string | null): StudioState {
  if (!raw) return initialStudioState();
  try {
    const value = JSON.parse(raw) as StudioState;
    if (
      value.version !== 1 ||
      !ROLES.includes(value.role) ||
      typeof value.request !== "string" ||
      !["request", "workflow", "plan", "run", "results"].includes(value.page) ||
      !value.run ||
      !["idle", "running", "paused", "waiting", "review", "completed"].includes(
        value.run.status,
      ) ||
      !Number.isInteger(value.run.elapsed) ||
      value.run.elapsed < 0 ||
      value.run.elapsed > RUN_LENGTH ||
      !Array.isArray(value.run.notes) ||
      !value.run.notes.every(
        (note) =>
          typeof note.text === "string" &&
          note.text.length <= 500 &&
          ROLES.includes(note.role) &&
          Number.isInteger(note.id) &&
          Number.isInteger(note.at) &&
          note.at >= 0 &&
          note.at <= RUN_LENGTH,
      )
    )
      return initialStudioState();
    // Reconstruct the known schema rather than trusting arbitrary stored plan fields.
    if (
      value.plan &&
      (typeof value.plan.requirement !== "string" ||
        value.plan.requirement.trim().length < 12 ||
        value.plan.requirement.length > 1200)
    )
      return initialStudioState();
    const plan = value.plan ? createStudioPlan(value.plan.requirement) : null;
    if (
      plan &&
      Array.isArray(value.plan?.criteria) &&
      value.plan.criteria.every(
        (c) =>
          typeof c.id === "string" &&
          typeof c.label === "string" &&
          c.label.length <= 180 &&
          typeof c.included === "boolean",
      )
    ) {
      plan.criteria = value.plan.criteria.slice(0, 8);
    }
    const approved =
      !!value.approved &&
      canApprove(value.approvedBy!) &&
      !!plan?.criteria.some((c) => c.included);
    const run = { ...emptyRun(), ...value.run };
    if (run.status !== "idle" && !approved)
      return initialStudioState(value.role);
    if (run.answer !== null && !plan?.question.options.includes(run.answer))
      return initialStudioState(value.role);
    if (
      run.handoffApproved &&
      (!canApprove(run.handoffBy!) || run.elapsed < REVIEW_AT)
    )
      return initialStudioState(value.role);
    if (
      run.status === "completed" &&
      (!run.handoffApproved || run.elapsed !== RUN_LENGTH)
    )
      return initialStudioState(value.role);
    if (run.elapsed >= QUESTION_AT && !run.answer) {
      run.status = "waiting";
      run.elapsed = QUESTION_AT;
    } else if (run.elapsed >= REVIEW_AT && !run.handoffApproved) {
      run.status = "review";
      run.elapsed = REVIEW_AT;
    }
    if (run.status === "running") run.status = "paused";
    if (!plan && run.status !== "idle") return initialStudioState(value.role);
    const restored: StudioState = {
      ...initialStudioState(value.role),
      request: value.request.slice(0, 1200),
      plan,
      approved,
      approvedBy: approved ? value.approvedBy : null,
      run,
    };
    restored.page = pageAvailable(restored, value.page)
      ? value.page
      : "request";
    return restored;
  } catch {
    return initialStudioState();
  }
}

export interface StudioEvent {
  id: string;
  at: number;
  role: StudioRole | "memory" | "team";
  title: string;
  detail: string;
}
export function runEvents(state: StudioState): StudioEvent[] {
  if (!state.plan || state.run.status === "idle") return [];
  const { plan, run } = state;
  const scheduled: StudioEvent[] = [
    {
      id: "start",
      at: 0,
      role: "team",
      title: translateUi("The approved plan is running"),
      detail: translateUi(
        "Project context loaded. Each agent has its own task scope.",
      ),
    },
    {
      id: "scope",
      at: 3,
      role: "analyst",
      title: translateUi("Acceptance criteria mapped"),
      detail:
        plan.criteria.filter((c) => c.included).length +
        " criteria linked to the team plan.",
    },
    {
      id: "question",
      at: 7,
      role: "analyst",
      title: translateUi("A decision needs your input"),
      detail: plan.question.title,
    },
    {
      id: "service",
      at: 8,
      role: "developer",
      title: plan.tasks[1].title,
      detail:
        plan.scenario === "vanguard"
          ? "The rule reads the agreed IR; changes stay in the rule workspace."
          : "Service agent is working in its assigned workspace.",
    },
    {
      id: "interface",
      at: 10,
      role: plan.tasks[2].role,
      title: plan.tasks[2].title,
      detail:
        plan.scenario === "vanguard"
          ? "Tester prepares the expected findings while Developer implements the rule."
          : "Interface work is running alongside the service task.",
    },
    {
      id: "service-progress",
      at: 16,
      role: "developer",
      title:
        plan.scenario === "vanguard"
          ? "Pagination rule is taking shape"
          : "Feature logic is taking shape",
      detail: plan.files[0].path,
    },
    {
      id: "service-complete",
      at: 23,
      role: "developer",
      title:
        plan.scenario === "vanguard"
          ? "The rule candidate is ready"
          : "Service changes are ready",
      detail: translateUi(
        "The changes are available for the integration checks.",
      ),
    },
    {
      id: "interface-complete",
      at: 27,
      role: plan.tasks[2].role,
      title:
        plan.scenario === "vanguard"
          ? "The reviewed corpus is ready"
          : "Interface changes are ready",
      detail:
        plan.scenario === "vanguard"
          ? "Rule candidate and corpus converge on the same policy for verification."
          : "Both implementation branches are ready for Testing.",
    },
    ...plan.checks.map((title, index) => ({
      id: "check-" + index,
      at: 30 + index * 3,
      role: "tester" as const,
      title: title + " · passed",
      detail: translateUi("The check result is attached to the handoff."),
    })),
    {
      id: "review",
      at: 46,
      role: "developer",
      title: translateUi("Reviewing the complete change"),
      detail: translateUi(
        "Comparing the changes with the agreed scope and criteria.",
      ),
    },
    {
      id: "handoff",
      at: 53,
      role: "team",
      title: translateUi("The handoff is ready for approval"),
      detail:
        plan.files.length +
        " changed files, " +
        plan.checks.length +
        " checks, and a review summary.",
    },
    {
      id: "memory",
      at: 55,
      role: "memory",
      title: translateUi("Saving decisions for the next request"),
      detail: translateUi(
        "The requirement, review decision, and team notes stay with the project.",
      ),
    },
    {
      id: "done",
      at: RUN_LENGTH,
      role: "team",
      title: translateUi("The work is ready to hand over"),
      detail: translateUi(
        "Open Results to inspect the changes, checks, and project memory.",
      ),
    },
  ];
  const events = scheduled.filter((e) => e.at <= run.elapsed);
  if (run.answer)
    events.push({
      id: "answer",
      at: QUESTION_AT,
      role: "analyst",
      title: translateUi("Your decision was shared with the team"),
      detail: run.answer,
    });
  if (run.handoffApproved)
    events.push({
      id: "approved",
      at: REVIEW_AT,
      role: run.handoffBy!,
      title: translateUi("Handoff approved"),
      detail: translateUi("Finishing the project memory update."),
    });
  for (const note of run.notes)
    events.push({
      id: "note-" + note.id,
      at: note.at,
      role: note.role,
      title: translateUi("Guidance shared with the team"),
      detail: note.text,
    });
  return events
    .map((event, index) => ({ event, index }))
    .sort((a, b) => b.event.at - a.event.at || b.index - a.index)
    .map(({ event }) => event);
}
export function formatElapsed(seconds: number) {
  return (
    Math.floor(seconds / 60)
      .toString()
      .padStart(2, "0") +
    ":" +
    (seconds % 60).toString().padStart(2, "0")
  );
}
export function createPatch(plan: StudioPlan) {
  return plan.files
    .map((file) =>
      [
        "diff --git a/" + file.path + " b/" + file.path,
        "new file mode 100644",
        "--- /dev/null",
        "+++ b/" + file.path,
        "@@ -0,0 +1," + file.additions.length + " @@",
        ...file.additions.map((line) => "+" + line),
        "",
      ].join("\n"),
    )
    .join("\n");
}
