import { translateUi, useUiLocale } from "@/i18n/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowUp,
  Check,
  ChevronRight,
  Folder,
  FolderOpen,
  Loader2,
} from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { extractApiErrorMessages } from "@/utils/apiError";
import {
  browseLocalFolders,
  type LocalProject,
  localProjectQueryKey,
  openLocalProject,
  useLocalProjects,
} from "./local-project-api";
import { useTranslation } from "react-i18next";
import "@/i18n";

type Props = {
  projectId?: string;
  disabled?: boolean;
  label?: string;
  onSelected: (project: LocalProject) => Promise<void> | void;
};

export default function ProjectSelector({
  projectId,
  disabled,
  label,
  onSelected,
}: Props) {
  useUiLocale();
  const projects = useLocalProjects();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [browse, setBrowse] = useState(false);
  const [path, setPath] = useState<string | undefined>();
  const [location, setLocation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const current = projects.data?.find((p) => p.project_id === projectId);
  const listing = useQuery({
    queryKey: ["adlcLocalFolders", path],
    queryFn: () => browseLocalFolders(path),
    enabled: open && browse,
    retry: false,
  });
  const go = (next?: string) => {
    setPath(next);
    setLocation(next ?? "");
    setError(null);
  };
  const select = async (project: LocalProject) => {
    setBusy(true);
    setError(null);
    try {
      await onSelected(project);
      setOpen(false);
    } catch (failure) {
      setError(
        extractApiErrorMessages(failure)[0] ??
          translateUi("The project could not be selected."),
      );
    } finally {
      setBusy(false);
    }
  };
  const chooseFolder = async () => {
    if (!listing.data?.path) return;
    setBusy(true);
    setError(null);
    try {
      const project = await openLocalProject(listing.data.path);
      await queryClient.invalidateQueries({ queryKey: localProjectQueryKey });
      await queryClient.invalidateQueries({ queryKey: ["useGetFolders"] });
      await onSelected(project);
      setOpen(false);
    } catch (failure) {
      setError(
        extractApiErrorMessages(failure)[0] ??
          translateUi("This folder could not be opened as a project."),
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Button
        variant="outline"
        size="sm"
        className="h-8 max-w-[190px] gap-2 text-xs"
        disabled={disabled}
        title={current?.source_path}
        aria-label={label ?? translateUi("Choose project")}
        onClick={() => {
          setOpen(true);
          setBrowse(Boolean(label));
          setError(null);
        }}
      >
        <FolderOpen size={14} />
        <span className="truncate">
          {label ?? current?.name ?? translateUi("Choose project")}
        </span>
      </Button>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (!busy) setOpen(next);
        }}
      >
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>
              {browse
                ? translateUi("Choose a local folder")
                : translateUi("Choose a project")}
            </DialogTitle>
            <DialogDescription>
              {translateUi(
                "Folders are on the computer running PokeDev. Live coding uses a separate copy of committed files.",
              )}
            </DialogDescription>
          </DialogHeader>
          <div className="flex gap-2 border-b pb-3">
            <Button
              size="sm"
              variant={browse ? "ghost" : "secondary"}
              onClick={() => setBrowse(false)}
              disabled={busy}
            >
              {translateUi("Projects")}
            </Button>
            <Button
              size="sm"
              variant={browse ? "secondary" : "ghost"}
              onClick={() => setBrowse(true)}
              disabled={busy}
            >
              {translateUi("Choose folder")}
            </Button>
          </div>
          {browse ? (
            <>
              <form
                className="space-y-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  // Portal events still bubble through the React parent tree.
                  // Browsing folders must never submit a containing workflow form.
                  event.stopPropagation();
                  go(location.trim() || undefined);
                }}
              >
                <Label htmlFor="project-folder-location">
                  {translateUi("Folder location")}
                </Label>
                <div className="flex gap-2">
                  <Input
                    id="project-folder-location"
                    value={location}
                    onChange={(event) => setLocation(event.target.value)}
                    placeholder={translateUi(
                      "Paste a folder path or browse below",
                    )}
                    disabled={busy}
                  />
                  <Button variant="outline" type="submit" disabled={busy}>
                    {translateUi("Go")}
                  </Button>
                </div>
              </form>
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  aria-label={translateUi("Parent folder")}
                  disabled={!listing.data?.parent || busy}
                  onClick={() => go(listing.data?.parent ?? undefined)}
                >
                  <ArrowUp size={14} />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => go()}
                  disabled={busy}
                >
                  {translateUi("Locations")}
                </Button>
                <span
                  className="min-w-0 truncate"
                  title={listing.data?.path ?? undefined}
                >
                  {listing.data?.path ?? translateUi("Available locations")}
                </span>
              </div>
              <div
                className="h-60 overflow-auto rounded-lg border p-1"
                aria-label={translateUi("Local folders")}
              >
                {listing.isLoading && (
                  <p className="flex items-center gap-2 p-3 text-sm text-muted-foreground">
                    <Loader2 size={14} className="animate-spin" />
                    {translateUi("Opening folder…")}
                  </p>
                )}
                {listing.isError && (
                  <p role="alert" className="p-3 text-sm text-destructive">
                    {extractApiErrorMessages(listing.error)[0] ??
                      translateUi("The folder is unavailable.")}
                  </p>
                )}
                {listing.data?.folders.map((folder) => (
                  <button
                    key={folder.path}
                    type="button"
                    disabled={busy}
                    onClick={() => go(folder.path)}
                    className="flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left text-sm hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <Folder size={16} className="shrink-0 text-primary" />
                    <span className="truncate">{folder.name}</span>
                    <ChevronRight
                      size={14}
                      className="ml-auto shrink-0 text-muted-foreground"
                    />
                  </button>
                ))}
                {listing.data && !listing.data.folders.length && (
                  <p className="p-3 text-sm text-muted-foreground">
                    {translateUi("No subfolders. You can use this folder.")}
                  </p>
                )}
              </div>
              {listing.data?.truncated && (
                <p className="text-xs text-muted-foreground">
                  {translateUi(
                    "Showing the first 200 folders. Paste a path to open another folder.",
                  )}
                </p>
              )}
            </>
          ) : (
            <div
              className="max-h-80 space-y-2 overflow-auto"
              aria-label={translateUi("Local projects")}
            >
              {projects.isLoading && (
                <p className="p-3 text-sm text-muted-foreground">
                  {translateUi("Loading projects…")}
                </p>
              )}
              {projects.isError && (
                <p role="alert" className="text-sm text-destructive">
                  {translateUi(
                    "Projects could not be loaded. Refresh and try again.",
                  )}
                </p>
              )}
              {projects.data?.map((project) => (
                <button
                  key={project.project_id}
                  type="button"
                  disabled={busy}
                  onClick={() => void select(project)}
                  className="flex w-full items-start gap-3 rounded-lg border p-3 text-left hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <FolderOpen
                    size={18}
                    className="mt-0.5 shrink-0 text-primary"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium">{project.name}</p>
                    <p
                      className="mt-1 truncate text-xs text-muted-foreground"
                      title={project.source_path}
                    >
                      {project.source_path}
                    </p>
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      {project.ready
                        ? translateUi("Committed source · {{value0}}", {
                            value0: project.base_commit?.slice(0, 8),
                          })
                        : project.message}
                    </p>
                  </div>
                  {project.project_id === projectId && (
                    <Check size={15} className="shrink-0 text-primary" />
                  )}
                </button>
              ))}
              {projects.data?.length === 0 && (
                <p className="rounded-lg bg-muted p-4 text-sm text-muted-foreground">
                  {translateUi(
                    "Choose a folder to create your first local project.",
                  )}
                </p>
              )}
            </div>
          )}
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setOpen(false)}
              disabled={busy}
            >
              {translateUi("Cancel")}
            </Button>
            {browse && (
              <Button
                loading={busy}
                disabled={
                  disabled ||
                  !listing.data?.path ||
                  listing.isFetching ||
                  listing.isError
                }
                onClick={() => void chooseFolder()}
              >
                {translateUi("Use this folder")}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
