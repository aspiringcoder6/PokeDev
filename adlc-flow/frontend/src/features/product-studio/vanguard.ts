import { translateUi } from "@/i18n/ui";
import type { ChangedFile, StudioTask } from "./model";

// Recording data for one reviewed slice of the Vanguard factory, not a live
// Vanguard scan. Keep the source briefs and execution boundary in the runbook.
export const VANGUARD_REQUEST =
  "Xây một lát cắt của Vanguard: rule list-paginated để phát hiện API GET trả danh sách nhưng thiếu phân trang trong Java/Spring. Rule chỉ đọc IR ApiSurface đã chốt, trả cảnh báo WARN kèm file và dòng nguồn. Đề xuất nhiệm vụ cho Developer và Tester chạy song song, kiểm tra bộ good/bad fixtures, review bản vá và chờ người duyệt bàn giao. Không sửa adapter Java, không merge main hoặc phát hành. Lưu quyết định và các giới hạn để dùng ở vòng tiếp theo.";

export const VANGUARD_OPTIONS = [
  "Accept Pageable or explicit page + size",
  "Require Spring Pageable only",
] as const;

export const VANGUARD_SCENARIO = {
  get title() {
    return translateUi("Vanguard · Pagination rule pilot");
  },
  get work() {
    return [
      translateUi("Implement the pagination rule"),
      translateUi("Prepare the good/bad corpus"),
    ];
  },
  get criteria() {
    return [
      translateUi("An unpaginated GET collection produces a WARN finding."),
      translateUi("Pagination follows the policy confirmed during the run."),
      translateUi("POST and single-object responses stay out of scope."),
      translateUi("Each finding keeps the original source file and line."),
      translateUi(
        "Review the patch and corpus before handoff; no merge or release.",
      ),
    ];
  },
  get scope() {
    return [
      translateUi("One list-paginated rule on frozen Java/Spring IR"),
      translateUi("Six versioned good/bad fixture cases"),
      translateUi("Rule, corpus, check report and documentation"),
    ];
  },
  get checks() {
    return [
      translateUi("Unpaginated GET collection → WARN"),
      translateUi("Spring Pageable accepted"),
      translateUi("Explicit page + size follows the chosen policy"),
      translateUi("POST endpoint excluded"),
      translateUi("Single-object GET excluded"),
      translateUi("Finding preserves source file and line"),
    ];
  },
  get files() {
    return [
      {
        path: "internal/rules/pagination/list_paginated.go",
        purpose: translateUi(
          "Evaluate the frozen IR without reopening Java source files.",
        ),
        additions: [
          "package pagination",
          "",
          "// The run pins this policy before evaluating any candidate.",
          "func Check(m ir.Method, policy PaginationPolicy) []Finding {",
          '    if m.Verb != "GET" || !m.ReturnsCollection { return nil }',
          "    paged := m.HasPageable || (policy.AllowExplicit && m.HasPageAndSize)",
          "    if paged { return nil }",
          '    return []Finding{{Rule: "R3xx-01", Severity: "WARN",',
          '        Message: "List endpoint needs pagination", Location: m.Location}}',
          "}",
        ],
      },
      {
        path: "testdata/pagination/cases.json",
        purpose: translateUi(
          "Keep positive, negative and out-of-scope cases independent of the rule.",
        ),
        additions: [
          "[",
          '  {"case": "missing-pagination", "method": "GET", "collection": true},',
          '  {"case": "spring-pageable", "method": "GET", "pageable": true},',
          '  {"case": "explicit-page-size", "method": "GET", "page_and_size": true},',
          '  {"case": "post-command", "method": "POST"},',
          '  {"case": "single-resource", "method": "GET", "collection": false},',
          '  {"case": "source-location", "file": "ShipmentController.java", "line": 22}',
          "]",
        ],
      },
      {
        path: "internal/rules/pagination/list_paginated_test.go",
        purpose: translateUi(
          "Compare findings with the reviewed corpus and selected policy.",
        ),
        additions: [
          "func TestListPaginated(t *testing.T) {",
          "    for _, tc := range LoadReviewedCorpus() {",
          "        got := Check(tc.Method, tc.FrozenPolicy)",
          "        AssertFindings(t, tc.Expected, got)",
          "    }",
          "}",
        ],
      },
      {
        path: "docs/rules/list-paginated.md",
        purpose: translateUi(
          "Document the rule boundary, source provenance and review decision.",
        ),
        additions: [
          "# list-paginated",
          "GET collection without the approved pagination convention produces WARN.",
          "Read ApiSurface IR only; preserve its source location.",
          "Do not change the Java adapter, merge main, or publish a release.",
          "Missing adapter metadata becomes a scoped task for the next Product Loop.",
        ],
      },
    ] satisfies ChangedFile[];
  },
  get question() {
    return {
      get title() {
        return translateUi(
          "Which pagination convention should this pilot accept?",
        );
      },
      get detail() {
        return translateUi(
          "Confirm the policy before the rule and corpus proceed. The Vanguard brief accepts Pageable or explicit page + size; the stricter option is a separate pilot policy.",
        );
      },
      options: [...VANGUARD_OPTIONS],
    };
  },
};

export function vanguardTasks(): StudioTask[] {
  return [
    {
      id: "scope",
      title: translateUi("Freeze the rule scope and criteria"),
      role: "analyst",
      description: translateUi(
        "Confirm one rule, the IR contract and acceptance criteria before implementation.",
      ),
      output: translateUi("Approved rule brief"),
      dependencies: [],
      start: 0,
      end: 7,
    },
    {
      id: "service",
      title: VANGUARD_SCENARIO.work[0],
      role: "developer",
      description: translateUi(
        "Read frozen ApiSurface IR and produce WARN findings with their source locations.",
      ),
      output: translateUi("Rule candidate"),
      dependencies: ["scope"],
      start: 7,
      end: 23,
    },
    {
      id: "interface",
      title: VANGUARD_SCENARIO.work[1],
      role: "tester",
      description: translateUi(
        "Prepare labelled inputs and expected findings independently of the implementation.",
      ),
      output: translateUi("Reviewed fixture corpus"),
      dependencies: ["scope"],
      start: 7,
      end: 27,
    },
    {
      id: "tests",
      title: translateUi("Compare the candidate with the corpus"),
      role: "tester",
      description: translateUi(
        "Evaluate the same candidate against the approved policy and expected findings.",
      ),
      output: translateUi("Candidate check report"),
      dependencies: ["service", "interface"],
      start: 27,
      end: 45,
    },
    {
      id: "review",
      title: translateUi("Review rule, evidence and scope"),
      role: "developer",
      description: translateUi(
        "Check the patch, source locations and limitations before asking for handoff approval.",
      ),
      output: translateUi("Review and handoff summary"),
      dependencies: ["tests"],
      start: 45,
      end: 53,
    },
    {
      id: "memory",
      title: translateUi("Save the decision and next-cycle task"),
      role: "memory",
      description: translateUi(
        "Keep the accepted pagination policy and the adapter follow-up for the next cycle.",
      ),
      output: translateUi("Project knowledge and follow-up"),
      dependencies: ["review"],
      start: 53,
      end: 58,
    },
  ];
}

export function createVanguardReport(answer: string | null) {
  const explicitAccepted = answer !== VANGUARD_OPTIONS[1];
  const cases = [
    {
      id: "missing-pagination",
      endpoint: "GET /orders",
      expectation: "WARN",
      finding: "WARN",
      source: "OrderController.java:24",
    },
    {
      id: "spring-pageable",
      endpoint: "GET /customers",
      expectation: "No finding",
      finding: "No finding",
      source: "CustomerController.java:31",
    },
    {
      id: "explicit-page-size",
      endpoint: "GET /products",
      expectation: explicitAccepted ? "No finding" : "WARN",
      finding: explicitAccepted ? "No finding" : "WARN",
      source: "ProductController.java:18",
    },
    {
      id: "post-command",
      endpoint: "POST /orders",
      expectation: "Out of scope",
      finding: "Out of scope",
      source: "OrderController.java:48",
    },
    {
      id: "single-resource",
      endpoint: "GET /orders/{id}",
      expectation: "Out of scope",
      finding: "Out of scope",
      source: "OrderController.java:60",
    },
    {
      id: "source-location",
      endpoint: "GET /shipments",
      expectation: "WARN + file:line",
      finding: "WARN + file:line",
      source: "ShipmentController.java:22",
    },
  ];
  return {
    project: "Vanguard",
    rule: "R3xx-01 · list-paginated",
    policy: answer || VANGUARD_OPTIONS[0],
    // These results are recording fixtures, not reports minted by a Go runner.
    origin: "studio-recording-fixtures",
    cases,
    findings: cases.filter((item) => item.finding.startsWith("WARN")),
    followUp:
      "Extend the Spring adapter metadata in a separately reviewed task; this pilot does not change it.",
  };
}
