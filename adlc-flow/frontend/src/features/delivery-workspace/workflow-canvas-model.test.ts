import {
  commandArgs,
  commandText,
  connectionIssue,
  graphFromPlan,
  starterGraph,
  controlledStarterGraph,
  outputPorts,
  arrangeGraph,
  duplicateTask,
  renameTask,
  parseGraph,
  templateGraph,
  workflowTemplates,
  pathIssue,
  templateSources,
} from "./workflow-canvas-model";

beforeAll(() => {
  global.structuredClone = (value) => JSON.parse(JSON.stringify(value));
});

test("arranging and renaming keep both branch ports, feedback, scopes and verification intact", () => {
  const graph = controlledStarterGraph();
  graph.nodes[0].task.write_paths = ["src/app.ts"];
  const renamed = renameTask(graph, "DEV", "DEV_MAIN");
  const arranged = arrangeGraph(renamed);
  expect(arranged.edges).toEqual(renamed.edges);
  expect(arranged.edges.find((e) => e.feedback)?.target).toBe("DEV_MAIN");
  expect(arranged.nodes[0].task.write_paths).toEqual(["src/app.ts"]);
  expect(arranged.commands).toEqual(graph.commands);
  expect(
    arranged.nodes.find((n) => n.id === "GATE")!.position.x,
  ).toBeGreaterThan(arranged.nodes[0].position.x);
  expect(() => renameTask(graph, "DEV", "SYS_VERIFY")).toThrow(/SYS_/);
  expect(() => renameTask(graph, "DEV", "TEST")).toThrow(/đã tồn tại/);
});

test("duplicated tasks have independent contracts, no copied dependencies and unique identities", () => {
  const graph = starterGraph();
  const next = duplicateTask(graph, "REVIEW");
  const node = next.nodes.at(-1)!;
  expect(node.task.depends_on).toEqual([]);
  expect(next.edges).toEqual(graph.edges);
  node.task.steps![0] = "Modified copy";
  expect(graph.nodes[2].task.steps![0]).not.toBe("Modified copy");
  expect(new Set(next.nodes.map((n) => n.id)).size).toBe(next.nodes.length);
});

test("all templates roundtrip through the advanced editor and leave project-specific setup explicit", () => {
  for (const template of workflowTemplates) {
    const graph = templateGraph(template.id);
    expect(graph.nodes).toHaveLength(template.count);
    expect(parseGraph(JSON.stringify(graph))).toEqual(graph);
    expect(graph.commands).toEqual([]);
    expect(graph.nodes.some((n) => n.task.kind === "test")).toBe(true);
  }
});

test("factory templates retain real routing and approval boundaries without release tools", () => {
  const release = templateGraph("factory-release");
  expect(release.edges).toContainEqual({
    source: "GATE",
    target: "HUMAN",
    port: "approved",
  });
  expect(release.nodes.find((n) => n.id === "GATE")?.task.control).toEqual({
    type: "gate",
    reviewer: "agent",
    max_rounds: 2,
  });
  expect(release.nodes.find((n) => n.id === "HUMAN")?.task.control).toEqual({
    type: "gate",
    reviewer: "human",
    max_rounds: 0,
  });
  const branch = templateGraph("factory-branch");
  expect(branch.edges).toContainEqual({
    source: "CONDITION",
    target: "REVIEW",
    port: "match",
  });
  expect(branch.edges).toContainEqual({
    source: "CONDITION",
    target: "GATE",
    port: "no_match",
  });
  const cross = templateGraph("factory-cross-review");
  expect(
    cross.edges
      .filter((e) => e.target === "GATE")
      .map((e) => e.source)
      .sort(),
  ).toEqual(["REVIEW_A", "REVIEW_B"]);
  for (const graph of [release, branch, cross]) {
    expect(
      graph.nodes.every((n) =>
        ["implement", "test", "review"].includes(n.task.kind!),
      ),
    ).toBe(true);
    expect(graph.commands).toEqual([]);
  }
  expect(templateSources["factory-release"].url).toContain(
    "/admin/factory-wilson/src/commit/",
  );
});

test("advanced import rejects malformed structures and file scope rejects traversal and patterns", () => {
  for (const mutate of [
    (g: any) => {
      g.nodes[0].task.steps = [null];
    },
    (g: any) => {
      g.nodes[0].position.x = 2e6;
    },
    (g: any) => {
      g.edges[0].target = "MISSING";
    },
    (g: any) => {
      g.nodes[1].id = "DEV";
    },
    (g: any) => {
      g.preview = { argv: "node app.js" };
    },
    (g: any) => {
      g.browser_checks = [null];
    },
  ]) {
    const graph = starterGraph();
    mutate(graph);
    expect(() => parseGraph(JSON.stringify(graph))).toThrow();
  }
  for (const path of [
    "../app.ts",
    "/etc/passwd",
    "src/*.ts",
    "C:\\app.ts",
    ".env.local",
    "keys/private-key.pem",
  ])
    expect(pathIssue(path)).toBeTruthy();
  expect(pathIssue("src/features/app.ts")).toBeNull();
});

test("controlled canvas preserves both condition ports and bounded feedback on roundtrip", () => {
  const graph = controlledStarterGraph();
  expect(graph.version).toBe(2);
  expect(outputPorts(graph.nodes.find((n) => n.id === "GATE")!.task)).toEqual([
    "approved",
    "changes_requested",
  ]);
  const plan = {
    title: graph.title,
    summary: graph.summary,
    digest: "p",
    tasks: graph.nodes.map((n) => ({
      ...n.task,
      depends_on: [
        ...new Set(
          graph.edges
            .filter((e) => !e.feedback && e.target === n.id)
            .map((e) => e.source),
        ),
      ],
    })),
    commands: graph.commands,
    control_flow: {
      version: 1 as const,
      edges: graph.edges,
      loops: [
        {
          gate: "GATE",
          target: "DEV",
          nodes: ["DEV", "VERIFY", "CONDITION"],
          max_rounds: 2,
        },
      ],
      max_repairs: 0 as const,
    },
  };
  expect(graphFromPlan(plan).edges).toEqual(graph.edges);
  const withoutFeedback = {
    ...graph,
    edges: graph.edges.filter((e) => !e.feedback),
  };
  expect(
    connectionIssue(withoutFeedback, "GATE", "DEV", "changes_requested"),
  ).toBeNull();
  expect(
    connectionIssue(withoutFeedback, "GATE", "TEST", "changes_requested"),
  ).toMatch(/Developer/);
  expect(connectionIssue(graph, "GATE", "DEV", "approved")).toMatch(/vòng lặp/);
  const noBranches = {
    ...graph,
    edges: graph.edges.filter((e) => e.source !== "CONDITION"),
  };
  expect(connectionIssue(noBranches, "CONDITION", "GATE", "match")).toBeNull();
  noBranches.edges.push({ source: "CONDITION", target: "GATE", port: "match" });
  expect(
    connectionIssue(noBranches, "CONDITION", "GATE", "no_match"),
  ).toBeNull();
});

test("plan roundtrip preserves file scopes, commands, preview and browser checks", () => {
  const starter = starterGraph();
  const plan = {
    title: "Counter plan",
    summary: "Counter",
    digest: "a".repeat(64),
    tasks: starter.nodes.map((node) => ({
      ...node.task,
      depends_on: starter.edges
        .filter((edge) => edge.target === node.id)
        .map((edge) => edge.source),
    })),
    commands: [
      {
        label: "Node test",
        argv: ["node", "--test", "tests/test_counter.mjs"],
      },
    ],
    preview: { path: "." },
    browser_checks: [
      {
        label: "Click counter",
        steps: [{ action: "click", selector: "#increment" }],
      },
    ],
  };
  const graph = graphFromPlan(plan);
  expect(graph.edges).toEqual(starter.edges);
  expect(graph.commands).toEqual(plan.commands);
  expect(graph.preview).toEqual(plan.preview);
  expect(graph.browser_checks).toEqual(plan.browser_checks);
  graph.nodes[0].task.title = "Changed";
  expect(plan.tasks[0].title).not.toBe("Changed");
});

test("canvas prevents cycles, duplicate edges, self edges and missing tasks", () => {
  const graph = starterGraph();
  expect(connectionIssue(graph, "REVIEW", "DEV")).toMatch(/vòng lặp/);
  expect(connectionIssue(graph, "DEV", "REVIEW")).toMatch(/đã được kết nối/);
  expect(connectionIssue(graph, "DEV", "DEV")).toMatch(/chính nó/);
  expect(connectionIssue(graph, "MISSING", "DEV")).toMatch(/Chọn hai task/);
  expect(connectionIssue(graph, "DEV", "TEST")).toBeNull();
});

test("argument editing preserves spaces, quotes, escapes and never evaluates shell syntax", () => {
  const argv = [
    "python",
    "tests/file with spaces.py",
    'a"b',
    "C:\\data\\test",
    "",
    "$(whoami)",
  ];
  expect(commandArgs(commandText(argv))).toEqual(argv);
  expect(commandArgs("node --test 'tests/my test.mjs'")).toEqual([
    "node",
    "--test",
    "tests/my test.mjs",
  ]);
  expect(commandArgs("echo hello | whoami")).toEqual([
    "echo",
    "hello",
    "|",
    "whoami",
  ]);
  expect(() => commandArgs('python "unterminated')).toThrow(/Đóng dấu/);
});
