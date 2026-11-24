export function workspaceLocation(params: URLSearchParams) {
  const view = params.get("view");
  // Preserve old orchestration links while keeping creation outside the dashboard.
  if (
    ["new-project", "advanced"].includes(view || "") ||
    params.has("tools_project")
  )
    return { projectId: "", section: "new-project" };
  const projectId = params.get("project") || params.get("project_id") || "";
  if (projectId) {
    const section = [
      "issues",
      "requests",
      "workflows",
      "results",
      "metrics",
      "environment",
      "settings",
    ].includes(view || "")
      ? view!
      : "work";
    return { projectId, section };
  }
  if (view === "results") return { projectId, section: "results" };
  if (view === "requests") return { projectId, section: "requests" };
  if (
    ["work", "history", "review"].includes(view || "") ||
    (!view && params.has("run"))
  )
    return { projectId, section: "work" };
  return { projectId, section: "overview" };
}
