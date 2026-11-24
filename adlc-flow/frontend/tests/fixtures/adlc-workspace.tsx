// Browser-test entry point using production components. Not an application route.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import PokeDevLogo from "../../src/assets/PokeDevLogo.svg?react";
import { TooltipProvider } from "../../src/components/ui/tooltip";
import AdlcWorkflowEditor from "../../src/features/adlc-workspace/workflow-editor";
import WorkspaceNavigation from "../../src/features/adlc-workspace/workspace-navigation";
import useAdlcBlueprintStore from "../../src/stores/adlcBlueprintStore";
import { useDarkStore } from "../../src/stores/darkStore";
import useFlowStore from "../../src/stores/flowStore";
import useFlowsManagerStore from "../../src/stores/flowsManagerStore";
import type { FlowType } from "../../src/types/flow";
import { createAdlcWorkflowMarker } from "../../src/utils/adlc-blueprint";
import "../../src/i18n";
import "@xyflow/react/dist/style.css";
import "../../src/style/index.css";
import "../../src/style/classes.css";
import "../../src/style/applies.css";
import "../../src/App.css";

const flowId = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const query = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
const saved = JSON.parse(localStorage.getItem("adlc-workspace-browser-fixture") ?? "null") as FlowType | null;
const flow: FlowType = saved ?? { id: flowId, name: "Implement user management", description: "Browser fixture", data: { adlc: createAdlcWorkflowMarker(flowId), nodes: [], edges: [], viewport: { x: 0, y: 0, zoom: 1 } } };
useFlowsManagerStore.setState({ flows: [flow], currentFlow: JSON.parse(JSON.stringify(flow)), currentFlowId: flowId, autoSaving: false });
useFlowStore.getState().setCurrentFlow(flow);
useFlowStore.getState().resetFlow(flow);
useFlowStore.setState({ onFlowPage: true });

Object.assign(window, { adlcFixture: {
  state: () => ({ flow: useFlowStore.getState().currentFlow, nodes: useFlowStore.getState().nodes, edges: useFlowStore.getState().edges, plan: useAdlcBlueprintStore.getState().plan, viewport: useFlowStore.getState().reactFlowInstance?.getViewport() }),
  lock: (locked: boolean) => { const current = useFlowStore.getState().currentFlow!; useFlowStore.getState().setCurrentFlow({ ...current, locked }); },
  theme: (dark: boolean) => { useDarkStore.setState({ dark }); document.body.classList.toggle("dark", dark); },
  approveLayout: () => useAdlcBlueprintStore.setState({ plan: { execution_plan_id: "fixture-approved", status: "ACCEPTED", tasks: [], resolved_node_specs: [], edges: [], warnings: [], validation_errors: [] } as never }),
} });
createRoot(document.getElementById("root")!).render(<QueryClientProvider client={query}><MemoryRouter initialEntries={[`/flow/${flowId}`]}><TooltipProvider><div className="flex h-screen flex-col"><header className="flex h-12 shrink-0 items-center gap-2 border-b bg-card px-4"><PokeDevLogo className="h-8 w-8" /><span className="text-sm font-semibold">Poke <span className="text-primary">Dev</span></span><span className="ml-auto text-[10px] text-muted-foreground">Browser test fixture</span></header><div className="flex min-h-0 flex-1"><WorkspaceNavigation /><div className="min-w-0 flex-1"><AdlcWorkflowEditor /></div></div></div></TooltipProvider></MemoryRouter></QueryClientProvider>);
