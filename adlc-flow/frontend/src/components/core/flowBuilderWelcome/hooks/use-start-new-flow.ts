import { useCallback } from "react";
import { useParams } from "react-router-dom";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import useAddFlow from "@/hooks/flows/use-add-flow";

/**
 * Entry-point for the "New Flow" button on the home page: creates an empty
 * ADLC workflow on the backend and opens the package designer directly.
 */
export function useStartNewFlow() {
  const addFlow = useAddFlow();
  const navigate = useCustomNavigate();
  const { folderId } = useParams();

  return useCallback(async () => {
    const id = await addFlow({ adlc: true });
    // ADLC workflows open directly in the package designer.
    navigate(`/flow/${id}${folderId ? `/folder/${folderId}` : ""}`);
  }, [addFlow, navigate, folderId]);
}
