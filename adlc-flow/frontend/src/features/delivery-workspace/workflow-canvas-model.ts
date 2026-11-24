import type {
  LiveRun,
  LiveTask,
  WorkflowGraph,
  WorkflowEdge,
} from "@/controllers/API/live-workflows";

export const controlKinds = {
  condition: {
    name: "Điều kiện",
    description: "Chọn nhánh theo kết quả",
    color: "amber",
  },
  verify: {
    name: "Kiểm chứng",
    description: "Chạy bộ kiểm thử đã khóa",
    color: "violet",
  },
  gate: {
    name: "Cổng duyệt",
    description: "Người hoặc Agent duyệt kết quả",
    color: "blue",
  },
};
export const portLabels: Record<string, string> = {
  done: "Hoàn tất",
  match: "Đúng",
  no_match: "Không khớp",
  approved: "Đã duyệt",
  changes_requested: "Yêu cầu sửa",
};
export function outputPorts(
  task: LiveTask,
): NonNullable<WorkflowEdge["port"]>[] {
  return task.control?.type === "condition"
    ? ["match", "no_match"]
    : task.control?.type === "gate"
      ? ["approved", "changes_requested"]
      : ["done"];
}

export const taskKinds = {
  implement: {
    name: "Developer",
    description: "Xây dựng & chỉnh sửa source",
    color: "blue",
  },
  test: {
    name: "Tester",
    description: "Viết kiểm thử độc lập",
    color: "violet",
  },
  review: {
    name: "Reviewer",
    description: "Đối chiếu kết quả & tiêu chí",
    color: "amber",
  },
};

export function graphFromPlan(
  plan: NonNullable<LiveRun["plan"]>,
): WorkflowGraph {
  const ranks: Record<string, number> = {};
  for (let i = 0; i < plan.tasks.length; i++) {
    for (const task of plan.tasks) {
      ranks[task.id] = Math.min(
        plan.tasks.length,
        task.depends_on.length
          ? 1 + Math.max(...task.depends_on.map((id) => ranks[id] ?? 0))
          : 0,
      );
    }
  }
  const counts: Record<number, number> = {};
  return {
    version: plan.control_flow ? 2 : 1,
    title: plan.title,
    summary: plan.summary,
    nodes: plan.tasks.map((task) => {
      const rank = ranks[task.id];
      const row = counts[rank] ?? 0;
      counts[rank] = row + 1;
      return {
        id: task.id,
        task: structuredClone(task),
        position: { x: rank * 290 + 40, y: row * 155 + 70 },
      };
    }),
    edges: plan.control_flow
      ? structuredClone(plan.control_flow.edges)
      : plan.tasks.flatMap((task) =>
          task.depends_on.map((source) => ({ source, target: task.id })),
        ),
    commands: structuredClone(plan.commands || []),
    preview: structuredClone(
      (plan as { preview?: WorkflowGraph["preview"] }).preview ?? null,
    ),
    browser_checks: structuredClone(
      (plan as { browser_checks?: WorkflowGraph["browser_checks"] })
        .browser_checks || [],
    ),
  };
}

export function starterGraph(): WorkflowGraph {
  return graphFromPlan({
    title: "Workflow của project",
    summary: "Phát triển, kiểm thử độc lập và review theo yêu cầu.",
    digest: "",
    tasks: [
      newTask("DEV", "implement"),
      newTask("TEST", "test"),
      { ...newTask("REVIEW", "review"), depends_on: ["DEV", "TEST"] },
    ],
    commands: [
      {
        label: "Unit tests",
        argv: ["python", "-m", "unittest", "discover", "-s", "tests", "-v"],
      },
    ],
  });
}

export function newTask(id: string, kind: string): LiveTask {
  if (kind in controlKinds)
    return {
      ...newTask(id, "review"),
      title:
        kind === "condition"
          ? "Chọn nhánh theo kết quả kiểm thử"
          : kind === "verify"
            ? "Kiểm chứng source bằng bộ test đã khóa"
            : "Duyệt kết quả trước khi tiếp tục",
      control:
        kind === "condition"
          ? { type: "condition", predicate: "verification_passed" }
          : kind === "verify"
            ? { type: "verify" }
            : { type: "gate", reviewer: "human", max_rounds: 0 },
    };
  return {
    id,
    kind,
    title:
      kind === "implement"
        ? "Thực hiện thay đổi theo yêu cầu"
        : kind === "test"
          ? "Viết kiểm thử độc lập theo tiêu chí"
          : "Review source và kết quả kiểm chứng",
    depends_on: [],
    write_paths: [],
    steps: [
      kind === "review"
        ? "Đối chiếu diff, spec và kết quả kiểm chứng"
        : kind === "test"
          ? "Viết kiểm thử độc lập trong các file được chỉ định"
          : "Đọc source và thực hiện thay đổi trong phạm vi được chỉ định",
    ],
    acceptance: ["Đáp ứng tiêu chí nghiệm thu của yêu cầu"],
  };
}

export function connectionIssue(
  graph: WorkflowGraph,
  source: string,
  target: string,
  port: WorkflowEdge["port"] = "done",
): string | null {
  if (source === target) return "Task không thể phụ thuộc chính nó.";
  if (
    !graph.nodes.some((n) => n.id === source) ||
    !graph.nodes.some((n) => n.id === target)
  )
    return "Chọn hai task trên canvas.";
  if (
    !outputPorts(graph.nodes.find((n) => n.id === source)!.task).includes(port)
  )
    return "Chọn nhánh đầu ra của node.";
  if (
    graph.edges.some(
      (e) =>
        e.source === source &&
        e.target === target &&
        (e.port || "done") === port,
    )
  )
    return "Hai task đã được kết nối.";
  if (port === "changes_requested") {
    const task = graph.nodes.find((n) => n.id === source)!.task;
    if (
      task.control?.type !== "gate" ||
      task.control.max_rounds < 1 ||
      graph.nodes.find((n) => n.id === target)?.task.kind !== "implement"
    )
      return "Đặt 1–3 vòng sửa rồi nối Yêu cầu sửa về Developer phía trước.";
    if (graph.edges.some((e) => e.source === source && e.feedback))
      return "Cổng duyệt đã có một đường quay lại sửa.";
    const pending = [target],
      seen = new Set<string>();
    while (pending.length) {
      const id = pending.pop()!;
      if (id === source) return null;
      if (seen.has(id)) continue;
      seen.add(id);
      pending.push(
        ...graph.edges
          .filter((e) => e.source === id && !e.feedback)
          .map((e) => e.target),
      );
    }
    return "Đường sửa phải quay về Developer ở phía trước cổng duyệt.";
  }
  const pending = [target],
    seen = new Set<string>();
  while (pending.length) {
    const id = pending.pop()!;
    if (id === source) return "Kết nối này tạo vòng lặp phụ thuộc.";
    if (seen.has(id)) continue;
    seen.add(id);
    pending.push(
      ...graph.edges
        .filter((e) => e.source === id && !e.feedback)
        .map((e) => e.target),
    );
  }
  return null;
}

export function controlledStarterGraph(): WorkflowGraph {
  const graph = starterGraph();
  const verify = newTask("VERIFY", "verify"),
    condition = newTask("CONDITION", "condition"),
    gate = newTask("GATE", "gate");
  gate.control = { type: "gate", reviewer: "human", max_rounds: 2 };
  graph.version = 2;
  graph.title = "Workflow có điều kiện và duyệt kết quả";
  graph.summary =
    "Developer và Tester độc lập → kiểm chứng → điều kiện → người dùng duyệt; tối đa 2 vòng sửa với bộ test giữ nguyên.";
  graph.nodes = [
    ...graph.nodes.filter((n) => n.id !== "REVIEW"),
    ...[verify, condition, gate].map((task, i) => ({
      id: task.id,
      task,
      position: { x: 335 + i * 290, y: 145 },
    })),
  ];
  graph.edges = [
    { source: "DEV", target: "VERIFY" },
    { source: "TEST", target: "VERIFY" },
    { source: "VERIFY", target: "CONDITION" },
    { source: "CONDITION", target: "GATE", port: "match" },
    { source: "CONDITION", target: "GATE", port: "no_match" },
    {
      source: "GATE",
      target: "DEV",
      port: "changes_requested",
      feedback: true,
    },
  ];
  return graph;
}

export function commandText(argv: string[]) {
  return argv
    .map((arg) =>
      /^[A-Za-z0-9_./=:@+-]+$/.test(arg) ? arg : JSON.stringify(arg),
    )
    .join(" ");
}

/** Lay out forward dependencies; a bounded repair edge never changes rank. */
export function arrangeGraph(graph: WorkflowGraph): WorkflowGraph {
  const ranks = new Map<string, number>();
  const rank = (id: string, visiting = new Set<string>()): number => {
    if (ranks.has(id)) return ranks.get(id)!;
    if (visiting.has(id)) return 0;
    const next = new Set([...visiting, id]);
    const parents = graph.edges.filter((e) => e.target === id && !e.feedback);
    const value = parents.length
      ? 1 + Math.max(...parents.map((e) => rank(e.source, next)))
      : 0;
    ranks.set(id, value);
    return value;
  };
  const rows = new Map<number, number>();
  return {
    ...graph,
    nodes: graph.nodes.map((node) => {
      const column = rank(node.id),
        row = rows.get(column) || 0;
      rows.set(column, row + 1);
      return { ...node, position: { x: 60 + column * 320, y: 60 + row * 210 } };
    }),
  };
}

export function nextTaskId(graph: WorkflowGraph): string {
  let n = graph.nodes.length + 1;
  while (
    graph.nodes.some((node) => node.id === `T${String(n).padStart(2, "0")}`)
  )
    n++;
  return `T${String(n).padStart(2, "0")}`;
}

export function renameTask(
  graph: WorkflowGraph,
  previous: string,
  id: string,
): WorkflowGraph {
  if (!/^[A-Z][A-Z0-9_-]{0,30}$/.test(id) || id.startsWith("SYS_"))
    throw new Error(
      "Mã task dùng chữ hoa, số, _ hoặc -; bắt đầu bằng chữ, tối đa 31 ký tự. SYS_ được dành riêng.",
    );
  if (graph.nodes.some((node) => node.id === id && node.id !== previous))
    throw new Error("Mã task đã tồn tại trong workflow.");
  return {
    ...graph,
    nodes: graph.nodes.map((node) => ({
      ...node,
      id: node.id === previous ? id : node.id,
      task: {
        ...node.task,
        id: node.id === previous ? id : node.task.id,
        depends_on: node.task.depends_on.map((parent) =>
          parent === previous ? id : parent,
        ),
      },
    })),
    edges: graph.edges.map((edge) => ({
      ...edge,
      source: edge.source === previous ? id : edge.source,
      target: edge.target === previous ? id : edge.target,
    })),
  };
}

export function duplicateTask(
  graph: WorkflowGraph,
  source: string,
): WorkflowGraph {
  const node = graph.nodes.find((n) => n.id === source);
  if (!node || graph.nodes.length >= 20) return graph;
  const id = nextTaskId(graph);
  return {
    ...graph,
    nodes: [
      ...graph.nodes,
      {
        ...structuredClone(node),
        id,
        position: { x: node.position.x + 40, y: node.position.y + 200 },
        task: {
          ...structuredClone(node.task),
          id,
          title: `${node.task.title} (bản sao)`.slice(0, 300),
          depends_on: [],
        },
      },
    ],
  };
}

export const workflowTemplates = [
  {
    id: "parallel",
    name: "Phát triển song song",
    description:
      "Developer và Tester làm việc độc lập, cùng chuyển sang Reviewer.",
    flow: "Dev + Test → Review",
    count: 3,
  },
  {
    id: "sequential",
    name: "Từng bước rõ ràng",
    description: "Hoàn thành phát triển, viết kiểm thử, sau đó review kết quả.",
    flow: "Dev → Test → Review",
    count: 3,
  },
  {
    id: "branches",
    name: "Chia nhánh phát triển",
    description:
      "Hai Developer phụ trách các file riêng, dùng chung bộ kiểm thử độc lập.",
    flow: "Dev A + Dev B + Test → Review",
    count: 4,
  },
  {
    id: "approval",
    name: "Duyệt trước khi bàn giao",
    description:
      "Chạy kiểm chứng rồi chờ người dùng duyệt kết quả trong giao diện.",
    flow: "Dev + Test → Verify → Duyệt",
    count: 4,
  },
  {
    id: "repair",
    name: "Duyệt và yêu cầu sửa",
    description:
      "Phân nhánh theo kết quả kiểm chứng. Người dùng có thể yêu cầu Developer sửa tối đa 2 vòng.",
    flow: "Dev + Test → Verify → Điều kiện → Duyệt ↺",
    count: 5,
  },
  {
    id: "agent",
    name: "Agent review có giới hạn",
    description:
      "Agent review độc lập sau kiểm chứng; cho phép 2 vòng sửa với bộ test giữ nguyên.",
    flow: "Dev + Test → Verify → Agent ↺",
    count: 4,
  },
  {
    id: "factory-release",
    name: "Agent review rồi người duyệt",
    description:
      "Kiểm chứng, Agent review với 2 vòng sửa, rồi người dùng duyệt trước khi bàn giao. Merge/triển khai vẫn theo bước bàn giao của project.",
    flow: "Dev + Test → Verify → Agent ↺ → Người duyệt",
    count: 5,
  },
  {
    id: "factory-branch",
    name: "Rẽ nhánh đạt hoặc lỗi",
    description:
      "Kiểm chứng đạt chuyển sang Reviewer; lỗi chuyển đến cổng người dùng xem xét. Việc duyệt không thay thế kết quả kiểm thử cuối.",
    flow: "Dev + Test → Verify → Đạt: Review / Lỗi: Người duyệt",
    count: 6,
  },
  {
    id: "factory-cross-review",
    name: "Review song song hai góc nhìn",
    description:
      "Hai task riêng rà soát độ đúng và rủi ro sau kiểm chứng, cùng chuyển cho người dùng duyệt kết quả.",
    flow: "Dev + Test → Verify → Review A + B → Người duyệt",
    count: 6,
  },
] as const;

export const templateSources: Record<string, { label: string; url: string }> = {
  repair: {
    label: "factory-wilson · review-cycle",
    url: "http://10.0.10.195:3000/admin/factory-wilson/src/commit/eec813d4e4d57520ba0ebcb8d12d0c531a3618e4/workflows/review-cycle.spec.yaml",
  },
  "factory-release": {
    label: "factory-wilson · implement-verify-release",
    url: "http://10.0.10.195:3000/admin/factory-wilson/src/commit/eec813d4e4d57520ba0ebcb8d12d0c531a3618e4/workflows/implement-verify-release.spec.yaml",
  },
  "factory-branch": {
    label: "factory-wilson · branch-review",
    url: "http://10.0.10.195:3000/admin/factory-wilson/src/commit/eec813d4e4d57520ba0ebcb8d12d0c531a3618e4/workflows/branch-review.spec.yaml",
  },
  "factory-cross-review": {
    label: "factory-wilson · playbooks",
    url: "http://10.0.10.195:3000/admin/factory-wilson/src/commit/eec813d4e4d57520ba0ebcb8d12d0c531a3618e4/skills/workloop-skill/references/playbooks.md",
  },
};

export function templateGraph(id: string): WorkflowGraph {
  let graph = id === "repair" ? controlledStarterGraph() : starterGraph();
  if (id === "sequential")
    graph.edges = [
      { source: "DEV", target: "TEST" },
      { source: "TEST", target: "REVIEW" },
    ];
  if (id === "branches") {
    const task = newTask("DEV_B", "implement");
    task.title = "Phát triển phần độc lập thứ hai";
    graph.nodes.splice(1, 0, { id: task.id, task, position: { x: 0, y: 0 } });
    graph.edges.push({ source: "DEV_B", target: "REVIEW" });
  }
  if (id === "approval" || id === "agent") {
    graph.version = 2;
    graph.nodes = graph.nodes.filter((n) => n.id !== "REVIEW");
    const gate = newTask("GATE", "gate");
    if (id === "agent")
      gate.control = { type: "gate", reviewer: "agent", max_rounds: 2 };
    graph.nodes.push(
      ...[newTask("VERIFY", "verify"), gate].map((task) => ({
        id: task.id,
        task,
        position: { x: 0, y: 0 },
      })),
    );
    graph.edges = [
      { source: "DEV", target: "VERIFY" },
      { source: "TEST", target: "VERIFY" },
      { source: "VERIFY", target: "GATE" },
    ];
    if (id === "agent")
      graph.edges.push({
        source: "GATE",
        target: "DEV",
        port: "changes_requested",
        feedback: true,
      });
  }
  if (id === "factory-release") {
    graph = templateGraph("agent");
    const human = newTask("HUMAN", "gate");
    human.title = "Người dùng duyệt logic, rủi ro và bằng chứng";
    human.acceptance = [
      "Đáp ứng yêu cầu đã duyệt và có kết quả kiểm chứng thật",
      "Các rủi ro và giới hạn được người dùng xem xét trước khi bàn giao",
    ];
    graph.nodes.push({ id: human.id, task: human, position: { x: 0, y: 0 } });
    graph.edges.push({ source: "GATE", target: "HUMAN", port: "approved" });
    const agent = graph.nodes.find((n) => n.id === "GATE")!.task;
    agent.title = "Agent rà soát source và bằng chứng kiểm thử";
    agent.acceptance = [
      "Source bám tiêu chí, không có logic thừa hoặc kiểm thử giả",
      "Không chấp nhận tự báo đạt khi thiếu kết quả kiểm chứng",
    ];
  }
  if (id === "factory-branch") {
    graph = templateGraph("approval");
    const condition = newTask("CONDITION", "condition"),
      review = newTask("REVIEW", "review");
    const gate = graph.nodes.find((n) => n.id === "GATE")!.task;
    gate.title = "Người dùng xem xét lỗi kiểm chứng";
    gate.acceptance = [
      "Người dùng đã xem log lỗi và quyết định có tiếp tục hay dừng",
      "Duyệt tại cổng này không thay thế yêu cầu kiểm thử cuối phải đạt",
    ];
    graph.nodes.push(
      ...[condition, review].map((task) => ({
        id: task.id,
        task,
        position: { x: 0, y: 0 },
      })),
    );
    graph.edges = graph.edges.filter((e) => e.target !== "GATE");
    graph.edges.push(
      { source: "VERIFY", target: "CONDITION" },
      { source: "CONDITION", target: "REVIEW", port: "match" },
      { source: "CONDITION", target: "GATE", port: "no_match" },
    );
  }
  if (id === "factory-cross-review") {
    graph = templateGraph("approval");
    const correctness = newTask("REVIEW_A", "review"),
      risks = newTask("REVIEW_B", "review");
    correctness.title = "Review độ đúng theo yêu cầu đã duyệt";
    correctness.steps = [
      "Đối chiếu source, yêu cầu và kết quả kiểm chứng",
      "Nêu chênh lệch kèm file, đoạn code và tiêu chí liên quan",
    ];
    correctness.acceptance = [
      "Mỗi kết luận có dẫn chiếu source hoặc kết quả kiểm thử",
      "Các yêu cầu còn thiếu được liệt kê rõ ràng",
    ];
    risks.title = "Review rủi ro và tác động ngược";
    risks.steps = [
      "Rà soát input, phân quyền và tương thích trong phạm vi thay đổi",
      "Chỉ rõ rủi ro có bằng chứng và giới hạn còn tồn tại",
    ];
    risks.acceptance = [
      "Phân biệt lỗi có bằng chứng với giả định cần kiểm tra",
      "Không sửa source hoặc thay đổi bộ kiểm thử",
    ];
    graph.nodes.push(
      ...[correctness, risks].map((task) => ({
        id: task.id,
        task,
        position: { x: 0, y: 0 },
      })),
    );
    graph.edges = graph.edges.filter((e) => e.target !== "GATE");
    graph.edges.push(
      { source: "VERIFY", target: "REVIEW_A" },
      { source: "VERIFY", target: "REVIEW_B" },
      { source: "REVIEW_A", target: "GATE" },
      { source: "REVIEW_B", target: "GATE" },
    );
  }
  const template = workflowTemplates.find((t) => t.id === id);
  graph.title = template?.name || graph.title;
  graph.summary = template?.description || graph.summary;
  // Scopes and commands must be chosen for the connected repository.
  graph.commands = [];
  return arrangeGraph(graph);
}

export function pathIssue(path: string): string | null {
  if (
    !path ||
    path.length > 300 ||
    path.startsWith("/") ||
    path.includes("\\") ||
    /[:*?\[\]\x00-\x1f]/.test(path) ||
    path.split("/").some((part) => !part || part === "." || part === "..")
  )
    return "Nhập đường dẫn tương đối tới một file cụ thể, ví dụ src/app.ts.";
  if (
    path
      .split("/")
      .some(
        (part) =>
          [".git", "node_modules", ".venv", "venv"].includes(part) ||
          part.startsWith(".env"),
      ) ||
    /credentials|private-key|id_rsa|\.pem/i.test(path)
  )
    return "File cấu hình bí mật hoặc thư mục hệ thống không được đưa vào phạm vi sửa.";
  return null;
}

export function isTestPath(path: string): boolean {
  const parts = path.split("/"),
    name = (parts.at(-1) || "").toLowerCase();
  return (
    parts.some((part) =>
      ["test", "tests", "spec", "specs", "__tests__"].includes(part),
    ) ||
    name.startsWith("test_") ||
    name.includes(".test.") ||
    name.includes(".spec.") ||
    name.endsWith("_test.py")
  );
}

/** Accept draft content, but reject data that cannot safely render in the editor. */
export function parseGraph(text: string): WorkflowGraph {
  if (text.length > 400_000) throw new Error("JSON tối đa 400.000 ký tự.");
  let graph: WorkflowGraph;
  try {
    graph = JSON.parse(text);
  } catch {
    throw new Error("JSON chưa hợp lệ. Kiểm tra dấu ngoặc và dấu phẩy.");
  }
  const fail = () => {
    throw new Error(
      "Cấu trúc workflow không hợp lệ. Xuất JSON hiện tại để xem định dạng.",
    );
  };
  if (
    !graph ||
    ![1, 2].includes(graph.version) ||
    typeof graph.title !== "string" ||
    typeof graph.summary !== "string"
  )
    fail();
  for (const [key, max] of [
    ["nodes", 20],
    ["edges", 190],
    ["commands", 8],
    ["browser_checks", 15],
  ] as const)
    if (!Array.isArray(graph[key]) || graph[key].length > max) fail();
  const ids = new Set<string>();
  for (const node of graph.nodes) {
    if (
      !node ||
      typeof node.id !== "string" ||
      !node.id ||
      ids.has(node.id) ||
      !node.position ||
      ![node.position.x, node.position.y].every(
        (v) => Number.isFinite(v) && Math.abs(v) <= 1e6,
      )
    )
      fail();
    ids.add(node.id);
    const task = node.task;
    if (
      !task ||
      task.id !== node.id ||
      typeof task.title !== "string" ||
      !["implement", "test", "review"].includes(task.kind || "") ||
      !Array.isArray(task.depends_on) ||
      task.depends_on.some((v) => typeof v !== "string")
    )
      fail();
    for (const key of ["steps", "acceptance", "write_paths"] as const)
      if (
        !Array.isArray(task[key]) ||
        task[key]!.length > 40 ||
        task[key]!.some((v) => typeof v !== "string" || v.length > 3000)
      )
        fail();
    if (task.join !== undefined && !["all", "any"].includes(task.join)) fail();
    if (task.control) {
      if (
        graph.version !== 2 ||
        !["condition", "verify", "gate"].includes(task.control.type)
      )
        fail();
      if (
        task.control.type === "condition" &&
        !["status_done", "verification_passed", "review_approved"].includes(
          task.control.predicate,
        )
      )
        fail();
      if (
        task.control.type === "gate" &&
        (!["human", "agent"].includes(task.control.reviewer) ||
          !Number.isInteger(task.control.max_rounds) ||
          task.control.max_rounds < 0 ||
          task.control.max_rounds > 3)
      )
        fail();
    }
  }
  if (
    graph.edges.some(
      (e) =>
        !e ||
        !ids.has(e.source) ||
        !ids.has(e.target) ||
        (e.port !== undefined && !Object.prototype.hasOwnProperty.call(portLabels, e.port)),
    )
  )
    fail();
  if (
    graph.commands.some(
      (c) =>
        !c ||
        typeof c.label !== "string" ||
        !Array.isArray(c.argv) ||
        c.argv.some((v) => typeof v !== "string") ||
        (c.timeout !== undefined && !Number.isFinite(c.timeout)),
    )
  )
    fail();
  if (graph.preview !== null && graph.preview !== undefined) {
    if (
      typeof graph.preview !== "object" ||
      (graph.preview.path !== undefined &&
        typeof graph.preview.path !== "string") ||
      (graph.preview.argv !== undefined &&
        (!Array.isArray(graph.preview.argv) ||
          graph.preview.argv.some((v) => typeof v !== "string")))
    )
      fail();
  }
  if (
    graph.browser_checks.some(
      (c) =>
        !c ||
        typeof c.label !== "string" ||
        !Array.isArray(c.steps) ||
        c.steps.some(
          (s) =>
            !s ||
            typeof s !== "object" ||
            Object.values(s).some((v) => typeof v !== "string"),
        ),
    )
  )
    fail();
  return graph;
}

// This is an argument editor. Shell operators are never evaluated by the runner.
export function commandArgs(text: string): string[] {
  const args: string[] = [];
  let word = "",
    quote = "",
    started = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quote) {
      if (c === quote) quote = "";
      else if (quote === '"' && c === "\\" && ['"', "\\"].includes(text[i + 1]))
        word += text[++i];
      else word += c;
    } else if (c === '"' || c === "'") {
      quote = c;
      started = true;
    } else if (/\s/.test(c)) {
      if (started) {
        args.push(word);
        word = "";
        started = false;
      }
    } else {
      word += c;
      started = true;
    }
  }
  if (quote) throw new Error("Đóng dấu ngoặc kép hoặc đơn trong lệnh.");
  if (started) args.push(word);
  return args;
}
