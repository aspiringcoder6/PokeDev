import { useQuery } from "@tanstack/react-query";
import { api } from "@/controllers/API/api";
import { getBaseUrl } from "@/customization/utils/urls";

const root = `${getBaseUrl().replace(/\/?$/, "/")}adlc`;
export const localProjectQueryKey = ["adlcLocalProjects"];

export type LocalProject = {
  project_id: string;
  name: string;
  source_path: string;
  ready: boolean;
  base_commit: string | null;
  uncommitted_changes: boolean;
  message: string | null;
};
export type LocalFolderListing = {
  path: string | null;
  parent: string | null;
  roots: { name: string; path: string }[];
  folders: { name: string; path: string }[];
  truncated: boolean;
};
export const useLocalProjects = () =>
  useQuery({
    queryKey: localProjectQueryKey,
    queryFn: async () =>
      (await api.get<LocalProject[]>(`${root}/local-projects`)).data,
    staleTime: 15000,
    retry: false,
  });
export const browseLocalFolders = async (path?: string) =>
  (
    await api.get<LocalFolderListing>(
      `${root}/local-folders${path ? `?path=${encodeURIComponent(path)}` : ""}`,
    )
  ).data;
export const openLocalProject = async (source_path: string) =>
  (await api.post<LocalProject>(`${root}/local-projects`, { source_path }))
    .data;
