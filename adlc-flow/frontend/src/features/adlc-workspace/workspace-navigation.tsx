import {
  BookOpen,
  ClipboardList,
  Ellipsis,
  FolderOpen,
  History,
  Inbox,
  LayoutDashboard,
  ListChecks,
  Play,
  Settings,
  ShieldCheck,
  Users,
  Workflow,
} from "lucide-react";
import { useLocation } from "react-router-dom";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import { translateUi, useUiLocale } from "@/i18n/ui";
import { cn } from "@/utils/utils";
import "@/i18n";
import { workspaceLocation } from "../delivery-workspace/workspace-location";

export default function WorkspaceNavigation() {
  useUiLocale();
  const { pathname, search } = useLocation();
  const navigate = useCustomNavigate();
  const editor = pathname.includes("/flow/") || pathname.startsWith("/work");
  const params = new URLSearchParams(search);
  const { projectId: project, section } = workspaceLocation(params);
  const workPath = (view?: string) =>
    `/work${view || project ? "?" : ""}${view ? `view=${view}` : ""}${view && project ? "&" : ""}${project ? `project=${project}` : ""}`;
  const links = [
    {
      label: "Tổng quan workspace",
      path: "/work",
      icon: LayoutDashboard,
      active: pathname.startsWith("/work") && section === "overview",
    },
    {
      label: "Yêu cầu & tài liệu",
      path: workPath("requests"),
      icon: Inbox,
      active: pathname.startsWith("/work") && section === "requests",
    },
    {
      label: project ? "Công việc" : "Lịch sử công việc",
      path: workPath(project ? undefined : "history"),
      icon: project ? ClipboardList : History,
      active:
        pathname.startsWith("/work") &&
        section === "work" &&
        params.get("view") !== "review",
    },
    ...(project
      ? [
          {
            label: "Workflow của project",
            path: workPath("workflows"),
            icon: Workflow,
            utility: true,
            active:
              pathname.startsWith("/work") &&
              params.get("view") === "workflows",
          },
        ]
      : []),
    {
      label: translateUi("Projects"),
      path: "/projects",
      icon: FolderOpen,
      active: pathname.includes("/projects"),
    },
    {
      label: "Kiểm thử & kết quả",
      path: workPath("results"),
      icon: Play,
      active: pathname.startsWith("/work") && search.includes("view=results"),
    },
    {
      label: "Phần cần duyệt",
      path: workPath("review"),
      icon: ListChecks,
      active: pathname.startsWith("/work") && search.includes("view=review"),
    },
    {
      label: translateUi("Library"),
      path: "/library",
      icon: BookOpen,
      utility: true,
      active: pathname.includes("/library"),
    },
    {
      label: "Thành viên",
      path: "/team-access",
      icon: ShieldCheck,
      utility: true,
      active: pathname.includes("/team-access"),
    },
    {
      label: "Không gian nhóm",
      path: "/collaboration",
      icon: Users,
      utility: true,
      active: pathname.includes("/collaboration"),
    },
  ];
  return (
    <nav
      aria-label={translateUi("ADLC workspace")}
      className={cn(
        "flex w-12 shrink-0 flex-col border-r bg-card px-1.5 py-4",
        !editor && "lg:w-48 lg:px-4",
      )}
    >
      {!editor && (
        <p className="mb-3 hidden px-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground lg:block">
          {translateUi("Workspace")}
        </p>
      )}
      <div className="space-y-1">
        {links
          .filter((link) => !link.utility)
          .map((link) => (
            <Button
              key={link.path}
              variant={link.active ? "secondary" : "ghost"}
              unstyled
              aria-label={link.label}
              aria-current={link.active ? "page" : undefined}
              title={link.label}
              onClick={() => navigate(link.path)}
              className={cn(
                "flex h-10 w-full items-center justify-center gap-2.5 rounded-lg text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                !editor && "lg:justify-start lg:px-2.5",
                link.active
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-accent hover:text-foreground",
              )}
            >
              <link.icon size={17} className="shrink-0" />
              <span className={cn("hidden", !editor && "lg:inline")}>
                {link.label}
              </span>
            </Button>
          ))}
      </div>
      <div className="mt-auto space-y-1 border-t pt-2">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              unstyled
              variant="ghost"
              aria-label="Thêm mục điều hướng"
              title="Thêm"
              aria-current={
                links.some((link) => link.utility && link.active)
                  ? "page"
                  : undefined
              }
              className={cn(
                "flex h-10 w-full items-center justify-center gap-2.5 rounded-lg text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                !editor && "lg:justify-start lg:px-2.5",
                links.some((link) => link.utility && link.active) &&
                  "bg-primary/10 text-primary",
              )}
            >
              <Ellipsis size={18} />
              <span className={cn("hidden", !editor && "lg:inline")}>Thêm</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            side="right"
            align="end"
            sideOffset={10}
            className="min-w-[220px] p-1.5"
            aria-label="Điều hướng bổ sung"
          >
            <DropdownMenuLabel className="px-2 py-2 text-[10px] uppercase tracking-wider text-muted-foreground">
              Tiện ích workspace
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            {links
              .filter((link) => link.utility)
              .map((link) => (
                <DropdownMenuItem
                  key={link.path}
                  onSelect={() => navigate(link.path)}
                  aria-current={link.active ? "page" : undefined}
                  className={cn(
                    "gap-2.5 rounded-md px-2.5 py-2.5 text-xs",
                    link.active && "bg-primary/10 text-primary",
                  )}
                >
                  <link.icon size={16} />
                  {link.label}
                </DropdownMenuItem>
              ))}
          </DropdownMenuContent>
        </DropdownMenu>
        <Button
          variant="ghost"
          unstyled
          aria-label={translateUi("Workspace settings")}
          title={translateUi("Settings")}
          onClick={() => navigate("/settings")}
          className={cn(
            "flex h-10 w-full items-center justify-center gap-2.5 rounded-lg text-xs text-muted-foreground hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            !editor && "lg:justify-start lg:px-2.5",
          )}
        >
          <Settings size={17} />
          <span className={cn("hidden", !editor && "lg:inline")}>
            {translateUi("Settings")}
          </span>
        </Button>
      </div>
    </nav>
  );
}
