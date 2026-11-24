import { resolve } from "node:path";
import ts from "typescript";

const configPath = ts.findConfigFile(".", ts.sys.fileExists, "tsconfig.json");
const config = ts.readConfigFile(configPath, ts.sys.readFile);
const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, ".");
const paths = [
  "src/components/adlc/ContractViewer/index.tsx",
  "src/components/adlc/ContractViewer/model.ts",
  "src/components/adlc/ContractPanel/index.tsx",
  "src/components/adlc/ContractExecutionPanel/index.tsx",
  "src/components/adlc/ContractExecutionPanel/model.ts",
  "src/types/contractExecution.ts",
  "src/pages/ContractHarnessPage/index.tsx",
  "src/controllers/API/contracts.ts",
  "src/types/contracts.ts",
  "src/features/adlc-blueprint/approved-reference.ts",
  "src/features/adlc-blueprint/stage-editor-dialog.tsx",
  "src/types/adlc.ts",
  "src/pages/RunDetailPage/HarnessSessions.tsx",
  "src/pages/RunDetailPage/index.tsx",
  "src/pages/RunDetailPage/TaskLoopTimeline.tsx",
  "src/pages/RunDetailPage/SourcePatchReview.tsx",
  "src/controllers/API/adlc.ts",
];
const program = ts.createProgram(
  [...paths, "src/vite-env.d.ts"],
  parsed.options,
);
const owned = new Set(paths.map((path) => resolve(path).toLowerCase()));
const diagnostics = ts.getPreEmitDiagnostics(program);
const focused = diagnostics.filter(
  (d) => !d.file || owned.has(resolve(d.file.fileName).toLowerCase()),
);
if (focused.length)
  console.error(
    ts.formatDiagnosticsWithColorAndContext(focused, {
      getCanonicalFileName: (name) => name,
      getCurrentDirectory: ts.sys.getCurrentDirectory,
      getNewLine: () => "\n",
    }),
  );
console.log(
  JSON.stringify({
    contract_files: paths.length,
    contract_errors: focused.length,
    unrelated_dependency_errors: diagnostics.length - focused.length,
  }),
);
// This is explicitly a focused check, not a claim that the whole frontend is clean.
process.exitCode = focused.length ? 1 : 0;
