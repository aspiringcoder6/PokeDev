import { useQuery } from "@tanstack/react-query";
import { useContext } from "react";
import { AuthContext } from "@/contexts/authContext";
import {
  documentIntake,
  type IntakeDocument,
} from "@/controllers/API/document-intake";

export function useDocumentInbox(
  projectId?: string,
  enabled = true,
  includeArchived = false,
) {
  const { userData } = useContext(AuthContext);
  return useQuery({
    queryKey: [
      "document-intake",
      userData?.id,
      projectId || "all",
      includeArchived,
    ],
    queryFn: () => documentIntake.list(projectId, includeArchived),
    enabled: !!userData && enabled,
    retry: false,
    staleTime: 4000,
    refetchInterval: 10000,
    refetchIntervalInBackground: true,
  });
}
export const documentNeedsReview = (doc: IntakeDocument) =>
  !doc.archived_at &&
  ["NEEDS_PROJECT", "NEEDS_REVIEW", "CHANGED"].includes(doc.state);
