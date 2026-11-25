import { lazy } from "react";
import {
  createBrowserRouter,
  createRoutesFromElements,
  Outlet,
  Route,
} from "react-router-dom";
import { ProtectedRoute } from "./components/authorization/authGuard";
import { ProtectedLoginRoute } from "./components/authorization/authLoginGuard";
import { AuthSettingsGuard } from "./components/authorization/authSettingsGuard";
import { PlaygroundAuthGate } from "./components/authorization/playgroundAuthGate";
import ContextWrapper from "./contexts";
import CustomDashboardWrapperPage from "./customization/components/custom-DashboardWrapperPage";
import { CustomNavigate } from "./customization/components/custom-navigate";
import { BASENAME } from "./customization/config-constants";
import {
  ENABLE_CUSTOM_PARAM,
  ENABLE_FILE_MANAGEMENT,
  ENABLE_KNOWLEDGE_BASES,
} from "./customization/feature-flags";
import { CustomAuthRoutesStore } from "./customization/utils/custom-auth-routes-store";
import { CustomRoutesStore } from "./customization/utils/custom-routes-store";
import { CustomRoutesStorePages } from "./customization/utils/custom-routes-store-pages";
import WorkspaceLibraryPage from "./features/adlc-workspace/library-page";
import HarnessRouteRedirect from "./features/adlc-workspace/harness-route-redirect";
import LocalProjectsPage from "./features/adlc-workspace/projects-page";
import WorkspaceSettingsPage from "./features/adlc-workspace/settings-page";
import WorkloopIntegrationPage from "./features/adlc-workspace/workloop-integration-page";
import { AppAuthenticatedPage } from "./pages/AppAuthenticatedPage";
import { AppInitPage } from "./pages/AppInitPage";
import { AppWrapperPage } from "./pages/AppWrapperPage";
import ContractHarnessPage from "./pages/ContractHarnessPage";
import FlowPage from "./pages/FlowPage";
import LoginPage from "./pages/LoginPage";
import FilesPage from "./pages/MainPage/pages/filesPage";
import HomePage from "./pages/MainPage/pages/homePage";
import KnowledgePage from "./pages/MainPage/pages/knowledgePage";
import SourceChunksPage from "./pages/MainPage/pages/knowledgePage/sourceChunksPage/SourceChunksPage";
import CollectionPage from "./pages/MainPage/pages/main-page";
import PlanDetailPage from "./pages/PlanDetailPage";
import RunDetailPage from "./pages/RunDetailPage";
import RunHistoryPage from "./pages/RunHistoryPage";
import SettingsPage from "./pages/SettingsPage";
import ApiKeysPage from "./pages/SettingsPage/pages/ApiKeysPage";
import DBProvidersPage from "./pages/SettingsPage/pages/DBProvidersPage";
import GeneralPage from "./pages/SettingsPage/pages/GeneralPage";
import GlobalVariablesPage from "./pages/SettingsPage/pages/GlobalVariablesPage";
import MCPServersPage from "./pages/SettingsPage/pages/MCPServersPage";
import McpClientPage from "./pages/SettingsPage/pages/McpClientPage";
import ModelProvidersPage from "./pages/SettingsPage/pages/ModelProvidersPage";
import MessagesPage from "./pages/SettingsPage/pages/messagesPage";
import ShortcutsPage from "./pages/SettingsPage/pages/ShortcutsPage";

const LoginAdminPage = lazy(() => import("./pages/AdminPage/LoginPage"));

const PlaygroundPage = lazy(() => import("./pages/Playground"));

const SignUp = lazy(() => import("./pages/SignUpPage"));
const DeliveryWorkspacePage = lazy(
  () => import("./features/delivery-workspace/workspace-page"),
);
const HarnessDemoPage = lazy(() => import("./pages/HarnessDemoPage"));
const RequirementIntakePage = lazy(
  () => import("./features/requirement-intake/intake-page"),
);
const TeamAccessPage = lazy(
  () => import("./features/team-access/team-access-page"),
);
const TeamProjectPage = lazy(
  () => import("./features/team-collaboration/project-page"),
);
const TeamRunDetailPage = lazy(() =>
  import("./features/team-collaboration/project-page").then((module) => ({
    default: module.TeamRunDetailPage,
  })),
);

const router = createBrowserRouter(
  createRoutesFromElements([
    <Route path="/playground/:id/">
      <Route
        path=""
        element={
          <ContextWrapper key={1}>
            <PlaygroundAuthGate>
              <PlaygroundPage />
            </PlaygroundAuthGate>
          </ContextWrapper>
        }
      />
    </Route>,
    <Route
      path={ENABLE_CUSTOM_PARAM ? "/:customParam?" : "/"}
      element={
        <ContextWrapper key={2}>
          <Outlet />
        </ContextWrapper>
      }
    >
      <Route path="" element={<AppInitPage />}>
        <Route path="" element={<AppWrapperPage />}>
          <Route
            path=""
            element={
              <ProtectedRoute>
                <Outlet />
              </ProtectedRoute>
            }
          >
            <Route path="" element={<AppAuthenticatedPage />}>
              <Route
                path="contracts/harness/:sessionId/"
                element={<ContractHarnessPage />}
              />
              <Route path="" element={<CustomDashboardWrapperPage />}>
                <Route
                  path="intake/:requestId?"
                  element={<RequirementIntakePage />}
                />
                <Route
                  path="work/:deliveryId?"
                  element={<DeliveryWorkspacePage />}
                />
                <Route
                  path="studio/"
                  element={<CustomNavigate replace to="/work" />}
                />
                <Route path="" element={<CollectionPage />}>
                  <Route
                    index
                    element={<CustomNavigate replace to={"work"} />}
                  />
                  {ENABLE_FILE_MANAGEMENT && (
                    <Route path="assets">
                      <Route
                        index
                        element={<CustomNavigate replace to="files" />}
                      />
                      <Route path="files" element={<FilesPage />} />
                      {ENABLE_KNOWLEDGE_BASES && (
                        <>
                          <Route
                            path="knowledge-bases"
                            element={<KnowledgePage />}
                          />
                          <Route
                            path="knowledge-bases/:sourceId/chunks"
                            element={<SourceChunksPage />}
                          />
                        </>
                      )}
                    </Route>
                  )}
                  <Route
                    path="flows/"
                    element={<HomePage key="flows" type="flows" />}
                  />
                  <Route
                    path="components/"
                    element={<HomePage key="components" type="components" />}
                  >
                    <Route
                      path="folder/:folderId"
                      element={<HomePage key="components" type="components" />}
                    />
                  </Route>
                  <Route
                    path="all/"
                    element={<HomePage key="flows" type="flows" />}
                  >
                    <Route
                      path="folder/:folderId"
                      element={<HomePage key="flows" type="flows" />}
                    />
                  </Route>
                  <Route
                    path="mcp/"
                    element={<HomePage key="mcp" type="mcp" />}
                  >
                    <Route
                      path="folder/:folderId"
                      element={<HomePage key="mcp" type="mcp" />}
                    />
                  </Route>
                </Route>
                <Route path="settings" element={<SettingsPage />}>
                  <Route index element={<WorkspaceSettingsPage />} />
                  <Route
                    path="integrations"
                    element={<WorkloopIntegrationPage />}
                  />
                  <Route
                    path="global-variables"
                    element={<GlobalVariablesPage />}
                  />
                  <Route
                    path="model-providers"
                    element={<ModelProvidersPage />}
                  />
                  <Route path="db-providers" element={<DBProvidersPage />} />
                  <Route path="mcp-servers" element={<MCPServersPage />} />
                  <Route path="mcp-client" element={<McpClientPage />} />

                  <Route path="api-keys" element={<ApiKeysPage />} />
                  <Route
                    path="general/:scrollId?"
                    element={
                      <AuthSettingsGuard>
                        <GeneralPage />
                      </AuthSettingsGuard>
                    }
                  />
                  <Route path="shortcuts" element={<ShortcutsPage />} />
                  <Route path="messages" element={<MessagesPage />} />
                  {CustomRoutesStore()}
                </Route>
                {CustomRoutesStorePages()}
              </Route>
              <Route path="flow/:id/">
                <Route path="" element={<CustomDashboardWrapperPage />}>
                  <Route path="folder/:folderId/" element={<FlowPage />} />
                  <Route path="" element={<FlowPage />} />
                </Route>
              </Route>
              <Route
                path="plans/:planId/"
                element={<CustomDashboardWrapperPage />}
              >
                <Route path="" element={<PlanDetailPage />} />
              </Route>
              <Route path="runs/" element={<CustomDashboardWrapperPage />}>
                <Route path="" element={<RunHistoryPage />} />
              </Route>
              <Route path="reviews/" element={<CustomDashboardWrapperPage />}>
                <Route path="" element={<RunHistoryPage reviewsOnly />} />
              </Route>
              <Route path="library/" element={<CustomDashboardWrapperPage />}>
                <Route path="" element={<WorkspaceLibraryPage />} />
              </Route>
              <Route
                path="runtime-sessions/"
                element={<CustomDashboardWrapperPage />}
              >
                <Route path="" element={<HarnessDemoPage />} />
              </Route>
              <Route path="harness/" element={<HarnessRouteRedirect />} />
              <Route path="harness-demo/" element={<HarnessRouteRedirect />} />
              <Route
                path="team-access/"
                element={<CustomDashboardWrapperPage />}
              >
                <Route path="" element={<TeamAccessPage />} />
              </Route>
              <Route
                path="collaboration/"
                element={<CustomDashboardWrapperPage />}
              >
                <Route path="" element={<TeamProjectPage />} />
                <Route path="runs/:runId/" element={<TeamRunDetailPage />} />
              </Route>
              <Route path="projects/" element={<CustomDashboardWrapperPage />}>
                <Route path="" element={<LocalProjectsPage />} />
              </Route>
              <Route
                path="runs/:runId/"
                element={<CustomDashboardWrapperPage />}
              >
                <Route path="" element={<RunDetailPage />} />
              </Route>
            </Route>
          </Route>
          <Route
            path="login"
            element={
              <ProtectedLoginRoute>
                <LoginPage />
              </ProtectedLoginRoute>
            }
          />
          <Route
            path="signup"
            element={
              <ProtectedLoginRoute>
                <SignUp />
              </ProtectedLoginRoute>
            }
          />
          <Route
            path="login/admin"
            element={
              <ProtectedLoginRoute>
                <LoginAdminPage />
              </ProtectedLoginRoute>
            }
          />
          {CustomAuthRoutesStore()}
        </Route>
      </Route>
      <Route path="*" element={<CustomNavigate replace to="/" />} />
    </Route>,
  ]),
  { basename: BASENAME || undefined },
);

export default router;
