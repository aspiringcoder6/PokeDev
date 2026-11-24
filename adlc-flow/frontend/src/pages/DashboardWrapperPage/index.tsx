import { Outlet } from "react-router-dom";
import AppHeader from "@/components/core/appHeaderComponent";
import { PermissionsProvider } from "@/contexts/permissionsContext";
import { useGetRefreshFlowsQuery } from "@/controllers/API/queries/flows/use-get-refresh-flows-query";
import useTheme from "@/customization/hooks/use-custom-theme";
import WorkspaceNavigation from "@/features/adlc-workspace/workspace-navigation";
import useAuthStore from "@/stores/authStore";
import useFlowStore from "@/stores/flowStore";

export function DashboardWrapperPage() {
  useTheme();
  const authenticated = useAuthStore((state) => state.isAuthenticated);
  useGetRefreshFlowsQuery(
    { get_all: true, header_flows: true },
    { enabled: authenticated },
  );
  const currentFlow = useFlowStore((state) => state.currentFlow);

  return (
    <PermissionsProvider
      resourceType="flow"
      resourceIds={currentFlow?.id ? [currentFlow.id] : []}
      domain={
        currentFlow?.folder_id ? `project:${currentFlow.folder_id}` : undefined
      }
    >
      <div className="flex h-screen w-full flex-col overflow-hidden bg-background text-foreground">
        <AppHeader />
        <div className="flex w-full flex-1 flex-row overflow-hidden">
          <WorkspaceNavigation />
          <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
            <Outlet />
          </div>
        </div>
      </div>
    </PermissionsProvider>
  );
}
