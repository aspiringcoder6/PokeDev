import { useLocation } from "react-router-dom";
import { CustomNavigate } from "@/customization/components/custom-navigate";

export default function HarnessRouteRedirect() {
  const { search, hash } = useLocation();
  return <CustomNavigate replace to={`/runtime-sessions/${search}${hash}`} />;
}
