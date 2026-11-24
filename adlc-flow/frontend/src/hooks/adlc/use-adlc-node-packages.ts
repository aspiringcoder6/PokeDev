import { useQuery } from "@tanstack/react-query";
import { listAdlcNodePackages } from "@/controllers/API/adlc";

export const ADLC_NODE_PACKAGES_QUERY_KEY = ["adlc-node-packages"];

export function useAdlcNodePackages() {
  return useQuery({
    queryKey: ADLC_NODE_PACKAGES_QUERY_KEY,
    // Old definitions remain available to existing nodes; the add-stage picker hides replaced entries.
    queryFn: () => listAdlcNodePackages(true),
    staleTime: 5 * 60 * 1000,
  });
}
