import { translateUi, useUiLocale } from "@/i18n/ui";
import { ArrowRight, FolderOpen, GitCommitHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import { useLocalProjects } from "./local-project-api";
import ProjectSelector from "./project-selector";
import { useTranslation } from "react-i18next";
import "@/i18n";

export default function LocalProjectsPage() {
  useUiLocale();
  const query = useLocalProjects();
  const navigate = useCustomNavigate();
  return (
    <main className="h-full w-full overflow-auto p-5 lg:p-8">
      <div className="mx-auto max-w-5xl space-y-6">
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="mb-2 text-xs font-medium text-primary">
              {translateUi("PokeDev · Workspace")}
            </p>
            <h1 className="text-2xl font-semibold tracking-tight">
              {translateUi("Local projects")}
            </h1>
            <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
              {translateUi(
                "Choose a folder on your computer, create workflows for it, and review changes from the Agent Harness.",
              )}
            </p>
          </div>
          <ProjectSelector
            label={translateUi("Open local folder")}
            onSelected={(project) =>
              navigate(`/all/folder/${project.project_id}`)
            }
          />
        </header>
        <div className="rounded-xl border bg-card p-4 text-sm leading-6 text-muted-foreground">
          {translateUi(
            "Runs use an exact committed revision in a separate working copy. Your chosen folder and uncommitted changes stay in place; review the resulting patch before applying it.",
          )}
        </div>
        {query.isLoading && (
          <p className="text-sm text-muted-foreground">
            {translateUi("Loading projects…")}
          </p>
        )}
        {query.isError && (
          <p role="alert" className="text-sm text-destructive">
            {translateUi(
              "Local projects could not be loaded. Make sure PokeDev is running on this computer.",
            )}
          </p>
        )}
        {query.data?.length === 0 && (
          <div className="rounded-xl border border-dashed p-10 text-center">
            <FolderOpen size={28} className="mx-auto text-primary" />
            <h2 className="mt-4 text-base font-semibold">
              {translateUi("Start with your project folder")}
            </h2>
            <p className="mt-2 text-sm text-muted-foreground">
              {translateUi(
                "Open a local folder to keep its workflows and source context together.",
              )}
            </p>
          </div>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          {query.data?.map((project) => (
            <article
              key={project.project_id}
              className="min-w-0 rounded-xl border bg-card p-5"
            >
              <div className="flex items-start gap-3">
                <span className="rounded-lg border p-2 text-primary">
                  <FolderOpen size={18} />
                </span>
                <div className="min-w-0">
                  <h2 className="truncate text-base font-semibold">
                    {project.name}
                  </h2>
                  <p
                    className="mt-1 truncate text-xs text-muted-foreground"
                    title={project.source_path}
                  >
                    {project.source_path}
                  </p>
                </div>
              </div>
              <p className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
                <GitCommitHorizontal size={14} />
                {project.ready
                  ? translateUi("Committed source · {{value0}}", {
                      value0: project.base_commit?.slice(0, 8),
                    })
                  : translateUi("Source setup required")}
              </p>
              {project.message && (
                <p className="mt-2 text-xs leading-5 text-muted-foreground">
                  {project.message}
                </p>
              )}
              <Button
                variant="ghost"
                size="sm"
                className="mt-4 px-0 text-primary"
                onClick={() => navigate(`/all/folder/${project.project_id}`)}
              >
                {translateUi("Open workflows")}
                <ArrowRight size={14} />
              </Button>
            </article>
          ))}
        </div>
      </div>
    </main>
  );
}
